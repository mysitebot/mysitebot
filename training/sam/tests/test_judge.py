import json

import judge
from conftest import make_claude_stub, make_scenario


def test_judge_pass_verdict(tmp_path, monkeypatch):
    body = ('print(json.dumps({"result": json.dumps('
            '{"passed": True, "reasoning": "looks right", "issues": []})}))')
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    verdict = judge.judge_scenario(
        make_scenario(checks={"judge": "title updated"}), tmp_path)
    assert verdict["passed"] is True
    assert "looks right" in verdict["reasoning"]
    assert verdict["issues"] == []


def test_judge_fail_verdict(tmp_path, monkeypatch):
    body = ('print(json.dumps({"result": json.dumps('
            '{"passed": False, "reasoning": "wrong page", "issues": ["edited /about"]})}))')
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    verdict = judge.judge_scenario(make_scenario(), tmp_path)
    assert verdict["passed"] is False
    assert verdict["issues"] == ["edited /about"]


def test_judge_unparseable_output_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, 'print("complete garbage")')))
    verdict = judge.judge_scenario(make_scenario(), tmp_path)
    assert verdict["passed"] is None
    # 3 garbage votes → no boolean majority → inconclusive
    assert "3 unknown" in verdict["reasoning"]


def test_judge_panel_majority_pass(tmp_path, monkeypatch):
    body = '''
import json, pathlib
c = pathlib.Path("vote_count")
n = int(c.read_text()) if c.exists() else 0
c.write_text(str(n + 1))
verdicts = [True, True, False]
v = verdicts[n % 3]
print(json.dumps({"result": json.dumps(
    {"passed": v, "reasoning": "r", "issues": [] if v else ["nope"]})}))
'''
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    verdict = judge.judge_scenario(make_scenario(checks={"judge": "ok"}), tmp_path)
    assert verdict["passed"] is True   # 2 of 3
    assert verdict["issues"] == []     # a passing majority carries no issues


def _scripted_votes(monkeypatch, passed_values):
    votes = iter([{"passed": p,
                   "reasoning": f"vote says {p}",
                   "issues": [] if p in (True, None) else ["problem"]}
                  for p in passed_values])
    monkeypatch.setattr(judge, "_one_vote", lambda *a, **kw: next(votes))


def test_judge_degraded_quorum_one_yes_vote_is_not_decisive(tmp_path, monkeypatch):
    # Two errored votes silently degrade the panel to best-of-1; a single
    # boolean vote must NEVER decide the verdict.
    _scripted_votes(monkeypatch, [True, None, None])
    verdict = judge.judge_scenario(make_scenario(checks={"judge": "ok"}), tmp_path)
    assert verdict["passed"] is None
    assert "degraded quorum" in verdict["reasoning"]


def test_judge_degraded_quorum_one_no_vote_is_not_decisive(tmp_path, monkeypatch):
    _scripted_votes(monkeypatch, [False, None, None])
    verdict = judge.judge_scenario(make_scenario(checks={"judge": "ok"}), tmp_path)
    assert verdict["passed"] is None
    assert "degraded quorum" in verdict["reasoning"]


def test_judge_two_boolean_votes_still_decide(tmp_path, monkeypatch):
    # Losing ONE vote keeps a 2-vote quorum: a unanimous remainder is decisive.
    _scripted_votes(monkeypatch, [True, True, None])
    verdict = judge.judge_scenario(make_scenario(checks={"judge": "ok"}), tmp_path)
    assert verdict["passed"] is True


def test_judge_criteria_selection(tmp_path, monkeypatch):
    # Which rubric the panel is asked to apply depends on the scenario:
    # explicit checks.judge wins; otherwise negative scenarios get the refusal
    # rubric and the rest get the default one.
    seen = []

    def capture(prompt, mode, cwd, **kw):
        seen.append(prompt)
        return json.dumps({"result": json.dumps(
            {"passed": True, "reasoning": "ok", "issues": []})})

    monkeypatch.setattr(judge.claude_cli, "run_claude", capture)

    judge.judge_scenario(make_scenario(negative=True), tmp_path)
    assert judge.NEGATIVE_CRITERIA in seen[0]
    assert judge.DEFAULT_CRITERIA not in seen[0]

    seen.clear()
    judge.judge_scenario(make_scenario(), tmp_path)
    assert judge.DEFAULT_CRITERIA in seen[0]

    seen.clear()
    judge.judge_scenario(
        make_scenario(negative=True, checks={"judge": "custom rubric"}), tmp_path)
    assert "custom rubric" in seen[0]
    assert judge.NEGATIVE_CRITERIA not in seen[0]


def test_judge_panel_tie_is_unknown(tmp_path, monkeypatch):
    # vote 1 -> pass, vote 2 -> fail, vote 3 -> garbage. The third vote stays
    # unknown across BOTH of _one_vote's retry attempts (counter >= 2 always
    # garbage), so the panel sees 1 pass / 1 fail / 1 unknown -> no majority.
    body = '''
import json, pathlib
c = pathlib.Path("vote_count")
n = int(c.read_text()) if c.exists() else 0
c.write_text(str(n + 1))
if n == 0:
    print(json.dumps({"result": json.dumps({"passed": True, "reasoning": "r", "issues": []})}))
elif n == 1:
    print(json.dumps({"result": json.dumps({"passed": False, "reasoning": "r", "issues": ["x"]})}))
else:
    print("garbage")
'''
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    verdict = judge.judge_scenario(make_scenario(), tmp_path)
    assert verdict["passed"] is None


def test_judge_model_override_reaches_cli(tmp_path, monkeypatch):
    body = '''
import json, pathlib, sys
pathlib.Path("argv.json").write_text(json.dumps(sys.argv))
print(json.dumps({"result": json.dumps(
    {"passed": True, "reasoning": "r", "issues": []})}))
'''
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    verdict = judge.judge_scenario(
        make_scenario(checks={"judge": "ok"}), tmp_path,
        model="claude-sonnet-5")
    assert verdict["passed"] is True
    argv = json.loads((tmp_path / "argv.json").read_text())
    assert "claude-sonnet-5" in argv
