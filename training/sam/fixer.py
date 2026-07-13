"""Diagnose-and-fix stage: run the claude CLI in yolo mode against the
wypiwyg repo, constrained to an allowlist that the orchestrator enforces."""
import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set

import claude_cli
from sam_runner import parse_porcelain_z

DIRECTIVE_PATH = Path(__file__).resolve().parent / "directives" / "fixer.md"

# Paths (relative to the repo root) the fixer may modify. Entries ending in
# "/" are directory prefixes.
ALLOWLIST = (
    "projects/agent/src/agent/prompts.py",
    "projects/agent/src/agent/site_editor.py",
    "projects/agent/src/agent/content_validator.py",
    "projects/agent/templates/astro-basic/",
    "projects/agent/templates/SECTIONS.md",
    "projects/agent/training/registry.json",
)


def is_allowlisted(path: str) -> bool:
    return any(path == entry or (entry.endswith("/") and path.startswith(entry))
               for entry in ALLOWLIST)


# Allowlisted paths whose edits "move the goalposts" (the eval can pass because
# the check itself was loosened) — flagged + judge-reconfirmed, vs behavioral
# edits to the prompt / tool docstrings.
GOALPOST_PREFIXES = (
    "projects/agent/src/agent/content_validator.py",
    "projects/agent/templates/",
    "projects/agent/training/registry.json",
)


def fix_provenance(applied: List[str]) -> str:
    """'goalpost' if the fix touched any validator/template/registry path,
    else 'behavioral' (prompt / tool docstrings)."""
    for f in applied:
        if any(f == p or (p.endswith("/") and f.startswith(p))
               for p in GOALPOST_PREFIXES):
            return "goalpost"
    return "behavioral"


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo_root), *args],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def dirty_files(repo_root: Path) -> Set[str]:
    """All files that differ from HEAD (staged, unstaged, or untracked)."""
    return parse_porcelain_z(_git(repo_root, "status", "--porcelain", "-z"))


def _head(repo_root: Path) -> str:
    return _git(repo_root, "rev-parse", "HEAD").strip()


def _stash_count(repo_root: Path) -> int:
    return len(_git(repo_root, "stash", "list").splitlines())


def _undo_git_protocol_violations(repo_root: Path, head_before: str,
                                  stash_before: int) -> List[str]:
    """The fixer directive forbids git commands, but a live agent sometimes
    runs them anyway. A `git commit` (or `git stash`) makes the tree CLEAN, so
    the dirty-set diff reports "fixer made no changes" while the edit hides in
    HEAD/the stash — invisible to the goalpost gate, the regression revert,
    restore_snapshot and the end-of-run diff report. Recover the changes into
    the working tree so normal attribution/revert applies, and report each
    violation."""
    violations: List[str] = []
    if _head(repo_root) != head_before:
        # --soft keeps the committed changes (staged); the normal allowlist
        # attribution + revert below then handles them like any other edit.
        _git(repo_root, "reset", "--soft", head_before)
        violations.append(
            f"fixer ran `git commit`; reset --soft back to {head_before[:12]} "
            "to recover the changes into the working tree")
    extra_stashes = _stash_count(repo_root) - stash_before
    if extra_stashes > 0:
        for _ in range(extra_stashes):
            # Best-effort: a pop can conflict, but the stash entry then stays
            # recoverable rather than silently lost.
            subprocess.run(["git", "-C", str(repo_root), "stash", "pop", "-q"],
                           capture_output=True)
        violations.append(
            f"fixer ran `git stash` ({extra_stashes}x); popped back into the "
            "working tree")
    return violations


def _read_or_none(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except (FileNotFoundError, IsADirectoryError):
        return None


def _list_allowlisted_files(repo_root: Path) -> List[str]:
    """Every allowlisted repo file git is aware of (directory-prefix entries
    expanded), as repo-relative posix paths. Uses `git ls-files` so it honors
    .gitignore — the same view as dirty_files — instead of walking into the
    template dir's node_modules/dist/.astro (tens of thousands of files the
    fixer never touches)."""
    paths = [entry.rstrip("/") for entry in ALLOWLIST]
    out = _git(repo_root, "ls-files", "-z", "--cached", "--others",
               "--exclude-standard", "--", *paths)
    return sorted(p for p in out.split("\0") if p)


def snapshot_allowlisted(repo_root: Path) -> Dict[str, bytes]:
    """Capture the current content of every allowlisted file. Pass the result to
    restore_snapshot to roll a failed fix back to this exact state — which may
    already carry earlier accepted fixes this run — instead of all the way to
    HEAD. A file that vanishes between listing and read is skipped (so a
    concurrent delete can't crash the snapshot)."""
    snap: Dict[str, bytes] = {}
    for f in _list_allowlisted_files(repo_root):
        content = _read_or_none(repo_root / f)
        if content is not None:
            snap[f] = content
    return snap


def ensure_allowlist_clean(repo_root: Path) -> None:
    """Refuse to start a fixing run when allowlisted files already carry
    uncommitted changes — otherwise a later revert would destroy operator
    work. Dirty files outside the allowlist are fine (never auto-reverted)."""
    dirty = sorted(f for f in dirty_files(repo_root) if is_allowlisted(f))
    if dirty:
        raise RuntimeError(
            "Refusing to run with --fix: allowlisted files have uncommitted "
            f"changes: {dirty}. Commit or stash them, or use --no-fix.")


def _revert_file(repo_root: Path, path: str,
                 quarantine_dir: Optional[Path] = None) -> None:
    """Restore `path` to its HEAD state in BOTH the index and the worktree.

    `git checkout -- path` is not enough: it copies index -> worktree, so a
    staged change survives it (live gemini agents sometimes run `git add`).
    If quarantine_dir is given, the rejected content is saved there first —
    a concurrent operator edit misattributed to the fixer must be
    recoverable, never destroyed.
    """
    target = repo_root / path
    if quarantine_dir is not None and target.exists():
        dest = Path(quarantine_dir) / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, dest)
    in_head = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "-e", f"HEAD:{path}"],
        capture_output=True).returncode == 0
    if in_head:
        _git(repo_root, "checkout", "HEAD", "--", path)
    else:
        # never committed: drop it from the index if staged, then delete
        subprocess.run(
            ["git", "-C", str(repo_root), "rm", "-q", "--cached", "--force",
             "--", path],
            capture_output=True)
        if target.exists():
            target.unlink()


def build_fix_directive(scenario, scen_dir: Path) -> str:
    verification = json.loads((scen_dir / "verification.json").read_text())
    summary = "\n".join(
        f"- [{name}] {detail}"
        for name, layer in verification["layers"].items()
        for detail in layer["details"]) or "(see verification.json)"
    return (DIRECTIVE_PATH.read_text()
            .replace("{{scenario_id}}", scenario.id)
            .replace("{{user_request}}", scenario.prompt)
            .replace("{{run_dir}}", str(scen_dir.resolve()))
            .replace("{{failure_summary}}", summary))


def run_fixer(scenario, scen_dir: Path, repo_root: Path) -> Dict[str, List[str]]:
    """Run the fixer, then enforce the allowlist: anything else it touched
    is reverted. Returns {"applied": [...], "reverted": [...],
    "protocol_violation": [...]}.
    Only files newly dirtied by the fixer are attributed to it; files that
    were already dirty before are never auto-reverted. A fixer that commits or
    stashes (forbidden by the directive) is unwound first — see
    _undo_git_protocol_violations — so attribution still sees its changes.

    May raise ClaudeCliError, subprocess.TimeoutExpired, or
    FileNotFoundError on fixer infrastructure failures; the caller is
    responsible for handling these."""
    before_dirty = dirty_files(repo_root)
    head_before = _head(repo_root)
    stash_before = _stash_count(repo_root)
    # Allowlisted files already dirty = accepted fixes earlier THIS run. A
    # dirty-set diff (after - before) cannot see a further edit to them (they are
    # dirty before AND after), so snapshot their content and detect changes
    # explicitly — otherwise a fix to such a file is attributed to nothing and so
    # never reverted on regression, silently persisting in the working tree.
    watch = sorted(f for f in before_dirty if is_allowlisted(f))
    before_content = {f: _read_or_none(repo_root / f) for f in watch}
    prompt = build_fix_directive(scenario, scen_dir)
    claude_cli.run_claude(prompt, mode="yolo", cwd=repo_root,
                          output_json=False, timeout=1800)
    violations = _undo_git_protocol_violations(
        repo_root, head_before, stash_before)
    after_dirty = dirty_files(repo_root)
    newly = after_dirty - before_dirty
    rechanged = [f for f in watch
                 if _read_or_none(repo_root / f) != before_content[f]]
    applied = sorted({f for f in newly if is_allowlisted(f)} | set(rechanged))
    # Non-allowlisted files the fixer NEWLY dirtied are reverted immediately;
    # files dirty before the run (operator work) are never touched.
    reverted = sorted(f for f in newly if not is_allowlisted(f))
    for f in reverted:
        _revert_file(repo_root, f, quarantine_dir=scen_dir / "rejected")
    return {"applied": applied, "reverted": reverted,
            "protocol_violation": violations}


def restore_snapshot(repo_root: Path, files: List[str],
                     snapshot: Dict[str, bytes],
                     quarantine_dir: Optional[Path] = None) -> None:
    """Roll each file back to its content in `snapshot` (the pre-fix state, which
    may carry earlier accepted fixes this run), or delete it if absent from the
    snapshot (the fix created it). Unstages first so a staged fixer edit doesn't
    survive. Current content is quarantined before being overwritten/removed.

    Reverting to the snapshot — rather than to HEAD — is what lets a regressing
    fix be rolled back without discarding an earlier accepted fix that touched
    the same file."""
    for f in files:
        target = repo_root / f
        if quarantine_dir is not None and target.exists():
            dest = Path(quarantine_dir) / f
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, dest)
        # Return the index entry to HEAD so a staged fixer edit is dropped too.
        subprocess.run(["git", "-C", str(repo_root), "reset", "-q", "--", f],
                       capture_output=True)
        if f in snapshot:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(snapshot[f])
        elif target.exists():
            target.unlink()
