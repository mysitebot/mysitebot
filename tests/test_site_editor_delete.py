"""The delete_content_file tool: real deletion with the same safety rails and
draft-branch stacking as branch_and_edit_content."""
import pytest

from agent.llm.types import LLMResult, Usage

SETTINGS_WITH_ABOUT = (
    "site:\n  name: My Business\n"
    "navigation:\n"
    "  - label: \"Home\"\n    url: \"/\"\n"
    "  - label: \"About\"\n    url: \"/about\"\n"
)

DELETE_FILES = {
    "content/pages/index.mdx": "---\ntitle: Home\n---\n",
    "content/pages/about.mdx": "---\ntitle: About\n---\n",
    "content/settings.yaml": SETTINGS_WITH_ABOUT,
}


def _driving(drive):
    """run_turn driver that hands the bound tool map to `drive` (same pattern
    as the api draft-flow tests)."""
    async def driver(*, system_instruction, messages, tools):
        tool_map = {t.__name__: t for t in tools}
        await drive(tool_map)
        return LLMResult(text="done", tool_calls=[], usage=Usage())
    return driver


@pytest.mark.asyncio
async def test_delete_tool_deletes_page_and_warns_about_dangling_nav(
        seed_workspace, make_editor):
    ws = seed_workspace(DELETE_FILES)
    out = {}

    async def drive(tools):
        out["res"] = await tools["delete_content_file"](
            branch_name="remove-about", file_path="content/pages/about.mdx")

    editor = make_editor(ws, _driving(drive))
    result = await editor.run("remove the about page", "local_project")

    assert not (ws / "content" / "pages" / "about.mdx").exists()
    assert out["res"].get("error") is None
    assert out["res"]["branch"] == "remove-about"
    # settings.yaml still links to /about — the tool must surface that so Sam
    # fixes the navigation in the same turn.
    assert "warning" in out["res"] and "/about" in out["res"]["warning"]
    assert result["pipeline_triggered"] is True


@pytest.mark.asyncio
async def test_delete_tool_refuses_homepage_and_settings(seed_workspace, make_editor):
    ws = seed_workspace(DELETE_FILES)
    out = {}

    async def drive(tools):
        out["home"] = await tools["delete_content_file"](
            branch_name="b", file_path="content/pages/index.mdx")
        out["settings"] = await tools["delete_content_file"](
            branch_name="b", file_path="content/settings.yaml")

    editor = make_editor(ws, _driving(drive))
    result = await editor.run("delete everything", "local_project")

    assert "error" in out["home"]
    assert "error" in out["settings"]
    assert (ws / "content" / "pages" / "index.mdx").exists()
    assert (ws / "content" / "settings.yaml").exists()
    assert result["pipeline_triggered"] is False


@pytest.mark.asyncio
async def test_delete_tool_refuses_paths_outside_content(seed_workspace, make_editor):
    ws = seed_workspace(DELETE_FILES)
    (ws / "package.json").write_text("{}")
    out = {}

    async def drive(tools):
        out["res"] = await tools["delete_content_file"](
            branch_name="b", file_path="content/../package.json")

    editor = make_editor(ws, _driving(drive))
    await editor.run("delete package.json", "local_project")

    assert "error" in out["res"]
    assert (ws / "package.json").exists()


@pytest.mark.asyncio
async def test_delete_tool_reports_missing_file_as_error(seed_workspace, make_editor):
    ws = seed_workspace(DELETE_FILES)
    out = {}

    async def drive(tools):
        out["res"] = await tools["delete_content_file"](
            branch_name="b", file_path="content/pages/ghost.mdx")

    editor = make_editor(ws, _driving(drive))
    result = await editor.run("remove the ghost page", "local_project")

    assert "error" in out["res"]
    assert result["pipeline_triggered"] is False


@pytest.mark.asyncio
async def test_delete_and_followup_edit_stack_on_one_branch(seed_workspace, make_editor):
    """The nav cleanup edit after a deletion must land on the deletion's branch
    so both changes publish together (same stacking rule as consecutive edits)."""
    ws = seed_workspace(DELETE_FILES)
    out = {}

    async def drive(tools):
        out["delete"] = await tools["delete_content_file"](
            branch_name="remove-about", file_path="content/pages/about.mdx")
        out["edit"] = await tools["branch_and_edit_content"](
            branch_name="totally-different-branch",
            file_path="content/settings.yaml",
            content="site:\n  name: My Business\nnavigation:\n"
                    "  - label: \"Home\"\n    url: \"/\"\n")

    editor = make_editor(ws, _driving(drive))
    await editor.run("remove the about page and its menu entry", "local_project")

    assert out["edit"]["branch"] == "remove-about"
