"""cerebrofy mcp — start the MCP stdio server."""

from __future__ import annotations

import asyncio
import sys

import rich_click as click


@click.command("mcp")
def cerebrofy_mcp() -> None:
    """Start the cerebrofy MCP stdio server (requires `cerebrofy[mcp]` extra)."""
    try:
        import mcp  # noqa: F401
    except ImportError:
        click.echo(
            "Error: MCP server requires the 'mcp' package. "
            "Install with: uv add 'cerebrofy[mcp]'  (or: pip install cerebrofy[mcp])",
            err=True,
        )
        sys.exit(1)

    from cerebrofy.mcp.server import run_mcp_server
    asyncio.run(run_mcp_server())
