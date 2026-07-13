import os
import subprocess
import sys
from pathlib import Path

import pytest

# Minimal inline bootstrap: conftest runs before sys.path knows about sam/, so
# _paths itself isn't importable yet — make sam/ importable, then delegate.
SAM_DIR = Path(__file__).resolve().parents[1]   # …/training/sam
if str(SAM_DIR) not in sys.path:
    sys.path.insert(0, str(SAM_DIR))

from _paths import bootstrap

REPO_ROOT = bootstrap()   # wypiwyg

# Must be set before any agent import (same pattern as projects/agent/cli.py)
os.environ.setdefault("ADMIN_USERNAME", "training_admin")
os.environ.setdefault("ADMIN_PASSWORD", "training_admin_password")
os.environ.setdefault("JWT_SECRET", "training_jwt_secret_placeholder_min_32_chars")
os.environ.setdefault("LLM_API_KEY", "offline_training_key_not_real")


@pytest.fixture(autouse=True)
def _fast_retries(monkeypatch):
    """run_claude retries transient CLI failures with backoff; the offline
    suite must never actually sleep (stubs that exit non-zero would otherwise
    cost ~15s each). Tests that assert the backoff maths restore the value."""
    import claude_cli
    monkeypatch.setattr(claude_cli, "RETRY_BASE_SECONDS", 0)


def make_scenario(checks=None, negative=False, **over):
    """Build a Scenario from minimal raw JSON for tests."""
    from scenario_schema import parse_scenario_dict
    raw = {
        "id": over.get("id", "scn_test"),
        "name": over.get("name", "Test scenario"),
        "negative": negative,
    }
    if "turns" in over:
        raw["turns"] = over["turns"]
    else:
        raw["prompt"] = over.get("prompt", "Do the thing")
    if checks is not None:
        raw["checks"] = checks
    if "dry_run" in over:
        raw["dry_run"] = over["dry_run"]
    if "setup" in over:
        raw["setup"] = over["setup"]
    if "split" in over:
        raw["split"] = over["split"]
    for key in ("is_system", "is_init"):
        if key in over:
            raw[key] = over[key]
    return parse_scenario_dict(raw, "inline-test")


def make_claude_stub(tmp_path: Path, body: str) -> Path:
    """Create an executable fake `claude` binary. `body` is python source."""
    stub = tmp_path / "claude-stub"
    stub.write_text("#!/usr/bin/env python3\nimport json, os, sys\n" + body + "\n")
    stub.chmod(0o755)
    return stub


def make_tmp_repo(tmp_path: Path) -> Path:
    """A small git repo standing in for wypiwyg/ in fixer/run_loop tests."""
    repo = tmp_path / "repo"
    (repo / "projects" / "agent" / "src" / "agent").mkdir(parents=True)
    (repo / "projects" / "agent" / "src" / "agent" / "prompts.py").write_text(
        "BASE_SYSTEM_INSTRUCTION = 'original'\n")
    (repo / "projects" / "agent" / "src" / "agent" / "content_validator.py").write_text(
        "# content_validator\n")
    (repo / "projects" / "agent" / "src" / "agent" / "site_editor.py").write_text(
        "# tools\n")
    (repo / "README.md").write_text("readme\n")
    (repo / "projects" / "agent" / "templates" / "astro-basic").mkdir(parents=True)
    (repo / "projects" / "agent" / "templates" / "astro-basic" / "placeholder.txt").write_text("x\n")

    def git(*args):
        subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True,
            env={**os.environ,
                 "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                 "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"},
        )

    git("init", "-q")
    git("add", "-A")
    git("commit", "-qm", "baseline")
    return repo
