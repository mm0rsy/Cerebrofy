"""cerebrofy health — codebase health timeline command."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import rich_click as click

from cerebrofy.config.loader import load_config
from cerebrofy.db.connection import open_db


def _render_snapshot(db_path: Path, config: object) -> None:
    """Open DB, compute current metrics, and print the health snapshot."""
    conn = open_db(db_path)
    try:
        from cerebrofy.health.metrics import compute_metrics
        from cerebrofy.health.reporter import format_health_snapshot
        from cerebrofy.health.snapshot import fetch_snapshots

        snapshots = fetch_snapshots(conn, limit=30)
        metrics = compute_metrics(conn, config.lobes, prior_snapshots=snapshots)
        prev = snapshots[0] if snapshots else None
        prev_ts = prev["build_ts"] if prev else None
        prev_commit = prev.get("commit_hash") if prev else None
        click.echo(format_health_snapshot(metrics, prev, prev_ts, prev_commit))
    finally:
        conn.close()


def _watch_loop(db_path: Path, config: object) -> None:
    """Poll cerebrofy.db mtime and re-render on every build/update."""
    click.echo("Watching for builds… Press Ctrl+C to exit.\n")
    last_mtime: float | None = None

    try:
        while True:
            try:
                mtime = db_path.stat().st_mtime
            except OSError:
                time.sleep(2)
                continue

            if mtime != last_mtime:
                last_mtime = mtime
                click.clear()
                click.echo("Watching for builds… Press Ctrl+C to exit.\n")
                _render_snapshot(db_path, config)

            time.sleep(2)
    except KeyboardInterrupt:
        pass


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
@click.option(
    "--watch",
    is_flag=True,
    default=False,
    help="Live-update mode: re-render after each cerebrofy build/update.",
)
def cerebrofy_health(history: int, trend: str | None, export_fmt: str | None, watch: bool) -> None:
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

    if watch:
        _watch_loop(db_path, config)
        return

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
