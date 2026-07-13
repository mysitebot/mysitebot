import os
import re
import pytest
from agent.site_editor import AgentSiteEditor
from agent.providers.git.base import LocalGitProvider


def test_cli_model_flag_has_no_hardcoded_default():
    """--model must default to None so the config fallback (the LLM_MODEL env
    var) wins — a hardcoded model id here silently overrode LLM_MODEL."""
    cli_path = os.path.join(os.path.dirname(__file__), "..", "cli.py")
    with open(cli_path) as f:
        source = f.read()
    m = re.search(r"add_argument\(\s*\"--model\",\s*default=(\S+?)[,)]", source)
    assert m, "cli.py no longer defines a --model flag"
    assert m.group(1) == "None"


def test_from_settings_none_model_defers_to_config(monkeypatch):
    """The mechanism the CLI's None default relies on: from_settings(model=None)
    resolves the configured model; an explicit model still wins."""
    from agent.config import settings
    from agent.llm import from_settings

    monkeypatch.setattr(settings, "llm_model", "model-from-env")
    assert from_settings(model=None, api_key="k").model == "model-from-env"
    assert from_settings(model="explicit", api_key="k").model == "explicit"

@pytest.mark.asyncio
async def test_local_git_provider_real_write(tmp_path):
    # Setup test workspace root using tmp_path
    workspace = str(tmp_path / "workspace")
    git = LocalGitProvider(workspace_root=workspace)
    
    # 1. Test project creation (copies templates/astro-basic and templates/layouts/restaurant-cafe/content)
    proj = await git.create_project("my-local-restaurant", "restaurant-cafe")
    assert proj["status"] == "created_locally"
    assert proj["project_id"] == "local_my-local-restaurant"
    
    # Verify directory structure
    dest_dir = os.path.join(workspace, "my-local-restaurant")
    assert os.path.exists(dest_dir)
    assert os.path.exists(os.path.join(dest_dir, "content"))
    
    # 2. Test committing local file
    commit = await git.commit_file(
        project_id="local_my-local-restaurant",
        branch_name="draft-branch",
        file_path="content/pages/index.mdx",
        content="---title: Luigi---\n<Hero />",
        message="Update index"
    )
    assert commit["status"] == "committed_locally"
    
    file_content = ""
    with open(os.path.join(dest_dir, "content/pages/index.mdx"), "r") as f:
        file_content = f.read()
    assert "Luigi" in file_content

@pytest.mark.asyncio
async def test_agent_site_editor_mock(tmp_path, monkeypatch):
    from agent.llm.testing import patch_run_turn
    from agent.llm.types import LLMResult, Usage

    workspace = str(tmp_path / "workspace")
    git = LocalGitProvider(workspace_root=workspace)

    editor = AgentSiteEditor(
        api_key="dummy_key",
        git_provider=git,
        model="dummy-model",
        session_id="test_session",
    )

    async def driver(*, system_instruction, messages, tools):
        tool_map = {t.__name__: t for t in tools}
        prompt_text = messages[-1]["content"] if messages else ""
        if "change" in prompt_text.lower() or "edit" in prompt_text.lower():
            if "branch_and_edit_content" in tool_map:
                await tool_map["branch_and_edit_content"](
                    branch_name="mock-edit-branch",
                    file_path="content/home.md",
                    content="# Welcome",
                )
            if "create_publish_request" in tool_map:
                await tool_map["create_publish_request"](
                    branch_name="mock-edit-branch",
                    title="Mock change request",
                )
        return LLMResult(
            text="I've made the change! A preview site is currently generating, and I'll notify you once it's ready to review.",
            tool_calls=[], usage=Usage())

    patch_run_turn(monkeypatch, driver)

    result = await editor.run("Please edit the homepage banner", "my-test-site")
    assert result["pipeline_triggered"] is True
    assert "I've made the change" in result["text"]
