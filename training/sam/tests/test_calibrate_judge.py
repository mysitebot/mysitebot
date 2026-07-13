import json

import calibrate_judge
from conftest import make_claude_stub


def _case_dir(tmp_path, name, baseline_passed, judge_criteria="looks right"):
    d = tmp_path / name
    d.mkdir()
    (d / "scenario.json").write_text(json.dumps({
        "id": name, "name": name, "prompt": "change the title",
        "negative": False, "checks": {"judge": judge_criteria}}))
    (d / "judge.json").write_text(json.dumps({
        "passed": baseline_passed, "reasoning": "baseline", "issues": []}))
    return d


def test_calibrate_compares_candidate_against_baseline(tmp_path, monkeypatch):
    # Candidate stub always votes PASS: it should agree with the baseline-pass
    # dir and disagree with the baseline-fail dir.
    body = ('print(json.dumps({"result": json.dumps('
            '{"passed": True, "reasoning": "cand", "issues": []})}))')
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    good = _case_dir(tmp_path, "good_pass", True)
    bad = _case_dir(tmp_path, "missed_fail", False)

    report = calibrate_judge.calibrate([good, bad], "claude-sonnet-5")

    s = report["summary"]
    assert s["candidate"] == "claude-sonnet-5"
    assert (s["pass_cases_agreed"], s["pass_cases"]) == (1, 1)
    assert (s["fail_cases_caught"], s["fail_cases"]) == (0, 1)
    by_dir = {r["dir"]: r for r in report["rows"] if "agree" in r}
    assert by_dir[str(good)]["agree"] is True
    assert by_dir[str(bad)]["agree"] is False


def test_calibrate_skips_dirs_without_judge_verdict(tmp_path, monkeypatch):
    body = ('print(json.dumps({"result": json.dumps('
            '{"passed": True, "reasoning": "cand", "issues": []})}))')
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    no_judge = tmp_path / "deterministic_fail"
    no_judge.mkdir()
    (no_judge / "scenario.json").write_text(json.dumps(
        {"id": "x", "name": "x", "prompt": "p", "checks": {}}))

    report = calibrate_judge.calibrate([no_judge], "claude-sonnet-5")

    assert report["summary"]["cases"] == 0
    assert report["rows"][0]["skipped"]
