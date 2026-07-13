import logging

import httpx
import openai
import pytest
from agent.llm import LLMClient
from agent.llm.client import MAX_TOOL_ITERATIONS
from agent.llm.types import Usage, LLMTransientError  # noqa: F401  (imported to assert availability)


class _Msg:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or None


class _ToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = type("F", (), {"name": name, "arguments": arguments})


class _Resp:
    def __init__(self, message, pt=1, ct=1):
        self.choices = [type("C", (), {"message": message})]
        self.usage = type("U", (), {"prompt_tokens": pt, "completion_tokens": ct})


class _FakeCompletions:
    """Returns queued responses in order; records calls. A queued Exception is
    raised instead of returned (to exercise the retry/escalation paths)."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeOpenAI:
    def __init__(self, responses):
        self._completions = _FakeCompletions(responses)
        self.chat = type("Chat", (), {"completions": self._completions})


def _timeout():
    return openai.APITimeoutError(request=httpx.Request("POST", "http://x"))


def _not_found():
    return openai.NotFoundError(
        "model not found", response=httpx.Response(404, request=httpx.Request("POST", "http://x")), body=None
    )


def _client_with(responses):
    c = LLMClient(api_key="k", base_url="http://x", model="m", model_thinking="mt",
                  temperature=0.3, max_output_tokens=100)
    c._client = _FakeOpenAI(responses)  # inject the fake
    return c


@pytest.mark.asyncio
async def test_run_turn_executes_tool_then_returns_text():
    ran = {}

    async def write_file(path: str, body: str) -> str:
        """Write a file."""
        ran["path"] = path
        return "written"

    responses = [
        _Resp(_Msg(tool_calls=[_ToolCall("call_1", "write_file", '{"path": "a", "body": "b"}')]), pt=5, ct=2),
        _Resp(_Msg(content="all done"), pt=3, ct=4),
    ]
    client = _client_with(responses)
    result = await client.run_turn(system_instruction="sys", messages=[{"role": "user", "content": "go"}], tools=[write_file])

    assert result.text == "all done"
    assert ran["path"] == "a"
    assert [t.name for t in result.tool_calls] == ["write_file"]
    # usage summed across both iterations: prompt 5+3, completion 2+4
    assert result.usage.prompt_tokens == 8
    assert result.usage.completion_tokens == 6


@pytest.mark.asyncio
async def test_run_turn_no_tools_returns_immediately():
    client = _client_with([_Resp(_Msg(content="hi"), pt=2, ct=1)])
    result = await client.run_turn(system_instruction="sys", messages=[{"role": "user", "content": "hi"}], tools=[])
    assert result.text == "hi"
    assert result.tool_calls == []
    assert result.usage.total_tokens == 3


@pytest.mark.asyncio
async def test_complete_returns_text_and_usage():
    client = _client_with([_Resp(_Msg(content="summary"), pt=10, ct=2)])
    result = await client.complete(system_instruction="sys", prompt="text", max_output_tokens=50)
    assert result.text == "summary"
    assert result.usage.prompt_tokens == 10


@pytest.mark.asyncio
async def test_force_thinking_routes_to_thinking_model():
    client = _client_with([_Resp(_Msg(content="ok"))])
    await client.run_turn(system_instruction="s", messages=[{"role": "user", "content": "x"}],
                          tools=[], force_thinking=True)
    assert client._client._completions.calls[0]["model"] == "mt"


@pytest.mark.asyncio
async def test_not_found_escalates_to_thinking_model(monkeypatch):
    # First call (model "m") 404s; client escalates to "mt" and succeeds.
    client = _client_with([_not_found(), _Resp(_Msg(content="recovered"))])
    result = await client.complete(system_instruction="s", prompt="x")
    assert result.text == "recovered"
    calls = client._client._completions.calls
    assert calls[0]["model"] == "m"
    assert calls[1]["model"] == "mt"


@pytest.mark.asyncio
async def test_tool_iteration_cap_logs_warning(caplog):
    # A turn that never stops calling tools hits MAX_TOOL_ITERATIONS and returns
    # best-effort — that must be observable in the logs, not silently identical
    # to a normal empty reply.
    async def noop_tool() -> str:
        """Does nothing."""
        return "ok"

    responses = [
        _Resp(_Msg(tool_calls=[_ToolCall(f"c{i}", "noop_tool", "{}")]))
        for i in range(MAX_TOOL_ITERATIONS)
    ]
    client = _client_with(responses)
    with caplog.at_level(logging.WARNING, logger="agent.llm.client"):
        result = await client.run_turn(
            system_instruction="s", messages=[{"role": "user", "content": "x"}], tools=[noop_tool])
    assert len(result.tool_calls) == MAX_TOOL_ITERATIONS
    assert any("MAX_TOOL_ITERATIONS" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_transient_exhaustion_raises_llmtransient(monkeypatch):
    # Avoid real backoff sleeps.
    async def _no_sleep(*a, **k):
        return None
    monkeypatch.setattr("agent.llm.client.asyncio.sleep", _no_sleep)
    client = _client_with([_timeout(), _timeout(), _timeout()])
    with pytest.raises(LLMTransientError):
        await client.complete(system_instruction="s", prompt="x")


def _status_error(status: int, message: str = "boom"):
    return openai.APIStatusError(
        message,
        response=httpx.Response(status, request=httpx.Request("POST", "http://x")),
        body=None,
    )


@pytest.mark.asyncio
async def test_transient_status_code_is_retried(monkeypatch):
    # A 500 whose message contains none of the legacy substring markers must
    # still classify as transient — the status code is the honest signal.
    async def _no_sleep(*a, **k):
        return None
    monkeypatch.setattr("agent.llm.client.asyncio.sleep", _no_sleep)
    client = _client_with([_status_error(500, "internal"), _Resp(_Msg(content="ok"))])
    result = await client.complete(system_instruction="s", prompt="x")
    assert result.text == "ok"


@pytest.mark.asyncio
async def test_permanent_status_with_transient_looking_message_raises(monkeypatch):
    # A 400 whose MESSAGE happens to contain "429"/"overloaded" text is NOT
    # transient: with a status code present, substring matching must not
    # apply. It surfaces immediately (no retries, no LLMTransientError).
    async def _no_sleep(*a, **k):
        raise AssertionError("must not retry a permanent 400")
    monkeypatch.setattr("agent.llm.client.asyncio.sleep", _no_sleep)
    client = _client_with([_status_error(400, "quota text mentioning 429 overloaded")])
    with pytest.raises(openai.APIStatusError) as exc_info:
        await client.complete(system_instruction="s", prompt="x")
    assert not isinstance(exc_info.value, LLMTransientError)


@pytest.mark.asyncio
async def test_model_fallback_keeps_full_transient_budget(monkeypatch):
    # The 404 escalation must have its own path: after falling back to the
    # thinking model, the FULL transient budget (3 attempts) is still
    # available — the 404 must not consume one.
    async def _no_sleep(*a, **k):
        return None
    monkeypatch.setattr("agent.llm.client.asyncio.sleep", _no_sleep)
    client = _client_with([
        _not_found(),                       # model "m" unknown → escalate
        _timeout(), _timeout(),             # two transients on "mt"...
        _Resp(_Msg(content="made it")),     # ...third attempt succeeds
    ])
    result = await client.complete(system_instruction="s", prompt="x")
    assert result.text == "made it"
    calls = client._client._completions.calls
    assert [c["model"] for c in calls] == ["m", "mt", "mt", "mt"]


@pytest.mark.asyncio
async def test_exhausted_404_raises_permanent_not_transient():
    # Both the configured and the fallback model 404 — that is permanent
    # (retrying cannot help) and must NOT surface as LLMTransientError, which
    # callers treat as retry-worthy.
    client = _client_with([_not_found(), _not_found()])
    with pytest.raises(openai.NotFoundError):
        await client.complete(system_instruction="s", prompt="x")


@pytest.mark.asyncio
async def test_malformed_tool_args_surface_error_and_model_self_corrects():
    # Iteration 1: the model emits unparseable tool arguments. The tool must
    # NOT run; the tool result must carry an explicit JSON error. Iteration 2:
    # the model retries with valid JSON and the tool runs.
    ran = []

    async def write_file(path: str) -> str:
        """Write a file."""
        ran.append(path)
        return "written"

    responses = [
        _Resp(_Msg(tool_calls=[_ToolCall("c1", "write_file", '{"path": "a')])),   # truncated JSON
        _Resp(_Msg(tool_calls=[_ToolCall("c2", "write_file", '{"path": "a"}')])),
        _Resp(_Msg(content="done")),
    ]
    client = _client_with(responses)
    result = await client.run_turn(
        system_instruction="s", messages=[{"role": "user", "content": "x"}], tools=[write_file])

    assert result.text == "done"
    assert ran == ["a"]  # the malformed call never invoked the tool
    assert "arguments were not valid JSON" in result.tool_calls[0].result
    assert result.tool_calls[0].args == {}
    # The error was fed back to the model as the tool message.
    second_call_messages = client._client._completions.calls[1]["messages"]
    tool_msgs = [m for m in second_call_messages if m.get("role") == "tool"]
    assert any("arguments were not valid JSON" in m["content"] for m in tool_msgs)
