"""A turn that hits MAX_TOOL_ITERATIONS never wrote its considered final
reply — its best-effort text is untrustworthy by construction. Live-caught
2026-07-18: a capped refine turn answered "I've corrected the image syntax on
your Impact page" while that file was untouched (another page's edit had
succeeded, so the committed-work path relayed the text verbatim)."""
import pytest

from agent.llm import LLMClient
from agent.llm.client import MAX_TOOL_ITERATIONS
from agent.llm.types import LLMResult, Usage
from agent.llm.testing import patch_run_turn
from agent.providers.git.base import LocalGitProvider
from agent.site_editor import AgentSiteEditor


class _Msg:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or None


class _ToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = type("F", (), {"name": name, "arguments": arguments})


class _Resp:
    def __init__(self, message):
        self.choices = [type("C", (), {"message": message})]
        self.usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})


class _FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)

    async def create(self, **kwargs):
        return self._responses.pop(0)


class _FakeOpenAI:
    def __init__(self, responses):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(responses)})


def _client_with(responses):
    client = LLMClient(api_key="k", base_url="http://x", model="m", model_thinking="mt",
                       temperature=0.0, max_output_tokens=100)
    client._client = _FakeOpenAI(responses)
    return client


@pytest.mark.asyncio
async def test_tool_iteration_cap_sets_capped_flag():
    async def noop_tool() -> str:
        """Does nothing."""
        return "ok"

    responses = [
        _Resp(_Msg(tool_calls=[_ToolCall(f"c{i}", "noop_tool", "{}")]))
        for i in range(MAX_TOOL_ITERATIONS)
    ]
    client = _client_with(responses)
    result = await client.run_turn(
        system_instruction="s", messages=[{"role": "user", "content": "x"}], tools=[noop_tool])
    assert result.capped is True

    normal = _client_with([_Resp(_Msg(content="done"))])
    result = await normal.run_turn(
        system_instruction="s", messages=[{"role": "user", "content": "x"}], tools=[noop_tool])
    assert result.capped is False


def _editor(tmp_path):
    ws = tmp_path / "workspace"
    (ws / "content" / "pages").mkdir(parents=True)
    (ws / "content" / "pages" / "index.mdx").write_text('---\ntitle: "Home"\n---\n\nHello.\n')
    (ws / "content" / "settings.yaml").write_text("site:\n  name: My Business\n")
    provider = LocalGitProvider(workspace_root=str(ws))
    return AgentSiteEditor(git_provider=provider, api_key="test-key")


@pytest.mark.asyncio
async def test_capped_turn_with_commits_gets_honest_partial_reply(tmp_path, monkeypatch):
    async def driver(*, system_instruction, messages, tools):
        edit = next(t for t in tools if t.__name__ == "branch_and_edit_content")
        out = await edit(branch_name="draft", file_path="content/pages/index.mdx",
                         content='---\ntitle: "Home"\n---\n\nUpdated body.\n')
        assert "error" not in out
        return LLMResult(text="I've corrected the image syntax on your Impact page!",
                         tool_calls=[], usage=Usage(), capped=True)

    patch_run_turn(monkeypatch, driver)
    editor = _editor(tmp_path)
    result = await editor.run("fix everything", "local_project")
    text = result["text"]
    assert "corrected the image syntax" not in text        # unfinished claim dropped
    assert "ran out of steps" in text                       # honest partial message
    assert result["pipeline_triggered"] is True


@pytest.mark.asyncio
async def test_capped_turn_without_commits_gets_honest_failure_reply(tmp_path, monkeypatch):
    async def driver(*, system_instruction, messages, tools):
        return LLMResult(text="All done — everything is updated!",
                         tool_calls=[], usage=Usage(), capped=True)

    patch_run_turn(monkeypatch, driver)
    editor = _editor(tmp_path)
    result = await editor.run("fix everything", "local_project")
    text = result["text"]
    assert "All done" not in text
    assert "smaller" in text                                # suggests splitting the ask
    assert result["pipeline_triggered"] is False
