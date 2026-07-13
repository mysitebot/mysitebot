"""Static guard: the OSS agent must not depend on private/commercial code or on
the (license-encumbered) WebSight mapper. Enforced by AST, so it runs with no
network/DB and fails the pipeline the moment the seam rots.
"""
import ast
from pathlib import Path

AGENT_SRC = Path(__file__).resolve().parent.parent / "src" / "agent"
SAM_DIR = Path(__file__).resolve().parent.parent / "training" / "sam"

# Top-level module names the OSS agent may never import.
FORBIDDEN_FOR_AGENT = {"api", "imagelibrary", "stripe"}
# The SAM eval loop may import `agent` and the shared `claude_driver` harness
# (a stdlib-only wrapper for driving the `claude` CLI, used by BOTH the SAM loop
# and the WebSight mapper — it ships into the public repo alongside training/sam).
# It must NOT import private code, nor the WebSight *download/mapper* drivers
# (`run_training`/`fetch_data`), which pull the HF-dataset data that stays private.
FORBIDDEN_FOR_SAM = FORBIDDEN_FOR_AGENT | {
    "run_training",
    "fetch_data",
}


def _imported_roots(py_file: Path) -> set[str]:
    """Top-level module name of every import in a file (absolute imports only)."""
    tree = ast.parse(py_file.read_text(), filename=str(py_file))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:  # skip relative imports
                roots.add(node.module.split(".")[0])
    return roots


def _violations(root_dir: Path, forbidden: set[str]) -> list[str]:
    out = []
    for py in root_dir.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        bad = _imported_roots(py) & forbidden
        if bad:
            out.append(f"{py.relative_to(root_dir.parent)}: imports {sorted(bad)}")
    return out


def test_agent_does_not_import_private_code():
    violations = _violations(AGENT_SRC, FORBIDDEN_FOR_AGENT)
    assert not violations, "agent seam broken:\n" + "\n".join(violations)


def test_sam_eval_loop_is_independent():
    if not SAM_DIR.exists():
        return
    violations = _violations(SAM_DIR, FORBIDDEN_FOR_SAM)
    assert not violations, "SAM/WebSight boundary broken:\n" + "\n".join(violations)
