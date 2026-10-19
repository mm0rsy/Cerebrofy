"""Canonical MCP error-content helper (Idea #25 / DRY hardening).

Every MCP tool handler returns a ``list[Any]`` of ``TextContent`` items; an
error response is just a single ``TextContent`` whose ``type`` is ``"text"``.
Previously each tool module duplicated this tiny constructor as a private
``_err`` helper — five identical copies that drifted in signature and import
placement. They now all delegate here.

``mcp`` is an *optional* extra, so :class:`mcp.types.TextContent` is imported
**lazily** inside :func:`mcp_error`. That keeps this module — and the tool
modules that alias ``mcp_error`` — importable from the CLI path where the
``mcp`` extra is not installed. Only the moment an error is actually turned
into an MCP payload does ``mcp`` get pulled in.
"""

from __future__ import annotations

from typing import Any


def mcp_error(message: str) -> list[Any]:
    """Build a single-element ``TextContent`` list carrying *message*.

    This is the single place that constructs an MCP error payload so the
    one-line ``[TextContent(type="text", text=...)]`` pattern is never
    duplicated across tool modules again.
    """
    from mcp.types import TextContent

    return [TextContent(type="text", text=message)]
