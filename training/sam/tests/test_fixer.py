import json
import subprocess

import pytest

import fixer
from conftest import make_claude_stub, make_scenario, make_tmp_repo


def _scen_dir(tmp_path):
    d = tmp_path / "scen"
    d.mkdir()
    (d / "verification.json").write_text(json.dumps({
        "status": "fail",
        "layers": {"deterministic": {
            "status": "fail",
            "details": ["expected tool not called: branch_and_edit_content"]}}}))
    return d


def test_is_allowlisted():
    assert fixer.is_allowlisted("projects/agent/src/agent/prompts.py")
    assert fixer.is_allowlisted("projects/agent/templates/astro-basic/src/components/sections/Hero.astro")
    assert not fixer.is_allowlisted("src/main.py")
    assert not fixer.is_allowlisted("README.md")


def test_ensure_allowlist_clean(tmp_path):
    repo = make_tmp_repo(tmp_path)
    fixer.ensure_allowlist_clean(repo)  # clean repo: no raise
    (repo / "README.md").write_text("dirty but not allowlisted\n")
    fixer.ensure_allowlist_clean(repo)  # still fine
    (repo / "projects" / "agent" / "src" / "agent" / "prompts.py").write_text("dirty\n")
    with pytest.raises(RuntimeError, match="prompts.py"):
        fixer.ensure_allowlist_clean(repo)


def test_run_fixer_applies_allowlisted_and_reverts_the_rest(tmp_path, monkeypatch):
    repo = make_tmp_repo(tmp_path)
    scen_dir = _scen_dir(tmp_path)
    body = '''
import pathlib
pathlib.Path("projects/agent/src/agent/prompts.py").write_text("BASE_SYSTEM_INSTRUCTION = 'improved'\\n")
pathlib.Path("README.md").write_text("vandalized\\n")
pathlib.Path("notes.txt").write_text("scratch\\n")
print("done")
'''
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    fix = fixer.run_fixer(make_scenario(), scen_dir, repo)
    assert fix["applied"] == ["projects/agent/src/agent/prompts.py"]
    assert sorted(fix["reverted"]) == ["README.md", "notes.txt"]
    assert (repo / "README.md").read_text() == "readme\n"          # restored
    assert not (repo / "notes.txt").exists()                        # deleted
    assert "improved" in (repo / "projects" / "agent" / "src" / "agent" / "prompts.py").read_text()


def test_snapshot_allowlisted_excludes_gitignored_files(tmp_path):
    # snapshot_allowlisted must use the git-aware view (honor .gitignore), not a
    # raw rglob — otherwise it slurps the template dir's node_modules/dist (tens
    # of thousands of files) into memory on every failing scenario.
    repo = make_tmp_repo(tmp_path)
    tmpl = repo / "projects" / "agent" / "templates" / "astro-basic"
    (tmpl / ".gitignore").write_text("node_modules/\n")
    (tmpl / "node_modules").mkdir()
    (tmpl / "node_modules" / "junk.js").write_text("x" * 1000)
    (tmpl / "new_section.astro").write_text("<div/>\n")  # untracked, NOT ignored
    snap = fixer.snapshot_allowlisted(repo)
    assert "projects/agent/templates/astro-basic/node_modules/junk.js" not in snap
    # untracked-but-not-ignored IS captured (a fix could have created it)
    assert "projects/agent/templates/astro-basic/new_section.astro" in snap
    # tracked files are captured
    assert "projects/agent/templates/astro-basic/placeholder.txt" in snap


def test_run_fixer_never_reverts_preexisting_dirty_files(tmp_path, monkeypatch):
    repo = make_tmp_repo(tmp_path)
    scen_dir = _scen_dir(tmp_path)
    # operator WIP outside the allowlist, dirty BEFORE the fixer runs
    (repo / "README.md").write_text("operator work in progress\n")
    body = ('import pathlib\n'
            'pathlib.Path("projects/agent/src/agent/prompts.py").write_text("IMPROVED\\n")\n'
            'print("done")')
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    fix = fixer.run_fixer(make_scenario(), scen_dir, repo)
    assert fix["applied"] == ["projects/agent/src/agent/prompts.py"]
    assert fix["reverted"] == []
    # the operator's pre-existing WIP must be untouched
    assert (repo / "README.md").read_text() == "operator work in progress\n"


def test_run_fixer_attributes_edit_to_already_dirty_allowlisted_file(tmp_path, monkeypatch):
    # Regression: when an allowlisted file is ALREADY dirty from a prior accepted
    # fix this run, a dirty-set diff (after - before) cannot see a further edit to
    # it (it is dirty before AND after), so the edit was attributed to nothing and
    # never reverted on regression — the bad change silently persisted. Attribution
    # must detect the content change.
    repo = make_tmp_repo(tmp_path)
    scen_dir = _scen_dir(tmp_path)
    prompts = repo / "projects" / "agent" / "src" / "agent" / "prompts.py"
    prompts.write_text("BASE_SYSTEM_INSTRUCTION = 'prior accepted fix'\n")  # already dirty
    body = ('import pathlib\n'
            'p = pathlib.Path("projects/agent/src/agent/prompts.py")\n'
            'p.write_text(p.read_text() + "# regression-causing bullet\\n")\n'
            'print("done")')
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    fix = fixer.run_fixer(make_scenario(), scen_dir, repo)
    assert fix["applied"] == ["projects/agent/src/agent/prompts.py"]


def test_snapshot_and_restore_preserves_prior_fix(tmp_path):
    # restore_snapshot must restore an allowlisted file to its PRE-fix snapshot
    # (which carries an earlier accepted fix), NOT to HEAD — else reverting a
    # regression on a file a prior fix also touched (e.g. prompts.py) would wipe
    # that prior fix too.
    repo = make_tmp_repo(tmp_path)
    prompts = repo / "projects" / "agent" / "src" / "agent" / "prompts.py"
    prompts.write_text("BASE_SYSTEM_INSTRUCTION = 'prior accepted fix'\n")  # prior fix
    snap = fixer.snapshot_allowlisted(repo)
    prompts.write_text("BASE_SYSTEM_INSTRUCTION = 'prior accepted fix'\n# bad bullet\n")
    fixer.restore_snapshot(repo, ["projects/agent/src/agent/prompts.py"], snap)
    assert prompts.read_text() == "BASE_SYSTEM_INSTRUCTION = 'prior accepted fix'\n"


def test_restore_snapshot_deletes_file_absent_from_snapshot(tmp_path):
    # A fix that CREATED a new allowlisted file must, on revert, be removed: the
    # snapshot predates it, so restore deletes it.
    repo = make_tmp_repo(tmp_path)
    snap = fixer.snapshot_allowlisted(repo)
    rel = "projects/agent/templates/astro-basic/src/New.astro"
    newf = repo / rel
    newf.parent.mkdir(parents=True, exist_ok=True)
    newf.write_text("created by fix\n")
    fixer.restore_snapshot(repo, [rel], snap)
    assert not newf.exists()


def test_ensure_allowlist_clean_catches_dirty_prefix_path(tmp_path):
    repo = make_tmp_repo(tmp_path)
    (repo / "projects" / "agent" / "templates" / "astro-basic" / "placeholder.txt").write_text("dirty\n")
    with pytest.raises(RuntimeError, match="placeholder"):
        fixer.ensure_allowlist_clean(repo)


def test_run_fixer_reverts_staged_changes_outside_allowlist(tmp_path, monkeypatch):
    repo = make_tmp_repo(tmp_path)
    scen_dir = _scen_dir(tmp_path)
    # the fixer edits AND STAGES a tracked file plus a new file (claude CLI
    # agents sometimes run `git add` even when told not to)
    body = '''
import pathlib, subprocess
pathlib.Path("README.md").write_text("vandalized\\n")
pathlib.Path("scratch.txt").write_text("junk\\n")
subprocess.run(["git", "add", "README.md", "scratch.txt"], check=True)
print("done")
'''
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    fix = fixer.run_fixer(make_scenario(), scen_dir, repo)
    assert sorted(fix["reverted"]) == ["README.md", "scratch.txt"]
    # content actually restored, in BOTH worktree and index
    assert (repo / "README.md").read_text() == "readme\n"
    assert not (repo / "scratch.txt").exists()
    porcelain = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True, text=True).stdout
    assert "README.md" not in porcelain
    assert "scratch.txt" not in porcelain


def _head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def test_run_fixer_recovers_a_commit_and_flags_protocol_violation(tmp_path, monkeypatch):
    # A fixer that runs `git commit` makes the tree CLEAN: the dirty-set diff
    # then reports "no changes" while the edit hides in HEAD — invisible to
    # the goalpost gate, the regression revert, restore_snapshot and the
    # end-of-run diff report. run_fixer must reset --soft back to the recorded
    # HEAD (recovering the changes into the working tree so normal
    # attribution/revert applies) and surface the protocol violation.
    repo = make_tmp_repo(tmp_path)
    scen_dir = _scen_dir(tmp_path)
    head_before = _head(repo)
    body = '''
import pathlib, subprocess
pathlib.Path("projects/agent/src/agent/prompts.py").write_text("BASE_SYSTEM_INSTRUCTION = 'improved'\\n")
pathlib.Path("README.md").write_text("vandalized\\n")
subprocess.run(["git", "add", "-A"], check=True)
subprocess.run(["git", "-c", "user.name=f", "-c", "user.email=f@f",
                "commit", "-qm", "sneaky fixer commit"], check=True)
print("done")
'''
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    fix = fixer.run_fixer(make_scenario(), scen_dir, repo)
    assert _head(repo) == head_before                       # commit undone
    assert fix["protocol_violation"]                        # and surfaced
    assert any("commit" in v for v in fix["protocol_violation"])
    # normal attribution/revert applied to the recovered changes
    assert fix["applied"] == ["projects/agent/src/agent/prompts.py"]
    assert fix["reverted"] == ["README.md"]
    assert (repo / "README.md").read_text() == "readme\n"
    assert "improved" in (repo / "projects" / "agent" / "src" / "agent"
                          / "prompts.py").read_text()


def test_run_fixer_recovers_a_stash_and_flags_protocol_violation(tmp_path, monkeypatch):
    # `git stash` likewise makes the tree clean while the change hides in the
    # stash — the harness must pop it back and flag the violation.
    repo = make_tmp_repo(tmp_path)
    scen_dir = _scen_dir(tmp_path)
    body = '''
import pathlib, subprocess
pathlib.Path("projects/agent/src/agent/prompts.py").write_text("BASE_SYSTEM_INSTRUCTION = 'stashed'\\n")
subprocess.run(["git", "-c", "user.name=f", "-c", "user.email=f@f",
                "stash", "push", "-q"], check=True)
print("done")
'''
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    fix = fixer.run_fixer(make_scenario(), scen_dir, repo)
    assert any("stash" in v for v in fix["protocol_violation"])
    assert fix["applied"] == ["projects/agent/src/agent/prompts.py"]
    assert "stashed" in (repo / "projects" / "agent" / "src" / "agent"
                         / "prompts.py").read_text()
    stashes = subprocess.run(["git", "-C", str(repo), "stash", "list"],
                             capture_output=True, text=True).stdout.strip()
    assert stashes == ""                                    # stash recovered


def test_run_fixer_no_git_use_has_no_protocol_violation(tmp_path, monkeypatch):
    repo = make_tmp_repo(tmp_path)
    scen_dir = _scen_dir(tmp_path)
    body = ('import pathlib\n'
            'pathlib.Path("projects/agent/src/agent/prompts.py").write_text("OK\\n")\n'
            'print("done")')
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    fix = fixer.run_fixer(make_scenario(), scen_dir, repo)
    assert fix["protocol_violation"] == []


def test_fix_provenance_classifies_paths():
    assert fixer.fix_provenance(["projects/agent/src/agent/prompts.py"]) == "behavioral"
    assert fixer.fix_provenance(
        ["projects/agent/src/agent/site_editor.py"]) == "behavioral"
    assert fixer.fix_provenance(
        ["projects/agent/src/agent/content_validator.py"]) == "goalpost"
    assert fixer.fix_provenance(
        ["projects/agent/templates/astro-basic/src/x.astro"]) == "goalpost"
    assert fixer.fix_provenance(
        ["projects/agent/training/registry.json"]) == "goalpost"
    # any goalpost file in the set => goalpost
    assert fixer.fix_provenance(
        ["projects/agent/src/agent/prompts.py",
         "projects/agent/training/registry.json"]) == "goalpost"


def test_reverted_content_is_quarantined_not_destroyed(tmp_path, monkeypatch):
    repo = make_tmp_repo(tmp_path)
    scen_dir = _scen_dir(tmp_path)
    body = ('import pathlib\n'
            'pathlib.Path("README.md").write_text("might be operator work\\n")\n'
            'print("done")')
    monkeypatch.setenv("SAM_TRAINING_CLAUDE_BIN",
                       str(make_claude_stub(tmp_path, body)))
    fix = fixer.run_fixer(make_scenario(), scen_dir, repo)
    assert fix["reverted"] == ["README.md"]
    quarantined = scen_dir / "rejected" / "README.md"
    assert quarantined.read_text() == "might be operator work\n"
