"""Shared path bootstrap: locate the repo root and make sam/ plus the repo root
importable. Previously duplicated across run_loop.py, sam_runner.py,
generate_scenarios.py and tests/conftest.py.

Works in two layouts: the mysite.bot monorepo (root carries a projects/ dir) and
the standalone `sam` repo (root is just the nearest pyproject.toml above sam/)."""
import sys
from pathlib import Path

SAM_DIR = Path(__file__).resolve().parent          # …/training/sam


def find_repo_root(start: Path = SAM_DIR) -> Path:
    ancestors = [start, *start.parents]
    # Monorepo layout: the root carries pyproject.toml AND a projects/ dir
    # (skips the intermediate projects/agent/pyproject.toml).
    for p in ancestors:
        if (p / "pyproject.toml").exists() and (p / "projects").is_dir():
            return p
    # Standalone `sam` repo: the nearest ancestor with a pyproject.toml.
    for p in ancestors:
        if (p / "pyproject.toml").exists():
            return p
    raise RuntimeError("repo root not found")


REPO_ROOT = find_repo_root()                       # monorepo root or sam/ root


def bootstrap() -> Path:
    """Idempotently put sam/ and the repo root on sys.path (sam/ modules import
    each other flat; agent.* imports resolve from the repo root). Returns
    REPO_ROOT for convenience."""
    for p in (str(SAM_DIR), str(REPO_ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)
    return REPO_ROOT
