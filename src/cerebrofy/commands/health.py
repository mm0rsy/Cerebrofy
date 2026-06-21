"""cerebrofy health — codebase health timeline command."""

from __future__ import annotations

import sys
from pathlib import Path

import rich_click as click

from cerebrofy.config.loader import load_config
from cerebrofy.db.connection import open_db


@click.command("health")
@click.option(
    "--history",
    default=0,
    type=int,
    metavar="N",
    help="Show last N builds in a history table.",
)
@click.option(
    "--trend",
    default=None,
    type=str,
    metavar="METRIC",
    help=(
        "Show ASCII sparkline for a metric over time. "
        "Valid: coupling, avg_blast, dead_code_pct, cohesion, "
        "test_surface, drift_velocity, hub_concentration."
    ),
)
@click.option(
    "--export",
    "export_fmt",
    default=None,
    type=click.Choice(["json"]),
    help="Export current snapshot as JSON.",
)
def cerebrofy_health(history: int, trend: str | None, export_fmt: str | None) -> None:
    """Show longitudinal codebase health metrics derived from the call graph."""
    root = Path.cwd()
    config_path = root / ".cerebrofy" / "config.yaml"
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"

    if not config_path.exists():
        click.echo(
            "Error: .cerebrofy/config.yaml not found. Run 'cerebrofy init' first.", err=True
        )
        sys.exit(1)

    if not db_path.exists():
        click.echo("Error: No index found. Run 'cerebrofy build' first.", err=True)
        sys.exit(1)

    config = load_config(config_path)
    conn = open_db(db_path)

    try:
        from cerebrofy.health.metrics import compute_metrics
        from cerebrofy.health.reporter import (
            format_health_snapshot,
            format_history_table,
            format_trend_sparkline,
            to_export_json,
        )
        from cerebrofy.health.snapshot import fetch_snapshots

        snapshots = fetch_snapshots(conn, limit=max(history, 30) if history > 0 else 30)

        if history > 0:
            click.echo(format_history_table(snapshots[:history]))
            return

        if trend:
            click.echo(format_trend_sparkline(snapshots, trend))
            return

        # Compute live metrics and display vs previous snapshot
        metrics = compute_metrics(conn, config.lobes, prior_snapshots=snapshots)
        prev = snapshots[0] if snapshots else None
        prev_ts = prev["build_ts"] if prev else None
        prev_commit = prev.get("commit_hash") if prev else None

        if export_fmt == "json":
            click.echo(to_export_json(metrics, prev, prev_ts, prev_commit))
            return

        click.echo(format_health_snapshot(metrics, prev, prev_ts, prev_commit))

    finally:
        conn.close()
