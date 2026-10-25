"""CLI command for Insight Daemon."""

from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

import rich_click as click
from rich.console import Console

from cerebrofy.insight.daemon import run_daemon
from cerebrofy.insight.notifier import format_insights_cli

console = Console()


def _find_db() -> Path | None:
    """Find cerebrofy.db, return None if not found."""
    root = Path.cwd()
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if db_path.exists():
        return db_path
    return None


def _read_insights(db_path: Path, type_filter: str | None, since_days: int | None, min_confidence: float) -> list[dict[str, object]]:
    """Read insights from memories table."""
    cutoff = 0
    if since_days:
        cutoff = int(time.time()) - since_days * 86400

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        query = "SELECT * FROM memories WHERE type = 'insight'"
        params: list[object] = []
        if cutoff:
            query += " AND created_ts >= ?"
            params.append(cutoff)
        if type_filter:
            query += " AND tags LIKE ?"
            params.append(f"%{type_filter}%")
        query += " ORDER BY created_ts DESC LIMIT 100"

        rows = conn.execute(query, params).fetchall()
        insights: list[dict[str, object]] = []
        for row in rows:
            insights.append(dict(row))
        return insights
    finally:
        conn.close()


@click.command()
@click.option("--type", "type_filter", help="Filter by insight type (e.g., 'trend_alert', 'silo_risk')")
@click.option("--since", "since_str", help="Time window e.g. '7d', '24h'")
@click.option("--run", "run_now", is_flag=True, help="Force a daemon run before showing insights")
@click.option("--watch", "watch_mode", is_flag=True, help="Stream insights as they generate (not implemented yet)")
@click.option("--min-confidence", "min_confidence", type=float, default=0.0, help="Minimum confidence 0-1")
def cerebrofy_insights(type_filter: str | None, since_str: str | None, run_now: bool, watch_mode: bool, min_confidence: float) -> None:
    """Show insights from the Insight Daemon, or force a daemon run."""
    db_path = _find_db()
    if db_path is None:
        console.print("[red]Error: [NO_INDEX] cerebrofy.db not found. Run 'cerebrofy build' first.[/red]")
        sys.exit(1)

    since_days = None
    if since_str:
        if since_str.endswith("d"):
            since_days = int(since_str[:-1])
        elif since_str.endswith("h"):
            since_days = max(1, int(since_str[:-1]) // 24)

    if run_now:
        console.print("[cyan]Running Insight Daemon...[/cyan]")
        new_insights = run_daemon(db_path)
        if new_insights:
            console.print(f"[green]Generated {len(new_insights)} new insight(s).[/green]")
            console.print(format_insights_cli(new_insights))
        else:
            console.print("[dim]No new insights generated.[/dim]")

    # Show existing insights
    insights = _read_insights(db_path, type_filter, since_days, min_confidence)
    if insights:
        # Convert to daemon Insight objects for formatting
        from cerebrofy.insight.daemon import Insight
        insight_objs = []
        for row in insights:
            tags = str(row.get("tags", ""))
            insight_objs.append(
                Insight(
                    type=tags.split(",")[0] if tags and "," in tags else "insight",
                    title=str(row.get("title", "")),
                    body=str(row.get("body", "")),
                    confidence=0.7,  # Default; could parse from body
                    affected_neurons=[],
                    affected_lobes=[],
                    recommendation="",
                    created_ts=int(str(row.get("created_ts", 0))),
                )
            )
        console.print(format_insights_cli(insight_objs))
    else:
        console.print("[dim]No insights found matching criteria.[/dim]")


if __name__ == "__main__":
    cerebrofy_insights()