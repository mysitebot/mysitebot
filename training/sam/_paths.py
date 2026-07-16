"""Shared path bootstrap: locate the repo root and make sam/ plus the repo root
importable. Previously duplicated across run_loop.py, sam_runner.py,
generate_scenarios.py and tests/conftest.py.

Standalone `sam` repo layout only — the monorepo layout was retired when sam
moved to its own repository. The repo root is the nearest ancestor of
training/sam that carries a pyproject.toml."""
import sys
from pathlib import Path

SAM_DIR = Path(__file__).resolve().parent          # …/training/sam

# Repo-relative paths of the training loop's targets. run_loop's startup guard
# and the fixer allowlists consume these — never hardcode layout paths there.
AGENT_PROMPTS = "src/agent/prompts.py"
AGENT_SITE_EDITOR = "src/agent/site_editor.py"
AGENT_CONTENT_VALIDATOR = "src/agent/content_validator.py"
TEMPLATE_DIR = "templates/astro-basic"
SECTIONS_DOC = "templates/SECTIONS.md"
TRAINING_REGISTRY = "training/sam/registry.json"


def find_repo_root(start: Path = SAM_DIR) -> Path:
    for p in [start, *start.parents]:
        if (p / "pyproject.toml").exists():
            return p
    raise RuntimeError("repo root not found")


REPO_ROOT = find_repo_root()                       # sam/ repo root


def bootstrap() -> Path:
    """Idempotently put sam/ and the repo root on sys.path (sam/ modules import
    each other flat; agent.* imports resolve from the repo root). Returns
    REPO_ROOT for convenience."""
    for p in (str(SAM_DIR), str(REPO_ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)
    return REPO_ROOT
