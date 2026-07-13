"""Thin wrapper around the headless `claude` (Claude Code) CLI.

This is the *meta* model that judges runs and edits Sam's prompt/template/
validator — it is independent of the model Sam itself runs under (set via
run_loop's --model and used by the OSS agent's LLMClient).

Retry/backoff/group-kill live in training/claude_driver.py (shared with the
WebSight harness); this module binds the SAM_TRAINING_* env contract and the
plan/yolo permission postures.
"""
import os
import sys
from pathlib import Path

_TRAINING_DIR = str(Path(__file__).resolve().parents[1])
if _TRAINING_DIR not in sys.path:
    sys.path.insert(0, _TRAINING_DIR)

import claude_driver
from claude_driver import ClaudeCliError, extract_json_payload

__all__ = ["ClaudeCliError", "DEFAULT_MODEL", "RETRY_BASE_SECONDS",
           "extract_json_payload", "run_claude"]

# Switched from claude-sonnet-4-6 on 2026-07-03 after a 34/34 calibration
# side-by-side (12 judge-fail + 22 judge-pass artifact dirs, 100% agreement —
# see calibration/2026-07-03-sonnet-5.json). The corpus pass-history is
# measured against this panel: calibrate (calibrate_judge.py) before changing.
DEFAULT_MODEL = "claude-sonnet-5"

# First retry backoff; doubles per attempt, plus jitter in [0, base]. Module
# constant so the offline tests can zero it out.
RETRY_BASE_SECONDS = 5


def run_claude(prompt: str, mode: str, cwd, timeout: int = 900,
               output_json: bool = True, model: str | None = None,
               retries: int = 3) -> str:
    """Run `claude -p <prompt>` headlessly and return raw stdout.

    The binary can be overridden via SAM_TRAINING_CLAUDE_BIN (tests use this).
    mode: "plan" (read-only) for the judge/generator, "yolo" (full autonomy,
    edits files) for the fixer — the same two postures the gemini CLI used via
    --approval-mode.

    A non-zero exit (or a hung CLI hitting the timeout) is retried with
    exponential backoff + jitter by the shared driver: the CLI mostly fails on
    transient API overload, and a brief wait recovers most of them — one blip
    must not kill a whole fixer/generator run. The subprocess runs in its own
    process group so a timeout kills the CLI's grandchildren too, instead of
    orphaning them to keep writing into the workspace.
    """
    binary = os.environ.get("SAM_TRAINING_CLAUDE_BIN", "claude")
    extra_args = []
    if mode == "yolo":
        extra_args.append("--dangerously-skip-permissions")
    else:
        extra_args += ["--permission-mode", "plan"]
    if output_json:
        extra_args += ["--output-format", "json"]
    return claude_driver.run_claude(
        prompt, model=model or DEFAULT_MODEL, cwd=cwd, binary=binary,
        timeout=timeout, retries=retries, base_seconds=RETRY_BASE_SECONDS,
        extra_args=extra_args)
