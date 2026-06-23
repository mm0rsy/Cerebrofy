"""MCP handler for the cerebrofy_onboard tool."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def _find_root(cwd: Path) -> Path:
    current = cwd if cwd.is_dir() else cwd.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".cerebrofy" / "config.yaml").exists():
            return candidate
    raise FileNotFoundError("No Cerebrofy config found. Run 'cerebrofy init' first.")


def _err(message: str) -> list[Any]:
    from mcp.types import TextContent
    return [TextContent(type="text", text=message)]


def handle_onboard(arguments: dict[str, Any]) -> list[Any]:
    """Return full Markdown + structured JSON for the onboarding guide.

    Output: {"markdown": str, "structured": dict}
    """
    from mcp.types import TextContent

    try:
        root = _find_root(Path.cwd())
    except Exception:
        return _err("NO_INDEX: could not find .cerebrofy directory")

    cerebrofy_dir = root / ".cerebrofy"
    db_path = cerebrofy_dir / "db" / "cerebrofy.db"
    if not db_path.exists():
        return _err("NO_INDEX: run cerebrofy build first")

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
