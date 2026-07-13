"""The prompt's compact section index must follow a SECTIONS.md/component
regeneration (the training loop rewrites both in-process) without a module
reload — it used to be an import-time constant, so a freshly added section
stayed invisible to the prompt for the process lifetime."""
import textwrap

from agent.prompts import base_system_instruction, section_index

SECTIONS_MD_ONE = textwrap.dedent("""\
    # Sections

    ## `<Hero />`
    Hero Component - A big banner.

    | Property | Required | Type | Description |
    |---|---|---|---|
    | `heading` | no | `string` | Headline |

    ---
""")

NEW_BLOCK = textwrap.dedent("""\
    ## `<Zebra />`
    Zebra Component - A striped section.

    | Property | Required | Type | Description |
    |---|---|---|---|
    | `stripes` | yes | `number` | How many stripes |

    ---
""")


def _seed_templates(root, sections_md, components):
    comp_dir = root / "astro-basic" / "src" / "components" / "sections"
    comp_dir.mkdir(parents=True, exist_ok=True)
    for name in components:
        (comp_dir / f"{name}.astro").write_text("---\n---\n<section />\n")
    (root / "SECTIONS.md").write_text(sections_md)


def test_new_section_appears_without_reimport(tmp_path, monkeypatch):
    import agent.templates as templates_mod

    root = tmp_path / "templates"
    _seed_templates(root, SECTIONS_MD_ONE, ["Hero"])
    monkeypatch.setattr(templates_mod, "_TEMPLATES_ROOT", None)
    monkeypatch.setattr(templates_mod, "_candidate_roots", lambda: [root])

    first = section_index()
    assert "<Hero />" in first
    assert "Zebra" not in first

    # Regenerate: a new component lands in both the component dir and
    # SECTIONS.md (what the training loop's sync step does).
    _seed_templates(root, SECTIONS_MD_ONE + "\n" + NEW_BLOCK, ["Hero", "Zebra"])

    second = section_index()
    assert "<Zebra />" in second
    assert "stripes" in second

    # And the assembled per-turn instruction picks it up too.
    assert "<Zebra />" in base_system_instruction()
