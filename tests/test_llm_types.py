from agent.llm.types import Usage, ToolCall, LLMResult, LLMTransientError


def test_usage_total_and_add():
    a = Usage(prompt_tokens=10, completion_tokens=5)
    b = Usage(prompt_tokens=3, completion_tokens=7)
    summed = a + b
    assert summed.prompt_tokens == 13
    assert summed.completion_tokens == 12
    assert summed.total_tokens == 25


def test_usage_defaults_zero():
    u = Usage()
    assert u.prompt_tokens == 0 and u.completion_tokens == 0 and u.total_tokens == 0


def test_llmresult_holds_fields():
    tc = ToolCall(name="read_content_file", args={"path": "x"}, result="ok")
    r = LLMResult(text="hi", tool_calls=[tc], usage=Usage(1, 2), raw=None)
    assert r.text == "hi"
    assert r.tool_calls[0].name == "read_content_file"
    assert r.usage.total_tokens == 3


def test_transient_error_is_exception():
    assert issubclass(LLMTransientError, Exception)
