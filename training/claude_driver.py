"""Shared headless `claude` (Claude Code) CLI driver for both training harnesses.

The WebSight mapper (training/scripts/claude_cli.py) and the Sam meta-loop
(training/sam/claude_cli.py) each drive the same binary with the same failure
modes (transient API overload, hung CLI trees); this module owns the one
retry/backoff/process-group implementation while the wrappers keep their own
public signatures, default models and env-var contracts (WEBSIGHT_CLAUDE_BIN /
SAM_TRAINING_CLAUDE_BIN, ...).

Guarantees:
  - every child runs in its OWN process group (start_new_session) and a timeout
    SIGKILLs the whole group, so grandchildren (node spawned by npm, the claude
    CLI's own children) can't keep writing into the workspace;
  - a TimeoutExpired counts as a retryable attempt, like a non-zero exit;
  - error messages carry BOTH output tails (stderr alone is often empty while
    the useful diagnostics went to stdout).
"""
import json
import os
import random
import re
import signal
import subprocess
import time
from typing import Optional, Sequence


class ClaudeCliError(RuntimeError):
    pass


def run_group(cmd, *, cwd=None, timeout: Optional[float] = None,
              env: Optional[dict] = None) -> subprocess.CompletedProcess:
    """subprocess.run(capture_output=True, text=True) equivalent that starts
    the child in a new session (its own process group) and SIGKILLs the whole
    group on timeout. Raises subprocess.TimeoutExpired with whatever output was
    captured before the kill attached (so callers can persist it, e.g. to
    build.log) instead of discarding it.

    `env=None` (the default) preserves the historical inherit-everything
    behavior — the claude CLI callers need the full parent environment (e.g.
    LLM_API_KEY). Callers that must NOT leak parent secrets to the child (e.g.
    the `npm run build` call, which executes MDX/plugin code on project
    content) pass an explicit allowlisted `env` dict instead."""
    proc = subprocess.Popen(
        cmd, cwd=None if cwd is None else str(cwd),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True, env=env)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)   # pgid == pid (new session)
        except (ProcessLookupError, PermissionError):
            pass
        stdout, stderr = proc.communicate()
        raise subprocess.TimeoutExpired(cmd, timeout,
                                        output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def _tails(stdout, stderr) -> str:
    """Both output tails, for error messages: stderr is often empty while the
    CLI's real diagnostics went to stdout (or vice versa)."""
    return f"stderr:{(stderr or '')[-1000:]} stdout:{(stdout or '')[-1000:]}"


def run_claude(prompt: str, *, model: str, cwd, binary: str = "claude",
               timeout: float = 900, retries: int = 3,
               base_seconds: float = 5, extra_args: Sequence[str] = (),
               env_overrides: Optional[dict] = None) -> str:
    """Run `claude -p <prompt> --model <model> [extra_args...]`; return stdout.

    A non-zero exit OR a timeout is retried with exponential backoff + jitter:
    at high concurrency the CLI mostly fails on transient API overload, and a
    brief wait (with jitter so parallel workers don't all retry in lockstep)
    recovers most of them. The backoff waits base_seconds * 2**attempt plus
    jitter in [0, that base]. Exhausted retries raise ClaudeCliError carrying
    both output tails of the last attempt.
    """
    cmd = [binary, "-p", prompt, "--model", model, *extra_args]
    env = {**os.environ, **env_overrides} if env_overrides else None
    last_err = "no attempts"
    for attempt in range(retries):
        try:
            result = run_group(cmd, cwd=cwd, timeout=timeout, env=env)
        except subprocess.TimeoutExpired as e:
            last_err = (f"claude timed out after {timeout}s: "
                        f"{_tails(e.output, e.stderr)}")
        else:
            if result.returncode == 0:
                return result.stdout
            last_err = (f"claude exited {result.returncode}: "
                        f"{_tails(result.stdout, result.stderr)}")
        if attempt < retries - 1:
            base = base_seconds * (2 ** attempt)
            time.sleep(base + random.uniform(0, base))
    raise ClaudeCliError(last_err)


def extract_json_payload(stdout: str):
    """Extract the JSON object/array a directive asked the model to produce.

    `claude --output-format json` wraps the model text in an envelope whose
    final text is under "result" ({"type":"result","result": "...", ...}); the
    model text may additionally fence its JSON. Try, in order: the envelope,
    a fenced block, the first bare object/array.
    """
    text = stdout.strip()
    try:
        envelope = json.loads(text)
        if isinstance(envelope, dict) and "result" in envelope:
            text = str(envelope["result"]).strip()
        elif isinstance(envelope, (dict, list)):
            return envelope
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    # Greedy on purpose: with multiple disjoint JSON fragments the result is
    # ambiguous, so this fails loudly rather than guessing the first one.
    bare = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if bare:
        try:
            return json.loads(bare.group(1))
        except json.JSONDecodeError as e:
            raise ClaudeCliError(f"unparseable JSON in claude output: {e}") from e
    raise ClaudeCliError(f"no JSON payload in claude output: {text[:300]!r}")
