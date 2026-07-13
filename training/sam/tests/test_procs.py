import os
import subprocess
import time

import pytest

import procs


def _gone_or_zombie(pid: int) -> bool:
    """True when the pid no longer runs (absent, or a zombie awaiting reap)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            # field 3 (after the parenthesised comm) is the state letter
            return f.read().rsplit(")", 1)[1].split()[0] == "Z"
    except (FileNotFoundError, ProcessLookupError):
        return True


def test_run_group_normal_completion_captures_output(tmp_path):
    result = procs.run_group(["bash", "-c", "echo out; echo err >&2"],
                             cwd=tmp_path, timeout=30)
    assert result.returncode == 0
    assert "out" in result.stdout
    assert "err" in result.stderr


def test_run_group_nonzero_exit_is_returned_not_raised(tmp_path):
    result = procs.run_group(["bash", "-c", "exit 7"], cwd=tmp_path, timeout=30)
    assert result.returncode == 7


def test_run_group_with_env_does_not_leak_parent_secrets(tmp_path, monkeypatch):
    # The build subprocess (npm run build) executes MDX/plugin code on
    # project content — it must NOT see the parent's secrets (e.g.
    # LLM_API_KEY). When an explicit `env` is passed, Popen must use ONLY
    # that env, not the full parent environment.
    monkeypatch.setenv("LEAKME", "top-secret")
    result = procs.run_group(["sh", "-c", "echo $LEAKME"], cwd=tmp_path,
                             timeout=30, env={"PATH": os.environ["PATH"]})
    assert "top-secret" not in result.stdout


def test_run_group_with_no_env_still_inherits_parent(tmp_path, monkeypatch):
    # The claude CLI callers pass no `env` and need the full parent
    # environment (e.g. LLM_API_KEY) — this must keep working unchanged.
    monkeypatch.setenv("LEAKME", "top-secret")
    result = procs.run_group(["sh", "-c", "echo $LEAKME"], cwd=tmp_path,
                             timeout=30)
    assert "top-secret" in result.stdout


def test_run_group_timeout_kills_grandchild_and_keeps_output(tmp_path):
    # A shell that spawns a long-sleeping GRANDCHILD: subprocess.run would kill
    # only the shell and orphan the sleep; run_group must kill the whole group,
    # and the TimeoutExpired must carry the output produced before the kill.
    pidfile = tmp_path / "grandchild.pid"
    cmd = ["bash", "-c",
           f"sleep 60 & echo $! > {pidfile}; echo spawned; wait"]
    with pytest.raises(subprocess.TimeoutExpired) as ei:
        procs.run_group(cmd, cwd=tmp_path, timeout=1)
    assert "spawned" in (ei.value.output or "")
    pid = int(pidfile.read_text().strip())
    for _ in range(100):                       # SIGKILL is fast, reap may lag
        if _gone_or_zombie(pid):
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"grandchild {pid} survived the group kill")
