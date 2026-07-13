"""Task 6: prompt growth governor.

SECTIONS.md (the section component reference) used to be inlined wholesale
into every turn's system prompt via BASE_SYSTEM_INSTRUCTION — 40KB+ and
growing with every new section the WebSight training loop adds. These tests
pin the replacement: a compact SECTION_INDEX (name + purpose + prop names,
one line per component) stays in the prompt's stable prefix, and the full
per-section prop table (types, requiredness, descriptions) moves behind an
on-demand `get_section_reference` tool.
"""
import pytest

from agent.content_validator import get_allowed_sections
from agent.prompts import BASE_SYSTEM_INSTRUCTION, section_index

# The compact index, rendered once for these content assertions (it is a
# function now — rendered fresh per turn — rather than an import-time constant).
SECTION_INDEX = section_index()


def test_sections_index_lists_all_components():
    """Every component the validator allows must be named in the compact
    index, so the model never sees a prompt that omits an available
    section."""
    for name in get_allowed_sections():
        assert f"<{name} />" in SECTION_INDEX, f"{name} missing from SECTION_INDEX"


def test_base_system_instruction_has_no_full_prop_table():
    """The old wholesale inline put the FULL SECTIONS.md markdown table into
    the prompt. A full prop-table row's verbose description text (only ever
    emitted in the per-section doc block, never the compact index) must not
    appear in the assembled base instruction."""
    # Distinctive verbose descriptions lifted straight from SECTIONS.md's
    # Hero and Article prop tables — the compact index only carries prop
    # NAMES, never these descriptions.
    assert "Omit for image-only hero sections." not in BASE_SYSTEM_INSTRUCTION
    assert "renders a two-column layout (position controlled by sidebarPosition)" not in BASE_SYSTEM_INSTRUCTION
    # The markdown table syntax itself should be gone too.
    assert "| Property | Required | Type | Description |" not in BASE_SYSTEM_INSTRUCTION


def test_section_index_still_names_hero_props():
    """The compact index must still carry prop NAMES (just not descriptions)
    so the model knows Hero accepts e.g. `heading` without a tool call."""
    hero_line = next(line for line in SECTION_INDEX.splitlines() if "<Hero />" in line)
    assert "heading" in hero_line
    assert "Omit for image-only hero sections." not in hero_line


def test_section_index_flags_structured_props_with_shape_hint():
    """Regression guard (T6 follow-up): the compact index must still signal
    which props are OBJECT/ARRAY-shaped, not just their bare names — dropping
    this caused gemini-2.5-flash to guess a plain string for Article/Hero's
    `image` prop (`image="/foo.jpg"` instead of `image={ src, alt }`),
    breaking the built page. A structured prop's index entry must show a
    compact shape hint; a scalar prop must stay a bare name."""
    article_line = next(line for line in SECTION_INDEX.splitlines() if "<Article />" in line)
    assert "image={" in article_line, f"Article's image prop lost its shape hint: {article_line}"
    assert "image={src,alt}" in article_line or "image={src, alt}" in article_line

    hero_line = next(line for line in SECTION_INDEX.splitlines() if "<Hero />" in line)
    assert "image={" in hero_line, f"Hero's image prop lost its shape hint: {hero_line}"

    # A scalar prop (heading is a plain string on both Article and Hero) must
    # NOT get a structured-shape hint — only object/array props do.
    assert "heading" in article_line
    assert "heading={" not in article_line
    assert "heading=[" not in article_line
    assert "heading" in hero_line
    assert "heading={" not in hero_line
    assert "heading=[" not in hero_line


@pytest.mark.asyncio
async def test_get_section_reference_returns_full_props(tmp_path, monkeypatch):
    """Calling the tool with a real section name returns its full prop table
    (types, requiredness, descriptions); an unknown name returns an error
    dict instead of raising."""
    tool_map = await _get_tool_map(tmp_path, monkeypatch)
    assert "get_section_reference" in tool_map

    result = await tool_map["get_section_reference"]("Hero")
    assert result["section"] == "Hero"
    assert "Omit for image-only hero sections." in result["reference"]
    assert "| Property | Required | Type | Description |" in result["reference"]

    error = await tool_map["get_section_reference"]("NotARealSection")
    assert "error" in error


@pytest.mark.asyncio
async def test_get_section_reference_is_read_only(tmp_path, monkeypatch):
    """get_section_reference must be registered as read-only so a turn that
    only calls it (no edit) stays 'honest' for the fabricated-success
    claim-guard instead of being treated as a no-op turn."""
    from agent.site_editor import _READ_ONLY_TOOLS

    assert "get_section_reference" in _READ_ONLY_TOOLS


async def _get_tool_map(tmp_path, monkeypatch):
    """Instantiates a real AgentSiteEditor over a throwaway local workspace,
    drives one turn with a stubbed LLM that performs no tool calls, and
    returns the {name: function} map of tools handed to run_turn. Mirrors
    test_prompts.py's _get_tool_map helper."""
    from agent.llm.testing import patch_run_turn
    from agent.llm.types import LLMResult, Usage
    from agent.providers.git.base import LocalGitProvider
    from agent.site_editor import AgentSiteEditor

    captured = {}

    async def driver(*, system_instruction, messages, tools):
        captured["tools"] = {t.__name__: t for t in tools}
        return LLMResult(text="ok", tool_calls=[], usage=Usage())

    patch_run_turn(monkeypatch, driver)

    ws = tmp_path / "workspace"
    (ws / "content" / "pages").mkdir(parents=True)
    (ws / "content" / "pages" / "index.mdx").write_text("---\ntitle: Home\n---\n")
    (ws / "content" / "settings.yaml").write_text("site:\n  name: My Business\n")
    provider = LocalGitProvider(workspace_root=str(ws))
    editor = AgentSiteEditor(git_provider=provider, api_key="test-key")
    await editor.run("hello", "local_project")
    return captured["tools"]
