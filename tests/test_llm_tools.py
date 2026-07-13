from typing import Optional

import pytest
from agent.llm.tools import function_to_schema, dispatch_tool_call, parse_tool_args


async def sample_tool(name: str, count: int = 1, tags: list = None) -> str:
    """Create a thing.

    Args:
        name: The thing's name.
        count: How many.
    """
    return f"{name}:{count}:{tags}"


async def no_arg_tool() -> str:
    """Does a fixed thing."""
    return "done"


async def optional_tool(x: Optional[int]) -> str:
    """Takes an optional with no default."""
    return str(x)


async def pep604_tool(x: int | None) -> str:
    """Takes a PEP 604 optional with no default."""
    return str(x)


async def wrapped_doc_tool(first: str, second: str) -> str:
    """Has wrapped param descriptions.

    Args:
        first: A description that wraps onto
            a second line for readability.
        second: The second parameter.
    """
    return f"{first}{second}"


def test_schema_shape_and_required():
    schema = function_to_schema(sample_tool)
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "sample_tool"
    assert fn["description"].startswith("Create a thing.")
    props = fn["parameters"]["properties"]
    assert props["name"]["type"] == "string"
    assert props["count"]["type"] == "integer"
    assert props["tags"]["type"] == "array"
    # only params without defaults are required
    assert fn["parameters"]["required"] == ["name"]


def test_param_descriptions_from_docstring():
    schema = function_to_schema(sample_tool)
    props = schema["function"]["parameters"]["properties"]
    assert props["name"]["description"] == "The thing's name."
    assert props["count"]["description"] == "How many."


def test_no_arg_tool_has_empty_properties():
    schema = function_to_schema(no_arg_tool)
    params = schema["function"]["parameters"]
    assert params["properties"] == {}
    assert params.get("required", []) == []


@pytest.mark.asyncio
async def test_dispatch_runs_named_tool():
    fn_by_name = {"sample_tool": sample_tool}
    out = await dispatch_tool_call(fn_by_name, "sample_tool", {"name": "a", "count": 2})
    assert out == "a:2:None"


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_returns_error_string():
    out = await dispatch_tool_call({}, "ghost", {})
    assert "ghost" in out and "unknown" in out.lower()


def test_parse_tool_args_valid_and_empty():
    assert parse_tool_args('{"a": 1}') == ({"a": 1}, None)
    assert parse_tool_args("") == ({}, None)
    assert parse_tool_args(None) == ({}, None)


def test_parse_tool_args_malformed_json_reports_error():
    args, err = parse_tool_args('{"a": 1')  # truncated — the live failure mode
    assert args is None
    assert err  # a human-readable JSON error the model can act on


def test_parse_tool_args_non_object_reports_error():
    args, err = parse_tool_args('[1, 2]')
    assert args is None
    assert "object" in err


def test_optional_no_default_is_not_required():
    schema = function_to_schema(optional_tool)
    fn = schema["function"]
    assert fn["parameters"]["properties"]["x"]["type"] == "integer"
    assert "x" not in fn["parameters"].get("required", [])


def test_pep604_union_no_default_is_not_required():
    # `int | None` has origin types.UnionType, not typing.Union — it must get
    # the same treatment as Optional[int], not fall through to string/required.
    schema = function_to_schema(pep604_tool)
    fn = schema["function"]
    assert fn["parameters"]["properties"]["x"]["type"] == "integer"
    assert "x" not in fn["parameters"].get("required", [])


def test_wrapped_param_description_is_joined_and_keeps_later_params():
    props = function_to_schema(wrapped_doc_tool)["function"]["parameters"]["properties"]
    assert props["first"]["description"] == "A description that wraps onto a second line for readability."
    # the param after a wrapped one must not be lost
    assert props["second"]["description"] == "The second parameter."


@pytest.mark.asyncio
async def test_dispatch_tool_exception_returns_error_string():
    async def bad_tool() -> str:
        raise ValueError("boom")
    out = await dispatch_tool_call({"bad_tool": bad_tool}, "bad_tool", {})
    assert "Error" in out and "boom" in out
