import asyncio
import json

import pytest

import run_loop
import sam_runner
from conftest import make_claude_stub, make_scenario, make_tmp_repo

PASS_SCENARIO = {
    "id": "dry_pass_001", "name": "Dry pass", "prompt": "change the heading",
    "checks": {
        "expected_tools": ["branch_and_edit_content"],
        "files_changed": ["content/pages/index.mdx"],
        "file_contains": {"content/pages/index.mdx": ["DRY RUN MARKER"]},
    },
    "dry_run": {
        "text": "done",
        "tool_calls": [{"name": "branch_and_edit_content", "args": {}}],
        "edits": {"content/pages/index.mdx":
                  "---\ntitle: Home\n---\nDRY RUN MARKER\n"},
    },
}

FAIL_SCENARIO = {
    "id": "dry_fail_001", "name": "Dry fail", "prompt": "change the heading",
    "checks": {
        "expected_tools": ["branch_and_edit_content"],
        "file_contains": {"content/pages/index.mdx": ["WANTED TEXT"]},
    },
    "dry_run": {
        "text": "did something else",
        "tool_calls": [{"name": "branch_and_edit_content", "args": {}}],
        "edits": {"content/pages/index.mdx":
                  "---\ntitle: Home\n---\nwrong content\n"},
    },
}


def _setup(tmp_path, *scenarios, registry=None):
    corpus = tmp_path / "scenarios" / "seed"
    corpus.mkdir(parents=True)
    (corpus / "s.json").write_text(json.dumps(list(scenarios)))
    env = {
        "scenarios_dir": tmp_path / "scenarios",
        "registry": tmp_path / "registry.json",
        "runs_dir": tmp_path / "runs",
        "repo": make_tmp_repo(tmp_path),
    }
    if registry is not None:
        env["registry"].write_text(json.dumps(registry))
    return env


def _run(env, *extra, dry=True):
    asyncio.run(run_loop.main([
        *(["--dry-run"] if dry else []),
        "--scenarios-dir", str(env["scenarios_dir"]),
        "--registry", str(env["registry"]),
        "--runs-dir", str(env["runs_dir"]),
        "--repo-root", str(env["repo"]),
        *extra,
    ]))


def _results(env):
    run_dirs = sorted(env["runs_dir"].iterdir())
    assert len(run_dirs) == 1
    return run_dirs[0], json.loads((run_dirs[0] / "results.json").read_text())


def test_dry_run_pass_records_results_and_registry(tmp_path):
    env = _setup(tmp_path, PASS_SCENARIO)
    _run(env)  # eval-only is the default
    run_dir, results = _results(env)
    assert results["outcomes"][0]["result"] == "pass"
    scen_dir = run_dir / "dry_pass_001"
    for artifact in ("scenario.json", "response.txt", "tool_calls.json",
                     "diff.patch", "verification.json"):
        assert (scen_dir / artifact).exists(), artifact
    assert (run_dir / "report.md").exists()
    registry = json.loads(env["registry"].read_text())
    assert registry["dry_pass_001"]["runs"][-1]["result"] == "pass"


def test_dry_run_fail_with_fix_reverts_and_flags_needs_human(tmp_path, monkeypatch):
    env = _setup(tmp_path, FAIL_SCENARIO)
    # stub "fixes" an allowlisted file; the dry-run replay still fails,
    # so the loop must revert the fix and flag the scenario
    body = ('import pathlib\n'
            'pathlib.Path("src/agent/prompts.py").write_text("CHANGED\\n")\n'
            'print("done")')
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    _run(env, "--fix", "--max-fix-attempts", "1")
    _, results = _results(env)
    outcome = results["outcomes"][0]
    assert outcome["result"] == "fail"
    assert outcome["fixes"][0]["applied"] == ["src/agent/prompts.py"]
    # fix was reverted
    assert (env["repo"] / "src" / "agent" / "prompts.py").read_text() == \
        "BASE_SYSTEM_INSTRUCTION = 'original'\n"
    registry = json.loads(env["registry"].read_text())
    assert registry["dry_fail_001"]["needs_human"] is True


def test_fixer_infra_failure_is_handled_not_fatal(tmp_path, monkeypatch):
    env = _setup(tmp_path, FAIL_SCENARIO)
    # stub claude exits non-zero -> ClaudeCliError from run_fixer; the loop
    # must record the failure and continue, not crash. With ZERO fixes
    # attempted this is a harness problem, not evidence Sam struggles here:
    # needs_human must NOT be set (it feeds weak_scenario_ids -> the
    # generator), and a distinct fixer_infra marker must be visible instead.
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, "sys.exit(7)")))
    _run(env, "--fix", "--max-fix-attempts", "1")
    _, results = _results(env)
    outcome = results["outcomes"][0]
    assert outcome["result"] == "fail"
    assert any("fixer error" in s for s in outcome["summary"])
    assert outcome["fixer_infra"] is True
    assert any("fixer_infra" in s for s in outcome["summary"])
    assert not any("needs-human" in s for s in outcome["summary"])
    registry = json.loads(env["registry"].read_text())
    assert registry["dry_fail_001"]["needs_human"] is False


def test_results_include_train_holdout_passrate(tmp_path):
    env = _setup(tmp_path, PASS_SCENARIO)
    _run(env)
    _, results = _results(env)
    assert "pass_rate" in results
    assert "train" in results["pass_rate"] and "holdout" in results["pass_rate"]
    assert results["outcomes"][0]["holdout"] in (True, False)


def test_suite_regression_confirms_flake_is_not_a_regression(tmp_path, monkeypatch):
    # A previously-passing scenario that flakes (fails once, then passes
    # best-of-k) must NOT be reported as a regression — otherwise a single flaky
    # eval falsely reverts a genuinely good fix (seen live: a working
    # gallery_homepage_001 fix reverted because hero_title_001 flaked once).
    target = make_scenario(id="target_001")
    other = make_scenario(id="other_001", split="train")
    registry = {"other_001": {"runs": [{"run": "r0", "result": "pass"}]}}
    seq = iter(["fail", "pass", "pass"])

    async def fake_exec(scenario, scen_dir, args):
        return next(seq), []

    monkeypatch.setattr(run_loop, "execute_scenario", fake_exec)
    args = run_loop.parse_args(["--k", "3"])
    regressed = asyncio.run(run_loop.suite_regression(
        target, [target, other], registry, tmp_path, args, attempt=1))
    assert regressed is None


def test_suite_regression_reports_confirmed_failure(tmp_path, monkeypatch):
    # A scenario that decisively fails best-of-k IS a real regression.
    target = make_scenario(id="target_001")
    other = make_scenario(id="other_001", split="train")
    registry = {"other_001": {"runs": [{"run": "r0", "result": "pass"}]}}

    async def fake_exec(scenario, scen_dir, args):
        return "fail", []

    monkeypatch.setattr(run_loop, "execute_scenario", fake_exec)
    args = run_loop.parse_args(["--k", "3"])
    regressed = asyncio.run(run_loop.suite_regression(
        target, [target, other], registry, tmp_path, args, attempt=1))
    assert regressed == "other_001"


def test_suite_regression_skips_holdout_scenarios(tmp_path, monkeypatch):
    # A holdout scenario that fails must NOT be reported as a regression —
    # otherwise fix acceptance is conditioned on holdout, biasing the headline.
    target = make_scenario(id="target_001")
    other = make_scenario(id="hold_001", split="holdout")
    registry = {"hold_001": {"runs": [{"run": "r0", "result": "pass"}]}}

    async def fake_exec(scenario, scen_dir, args):
        return "fail", []

    monkeypatch.setattr(run_loop, "execute_scenario", fake_exec)
    args = run_loop.parse_args(["--k", "3"])
    regressed = asyncio.run(run_loop.suite_regression(
        target, [target, other], registry, tmp_path, args, attempt=1))
    assert regressed is None


def test_suite_regression_reconfirms_a_single_best_of_k_fail(tmp_path, monkeypatch):
    # A near-threshold scenario can fail ONE best-of-k yet pass the next — the
    # whole best-of-k aggregate is itself flaky, so is_flaky (which sees only
    # aggregates) marks it not-flaky and can't catch this. A single best-of-k
    # FAIL must therefore be re-confirmed by a second best-of-k before it reverts
    # a good fix (seen live: a working newsletter_about_001 fix reverted on run
    # 21-22-02 because nav_update_001's best-of-k flaked to fail exactly once).
    target = make_scenario(id="target_001")
    other = make_scenario(id="other_001", split="train")
    registry = {"other_001": {"runs": [{"run": "r0", "result": "pass"}]}}
    # first best-of-k: fail,fail -> "fail"; re-confirm best-of-k: pass,pass -> "pass"
    seq = iter(["fail", "fail", "pass", "pass"])

    async def fake_exec(scenario, scen_dir, args):
        return next(seq), []

    monkeypatch.setattr(run_loop, "execute_scenario", fake_exec)
    args = run_loop.parse_args(["--k", "3"])
    regressed = asyncio.run(run_loop.suite_regression(
        target, [target, other], registry, tmp_path, args, attempt=1))
    assert regressed is None


def test_unknown_scenario_id_exits(tmp_path):
    env = _setup(tmp_path, PASS_SCENARIO)
    with pytest.raises(SystemExit):
        _run(env, "--scenarios", "nope_001")


def test_second_concurrent_run_fails_fast_on_registry_lock(tmp_path):
    import sam_registry
    env = _setup(tmp_path, PASS_SCENARIO)
    lock = sam_registry.acquire_lock(env["registry"])  # simulate a live run
    try:
        with pytest.raises(SystemExit, match="locked by a live run"):
            _run(env)
        assert not env["runs_dir"].exists()            # failed BEFORE running
    finally:
        sam_registry.release_lock(lock)
    _run(env)                                          # lock released -> runs
    _, results = _results(env)
    assert results["outcomes"][0]["result"] == "pass"
    # ... and the run released its own lock on exit
    assert not env["registry"].with_suffix(".json.lock").exists()


def test_best_of_k_majority_pass(tmp_path, monkeypatch):
    seq = iter(["fail", "pass", "pass"])

    async def fake_exec(scenario, scen_dir, args):
        return next(seq), []

    monkeypatch.setattr(run_loop, "execute_scenario", fake_exec)
    args = run_loop.parse_args(["--k", "3"])
    status, _ = asyncio.run(run_loop.best_of_k(make_scenario(), tmp_path / "s", args))
    assert status == "pass"


def test_best_of_k_all_error_returns_error(tmp_path, monkeypatch):
    # Every attempt is an infra "error" (no decisive pass/fail). best_of_k must
    # report "error" — not silently a fail — after exhausting the 2*k cap.
    calls = {"n": 0}

    async def fake_exec(scenario, scen_dir, args):
        calls["n"] += 1
        return "error", []

    monkeypatch.setattr(run_loop, "execute_scenario", fake_exec)
    args = run_loop.parse_args(["--k", "3"])
    status, _ = asyncio.run(run_loop.best_of_k(make_scenario(), tmp_path / "s", args))
    assert status == "error"
    assert calls["n"] == 6  # 2*k attempts, never reached a decisive majority


def test_best_of_k_early_exits_on_two_passes(tmp_path, monkeypatch):
    calls = {"n": 0}

    async def fake_exec(scenario, scen_dir, args):
        calls["n"] += 1
        return "pass", []

    monkeypatch.setattr(run_loop, "execute_scenario", fake_exec)
    args = run_loop.parse_args(["--k", "3"])
    status, _ = asyncio.run(run_loop.best_of_k(make_scenario(), tmp_path / "s", args))
    assert status == "pass"
    assert calls["n"] == 2  # stopped as soon as majority (2/3) was locked


def test_reload_agent_source_picks_up_on_disk_edits(tmp_path, monkeypatch):
    # Mirrors the real bug: site_editor does `from agent.prompts import
    # BASE_SYSTEM_INSTRUCTION`, so a fixer edit to prompts.py is invisible to a
    # long-lived run_loop process until the modules are reloaded IN ORDER
    # (dependency first). Without that, every behavioral fix was reverted.
    import sys
    monkeypatch.syspath_prepend(str(tmp_path))
    # Different-length bodies so the .pyc staleness check (mtime + size) forces a
    # recompile on reload — a real fixer prompt rewrite always changes the size.
    (tmp_path / "_reltest_dep.py").write_text("VALUE = 'before'\n")
    (tmp_path / "_reltest_use.py").write_text("from _reltest_dep import VALUE\n")
    try:
        import _reltest_dep  # noqa: F401
        import _reltest_use
        assert _reltest_use.VALUE == "before"

        # fixer-style on-disk edit; cached modules don't see it yet
        (tmp_path / "_reltest_dep.py").write_text("VALUE = 'after-the-edit'\n")
        assert _reltest_use.VALUE == "before"

        run_loop.reload_agent_source(modules=["_reltest_dep", "_reltest_use"])
        assert _reltest_use.VALUE == "after-the-edit"   # the cross-module rebind that was broken

        # a module that was never imported is skipped, not force-imported
        run_loop.reload_agent_source(modules=["_reltest_never_imported"])
    finally:
        for m in ("_reltest_dep", "_reltest_use"):
            sys.modules.pop(m, None)


def test_pass_rate_shape_and_holdout_split():
    outcomes = [
        {"result": "pass", "holdout": False},
        {"result": "fail", "holdout": False},
        {"result": "pass", "holdout": True},
    ]
    assert run_loop._pass_rate(outcomes, holdout=False) == {
        "passed": 1, "total": 2, "errors": 0, "rate": 0.5}
    # exercises the holdout=True branch
    assert run_loop._pass_rate(outcomes, holdout=True) == {
        "passed": 1, "total": 1, "errors": 0, "rate": 1.0}
    # empty group reports rate=None, never divides by zero
    assert run_loop._pass_rate([], holdout=True) == {
        "passed": 0, "total": 0, "errors": 0, "rate": None}


def test_pass_rate_excludes_infra_errors_from_denominator():
    # An infra "error" is not a Sam failure: it must not depress the headline
    # rate (matching sam_registry.pass_rate, which only counts decisive runs),
    # but it must stay visible via an explicit errors count.
    outcomes = [
        {"result": "pass", "holdout": False},
        {"result": "error", "holdout": False},
        {"result": "error", "holdout": False},
    ]
    assert run_loop._pass_rate(outcomes, holdout=False) == {
        "passed": 1, "total": 1, "errors": 2, "rate": 1.0}
    # all-error group: no decisive runs, rate is None (not 0.0)
    all_err = [{"result": "error", "holdout": False}]
    assert run_loop._pass_rate(all_err, holdout=False) == {
        "passed": 0, "total": 0, "errors": 1, "rate": None}


def test_report_surfaces_error_counts_and_escapes_pipes(tmp_path):
    # 1) infra error counts appear in the report's pass-rate lines;
    # 2) check details containing "|" must not break the Markdown table.
    run_dir = tmp_path / "r"
    run_dir.mkdir()
    outcomes = [
        {"id": "s1", "result": "fail",
         "summary": ["expected 'A | B' got 'C | D'"], "fixes": [],
         "holdout": False},
        {"id": "s2", "result": "error", "summary": [], "fixes": [],
         "holdout": False},
    ]
    pass_rate = {"train": run_loop._pass_rate(outcomes, False),
                 "holdout": run_loop._pass_rate(outcomes, True)}
    run_loop.write_report(run_dir, "test_run", outcomes,
                          make_tmp_repo(tmp_path), pass_rate)
    report = (run_dir / "report.md").read_text()
    assert "errors: 1" in report
    row = next(l for l in report.splitlines() if l.startswith("| s1 "))
    assert "\\|" in row                     # pipes escaped …
    assert row.count(" | ") == 2            # … so the table still has 3 columns


def test_fix_that_regresses_the_suite_is_reverted(tmp_path, monkeypatch):
    env = _setup(tmp_path, FAIL_SCENARIO, PASS_SCENARIO, registry={
        "dry_pass_001": {"runs": [{"run": "r0", "result": "pass"}],
                         "fixes": [], "flaky": False, "needs_human": False}})
    body = ('import pathlib\n'
            'pathlib.Path("src/agent/prompts.py").write_text("CHANGED\\n")\n'
            'print("done")')
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))

    async def scripted(scenario, scen_dir, args):
        scen_dir.mkdir(parents=True, exist_ok=True)
        (scen_dir / "verification.json").write_text(json.dumps(
            {"status": "fail", "layers": {"deterministic":
             {"status": "fail", "details": ["scripted"]}}}))
        name = scen_dir.name
        if name.startswith("dry_fail_001__fix"):
            return "pass", []          # fix "works" on the target
        if name.startswith("dry_fail_001"):
            return "fail", ["initial"] # initial + best-of-k confirm
        if name.startswith("dry_pass_001"):
            return "fail", ["regressed"]  # the fix broke a passing scenario
        return "pass", []

    monkeypatch.setattr(run_loop, "execute_scenario", scripted)
    _run(env, "--fix", "--scenarios", "dry_fail_001",
         "--max-fix-attempts", "1", "--k", "1")
    _, results = _results(env)
    outcome = results["outcomes"][0]
    assert outcome["result"] == "fail"
    assert any("regressed" in s for s in outcome["summary"])
    assert (env["repo"] / "src/agent/prompts.py").read_text() == \
        "BASE_SYSTEM_INSTRUCTION = 'original'\n"
    registry = json.loads(env["registry"].read_text())
    assert registry["dry_fail_001"]["needs_human"] is True


def test_goalpost_fix_rejected_by_judge_is_reverted(tmp_path, monkeypatch):
    # A fix that edits a GOALPOST file (content_validator.py) and "passes"
    # best-of-k must still be reverted when the judge re-confirm rejects it.
    # Runs WITHOUT --dry-run so the goalpost judge-reconfirm branch executes;
    # execute_scenario and judge.judge_scenario are stubbed so no live model runs.
    env = _setup(tmp_path, FAIL_SCENARIO)
    # fixer stub edits an allowlisted GOALPOST file
    body = ('import pathlib\n'
            'pathlib.Path("src/agent/content_validator.py")'
            '.write_text("# changed by fixer\\n")\n'
            'print("done")')
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))

    async def scripted(scenario, scen_dir, args):
        scen_dir.mkdir(parents=True, exist_ok=True)
        (scen_dir / "verification.json").write_text(json.dumps(
            {"status": "fail", "layers": {"deterministic":
             {"status": "fail", "details": ["scripted"]}}}))
        # the fix "works" deterministically; the judge is what rejects it
        return ("pass", []) if scen_dir.name.startswith("dry_fail_001__fix") \
            else ("fail", ["initial"])

    monkeypatch.setattr(run_loop, "execute_scenario", scripted)
    monkeypatch.setattr("judge.judge_scenario",
                        lambda scenario, run_dir: {
                            "passed": False, "reasoning": "moved the goalposts",
                            "issues": ["loosened validator"]})
    _run(env, "--fix", "--scenarios", "dry_fail_001",   # NOT --dry-run
         "--max-fix-attempts", "1", "--k", "1", dry=False)
    _, results = _results(env)
    outcome = results["outcomes"][0]
    assert outcome["result"] == "fail"
    assert any("goalpost fix rejected" in s for s in outcome["summary"])
    # the goalpost edit must be reverted to its original content
    assert (env["repo"] / "src/agent/content_validator.py").read_text() == \
        "# content_validator\n"
    registry = json.loads(env["registry"].read_text())
    assert registry["dry_fail_001"]["needs_human"] is True


def test_run_aborts_on_trailing_consecutive_errors(tmp_path, monkeypatch):
    # One early pass must NOT disarm the dead-environment guard: a mid-run
    # quota death shows up as a trailing error streak and must abort instead of
    # thrashing the remaining suite. A pass resets the streak.
    scenarios = [{**PASS_SCENARIO, "id": f"seq_{i:03}", "name": f"Seq {i}"}
                 for i in range(10)]
    env = _setup(tmp_path, *scenarios)
    # error,error,PASS (streak resets), then 3 straight errors => abort at #6
    seq = iter(["error", "error", "pass", "error", "error", "error",
                "pass", "pass", "pass", "pass"])
    calls = []

    async def fake_exec(scenario, scen_dir, args):
        calls.append(scenario.id)
        return next(seq), []

    monkeypatch.setattr(run_loop, "execute_scenario", fake_exec)
    _run(env)
    assert len(calls) == 6          # aborted mid-run, streak reset by the pass
    _, results = _results(env)
    assert [o["result"] for o in results["outcomes"]] == \
        ["error", "error", "pass", "error", "error", "error"]


def test_run_aborts_early_when_every_scenario_errors(tmp_path, monkeypatch):
    # A dead key errors every scenario identically; the loop must stop after
    # the first few instead of thrashing the whole suite.
    scenarios = [{**PASS_SCENARIO, "id": f"err_{i:03}", "name": f"Err {i}"}
                 for i in range(5)]
    env = _setup(tmp_path, *scenarios)
    calls = []

    async def fake_exec(scenario, scen_dir, args):
        calls.append(scenario.id)
        return "error", ["infra: AuthenticationError 401"]

    monkeypatch.setattr(run_loop, "execute_scenario", fake_exec)
    _run(env)
    assert len(calls) == 3          # aborted after 3 straight errors, not 5
    _, results = _results(env)
    assert [o["result"] for o in results["outcomes"]] == ["error"] * 3


@pytest.mark.asyncio
async def test_judge_inconclusive_verdict_routes_to_error_not_pass(tmp_path, monkeypatch):
    # A degraded-quorum panel returns passed=None; the scenario must surface as
    # non-decisive "error" (topped up / flagged), never silently stay "pass".
    args = run_loop.parse_args(["--runs-dir", str(tmp_path / "runs")])
    scenario = make_scenario(is_init=True, checks={"judge": "did it work"})

    async def fake_run_sam(scenario, provider, model):
        return sam_runner.SamRunResult(text="all done")

    monkeypatch.setattr(run_loop.sam_runner, "run_sam", fake_run_sam)
    monkeypatch.setattr("judge.judge_scenario",
                        lambda scenario, scen_dir: {
                            "passed": None, "reasoning": "degraded quorum",
                            "issues": []})
    status, summary = await run_loop.execute_scenario(
        scenario, tmp_path / "art", args)
    assert status == "error"
    assert any("degraded quorum" in s for s in summary)
    verification = json.loads(
        (tmp_path / "art" / "verification.json").read_text())
    assert verification["status"] == "error"
    assert verification["layers"]["judge"]["status"] == "error"


def test_goalpost_fix_with_inconclusive_judge_is_reverted(tmp_path, monkeypatch):
    # The goalpost gate exists because such fixes can pass by neutralizing the
    # check; an INCONCLUSIVE judge re-confirm (passed=None) is not a
    # confirmation — the fix must be reverted, same as an explicit rejection.
    env = _setup(tmp_path, FAIL_SCENARIO)
    body = ('import pathlib\n'
            'pathlib.Path("src/agent/content_validator.py")'
            '.write_text("# changed by fixer\\n")\n'
            'print("done")')
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))

    async def scripted(scenario, scen_dir, args):
        scen_dir.mkdir(parents=True, exist_ok=True)
        (scen_dir / "verification.json").write_text(json.dumps(
            {"status": "fail", "layers": {"deterministic":
             {"status": "fail", "details": ["scripted"]}}}))
        return ("pass", []) if scen_dir.name.startswith("dry_fail_001__fix") \
            else ("fail", ["initial"])

    monkeypatch.setattr(run_loop, "execute_scenario", scripted)
    monkeypatch.setattr("judge.judge_scenario",
                        lambda scenario, run_dir: {
                            "passed": None, "reasoning": "degraded quorum",
                            "issues": []})
    _run(env, "--fix", "--scenarios", "dry_fail_001",   # NOT --dry-run
         "--max-fix-attempts", "1", "--k", "1", dry=False)
    _, results = _results(env)
    outcome = results["outcomes"][0]
    assert outcome["result"] == "fail"
    assert any("inconclusive" in s for s in outcome["summary"])
    assert (env["repo"] / "src/agent/content_validator.py").read_text() == \
        "# content_validator\n"


@pytest.mark.asyncio
async def test_sam_error_goes_to_error_txt_not_response_txt(tmp_path, monkeypatch):
    # response.txt is judge/fixer evidence of what Sam SAID; a crash/error
    # string there conflates the reply with a harness message. Errors get
    # their own artifact.
    args = run_loop.parse_args(["--dry-run", "--runs-dir", str(tmp_path / "runs")])
    scenario = make_scenario(is_init=True)
    monkeypatch.setattr(
        run_loop.sam_runner, "run_sam_dry",
        lambda scenario, project_dir: sam_runner.SamRunResult(error="Boom: crash"))
    scen_dir = tmp_path / "art"
    status, _ = await run_loop.execute_scenario(scenario, scen_dir, args)
    assert status == "fail"
    assert (scen_dir / "response.txt").read_text() == ""
    assert (scen_dir / "error.txt").read_text() == "Boom: crash"


@pytest.mark.asyncio
async def test_no_error_txt_when_sam_replied_cleanly(tmp_path):
    args = run_loop.parse_args(["--dry-run", "--runs-dir", str(tmp_path / "runs")])
    scenario = make_scenario(is_init=True, dry_run={"text": "done", "tool_calls": []})
    scen_dir = tmp_path / "art"
    await run_loop.execute_scenario(scenario, scen_dir, args)
    assert (scen_dir / "response.txt").read_text() == "done"
    assert not (scen_dir / "error.txt").exists()


def test_workspace_deleted_after_verification_by_default(tmp_path):
    # runs/ grows ~150MB per suite from node_modules/dist per attempt; the
    # judge/fixer only read the artifact files, so the workspace is deleted
    # once verification (and judging) is done.
    env = _setup(tmp_path, PASS_SCENARIO)
    _run(env)
    run_dir, results = _results(env)
    assert results["outcomes"][0]["result"] == "pass"
    scen_dir = run_dir / "dry_pass_001"
    assert not (scen_dir / "workspace").exists()
    # every judgeable artifact is still there
    for artifact in ("scenario.json", "response.txt", "tool_calls.json",
                     "diff.patch", "verification.json"):
        assert (scen_dir / artifact).exists(), artifact


def test_workspace_kept_with_keep_workspaces_flag(tmp_path):
    env = _setup(tmp_path, PASS_SCENARIO)
    _run(env, "--keep-workspaces")
    run_dir, _ = _results(env)
    assert (run_dir / "dry_pass_001" / "workspace").exists()


@pytest.mark.asyncio
async def test_execute_scenario_writes_transcript_for_multi_turn(tmp_path):
    # The judge assesses sequencing (e.g. published only after the go-ahead)
    # from the conversation, so multi-turn runs must persist it as an artifact.
    args = run_loop.parse_args(["--dry-run", "--runs-dir", str(tmp_path / "runs")])
    scenario = make_scenario(
        turns=[{"prompt": "change the tagline"}, {"prompt": "publish"}],
        checks={"expected_tools": ["branch_and_edit_content"]},
        dry_run={"text": "done",
                 "tool_calls": [{"name": "branch_and_edit_content", "args": {}}],
                 "edits": {"content/settings.yaml": "site:\n  name: X\n"}})
    scen_dir = tmp_path / "art"
    status, summary = await run_loop.execute_scenario(scenario, scen_dir, args)
    assert status == "pass", summary
    transcript = json.loads((scen_dir / "transcript.json").read_text())
    assert [t["role"] for t in transcript] == ["user", "user", "agent"]
