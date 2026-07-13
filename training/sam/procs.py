"""Subprocess helper: run a command in its OWN process group so a timeout
kills the whole tree.

`subprocess.run(timeout=...)` only kills the direct child; grandchildren
(node spawned by npm, the claude CLI's own children) survive and keep writing
into the workspace after the harness has moved on. Running the child with
start_new_session=True and killing the group on timeout closes that hole for
both call sites (verifier's `npm run build` and claude_cli's `claude -p`).

The implementation lives in training/claude_driver.py (shared with the
WebSight harness); this module re-exports it for sam's flat imports.
"""
import sys
from pathlib import Path

_TRAINING_DIR = str(Path(__file__).resolve().parents[1])
if _TRAINING_DIR not in sys.path:
    sys.path.insert(0, _TRAINING_DIR)

from claude_driver import run_group

__all__ = ["run_group"]
