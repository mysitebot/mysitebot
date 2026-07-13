"""The empty/fabricated-reply regeneration loop in AgentSiteEditor.run:
honest replies (including after read-only tool work) are relayed untouched,
fabricated edit claims with no tool activity are regenerated on the stronger
model, and only a persistently scripted lie is replaced with the honest
failure apology."""
import pytest

from agent.llm.types import LLMResult, Usage

CONTACT_FILES = {
    "content/pages/contact.mdx":
        "---\ntitle: Contact\n---\n<ContactForm heading=\"Call us on 555-0100\" />\n",
    "content/settings.yaml": "site:\n  name: My Business\n",
}


def _scripted(replies):
    """run_turn driver returning queued (text, tool_runner) pairs; records the
    force_thinking flag of every call. tool_runner, when set, is awaited with
    the bound tool map so the turn performs real tool work."""
    calls = []

    async def driver(*, system_instruction, messages, tools, force_thinking=False):
        calls.append({"force_thinking": force_thinking})
        text, tool_runner = replies[min(len(calls) - 1, len(replies) - 1)]
        tool_map = {t.__name__: t for t in tools}
        executed = []
        if tool_runner is not None:
            executed = await tool_runner(tool_map)
        return LLMResult(text=text, tool_calls=executed, usage=Usage())

    return driver, calls


async def _read_contact_page(tool_map):
    from agent.llm.types import ToolCall
    out = await tool_map["read_content_file"](file_path="content/pages/contact.mdx")
    return [ToolCall(name="read_content_file",
                     args={"file_path": "content/pages/contact.mdx"}, result=str(out))]


@pytest.mark.asyncio
async def test_honest_double_check_after_read_is_relayed(seed_workspace, make_editor):
    ws = seed_workspace(CONTACT_FILES)
    honest = "I've double-checked — the phone number on your contact page is correct."
    driver, calls = _scripted([(honest, _read_contact_page)])
    editor = make_editor(ws, driver)
    result = await editor.run("is my phone number right?", "local_project")
    assert result["text"] == honest
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_scripted_phrase_after_read_only_tools_is_honest(seed_workspace, make_editor):
    # "double-checking" narration after genuinely reading the file is real
    # verification work, not a parroted post-edit script — never regenerate it.
    ws = seed_workspace(CONTACT_FILES)
    reply = "I'm double-checking everything now — the number reads 555-0100."
    driver, calls = _scripted([(reply, _read_contact_page)])
    editor = make_editor(ws, driver)
    result = await editor.run("check my phone number", "local_project")
    assert result["text"] == reply
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_negated_changes_ready_reply_is_relayed(seed_workspace, make_editor):
    ws = seed_workspace(CONTACT_FILES)
    reply = "No changes are ready to publish yet — make an edit first."
    driver, calls = _scripted([(reply, None)])
    editor = make_editor(ws, driver)
    result = await editor.run("publish my site", "local_project")
    assert result["text"] == reply
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_scripted_claim_with_zero_tool_calls_is_replaced(seed_workspace, make_editor):
    # Every attempt parrots the post-edit script without running any tool —
    # the lie must never be relayed.
    ws = seed_workspace(CONTACT_FILES)
    lie = "I'm double-checking everything now — your changes are ready!"
    driver, calls = _scripted([(lie, None)])
    editor = make_editor(ws, driver)
    result = await editor.run("change my heading", "local_project")
    assert result["pipeline_triggered"] is False
    assert "wasn't able to apply" in result["text"]
    assert len(calls) == 3
    # Regeneration escalates to the stronger model.
    assert calls[1]["force_thinking"] is True
    assert calls[2]["force_thinking"] is True


@pytest.mark.asyncio
async def test_fabricated_claim_regenerates_then_relays_honest_retry(seed_workspace, make_editor):
    ws = seed_workspace(CONTACT_FILES)
    honest = "Which page would you like me to update — Home or Contact?"
    driver, calls = _scripted([
        ("I'm adding the newsletter section now.", None),
        (honest, None),
    ])
    editor = make_editor(ws, driver)
    result = await editor.run("add a newsletter", "local_project")
    assert result["text"] == honest
    assert len(calls) == 2
    assert calls[0]["force_thinking"] is False
    assert calls[1]["force_thinking"] is True


@pytest.mark.asyncio
async def test_empty_reply_escalates_on_first_retry(seed_workspace, make_editor):
    # Attempt 0 at temp 0.3 came back empty; replaying identical inputs on the
    # same model mostly reproduces the same nothing — the first retry must
    # already escalate to the thinking model.
    ws = seed_workspace(CONTACT_FILES)
    driver, calls = _scripted([("", None), ("Hello! How can I help?", None)])
    editor = make_editor(ws, driver)
    result = await editor.run("hi", "local_project")
    assert result["text"] == "Hello! How can I help?"
    assert len(calls) == 2
    assert calls[0]["force_thinking"] is False
    assert calls[1]["force_thinking"] is True


@pytest.mark.asyncio
async def test_all_empty_replies_fall_back_to_apology(seed_workspace, make_editor):
    ws = seed_workspace(CONTACT_FILES)
    driver, calls = _scripted([("", None)])
    editor = make_editor(ws, driver)
    result = await editor.run("hi", "local_project")
    assert "trouble forming a reply" in result["text"]
    assert len(calls) == 3
