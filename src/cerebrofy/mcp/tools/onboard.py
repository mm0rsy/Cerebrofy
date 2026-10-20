"""MCP handler for the cerebrofy_onboard tool."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from cerebrofy.errors import NO_INDEX
from cerebrofy.mcp.errors import mcp_error as _err
from cerebrofy.utils.paths import find_repo_root as _find_repo_root_impl


def _find_root(cwd: Path) -> Path:
    """Resolve the repo root from *cwd* (delegates to the shared helper).

    Honors an explicit ``--root``/``CEREBROFY_ROOT`` binding before walking up
    so a manipulated CWD cannot redirect the tool at another project.
    """
    root = _find_repo_root_impl(cwd)
    if root is None:
        raise FileNotFoundError("No Cerebrofy config found. Run 'cerebrofy init' first.")
    return root


def handle_onboard(arguments: dict[str, Any]) -> list[Any]:
    """Return full Markdown + structured JSON for the onboarding guide.

    Output: {"markdown": str, "structured": dict}
    """
    from mcp.types import TextContent

    try:
        root = _find_root(Path.cwd())
    except Exception:
        return _err(f"[{NO_INDEX}] could not find .cerebrofy directory")

    cerebrofy_dir = root / ".cerebrofy"
    db_path = cerebrofy_dir / "db" / "cerebrofy.db"
    if not db_path.exists():
        return _err(f"[{NO_INDEX}] run cerebrofy build first")

    try:
        from cerebrofy.config.loader import load_config
        from cerebrofy.db.connection import check_schema_version
        from cerebrofy.onboard.planner import build_plan
        from cerebrofy.onboard.renderer import render_markdown

        config = load_config(cerebrofy_dir / "config.yaml")
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            check_schema_version(conn)
            plan = build_plan(
                conn=conn,
                lobes=config.lobes,
                cerebrofy_dir=cerebrofy_dir,
                repo_name=root.name,
                depth=arguments.get("depth", "junior"),
                name=arguments.get("name"),
                focus_lobe=arguments.get("focus_lobe"),
            )
        finally:
            conn.close()

        md = render_markdown(plan)
        out = {"markdown": md, "structured": plan.to_dict()}
        return [TextContent(type="text", text=json.dumps(out, indent=2))]

    except ValueError as exc:
        msg = str(exc)
        if "schema" in msg.lower():
            return _err("Schema version mismatch. Run 'cerebrofy migrate'.")
        return _err(f"cerebrofy_onboard failed: {exc}")
    except Exception as exc:
        return _err(f"cerebrofy_onboard failed: {exc}")
