"""F04 regression: the training loop must resolve the REAL standalone repo —
the old guard/allowlists pointed at the retired monorepo layout, so the loop
exited immediately and the fixer would have reverted every intended edit."""
import _paths
import fixer


def test_repo_root_is_the_sam_checkout():
    assert (_paths.REPO_ROOT / _paths.TEMPLATE_DIR).is_dir()
    assert (_paths.REPO_ROOT / _paths.AGENT_PROMPTS).is_file()
    assert (_paths.REPO_ROOT / _paths.TRAINING_REGISTRY).is_file()


def test_run_loop_guard_path_exists():
    # The exact path run_loop.main checks before anything else.
    assert (_paths.REPO_ROOT / _paths.TEMPLATE_DIR / "src").is_dir()


def test_fixer_allowlist_matches_real_standalone_files():
    assert fixer.is_allowlisted("src/agent/prompts.py")
    assert fixer.is_allowlisted("src/agent/site_editor.py")
    assert fixer.is_allowlisted("src/agent/content_validator.py")
    assert fixer.is_allowlisted("templates/astro-basic/src/components/sections/Hero.astro")
    assert fixer.is_allowlisted("templates/SECTIONS.md")
    assert fixer.is_allowlisted("training/sam/registry.json")
    assert not fixer.is_allowlisted("projects/agent/src/agent/prompts.py")
    assert not fixer.is_allowlisted("training/sam/run_loop.py")


def test_goalpost_classification_standalone():
    assert fixer.fix_provenance(["templates/astro-basic/src/components/sections/Hero.astro"]) == "goalpost"
    assert fixer.fix_provenance(["src/agent/content_validator.py"]) == "goalpost"
    assert fixer.fix_provenance(["src/agent/prompts.py"]) == "behavioral"


def test_fixer_directive_names_no_monorepo_paths():
    text = fixer.DIRECTIVE_PATH.read_text()
    assert "projects/agent" not in text
    assert "src/agent/prompts.py" in text
