import json
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
    (a slim install), the whitelist comes from the committed schema — exactly
    the sections it lists, not a stale hand-maintained list. Assert against the
    schema itself rather than a literal count: the WebSight training loop grows
    the library, and a hard-coded number would just be the stale list again."""
    from agent.content_validator import get_allowed_sections

    schema_src = template_path("sections-schema.json")
    with open(schema_src) as f:
        expected = set(json.load(f)["sections"])

    slim_root = tmp_path / "templates"
    slim_root.mkdir()
    shutil.copyfile(schema_src, slim_root / "sections-schema.json")

    monkeypatch.setattr(templates_mod, "_TEMPLATES_ROOT", None)
    monkeypatch.setattr(templates_mod, "_candidate_roots", lambda: [slim_root])

    names = get_allowed_sections()
    assert set(names) == expected
    assert "Hero" in names and "ContactForm" in names and "TwoColumn" in names
