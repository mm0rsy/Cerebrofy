"""Cerebrofy Multi-Agent Coordination — Metrics & Observability.

Provides counters and gauges for coordination events:
- Claims made/released
- Conflicts detected (claim & memory)
- Resolutions by strategy
- Stale agent cleanups
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cerebrofy.db.connection import open_db, write_transaction


@dataclass
class CoordinationMetrics:
    """In-memory coordination metrics (reset on process restart)."""

    claims_made: int = 0
    claims_released: int = 0
    claim_conflicts_detected: int = 0
    memory_conflicts_detected: int = 0
    resolutions: dict[str, int] = field(default_factory=dict)
    stale_agents_cleaned: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def inc_claims_made(self, count: int = 1) -> None:
        with self._lock:
            self.claims_made += count

    def inc_claims_released(self, count: int = 1) -> None:
        with self._lock:
            self.claims_released += count

    def inc_claim_conflicts(self, count: int = 1) -> None:
        with self._lock:
            self.claim_conflicts_detected += count

    def inc_memory_conflicts(self, count: int = 1) -> None:
        with self._lock:
            self.memory_conflicts_detected += count

    def inc_resolution(self, strategy: str) -> None:
        with self._lock:
            self.resolutions[strategy] = self.resolutions.get(strategy, 0) + 1

    def inc_stale_cleaned(self, count: int = 1) -> None:
        with self._lock:
            self.stale_agents_cleaned += count

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "claims_made": self.claims_made,
                "claims_released": self.claims_released,
                "claim_conflicts_detected": self.claim_conflicts_detected,
                "memory_conflicts_detected": self.memory_conflicts_detected,
                "resolutions": dict(self.resolutions),
                "stale_agents_cleaned": self.stale_agents_cleaned,
                "timestamp": int(time.time()),
            }


# Global metrics instance (per-process)
_metrics: CoordinationMetrics | None = None
_metrics_lock = threading.Lock()


def get_metrics() -> CoordinationMetrics:
    """Get the global metrics instance, creating if needed."""
    global _metrics
    with _metrics_lock:
        if _metrics is None:
            _metrics = CoordinationMetrics()
        return _metrics


def reset_metrics() -> None:
    """Reset the global metrics (for testing)."""
    global _metrics
    with _metrics_lock:
        _metrics = CoordinationMetrics()


# ---------------------------------------------------------------------------
# Persistent metrics (SQLite-backed for cross-process visibility)
# ---------------------------------------------------------------------------


METRICS_DDL = """
CREATE TABLE IF NOT EXISTS coordination_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    event_subtype TEXT,
    count INTEGER NOT NULL DEFAULT 1,
    details TEXT,
    created_ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_type_ts ON coordination_metrics(event_type, created_ts);
"""


class PersistentMetrics:
    """SQLite-backed coordination metrics for cross-process observability."""

    def __init__(self, cerebrofy_dir: str | Path) -> None:
        self.cerebrofy_dir = Path(cerebrofy_dir)
        self.db_path = self.cerebrofy_dir / "db" / "metrics.db"
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = open_db(self.db_path)
        try:
            with write_transaction(conn):
                for stmt in METRICS_DDL.strip().split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        conn.execute(stmt)
            self._initialized = True
        finally:
            conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        self._ensure_initialized()
        return open_db(self.db_path)

    def record(self, event_type: str, event_subtype: str | None = None, count: int = 1, details: dict[str, Any] | None = None) -> None:
        """Record a coordination event."""
        import json
        conn = self._get_conn()
        try:
            with write_transaction(conn):
                conn.execute(
                    "INSERT INTO coordination_metrics (event_type, event_subtype, count, details, created_ts) VALUES (?, ?, ?, ?, ?)",
                    (event_type, event_subtype, count, json.dumps(details) if details else None, int(time.time())),
                )
        finally:
            conn.close()

    def record_claim(self, neurons: int, agent_id: str) -> None:
        self.record("claim_made", details={"neurons": neurons, "agent_id": agent_id})

    def record_release(self, neurons: int, agent_id: str) -> None:
        self.record("claim_released", details={"neurons": neurons, "agent_id": agent_id})

    def record_claim_conflict(self, neuron: str, requester: str, holder: str) -> None:
        self.record("claim_conflict", details={"neuron": neuron, "requester": requester, "holder": holder})

    def record_memory_conflict(self, neuron: str, memory_a: str, memory_b: str) -> None:
        self.record("memory_conflict", details={"neuron": neuron, "memory_a": memory_a, "memory_b": memory_b})

    def record_resolution(self, strategy: str, winner: str, superseded: list[str]) -> None:
        self.record("resolution", event_subtype=strategy, details={"winner": winner, "superseded": superseded})

    def record_stale_cleanup(self, agents: int) -> None:
        self.record("stale_cleanup", details={"agents_cleaned": agents})

    def get_summary(self, since_ts: int | None = None) -> dict[str, Any]:
        """Get metrics summary since timestamp."""
        self._ensure_initialized()
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            where = "WHERE created_ts >= ?" if since_ts else ""
            params = (since_ts,) if since_ts else ()
            rows = conn.execute(f"SELECT * FROM coordination_metrics {where} ORDER BY created_ts DESC", params).fetchall()
        finally:
            conn.close()

        by_type: dict[str, int] = {}
        by_strategy: dict[str, int] = {}
        for row in rows:
            by_type[row["event_type"]] = by_type.get(row["event_type"], 0) + row["count"]
            if row["event_subtype"]:
                subtype = row["event_subtype"]
                by_strategy[subtype] = by_strategy.get(subtype, 0) + row["count"]

        return {
            "total_events": len(rows),
            "by_type": by_type,
            "by_strategy": by_strategy,
            "recent": [dict(r) for r in rows[:100]],
        }


def get_persistent_metrics(cerebrofy_dir: str | Path) -> PersistentMetrics:
    """Get a PersistentMetrics instance for the given cerebrofy directory."""
    return PersistentMetrics(cerebrofy_dir)


__all__ = [
    "CoordinationMetrics",
    "get_metrics",
    "reset_metrics",
    "PersistentMetrics",
    "get_persistent_metrics",
]