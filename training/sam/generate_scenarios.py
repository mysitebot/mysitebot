#!/usr/bin/env python3
"""Generate new training scenarios with the headless claude CLI (read-only)."""
import argparse
import asyncio
import json
import re
import tempfile
from pathlib import Path

from _paths import SAM_DIR, bootstrap

_REPO = bootstrap()

import claude_cli
import sam_registry
import sam_runner
import verifier
from scenario_schema import load_scenarios, parse_scenario_dict

DIRECTIVE_PATH = SAM_DIR / "directives" / "generator.md"

# expected_tools must assert the OUTCOME (edit tools), never the discovery
# path: a correct solution may legitimately skip list/read (e.g. the site
# snapshot in the system prompt already shows the file), so mandating them
# false-fails good runs (settings_name_rebrand_001 lesson, session 7).
DISCOVERY_TOOLS = {"read_content_file", "list_content_files"}


def _tokens(text: str):
    return set(re.findall(r"[a-z']+", text.lower()))


def is_duplicate(prompt: str, existing_prompts, threshold: float = 0.8) -> bool:
    candidate = _tokens(prompt)
    for existing in existing_prompts:
        other = _tokens(existing)
        union = candidate | other
        if union and len(candidate & other) / len(union) >= threshold:
            return True
    return False


def structural_violation(scenario):
    """Reject shapes validate_candidate cannot catch — a dry_run reference can
    fake-satisfy these offline while the live scenario is unjudgeable or
    unwinnable. Returns a reason string, or None if the shape is sound."""
    # Tripwire heuristic, NOT a guarantee: a criterion can name these cues
    # without honoring them, but their absence reliably marks the wrong shape.
    # The directive mandates both a transcript.json reference and explicit
    # "Fail if ..." clauses; the bare substring "transcript" alone was
    # keyword-bypassable (name the word, still judge only the final reply).
    judge_text = (scenario.checks.judge or "").lower()
    if scenario.turns and not ("transcript" in judge_text
                               and "fail if" in judge_text):
        return ("multi-turn scenarios need a transcript-aware judge criterion "
                "(read transcript.json, per-turn expectations, explicit "
                "'Fail if ...' clauses) — response.txt holds only the LAST "
                "reply, so a final-reply-only criterion judges the wrong "
                "evidence")
    if not scenario.turns and re.search(r"\[Turn\s*\d|\[SYSTEM\]", scenario.prompt):
        # Seen live: the generator pasted the synthesized "[Turn 1 — user]: ..."
        # rendering (the shape it sees in EXISTING SCENARIOS) into a single
        # prompt string. site_editor scrubs such markers from user input, so
        # this is one weird message, not a conversation.
        return ("prompt contains turn/[SYSTEM] markers — those are synthesized "
                "by the harness; author a real conversation via 'turns' (and "
                "is_system flags), never marker text in 'prompt'")
    if scenario.is_init:
        # Onboarding starts from an EMPTY workspace, and live create_project
        # provisions a NEW project dir outside the measured workspace.
        if scenario.setup:
            return "is_init starts from an EMPTY workspace — setup is not allowed"
        c = scenario.checks
        if (c.files_changed or c.file_contains or c.file_not_contains
                or c.files_absent or c.build or c.dom):
            return ("is_init scenarios cannot use file/build/dom checks — live "
                    "create_project writes outside the measured workspace, so "
                    "they never pass; assert expected_tools/response/judge only")
    return None


def _quarantine(out_dir: Path, scenario_id: str, raw) -> None:
    quarantine = out_dir / "rejected"
    quarantine.mkdir(parents=True, exist_ok=True)
    (quarantine / f"{scenario_id}.json").write_text(json.dumps(raw, indent=2))


def validate_candidate(raw):
    """Replay the candidate's dry_run reference through the FULL verifier
    (deterministic checks plus, for build/dom scenarios, a real npm build +
    headless render). Returns (ok, reason). A candidate with no dry_run is
    rejected — we can't prove its checks are satisfiable.

    Build+dom matter because a reference can satisfy the deterministic checks
    (file_contains/tools) yet use a content format that never renders — e.g. a
    YAML `sections:` block in frontmatter instead of the template's MDX/JSX
    components. file_contains then passes (the literal strings are in the file)
    but the page builds empty and the dom checks fail. Gating on build+dom here
    stops the generator promoting such non-rendering references."""
    if not raw.get("dry_run"):
        return False, "no dry_run reference solution"
    try:
        scenario = parse_scenario_dict(raw, "candidate")
    except Exception as e:
        return False, f"unparseable: {e}"

    async def _run():
        with tempfile.TemporaryDirectory() as td:
            scen_dir = Path(td)
            _, project_dir = await sam_runner.provision_workspace(scen_dir, scenario)
            run_result = sam_runner.run_sam_dry(scenario, project_dir)
            changes = sam_runner.workspace_changes(project_dir)
            artifacts = scen_dir / "artifacts"
            return await verifier.verify(
                project_dir, scenario, run_result, artifacts, changes)

    try:
        result = asyncio.run(_run())
    except Exception as e:
        # A structurally malformed candidate (e.g. dry_run.tool_calls authored
        # as bare strings instead of {name, args} objects) must be rejected with
        # a reason — never crash the whole generation batch.
        return False, f"reference crashed validation: {type(e).__name__}: {e}"
    if result.status == "pass":
        return True, "reference satisfies its own checks (deterministic + build + dom)"
    # Name the failing layer(s) so the reason points at the real problem: a
    # missing needle, a build error, or a dom assertion that never rendered.
    details = [f"[{name}] {d}"
               for name, layer in result.layers.items()
               if layer.status != "pass" for d in layer.details]
    return False, "; ".join(details) or "reference failed its own checks"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--from-websight", default=None,
                        help="websight sample id whose idea.txt seeds inspiration")
    parser.add_argument("--scenarios-dir", type=Path,
                        default=SAM_DIR / "scenarios")
    parser.add_argument("--registry", type=Path,
                        default=SAM_DIR / "registry.json",
                        help="path to sam_registry.json for weak-scenario targeting")
    args = parser.parse_args(argv)

    existing = load_scenarios(args.scenarios_dir)
    existing_ids = {s.id for s in existing}
    existing_prompts = [s.prompt for s in existing]

    sections_path = _REPO / "projects" / "agent" / "templates" / "SECTIONS.md"
    sections = sections_path.read_text()[:8000] if sections_path.exists() else "(none)"
    inspiration = "(none)"
    if args.from_websight:
        idea = SAM_DIR.parent / "data" / args.from_websight / "idea.txt"
        if idea.exists():
            inspiration = idea.read_text()[:2000]

    registry = sam_registry.load(args.registry)
    weak = sam_registry.weak_scenario_ids(registry)
    weak_block = ("\n".join(f"- {w}" for w in weak)
                  or "(suite is all green — generate net-new hard scenarios)")

    prompt = (DIRECTIVE_PATH.read_text()
              .replace("{{count}}", str(args.count))
              .replace("{{sections}}", sections)
              .replace("{{existing_scenarios}}",
                       "\n".join(f"- {s.id}: {s.prompt}" for s in existing))
              .replace("{{inspiration}}", inspiration)
              .replace("{{weak_scenarios}}", weak_block))

    stdout = claude_cli.run_claude(prompt, mode="plan", cwd=_REPO)
    payload = claude_cli.extract_json_payload(stdout)
    if isinstance(payload, dict):
        raw_items = payload.get("scenarios")
        if raw_items is None:
            # A single scenario object emitted without the {"scenarios": [...]}
            # wrapper used to yield [] silently (nothing written, nothing
            # skipped, no clue why); a dict carrying an "id" is a scenario —
            # treat it as a one-item batch.
            raw_items = [payload] if payload.get("id") else []
    else:
        raw_items = payload

    out_dir = args.scenarios_dir / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    written, skipped = [], []
    for raw in raw_items:
        if not isinstance(raw, dict):
            skipped.append(f"(non-dict item) {str(raw)[:80]!r}")
            continue
        try:
            scenario = parse_scenario_dict(raw, "generated")
        except Exception as e:
            skipped.append(f"{raw.get('id', '?')}: {e}")
            continue
        if scenario.id in existing_ids:
            skipped.append(f"{scenario.id}: id already exists")
            continue
        if is_duplicate(scenario.prompt, existing_prompts):
            skipped.append(f"{scenario.id}: near-duplicate prompt")
            continue
        bad_tools = DISCOVERY_TOOLS & set(scenario.checks.expected_tools)
        if bad_tools:
            _quarantine(out_dir, scenario.id, raw)
            skipped.append(
                f"{scenario.id}: expected_tools must be edit tools only, "
                f"got discovery tools {sorted(bad_tools)}")
            continue
        violation = structural_violation(scenario)
        if violation:
            _quarantine(out_dir, scenario.id, raw)
            skipped.append(f"{scenario.id}: {violation}")
            continue
        ok, reason = validate_candidate(raw)
        if not ok:
            _quarantine(out_dir, scenario.id, raw)
            skipped.append(f"{scenario.id}: reference invalid ({reason})")
            continue
        (out_dir / f"{scenario.id}.json").write_text(json.dumps(raw, indent=2))
        existing_ids.add(scenario.id)
        existing_prompts.append(scenario.prompt)
        written.append(scenario.id)

    print(f"wrote {len(written)}: {written}")
    if skipped:
        print(f"skipped {len(skipped)}: {skipped}")


if __name__ == "__main__":
    main()
