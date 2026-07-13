"""show_settings_page must report a read failure instead of fabricating
plausible defaults (smb@mysitebot.ai / #6366f1) that the model then relays to
the user as if they were the site's real settings."""
import pytest

from agent.llm.types import LLMResult, Usage


def _capture_settings_tool(captured):
    async def driver(*, system_instruction, messages, tools):
        tool_map = {t.__name__: t for t in tools}
        captured["settings"] = await tool_map["show_settings_page"]()
        return LLMResult(text="done", tool_calls=[], usage=Usage())
    return driver


@pytest.mark.asyncio
async def test_show_settings_page_reports_error_when_unreadable(tmp_path, make_editor):
    ws = tmp_path / "workspace"
    (ws / "content").mkdir(parents=True)  # no settings.yaml
    captured = {}
    editor = make_editor(ws, _capture_settings_tool(captured))
    await editor.run("show my settings", "local_project")

    out = captured["settings"]
    assert "error" in out
    # No invented stub values may leak into the reply.
    assert "smb@mysitebot.ai" not in str(out)
    assert "#6366f1" not in str(out)


@pytest.mark.asyncio
async def test_show_settings_page_returns_real_settings(seed_workspace, make_editor):
    ws = seed_workspace({
        "content/settings.yaml":
            "site:\n  name: Real Site\ncontact:\n  email: owner@real.example\n",
    })
    captured = {}
    editor = make_editor(ws, _capture_settings_tool(captured))
    await editor.run("show my settings", "local_project")

    out = captured["settings"]
    assert out["site"]["name"] == "Real Site"
    assert out["contact"]["email"] == "owner@real.example"
