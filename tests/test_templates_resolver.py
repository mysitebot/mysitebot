import os
import shutil

import pytest

import agent.templates as templates_mod
from agent.templates import TemplatesUnavailableError, template_path, templates_root


def test_resolver_points_at_bundled_templates():
    assert os.path.isdir(templates_root())
    assert os.path.isdir(template_path("astro-basic"))
    assert os.path.isfile(template_path("SECTIONS.md"))
    assert os.path.isdir(template_path("astro-basic", "src", "components", "sections"))


def test_missing_templates_tree_raises_loudly(monkeypatch, tmp_path):
    """No silent empty resolution: when neither the source checkout nor the
    installed package data exists, template_path must raise, not hand back a
    path into nowhere that downstream code treats as 'no sections exist'."""
    monkeypatch.setattr(templates_mod, "_TEMPLATES_ROOT", None)
    monkeypatch.setattr(
        templates_mod, "_candidate_roots",
        lambda: [tmp_path / "nope-a", tmp_path / "nope-b"])
    with pytest.raises(TemplatesUnavailableError):
        template_path("SECTIONS.md")


def test_allowed_sections_fall_back_to_schema_file(monkeypatch, tmp_path):
    """With the component directory missing but sections-schema.json present
    (a slim install), the whitelist comes from the committed schema — all 21
    section names, not a stale hand-maintained list."""
    from agent.content_validator import get_allowed_sections

    slim_root = tmp_path / "templates"
    slim_root.mkdir()
    shutil.copyfile(template_path("sections-schema.json"),
                    slim_root / "sections-schema.json")

    monkeypatch.setattr(templates_mod, "_TEMPLATES_ROOT", None)
    monkeypatch.setattr(templates_mod, "_candidate_roots", lambda: [slim_root])

    names = get_allowed_sections()
    assert len(names) == 21
    assert "Hero" in names and "ContactForm" in names and "TwoColumn" in names
