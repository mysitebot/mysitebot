from dataclasses import dataclass, field
from typing import Any


class LLMTransientError(Exception):
    """Raised by LLMClient when transient (rate-limit / overloaded / unavailable)
    errors are exhausted, so callers can degrade gracefully if work already
    committed mid-turn."""


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
        )


@dataclass
class ToolCall:
    name: str
    args: dict
    result: str


@dataclass
class LLMResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    raw: Any = None
    # True when the turn hit MAX_TOOL_ITERATIONS: the text is best-effort,
    # never the model's considered final reply — treat its claims as unfinished.
    capped: bool = False
