"""Storeless (local CLI) mode must not offer the multi-project lifecycle tools,
and the local provider's availability answer must match what create_project
will actually do.

Seen live 2026-07-18: `cli.py --dir ./site --prompt "Create a website..."`
made the agent call create_project, which built the site in a SIBLING
directory of --dir (the CLI's own workspace stayed the pristine template),
while check_project_availability had just answered available=True for a name
create_project then refused as already existing.
"""
import pytest

from agent.providers.git.base import LocalGitProvider
from agent.site_editor import AgentSiteEditor, TurnContext
from agent.toolbox import build_tools


def _editor(tmp_path, store=None):
    return AgentSiteEditor(
        git_provider=LocalGitProvider(workspace_root=str(tmp_path)),
        session_id="test", api_key="test-key", store=store)


def _tool_names(editor):
    ctx = TurnContext(active_project_id="p", active_provider_id="p")
    return [fn.__name__ for fn in build_tools(editor, ctx)]


def test_storeless_mode_offers_no_project_lifecycle_tools(tmp_path):
    """The CLI edits ONE local workspace: creating additional projects (and
    checking name availability for them) is a SaaS concern, exactly like the
    publish pair — offering them makes 'Create a website...' prompts build a
    sibling directory instead of the user's --dir."""
    names = _tool_names(_editor(tmp_path))
    assert "create_project" not in names
    assert "check_project_availability" not in names
    assert "create_publish_request" not in names          # existing invariant
    assert "publish_changes" not in names
    # the single-site editing core stays intact
    for core in ("list_content_files", "read_content_file",
                 "branch_and_edit_content", "delete_content_file",
                 "show_settings_page", "get_section_reference"):
        assert core in names


def test_store_mode_still_offers_project_lifecycle_tools(tmp_path):
    class _StubStore:
        pass

    names = _tool_names(_editor(tmp_path, store=_StubStore()))
    for tool in ("create_project", "check_project_availability",
                 "create_publish_request", "publish_changes"):
        assert tool in names


@pytest.mark.asyncio
async def test_local_availability_answer_is_creatable(tmp_path):
    """If a project directory already exists, availability must not answer
    with that same name (create_project refuses to overwrite it) — it appends
    a numeric suffix, as the tool contract advertises."""
    provider = LocalGitProvider(workspace_root=str(tmp_path))
    first = await provider.check_project_availability("Cafe Luna!")
    assert first == {"available": True, "name": "cafe-luna"}
    await provider.create_project("cafe-luna", "astro-basic")

    second = await provider.check_project_availability("Cafe Luna!")
    assert second["available"] is True
    assert second["name"] != "cafe-luna"
    # the suggested name is genuinely creatable
    created = await provider.create_project(second["name"], "astro-basic")
    assert created.get("id") or created.get("project_id")
