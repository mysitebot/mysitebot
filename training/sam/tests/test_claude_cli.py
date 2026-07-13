import json

import pytest

import claude_cli
import claude_driver
from conftest import make_claude_stub


def test_extract_payload_from_envelope_with_fenced_json():
    inner = "Here you go:\n```json\n{\"passed\": true, \"reasoning\": \"ok\", \"issues\": []}\n```"
    stdout = json.dumps({"result": inner, "stats": {}})
    assert claude_cli.extract_json_payload(stdout)["passed"] is True


def test_extract_payload_from_bare_json_response():
    stdout = json.dumps({"result": "{\"passed\": false, \"reasoning\": \"no\", \"issues\": [\"x\"]}"})
    payload = claude_cli.extract_json_payload(stdout)
    assert payload["issues"] == ["x"]


def test_extract_payload_from_plain_text_with_object():
    stdout = "some preamble {\"scenarios\": []} trailing"
    assert claude_cli.extract_json_payload(stdout) == {"scenarios": []}


def test_extract_payload_array():
    stdout = json.dumps({"result": "```json\n[{\"id\": \"a\"}]\n```"})
    assert claude_cli.extract_json_payload(stdout) == [{"id": "a"}]


def test_extract_payload_garbage_raises():
    with pytest.raises(claude_cli.ClaudeCliError):
        claude_cli.extract_json_payload("no json here at all")


def test_extract_payload_two_separate_objects_raises():
    # the bare-object fallback is deliberately all-or-nothing: two separate
    # JSON objects in plain text are ambiguous, so it must raise, not guess
    with pytest.raises(claude_cli.ClaudeCliError):
        claude_cli.extract_json_payload('{"a": 1} junk {"b": 2}')


def test_run_claude_uses_bin_override(tmp_path, monkeypatch):
    stub = make_claude_stub(tmp_path, 'print(json.dumps({"result": "hello"}))')
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN", str(stub))
    out = claude_cli.run_claude("ignored", mode="plan", cwd=tmp_path)
    assert json.loads(out)["result"] == "hello"


def test_run_claude_nonzero_exit_raises(tmp_path, monkeypatch):
    stub = make_claude_stub(tmp_path, "sys.exit(3)")
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN", str(stub))
    with pytest.raises(claude_cli.ClaudeCliError, match="exited 3"):
        claude_cli.run_claude("ignored", mode="plan", cwd=tmp_path)


def test_run_claude_retries_transient_failure_then_succeeds(tmp_path, monkeypatch):
    # One transient CLI death (API overload) must not kill a judge/fixer/
    # generator run: run_claude retries with backoff, mirroring the websight
    # harness (scripts/claude_cli.py).
    body = '''
import pathlib
c = pathlib.Path("attempts")
n = int(c.read_text()) if c.exists() else 0
c.write_text(str(n + 1))
if n == 0:
    sys.exit(1)
print(json.dumps({"result": "recovered"}))
'''
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    out = claude_cli.run_claude("ignored", mode="plan", cwd=tmp_path)
    assert json.loads(out)["result"] == "recovered"
    assert (tmp_path / "attempts").read_text() == "2"


def test_run_claude_backoff_is_exponential_with_jitter(tmp_path, monkeypatch):
    stub = make_claude_stub(tmp_path, "sys.exit(2)")
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN", str(stub))
    monkeypatch.setattr(claude_cli, "RETRY_BASE_SECONDS", 5)  # undo _fast_retries
    sleeps = []
    # the retry loop (and its sleep) lives in the shared driver
    monkeypatch.setattr(claude_driver.time, "sleep", sleeps.append)
    with pytest.raises(claude_cli.ClaudeCliError, match="exited 2"):
        claude_cli.run_claude("ignored", mode="plan", cwd=tmp_path)
    assert len(sleeps) == 2                    # 3 attempts => 2 waits
    assert 5 <= sleeps[0] <= 10                # base + jitter in [0, base]
    assert 10 <= sleeps[1] <= 20


def test_run_claude_retries_1_means_single_attempt(tmp_path, monkeypatch):
    body = '''
import pathlib
c = pathlib.Path("attempts")
n = int(c.read_text()) if c.exists() else 0
c.write_text(str(n + 1))
sys.exit(1)
'''
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    with pytest.raises(claude_cli.ClaudeCliError):
        claude_cli.run_claude("ignored", mode="plan", cwd=tmp_path, retries=1)
    assert (tmp_path / "attempts").read_text() == "1"
