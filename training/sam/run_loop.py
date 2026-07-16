#!/usr/bin/env python3
"""Sam self-improvement training loop.

Run from the sam repository root, e.g.:

    python training/sam/run_loop.py --limit 2            # eval-only (default)
    python training/sam/run_loop.py --scenarios hero_title_001 --fix  # opt-in fixer
"""
import argparse
import asyncio
import importlib
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from _paths import SAM_DIR, bootstrap

K = 3  # default best-of-k; overridable via --k
# Abort the run when this many CONSECUTIVE scenarios end in "error": that
# signature is a broken environment (dead API key, quota exhausted mid-run,
# endpoint down), not Sam — running the rest of the suite would just thrash
# (each scenario burns up to 2*k attempts). A decisive pass/fail resets the
# streak, so the guard catches a mid-run death, not only a dead start.
ABORT_AFTER_CONSECUTIVE_ERRORS = 3

# The fixer's allowlisted Python modules, in dependency order (site_editor does
# `from agent.prompts import BASE_SYSTEM_INSTRUCTION`, so prompts reloads first).
AGENT_SOURCE_MODULES = (
    "agent.prompts", "agent.content_validator", "agent.site_editor")


def reload_agent_source(modules=AGENT_SOURCE_MODULES):
    """Reload the fixer's allowlisted Python modules so an on-disk source edit
    takes effect within this long-lived process. Python caches imported modules,
    so without this a post-fix re-eval validates the fix against the PRE-fix code
    (e.g. BASE_SYSTEM_INSTRUCTION is bound at import) and every behavioral /
    validator fix is reverted no matter how correct. Reload in dependency order;
    modules not yet imported are skipped (nothing stale yet)."""
    for name in modules:
        mod = sys.modules.get(name)
        if mod is not None:
            importlib.reload(mod)


bootstrap()

import fixer
import judge
import sam_registry
import sam_runner
import verifier
from _paths import TEMPLATE_DIR
from scenario_schema import load_scenarios, is_holdout


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenarios", nargs="*", default=None,
                        help="scenario ids to run (default: all)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--fix", action="store_true",
                        help="enable the self-modifying fixer (default: eval-only). "
                             "Even with --fix, nothing is ever committed — the fixer "
                             "proposes edits in the working tree for human review "
                             "(see `git diff`), within the allowlist, and reverts on regression.")
    parser.add_argument("--max-fix-attempts", type=int, default=2)
    parser.add_argument("--fix-budget", type=int, default=5,
                        help="max fixer invocations per run")
    parser.add_argument("--model", default="gemini-2.5-flash",
                        help="Sam's model. Default = the corpus baseline: every "
                             "green registry run was measured on gemini-2.5-flash, "
                             "so a different model invalidates pass-rate comparisons.")
    parser.add_argument("--k", type=int, default=K,
                        help="best-of-k runs at decision points (majority vote)")
    parser.add_argument("--dry-run", action="store_true",
                        help="replay scenarios' dry_run blocks instead of calling Sam")
    parser.add_argument("--keep-workspaces", action="store_true",
                        help="keep each attempt's workspace/ dir for debugging "
                             "(default: deleted after verification+judging — "
                             "node_modules/dist grow runs/ by ~150MB per full "
                             "suite; all judgeable artifacts are kept either way)")
    parser.add_argument("--scenarios-dir", type=Path, default=SAM_DIR / "scenarios")
    parser.add_argument("--registry", type=Path, default=SAM_DIR / "registry.json")
    parser.add_argument("--runs-dir", type=Path, default=SAM_DIR / "runs")
    parser.add_argument("--repo-root", type=Path, default=sam_runner.REPO_ROOT)
    return parser.parse_args(argv)


async def best_of_k(scenario, base_dir, args):
    """Run the scenario up to args.k decisive times and return
    (majority_status, pass_dir). pass_dir is the artifact directory of a PASSING
    attempt (or None if none passed) — callers that judge the result (e.g. the
    goalpost re-confirm) must inspect a sample that actually passed, not blindly
    __k1 which may have failed while __k2/__k3 clinched the majority. Infra
    'error' runs don't count and are topped up (cap 2*k attempts). Early-exits
    once one side reaches a majority. Artifacts go in f"{base_dir}__k{n}"."""
    k = args.k
    need = k // 2 + 1
    passes = fails = decisive = attempt = 0
    pass_dir = None
    while decisive < k and attempt < 2 * k:
        attempt += 1
        attempt_dir = Path(f"{base_dir}__k{attempt}")
        status, _ = await execute_scenario(scenario, attempt_dir, args)
        if status == "pass":
            passes += 1; decisive += 1; pass_dir = attempt_dir
        elif status == "fail":
            fails += 1; decisive += 1
        if passes >= need:
            return "pass", pass_dir
        if fails >= need:
            return "fail", pass_dir
    if decisive == 0:
        return "error", pass_dir
    # No side reached the majority within the cap (only possible for even k):
    # a tie breaks to "fail" — we don't claim a pass we couldn't confirm.
    return ("pass" if passes > fails else "fail"), pass_dir


async def suite_regression(target, all_scenarios, registry, run_dir, args, attempt):
    """Re-run every scenario (other than target) that was passing per the
    registry; return the first id whose best-of-k now FAILS *and stays failing on
    a second best-of-k*, else None. A single best-of-k can itself flake to "fail"
    for a near-threshold scenario (its flakiness is *within* a run, so the
    aggregate history looks clean and is_flaky can't catch it) — re-confirming
    before reverting keeps that from falsely reverting a good fix. An 'error'
    (infra) is likewise not a regression."""
    for other in all_scenarios:
        if other.id == target.id:
            continue
        # Holdout scenarios must not gate fix acceptance — otherwise fixes get
        # indirectly fitted to the holdout set and the headline holdout pass-rate
        # stops being an unbiased generalization measure.
        if is_holdout(other):
            continue
        runs = registry.get(other.id, {}).get("runs", [])
        if not (runs and runs[-1].get("result") == "pass"):
            continue
        st, _ = await best_of_k(
            other, run_dir / f"{other.id}__regress{attempt}", args)
        if st != "fail":
            continue
        # Re-confirm with an independent best-of-k; revert only on a repeat fail.
        st2, _ = await best_of_k(
            other, run_dir / f"{other.id}__regress{attempt}b", args)
        if st2 == "fail":
            return other.id
    return None


async def execute_scenario(scenario, scen_dir: Path, args):
    """Provision, run Sam (or replay), verify, judge.
    Returns (status, summary_lines). Writes all artifacts into scen_dir."""
    # Pick up any fixer edit to Sam's source so each eval (esp. the post-fix
    # re-eval and regression sweep) reflects the current files, not stale imports.
    reload_agent_source()
    scen_dir.mkdir(parents=True, exist_ok=True)
    provider, project_dir = await sam_runner.provision_workspace(scen_dir, scenario)
    if args.dry_run:
        run_result = sam_runner.run_sam_dry(scenario, project_dir)
    else:
        run_result = await sam_runner.run_sam(scenario, provider, args.model)
    changes = sam_runner.workspace_changes(project_dir)

    (scen_dir / "scenario.json").write_text(
        json.dumps(asdict(scenario), indent=2))
    # response.txt is judge/fixer evidence of what Sam SAID — an error string
    # there would conflate Sam's reply with a harness message, so errors get
    # their own artifact.
    (scen_dir / "response.txt").write_text(run_result.text or "")
    if run_result.error:
        (scen_dir / "error.txt").write_text(run_result.error)
    if scenario.turns and run_result.transcript:
        # The judge assesses sequencing (e.g. published only after the user's
        # go-ahead) from the conversation, not just the final reply.
        (scen_dir / "transcript.json").write_text(
            json.dumps(run_result.transcript, indent=2))
    (scen_dir / "tool_calls.json").write_text(
        json.dumps(run_result.tool_calls, indent=2))
    (scen_dir / "diff.patch").write_text(changes["diff"])

    verification = await verifier.verify(
        project_dir, scenario, run_result, scen_dir, changes)
    layers = {name: asdict(layer) for name, layer in verification.layers.items()}
    status = verification.status

    run_judge = (status == "pass" and not args.dry_run
                 and (scenario.checks.judge or scenario.negative))
    if run_judge:
        verdict = judge.judge_scenario(scenario, scen_dir)
        (scen_dir / "judge.json").write_text(json.dumps(verdict, indent=2))
        if verdict["passed"] is False:
            status = "fail"
            layers["judge"] = {"status": "fail",
                               "details": verdict["issues"] or [verdict["reasoning"]]}
        elif verdict["passed"] is True:
            layers["judge"] = {"status": "pass", "details": []}
        else:
            # Degraded quorum / inconclusive panel: neither pass nor fail is
            # safe to claim. Route to the non-decisive "error" path — the run
            # doesn't count toward pass-rate and best_of_k tops it up — rather
            # than silently keeping the deterministic "pass".
            status = "error"
            layers["judge"] = {"status": "error", "details": [verdict["reasoning"]]}

    (scen_dir / "verification.json").write_text(
        json.dumps({"status": status, "layers": layers}, indent=2))
    summary = [d for layer in layers.values() for d in layer["details"]]
    if not args.keep_workspaces:
        # The workspace (node_modules/dist/.astro — the bulk of runs/ growth)
        # is only needed during verification; the judge and fixer read only
        # the artifacts written above (scenario.json, response.txt,
        # tool_calls.json, diff.patch, verification.json, build.log,
        # screenshots), and re-evals/regression sweeps always provision fresh
        # workspaces. --keep-workspaces preserves it for debugging.
        shutil.rmtree(scen_dir / "workspace", ignore_errors=True)
    return status, summary


@dataclass
class FixOutcome:
    """Result of a scenario's fix attempts: whether one stuck, and the run's
    remaining fixer budget."""
    fixed: bool
    fix_budget: int


async def attempt_fixes(scenario, outcome, *, registry, all_scenarios,
                        run_dir, args, fix_budget) -> FixOutcome:
    """Run the self-modifying fixer for one confirmed-failing TRAIN scenario.

    Mutates `outcome` (fixes / summary / result / fixer_infra) and the
    registry's needs_human flag; on success the accepted edits stay in the
    working tree for human review, otherwise they are reverted to the
    pre-fix snapshot (which may already carry earlier accepted fixes this
    run — never to HEAD, or a shared file like prompts.py would lose them).
    """
    applied_all = []
    pre_fix_snapshot = fixer.snapshot_allowlisted(args.repo_root)
    fixed = False
    fixer_infra = False
    for attempt in range(1, args.max_fix_attempts + 1):
        if fix_budget <= 0:
            outcome["summary"].append("fix budget exhausted")
            break
        fix_budget -= 1
        try:
            fix = fixer.run_fixer(scenario, run_dir / scenario.id,
                                  args.repo_root)
        except Exception as e:
            # fixer infra failure (missing binary, timeout, CLI error):
            # record it, stop fixing this scenario, keep the run alive
            outcome["summary"].append(
                f"fixer error: {type(e).__name__}: {e}")
            fixer_infra = True
            break
        if not fix.get("applied"):
            # The fixer changed no source. Don't run a best-of-k that
            # could pass by flake and get miscredited to a no-op fix;
            # move to the next attempt (or exhaust the budget).
            outcome["summary"].append("fixer made no changes")
            continue
        outcome["fixes"].append(fix)
        applied_all.extend(fix["applied"])
        fix_status, fix_pass_dir = await best_of_k(
            scenario, run_dir / f"{scenario.id}__fix{attempt}", args)
        if fix_status != "pass":
            continue
        # Goalpost fixes must survive a judge re-confirm (they can pass
        # merely by neutralizing the check they failed). Classify the
        # CUMULATIVE on-disk edits, not just this attempt's: an earlier
        # failed attempt's goalpost edit lingers on disk (reverted only
        # at the end), so a later behavioral attempt could otherwise
        # smuggle it past the guard.
        fix["provenance"] = fixer.fix_provenance(fix["applied"])
        prov = fixer.fix_provenance(sorted(set(applied_all)))
        if prov == "goalpost" and not args.dry_run:
            # Judge a sample that actually passed, not a blind __k1 which
            # may have failed while a later attempt clinched the majority.
            verdict = judge.judge_scenario(
                scenario, fix_pass_dir or run_dir / f"{scenario.id}__fix{attempt}__k1")
            if verdict["passed"] is not True:
                # A None verdict (degraded quorum) is NOT a
                # confirmation — a goalpost fix stands only on an
                # explicit judge pass; anything else reverts.
                reason = ("goalpost fix rejected by judge re-confirm"
                          if verdict["passed"] is False else
                          "goalpost fix not confirmed by judge "
                          "(inconclusive verdict)")
                outcome["summary"].append(f"{reason}; reverting")
                break
        regressed = await suite_regression(
            scenario, all_scenarios, registry, run_dir, args, attempt)
        if regressed:
            outcome["summary"].append(
                f"fix regressed scenario {regressed}; reverting")
            break
        fixed = True
        break

    if fixed:
        outcome["result"] = "pass"
        outcome["summary"].append(
            f"fixed by modifying {sorted(set(applied_all))}")
    else:
        if applied_all:
            fixer.restore_snapshot(
                args.repo_root, sorted(set(applied_all)), pre_fix_snapshot,
                quarantine_dir=run_dir / scenario.id / "rejected_fix")
            outcome["summary"].append(
                f"fix reverted: {sorted(set(applied_all))}")
            outcome["result"] = "fail"
        if fixer_infra and not applied_all:
            # Fixer INFRA failure with zero fixes attempted: that's the
            # harness's problem, not evidence Sam struggles here — a
            # needs_human flag would poison weak_scenario_ids (the
            # generator would target this scenario as "weak"). A
            # distinct marker keeps it visible in results/report.
            outcome["fixer_infra"] = True
            outcome["summary"].append(
                "fixer_infra: no fix attempted (fixer infrastructure "
                "failed), not a Sam weakness")
        else:
            sam_registry.set_needs_human(registry, scenario.id)
            outcome["summary"].append("needs-human")
    return FixOutcome(fixed=fixed, fix_budget=fix_budget)


def _pass_rate(outcomes, holdout: bool):
    group = [o for o in outcomes if bool(o.get("holdout", False)) == holdout]
    # Infra errors are non-decisive: they are not Sam failures and must not
    # depress the rate (matching sam_registry.pass_rate) — but they must stay
    # visible, so they're surfaced as an explicit count.
    decisive = [o for o in group if o["result"] in ("pass", "fail")]
    passed = sum(1 for o in decisive if o["result"] == "pass")
    errors = sum(1 for o in group if o["result"] == "error")
    return {"passed": passed, "total": len(decisive), "errors": errors,
            "rate": round(passed / len(decisive), 3) if decisive else None}


def write_report(run_dir: Path, run_id: str, outcomes, repo_root: Path,
                 pass_rate: dict) -> None:
    lines = [f"# Sam training run {run_id}", "",
             "| scenario | result | notes |", "|---|---|---|"]
    for o in outcomes:
        # Escape "|" in check details so a needle like "A | B" can't break
        # the Markdown table into extra columns.
        notes = ("; ".join(o["summary"])[:300] or "-").replace("|", "\\|")
        lines.append(f"| {o['id']} | {o['result']} | {notes} |")
    lines += ["", "## Fixes"]
    fixes = [(o["id"], f) for o in outcomes for f in o.get("fixes", [])]
    if fixes:
        for sid, f in fixes:
            lines.append(f"- {sid}: applied {f['applied'] or '(none)'} "
                         f"[{f.get('provenance', 'n/a')}]; "
                         f"auto-reverted (outside allowlist): {f['reverted'] or '(none)'}")
            for violation in f.get("protocol_violation", []):
                lines.append(f"  - PROTOCOL VIOLATION: {violation}")
    else:
        lines.append("- none")
    hold = pass_rate["holdout"]
    train = pass_rate["train"]
    lines += ["", "## Pass rate (decisive runs only)",
              f"- holdout (headline): {hold['passed']}/{hold['total']} "
              f"({hold['rate']}), errors: {hold['errors']}",
              f"- train: {train['passed']}/{train['total']} "
              f"({train['rate']}), errors: {train['errors']}"]
    stat = subprocess.run(["git", "-C", str(repo_root), "diff", "--stat"],
                          capture_output=True, text=True).stdout
    lines += ["", "## Working tree (git diff --stat)", "```",
              stat.strip() or "(clean)", "```", ""]
    (run_dir / "report.md").write_text("\n".join(lines))


async def main(argv=None):
    args = parse_args(argv)
    if not (args.repo_root / TEMPLATE_DIR).exists():
        sys.exit(f"repo root looks wrong: {TEMPLATE_DIR} not found under {args.repo_root}")
    all_scenarios = load_scenarios(args.scenarios_dir)
    by_id = {s.id: s for s in all_scenarios}
    selected = all_scenarios
    if args.scenarios:
        missing = set(args.scenarios) - set(by_id)
        if missing:
            sys.exit(f"Unknown scenario ids: {sorted(missing)}")
        selected = [by_id[i] for i in args.scenarios]
    if args.limit:
        selected = selected[: args.limit]
    if args.fix:
        fixer.ensure_allowlist_clean(args.repo_root)
        print("NOTE: fixing is enabled — avoid editing this repository while "
              "the run is active; concurrent edits can be misattributed to "
              "the fixer and auto-reverted (quarantined under the run dir).")

    # One run at a time per registry: the load-once/save-whole cycle below
    # means a second concurrent run would silently clobber this one's records.
    try:
        registry_lock = sam_registry.acquire_lock(args.registry)
    except sam_registry.RegistryLockError as e:
        sys.exit(str(e))
    try:
        await _run_suite(args, selected, all_scenarios)
    finally:
        sam_registry.release_lock(registry_lock)


async def _run_suite(args, selected, all_scenarios):
    registry = sam_registry.load(args.registry)
    base_id = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    run_id, n = base_id, 1
    while (args.runs_dir / run_id).exists():
        n += 1
        run_id = f"{base_id}-{n}"
    run_dir = args.runs_dir / run_id
    run_dir.mkdir(parents=True)
    fix_budget = args.fix_budget
    outcomes = []
    consecutive_errors = 0

    for scenario in selected:
        status, summary = await execute_scenario(
            scenario, run_dir / scenario.id, args)
        outcome = {"id": scenario.id, "result": status,
                   "summary": list(summary), "fixes": [],
                   "holdout": is_holdout(scenario)}

        # Confirm any fail with best-of-k before reacting (generalizes the old
        # single flake re-run). Passing scenarios stay single-sample.
        if status == "fail":
            status, _ = await best_of_k(scenario, run_dir / scenario.id, args)
            outcome["result"] = status
            if status == "pass":
                outcome["summary"].append(
                    "flaky: failed once, passed best-of-k confirmation")

        # "error" outcomes (harness/infra problems) deliberately skip the
        # flake guard, the fixer, and needs_human — they mean the harness,
        # not Sam, needs attention; they stay visible in registry + report.
        if status == "fail" and args.fix and not outcome["holdout"]:
            fix_outcome = await attempt_fixes(
                scenario, outcome, registry=registry,
                all_scenarios=all_scenarios, run_dir=run_dir, args=args,
                fix_budget=fix_budget)
            fix_budget = fix_outcome.fix_budget

        fix_record = None
        if outcome["result"] == "pass" and outcome["fixes"]:
            fix_files = sorted({f for fx in outcome["fixes"] for f in fx["applied"]})
            fix_record = {"run": run_id, "files": fix_files,
                          "provenance": fixer.fix_provenance(fix_files)}
        sam_registry.record_run(registry, scenario.id, run_id,
                                outcome["result"], fix=fix_record)
        sam_registry.save(args.registry, registry)
        outcomes.append(outcome)
        print(f"[{outcome['result'].upper():5}] {scenario.id}")
        consecutive_errors = (consecutive_errors + 1
                              if outcome["result"] == "error" else 0)
        if consecutive_errors >= ABORT_AFTER_CONSECUTIVE_ERRORS:
            print(f"Aborting: the last {consecutive_errors} scenarios all "
                  "ended in 'error' — the harness/environment is broken "
                  "(check the API key and endpoint), this is not a Sam "
                  "problem. Fix it and re-run.")
            break

    pass_rate = {"train": _pass_rate(outcomes, False),
                 "holdout": _pass_rate(outcomes, True)}
    (run_dir / "results.json").write_text(
        json.dumps({"run": run_id, "pass_rate": pass_rate, "outcomes": outcomes}, indent=2))
    write_report(run_dir, run_id, outcomes, args.repo_root, pass_rate)
    print(f"\nReport: {run_dir / 'report.md'}")
    stat = subprocess.run(["git", "-C", str(args.repo_root), "diff", "--stat"],
                          capture_output=True, text=True).stdout.strip()
    if stat:
        print("\nWorking tree changes (review before committing):\n" + stat)


if __name__ == "__main__":
    asyncio.run(main())
