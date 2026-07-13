import inspect
import json
import re
import types
import typing
from typing import Any, Callable

# Python annotation -> JSON Schema "type"
_JSON_TYPES = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _annotation_to_type(annotation: Any) -> tuple[str, bool]:
    """Return (json_type, optional). Unwraps Optional[T] / T | None.
    PEP 604 unions (`T | None`) have origin types.UnionType, not typing.Union —
    both spellings must unwrap identically."""
    optional = False
    origin = typing.get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(typing.get_args(annotation)) != len(args):
            optional = True
        annotation = args[0] if args else str
        origin = typing.get_origin(annotation)
    base = origin or annotation
    return _JSON_TYPES.get(base, "string"), optional


def _parse_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """Return (summary, {param: description}) from a Google-style docstring.
    Summary is the first paragraph; param descriptions come from an `Args:`
    section if present."""
    if not doc:
        return "", {}
    lines = doc.strip().splitlines()
    summary_lines: list[str] = []
    for line in lines:
        if line.strip().lower().startswith("args:") or not line.strip():
            break
        summary_lines.append(line.strip())
    summary = " ".join(summary_lines).strip()

    params: dict[str, str] = {}
    in_args = False
    current_param: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith("args:"):
            in_args = True
            continue
        if in_args:
            if not stripped:
                break
            m = re.match(r"(\w+)\s*(?:\([^)]*\))?\s*:\s*(.+)", stripped)
            if m:
                current_param = m.group(1)
                params[current_param] = m.group(2).strip()
            elif current_param:
                # Continuation of a wrapped param description.
                params[current_param] += " " + stripped
            else:
                break
    return summary, params


def function_to_schema(fn: Callable) -> dict:
    """Build an OpenAI tool schema from a plain (async) Python function using its
    signature, type hints, and docstring. No `strict` mode (broad provider
    compatibility, incl. Gemini's OpenAI-compatible endpoint)."""
    sig = inspect.signature(fn)
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        hints = {}
    summary, param_docs = _parse_docstring(fn.__doc__)

    properties: dict[str, dict] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name in ("self", "cls") or param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        json_type, optional = _annotation_to_type(hints.get(name, str))
        prop: dict = {"type": json_type}
        if name in param_docs:
            prop["description"] = param_docs[name]
        properties[name] = prop
        if param.default is inspect.Parameter.empty and not optional:
            required.append(name)

    parameters: dict = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required

    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": summary,
            "parameters": parameters,
        },
    }


def parse_tool_args(arguments: str) -> tuple[dict | None, str | None]:
    """Parse a tool call's raw JSON `arguments` string ONCE.
    Returns (args, None) on success or (None, error_description) when the
    string is not a JSON object — the caller surfaces that to the model as an
    explicit tool-result error so it can correct itself, instead of the tool
    being silently invoked with no arguments."""
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError as e:
        return None, str(e)
    if not isinstance(parsed, dict):
        return None, f"expected a JSON object of arguments, got {type(parsed).__name__}"
    return parsed, None


async def dispatch_tool_call(fn_by_name: dict[str, Callable], name: str, args: dict) -> str:
    """Run one tool call by name with already-parsed arguments (see
    parse_tool_args) and await it. Returns a string result (tool-message
    content must be a string). Unknown tools and tool errors return a
    descriptive string so the model can recover."""
    fn = fn_by_name.get(name)
    if fn is None:
        return f"Error: unknown tool '{name}'."
    try:
        out = await fn(**args)
    except Exception as e:  # surface to the model, don't crash the turn
        return f"Error running tool '{name}': {e}"
    if isinstance(out, str):
        return out
    try:
        return json.dumps(out)
    except (TypeError, ValueError):
        return str(out)
