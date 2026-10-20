"""Unit tests for cerebrofy.mcp.errors.mcp_error (Idea #25 / DRY).

Verifies the canonical MCP error-payload constructor and that each tool
module's private _err is just an alias to it.
"""

from __future__ import annotations

import pytest

from cerebrofy.mcp.errors import mcp_error

pytest.importorskip("mcp")

from mcp.types import TextContent  # noqa: E402
from cerebrofy.mcp.tools import changelog, memory_graph, onboard, plan, session  # noqa: E402


def test_mcp_error_returns_single_text_content() -> None:
    result = mcp_error("something broke")
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], TextContent)
    assert result[0].type == "text"
    assert result[0].text == "something broke"


def test_mcp_error_preserves_bracket_codes_and_punctuation() -> None:
    msg = "[NO_INDEX] Index not found. Run 'cerebrofy build' first."
    assert mcp_error(msg)[0].text == msg


def test_mcp_error_empty_message() -> None:
    result = mcp_error("")
    assert len(result) == 1
    assert result[0].type == "text"
    assert result[0].text == ""


def test_mcp_error_does_not_mutate_message() -> None:
    original = "[error] 'task' is required"
    result = mcp_error(original)
    assert result[0].text == original
    assert original == "[error] 'task' is required"


_ALL_TOOL_MODULES = (changelog, memory_graph, onboard, plan, session)


@pytest.mark.parametrize("module", _ALL_TOOL_MODULES, ids=lambda m: m.__name__)
def test_tool_module_err_is_alias_of_mcp_error(module) -> None:
    assert module._err is mcp_error


@pytest.mark.parametrize("module", _ALL_TOOL_MODULES, ids=lambda m: m.__name__)
def test_alias_produces_identical_payload(module) -> None:
    assert module._err("boom") == mcp_error("boom")
    assert module._err("[NO_INDEX] nope")[0].text == "[NO_INDEX] nope"
