"""The doc generator must emit sections-schema.json while leaving SECTIONS.md
byte-identical — Sam's prompt context is derived from SECTIONS.md, so any byte
drift there is a behavior change requiring an eval run (spec 2026-07-09 §4)."""
import json
import runpy
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
GENERATOR = TEMPLATES / "generate_sections_doc.py"
SECTIONS_MD = TEMPLATES / "SECTIONS.md"
SCHEMA_JSON = TEMPLATES / "sections-schema.json"


def test_generator_keeps_sections_md_byte_identical_and_emits_schema():
    before = SECTIONS_MD.read_bytes()
    assert SCHEMA_JSON.exists(), \
        "sections-schema.json is missing from the checkout — regenerate and commit it"
    schema_before = SCHEMA_JSON.read_bytes()

    runpy.run_path(str(GENERATOR), run_name="__main__")

    assert SECTIONS_MD.read_bytes() == before, "SECTIONS.md changed — Sam prompt drift"
    assert SCHEMA_JSON.exists(), "sections-schema.json was not written"
    assert SCHEMA_JSON.read_bytes() == schema_before, \
        "sections-schema.json is stale — regenerate via generate_sections_doc.py and commit it"

    schema = json.loads(SCHEMA_JSON.read_text(encoding="utf-8"))
    assert schema["version"] == 1
    sections = schema["sections"]
    # Spot-check Hero against known props (SECTIONS.md documents these).
    hero = sections["Hero"]
    props = {p["name"]: p for p in hero["props"]}
    assert props["heading"]["kind"] == "string"
    assert props["actions"]["kind"] == "object_list"
    action_fields = {f["name"]: f for f in props["actions"]["fields"]}
    assert action_fields["label"]["kind"] == "string"
    assert action_fields["variant"]["kind"] == "enum"
    assert "primary" in action_fields["variant"]["values"]
    assert props["image"]["kind"] == "image"
    # Every section present in the MD is present in the JSON.
    md_names = {ln.split("`<")[1].split(" ")[0] for ln in SECTIONS_MD.read_text().splitlines()
                if ln.startswith("## `<")}
    assert md_names == set(sections.keys())


def test_schema_types_are_not_truncated():
    schema = json.loads(SCHEMA_JSON.read_text(encoding="utf-8"))
    for section in schema["sections"].values():
        for prop in section["props"]:
            assert not prop["type"].endswith("..."), f"truncated type leaked into schema: {prop}"
