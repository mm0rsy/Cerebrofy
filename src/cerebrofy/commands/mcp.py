"""cerebrofy mcp — start the MCP stdio server."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import rich_click as click


@click.command("mcp")
@click.option(
    "--root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Project root to serve (defaults to CEREBROFY_ROOT or CWD walk-up).",
)
def cerebrofy_mcp(root: Path | None) -> None:
    """Start the cerebrofy MCP stdio server (requires `cerebrofy[mcp]` extra)."""
    try:
        import mcp
    except ImportError:
        click.echo(
            "Error: MCP server requires the 'mcp' package. "
            "Install with: uv add 'cerebrofy[mcp]'  (or: pip install cerebrofy[mcp])",
            err=True,
        )
        sys.exit(1)

    from cerebrofy.mcp.server import run_mcp_server
    asyncio.run(run_mcp_server(root))
