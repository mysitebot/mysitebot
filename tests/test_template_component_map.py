"""Template lint: the MDX component map in the sealed template must stay in sync
with the actual section components.

A section that exists and is documented (SECTIONS.md / registry) but is missing
from the shared `sectionComponents` map (src/components/sections/index.ts)
renders as an inert unknown element — the build succeeds and the page ships
with a silent hole (this is exactly how Parallax shipped broken). Conversely a
mapped-but-unimported name breaks the build. This test turns both into a hard
failure.

The map used to live inline in [...slug].astro; it was extracted to
components/sections/index.ts so blog/[slug].astro could share it without the
two drifting apart — this test follows the map to its new home.
"""
import re
from pathlib import Path

from agent.templates import template_path


def _read_section_index() -> str:
    return Path(template_path("astro-basic", "src", "components", "sections", "index.ts")).read_text()


def _section_component_names() -> set:
    sections_dir = Path(template_path("astro-basic", "src", "components", "sections"))
    return {p.stem for p in sections_dir.glob("*.astro")}


def _mapped_component_names() -> set:
    text = _read_section_index()
    m = re.search(r"export const sectionComponents = \{(.*?)\};", text, re.DOTALL)
    assert m, "Could not locate the `sectionComponents` map in components/sections/index.ts"
    return {tok.strip() for tok in m.group(1).split(",") if tok.strip()}


def test_every_section_component_is_registered_in_mdx_map():
    sections = _section_component_names()
    mapped = _mapped_component_names()
    missing = sections - mapped
    extra = mapped - sections
    assert not missing, f"Section components missing from the MDX map (would render nothing): {sorted(missing)}"
    assert not extra, f"MDX map references components with no .astro file: {sorted(extra)}"


def test_every_mapped_component_is_imported():
    text = _read_section_index()
    for name in _mapped_component_names():
        assert re.search(rf"^import {name} from ", text, re.MULTILINE), \
            f"Component '{name}' is in the map but never imported — the build would fail."
