"""Read and write health_snapshots table in cerebrofy.db."""

from __future__ import annotations

import sqlite3
import subprocess
import time
from typing import Any

from cerebrofy.db.schema import ensure_health_schema
from cerebrofy.health.metrics import HealthMetrics


def _get_current_commit(repo_root: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except Exception:
        pass
    return None


def record_snapshot(
    conn: sqlite3.Connection,
    metrics: HealthMetrics,
    repo_root: str = ".",
) -> None:
    """Insert a health snapshot row for the current build."""
    ensure_health_schema(conn)
    commit_hash = _get_current_commit(repo_root)
    conn.execute(
        """
        INSERT INTO health_snapshots (
            build_ts, commit_hash, coupling, avg_blast, dead_code_pct,
            cohesion, test_surface, drift_velocity, hub_concentration,
            neuron_count, edge_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(time.time()),
            commit_hash,
            metrics.coupling,
            metrics.avg_blast,
            metrics.dead_code_pct,
            metrics.cohesion,
            metrics.test_surface,
            metrics.drift_velocity,
            metrics.hub_concentration,
            metrics.neuron_count,
            metrics.edge_count,
        ),
    )


def fetch_snapshots(
    conn: sqlite3.Connection,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Return the most recent *limit* health snapshots, newest first."""
    ensure_health_schema(conn)
    rows = conn.execute(
        """
        SELECT id, build_ts, commit_hash, coupling, avg_blast, dead_code_pct,
               cohesion, test_surface, drift_velocity, hub_concentration,
               neuron_count, edge_count
        FROM health_snapshots
        ORDER BY build_ts DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    cols = (
        "id", "build_ts", "commit_hash", "coupling", "avg_blast",
        "dead_code_pct", "cohesion", "test_surface", "drift_velocity",
        "hub_concentration", "neuron_count", "edge_count",
    )
    return [dict(zip(cols, row)) for row in rows]


def fetch_latest_snapshot(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Return the most recent health snapshot, or None if none exist."""
    snapshots = fetch_snapshots(conn, limit=1)
    return snapshots[0] if snapshots else None
