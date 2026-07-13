"""Publish flow gating (store-less vs SaaS mode).

Without a store there is no pending-draft record for create_publish_request /
publish_changes to work against (publish_changes could only ever answer
"there is no pending draft"), so in CLI mode the two tools must not be offered
and the prompt must not narrate a publish step the model cannot perform. With
a store, tools and narrative are unchanged."""
import pytest

from agent.llm.types import LLMResult, Usage
from agent.prompts import BASE_SYSTEM_INSTRUCTION, PUBLISH_POLICY

PUBLISH_TOOLS = {"create_publish_request", "publish_changes"}


def _capture(captured):
    async def driver(*, system_instruction, messages, tools):
        captured["instruction"] = system_instruction
        captured["tools"] = {t.__name__ for t in tools}
        return LLMResult(text="ok", tool_calls=[], usage=Usage())
    return driver


@pytest.mark.asyncio
async def test_cli_mode_offers_no_publish_tools_and_no_publish_narrative(
        seed_workspace, make_editor):
    ws = seed_workspace()
    captured = {}
    editor = make_editor(ws, _capture(captured))  # store=None
    await editor.run("hello", "local_project")

    assert not (PUBLISH_TOOLS & captured["tools"])
    assert "create_publish_request" not in captured["instruction"]
    assert "publish_changes" not in captured["instruction"]
    assert PUBLISH_POLICY not in captured["instruction"]
    # The rest of the edit loop survives the scrub.
    assert "branch_and_edit_content" in captured["instruction"]


@pytest.mark.asyncio
async def test_cli_wizard_mode_also_drops_publish_tools_from_narrative(
        seed_workspace, make_editor):
    ws = seed_workspace()
    captured = {}
    editor = make_editor(ws, _capture(captured))  # store=None
    await editor.run("a website for my bakery", "local_project", is_init=True)

    assert not (PUBLISH_TOOLS & captured["tools"])
    assert "create_publish_request" not in captured["instruction"]
    assert "publish_changes" not in captured["instruction"]
    # The wizard addendum itself is still present.
    assert "ONBOARDING WIZARD" in captured["instruction"]


@pytest.mark.asyncio
async def test_saas_mode_offers_publish_tools_and_unchanged_prompt(
        seed_workspace, make_editor, fake_store):
    ws = seed_workspace()
    captured = {}
    editor = make_editor(ws, _capture(captured), store=fake_store)
    await editor.run("hello", "local_project")

    assert PUBLISH_TOOLS <= captured["tools"]
    # SaaS mode keeps the exact publish-capable prompt (prefix: volatile
    # context is appended after it).
    assert captured["instruction"].startswith(BASE_SYSTEM_INSTRUCTION)
    assert PUBLISH_POLICY in captured["instruction"]
