"""Test seam: patch LLMClient.run_turn / complete in suites without a live API.
Imported by both projects/agent and projects/api test suites."""
import inspect

from agent.llm.types import LLMResult, Usage


def patch_run_turn(monkeypatch, driver):
    """driver: async (system_instruction, messages, tools) -> LLMResult.
    Drives the passed tool functions to simulate the model deciding to call them.
    A driver may additionally declare a `force_thinking` keyword parameter to
    observe the editor's model-escalation decisions (the retry tests do)."""
    forward_force_thinking = "force_thinking" in inspect.signature(driver).parameters

    async def _run_turn(self, *, system_instruction, messages, tools, force_thinking=False):
        kwargs = dict(system_instruction=system_instruction, messages=messages, tools=tools)
        if forward_force_thinking:
            kwargs["force_thinking"] = force_thinking
        return await driver(**kwargs)
    monkeypatch.setattr("agent.llm.LLMClient.run_turn", _run_turn)


def patch_complete(monkeypatch, text):
    async def _complete(self, *, system_instruction, prompt, max_output_tokens=None):
        return LLMResult(text=text, tool_calls=[], usage=Usage())
    monkeypatch.setattr("agent.llm.LLMClient.complete", _complete)
