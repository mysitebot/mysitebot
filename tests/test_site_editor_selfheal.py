"""[SYSTEM] self-heal turns must never end with the generic saved-your-changes
fallback: when tools committed a fix but the model produced no final text, the
reply the user sees must be the self-heal script (an issue was noticed and
auto-corrected), not a routine save confirmation. Seen live 3/3 on
sam_self_heal_001 (run 2026-07-03T08-59-17)."""
import pytest

from agent.llm.types import LLMResult, LLMTransientError, Usage

FIXED_PAGE = "---\ntitle: About\npageLayout: \"default\"\n---\n<Hero heading=\"About Us\" />\n"

BROKEN_ABOUT_FILES = {
    "content/pages/about.mdx": "---\ntitle: About\n---\nbroken",
    "content/settings.yaml": "site:\n  name: My Business\n",
}


def _empty_text_after_edit():
    """run_turn driver: performs one real edit, then returns empty final text."""
    async def driver(*, system_instruction, messages, tools):
        tool_map = {t.__name__: t for t in tools}
        await tool_map["branch_and_edit_content"](
            branch_name="fix-build", file_path="content/pages/about.mdx",
            content=FIXED_PAGE)
        return LLMResult(text="", tool_calls=[], usage=Usage())
    return driver


@pytest.mark.asyncio
async def test_system_turn_empty_reply_falls_back_to_self_heal_script(
        seed_workspace, make_editor):
    ws = seed_workspace(BROKEN_ABOUT_FILES)
    editor = make_editor(ws, _empty_text_after_edit())
    result = await editor.run("build failed logs...", "local_project",
                              is_system=True)
    assert result["pipeline_triggered"] is True
    assert "corrected it automatically" in result["text"]
    assert "saved your changes" not in result["text"]


@pytest.mark.asyncio
async def test_user_turn_empty_reply_keeps_generic_fallback(
        seed_workspace, make_editor):
    ws = seed_workspace(BROKEN_ABOUT_FILES)
    editor = make_editor(ws, _empty_text_after_edit())
    result = await editor.run("please fix my about page", "local_project")
    assert result["pipeline_triggered"] is True
    assert "saved your changes" in result["text"]


@pytest.mark.asyncio
async def test_system_turn_transient_drop_after_commit_uses_self_heal_script(
        seed_workspace, make_editor):
    async def driver(*, system_instruction, messages, tools):
        tool_map = {t.__name__: t for t in tools}
        await tool_map["branch_and_edit_content"](
            branch_name="fix-build", file_path="content/pages/about.mdx",
            content=FIXED_PAGE)
        raise LLMTransientError("model dropped")

    ws = seed_workspace(BROKEN_ABOUT_FILES)
    editor = make_editor(ws, driver)
    result = await editor.run("build failed logs...", "local_project",
                              is_system=True)
    assert result["pipeline_triggered"] is True
    assert "corrected it automatically" in result["text"]
