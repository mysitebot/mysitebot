import asyncio
import json
import logging

import openai
from openai import AsyncOpenAI

from agent.llm.tools import function_to_schema, dispatch_tool_call, parse_tool_args
from agent.llm.types import LLMResult, LLMTransientError, ToolCall, Usage

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 20          # was Gemini's maximum_remote_calls=20
TRANSIENT_ATTEMPTS = 3            # per-model transient retry budget
# Honest transient classification: the response status code decides when the
# SDK exposes one; the substring markers are only a FALLBACK for errors that
# carry no status_code (e.g. a provider error tunneled through a connection
# layer as text).
_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
_TRANSIENT_MARKERS = ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "overloaded")


def _is_transient_status_error(e: openai.APIStatusError) -> bool:
    status = getattr(e, "status_code", None)
    if status is not None:
        return status in _TRANSIENT_STATUS_CODES
    return any(m in str(e) for m in _TRANSIENT_MARKERS)


class LLMClient:
    """Single source of truth for chat LLM calls over any OpenAI-compatible API."""

    def __init__(self, *, api_key: str, base_url: str, model: str, model_thinking: str,
                 temperature: float, max_output_tokens: int):
        self.model = model
        self.model_thinking = model_thinking
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def _create_on_model(self, active_model, *, messages, tools=None, max_tokens=None):
        """One model's chat.completions call with its own transient retry
        budget. Raises LLMTransientError when transient retries are exhausted;
        openai.NotFoundError (unknown model) propagates immediately so the
        caller can try the fallback model."""
        for attempt in range(TRANSIENT_ATTEMPTS):
            try:
                return await self._client.chat.completions.create(
                    model=active_model,
                    messages=messages,
                    tools=tools or None,
                    temperature=self.temperature,
                    max_tokens=max_tokens if max_tokens is not None else self.max_output_tokens,
                )
            except openai.NotFoundError:
                raise
            except (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError) as e:
                if attempt == TRANSIENT_ATTEMPTS - 1:
                    raise LLMTransientError(str(e)) from e
                await asyncio.sleep(2 * (attempt + 1))
            except openai.APIStatusError as e:
                if not _is_transient_status_error(e):
                    raise
                if attempt == TRANSIENT_ATTEMPTS - 1:
                    raise LLMTransientError(str(e)) from e
                await asyncio.sleep(2 * (attempt + 1))
        raise LLMTransientError(f"exhausted retries for model '{active_model}'")

    async def _create(self, *, model, messages, tools=None, max_tokens=None):
        """chat.completions with 404 model escalation on a budget of its own:
        the configured model id can lag what the endpoint serves, so an unknown
        model falls back to the thinking model WITHOUT consuming any of the
        transient retry budget. When every candidate 404s, the final
        openai.NotFoundError propagates — a permanent error (retrying cannot
        help), deliberately NOT LLMTransientError."""
        candidates = [model]
        if self.model_thinking != model:
            candidates.append(self.model_thinking)
        for i, active_model in enumerate(candidates):
            try:
                return await self._create_on_model(
                    active_model, messages=messages, tools=tools, max_tokens=max_tokens)
            except openai.NotFoundError:
                if i == len(candidates) - 1:
                    raise
                logger.warning(f"[LLM] Model '{active_model}' not found — falling back to '{candidates[i + 1]}'.")

    async def run_turn(self, *, system_instruction: str, messages: list, tools: list,
                       force_thinking: bool = False) -> LLMResult:
        model = self.model_thinking if force_thinking else self.model
        schemas = [function_to_schema(fn) for fn in tools]
        fn_by_name = {fn.__name__: fn for fn in tools}
        convo = [{"role": "system", "content": system_instruction}] + list(messages)
        usage = Usage()
        executed: list[ToolCall] = []

        last_resp = None
        for _ in range(MAX_TOOL_ITERATIONS):
            resp = await self._create(model=model, messages=convo, tools=schemas)
            last_resp = resp
            if resp.usage:
                usage = usage + Usage(resp.usage.prompt_tokens or 0, resp.usage.completion_tokens or 0)
            msg = resp.choices[0].message
            if not msg.tool_calls:
                return LLMResult(text=msg.content or "", tool_calls=executed, usage=usage, raw=resp)
            # Echo the assistant tool-call turn, then append each tool result.
            convo.append({
                "role": "assistant",
                "content": msg.content or None,
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in msg.tool_calls
                ],
            })
            for tc in msg.tool_calls:
                # Arguments are parsed exactly once. Malformed JSON becomes an
                # explicit error tool result instead of silently calling the
                # tool with no arguments — the model can read it and reissue
                # the call correctly.
                args, parse_error = parse_tool_args(tc.function.arguments)
                if parse_error is not None:
                    args = {}
                    out = json.dumps({"error": f"arguments were not valid JSON: {parse_error}"})
                else:
                    out = await dispatch_tool_call(fn_by_name, tc.function.name, args)
                executed.append(ToolCall(name=tc.function.name, args=args, result=out))
                convo.append({"role": "tool", "tool_call_id": tc.id, "content": out})

        # Hit the iteration cap: return best-effort text + what ran. Log it —
        # otherwise a capped turn is indistinguishable from a normal empty reply.
        logger.warning(
            f"[LLM] run_turn hit MAX_TOOL_ITERATIONS ({MAX_TOOL_ITERATIONS}) without a final "
            f"reply after {len(executed)} tool calls — returning best-effort text.")
        text = (last_resp.choices[0].message.content if last_resp else "") or ""
        return LLMResult(text=text, tool_calls=executed, usage=usage, raw=last_resp)

    async def complete(self, *, system_instruction: str, prompt: str,
                       max_output_tokens: int | None = None) -> LLMResult:
        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt},
        ]
        resp = await self._create(model=self.model, messages=messages, max_tokens=max_output_tokens)
        msg = resp.choices[0].message
        usage = Usage(resp.usage.prompt_tokens or 0, resp.usage.completion_tokens or 0) if resp.usage else Usage()
        return LLMResult(text=msg.content or "", tool_calls=[], usage=usage, raw=resp)


def from_settings(*, model: str | None = None, model_thinking: str | None = None,
                  api_key: str | None = None) -> "LLMClient":
    """Build an LLMClient from agent.config.settings, with optional overrides."""
    from agent.config import settings
    return LLMClient(
        api_key=api_key if api_key is not None else settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=model or settings.llm_model,
        model_thinking=model_thinking or settings.llm_model_thinking,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
    )
