"""MCP tool for Insight Daemon."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.types import CallToolResult

from cerebrofy.insight.daemon import run_daemon
from cerebrofy.insight.notifier import format_insights_mcp
from cerebrofy.mcp.errors import mcp_error


def _find_db(root: Path) -> Path | None:
    """Find cerebrofy.db."""
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if db_path.exists():
        return db_path
    return None


def _read_insights(
    conn: sqlite3.Connection,
    type_filter: str | None,
    since_seconds: int | None,
    min_confidence: float,
    limit: int = 100,
) -> list[dict[str, object]]:
    """Read insights from memories table."""
    cutoff = 0
    if since_seconds:
        import time

        cutoff = int(time.time()) - since_seconds

    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM memories WHERE type = 'insight'"
    params: list[object] = []
    if cutoff:
        query += " AND created_ts >= ?"
        params.append(cutoff)
    if type_filter:
        query += " AND tags LIKE ?"
        params.append(f"%{type_filter}%")
    query += " ORDER BY created_ts DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    insights = []
    for i, row in enumerate(rows):
        insights.append(
            {
                "id": f"insight-{row['id']}",
                "type": row["tags"].split(",")[0] if row["tags"] and "," in row["tags"] else "insight",
                "title": row["title"],
                "body": row["body"],
                "confidence": 0.7,  # Default; could parse from body
                "affected_neurons": [],
                "affected_lobes": [],
                "created_ts": row["created_ts"],
                "recommendation": "",
            }
        )
    return insights


def handle_insights(arguments: dict[str, object]) -> "CallToolResult":
    """Handle cerebrofy_insights MCP tool call."""
    from mcp.types import TextContent

    root = Path.cwd()
    db_path = _find_db(root)

    if db_path is None:
        return mcp_error("[NO_INDEX] cerebrofy.db not found. Run 'cerebrofy build' first.")

    run_now = bool(arguments.get("run_now", False))
    type_filter: str | None = arguments.get("type")  # type: ignore[assignment]
    since: str | None = arguments.get("since")  # type: ignore[assignment]
    min_confidence = float(str(arguments.get("min_confidence", 0.7)))

    # Parse since string
    since_seconds: int | None = None
    if since:
        if since.endswith("d"):
            since_seconds = int(since[:-1]) * 86400
        elif since.endswith("h"):
            since_seconds = int(since[:-1]) * 3600

    conn = sqlite3.connect(db_path)
    try:
        last_daemon_run = 0

        if run_now:
            run_daemon(db_path)
            last_daemon_run = int(__import__("time").time())

            # Read all insights after run
            all_insights = _read_insights(conn, type_filter, since_seconds, min_confidence)
            # Filter by confidence
            all_insights = [i for i in all_insights if float(str(i["confidence"])) >= min_confidence]

            result = format_insights_mcp(all_insights, len(all_insights), last_daemon_run)
            return [TextContent(type="text", text=__import__("json").dumps(result, indent=2))]

        # Just read existing insights
        insights = _read_insights(conn, type_filter, since_seconds, min_confidence)
        insights = [i for i in insights if float(str(i["confidence"])) >= min_confidence]

        # Get last daemon run time from most recent insight
        if insights:
            last_daemon_run = max(int(str(i["created_ts"])) for i in insights)

        result = format_insights_mcp(insights, len(insights), last_daemon_run)
        return [TextContent(type="text", text=__import__("json").dumps(result, indent=2))]

    finally:
        conn.close()