"""Cerebrofy Multi-Agent Coordination — Active Agent Registry.

The registry is the persistent source of truth for which agents are currently
working on which neurons (Idea #25).  Every mutation is written to the local
index database (``.cerebrofy/db/cerebrofy.db``) inside a single
``BEGIN IMMEDIATE`` transaction, so claims made by one process are immediately
visible to every other Cerebrofy process on the machine.

Design notes
------------
* **Persistent, not in-memory.**  Earlier revisions kept state in a Python
  dict, which meant two agents (or two CLI invocations) never saw each other.
  All reads and writes now go through SQLite.
* **Ephemeral by design.**  ``active_agents`` lives in the index database.
  Rebuilding the index recreates ``cerebrofy.db`` and therefore intentionally
  discards coordination state.  Claims are transient coordination metadata,
  not durable knowledge (that is what ``memories.db`` is for).
* **Atomic writes.**  Mutations use :func:`cerebrofy.db.connection.write_transaction`
  (``BEGIN IMMEDIATE``, rejects nesting).  An in-process :class:`threading.RLock`
  additionally serialises registry operations.
* **Stale claims are reclaimed automatically.**  A claim expires when its TTL
  elapses (``expires_ts``) or when no heartbeat has been seen for two
  heartbeat intervals.  ``cleanup_stale_agents`` marks such agents
  ``completed`` and clears their claims.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from cerebrofy.coordination.constants import HEARTBEAT_INTERVAL_SECONDS
from cerebrofy.coordination.metrics import get_metrics, get_persistent_metrics
from cerebrofy.db.connection import open_db, open_db_readonly, write_transaction
from cerebrofy.db.schema import ACTIVE_AGENTS_DDL
from cerebrofy.errors import NEURON_ALREADY_CLAIMED, ClaimExpiredError, NoActiveAgentError

#: Columns selected for every agent row (order matters — see ``_row_to_agent``).
_AGENT_COLUMNS = (
    "agent_id, agent_type, session_id, intent, claimed_neurons, "
    "started_ts, last_heartbeat, status, ttl_minutes, expires_ts"
)

#: Every column the current schema requires on ``active_agents``.
_REQUIRED_COLUMNS = frozenset(
    {
        "agent_id",
        "agent_type",
        "session_id",
        "intent",
        "claimed_neurons",
        "started_ts",
        "last_heartbeat",
        "status",
        "ttl_minutes",
        "expires_ts",
        "created_ts",
    }
)


class ActiveAgentRegistry:
    """Persistent registry of active agents and their neuron claims."""

    heartbeat_interval: int = HEARTBEAT_INTERVAL_SECONDS

    def __init__(
        self,
        db_path: str | Path,
        *,
        readonly: bool = False,
        heartbeat_interval: int = HEARTBEAT_INTERVAL_SECONDS,
        metrics: bool = True,
    ) -> None:
        self.db_path = Path(db_path)
        self.readonly = readonly
        self.heartbeat_interval = heartbeat_interval
        self._lock = threading.RLock()
        self._metrics = get_metrics() if metrics else None
        self._persistent_metrics = None
        if metrics and not readonly:
            try:
                self._persistent_metrics = get_persistent_metrics(self.db_path.parent.parent)
            except Exception:
                pass  # Fail silently if metrics can't be initialized

        if readonly:
            # Read-only handles must never create or mutate the index.
            self._conn: sqlite3.Connection | None = open_db_readonly(self.db_path)
            return

        if not self.db_path.exists():
            raise FileNotFoundError(
                "Index not found. Run 'cerebrofy build' first."
            )
        self._conn = open_db(self.db_path)
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Connection / schema lifecycle
    # ------------------------------------------------------------------

    @property
    def conn(self) -> sqlite3.Connection:
        """Return the open SQLite connection (raises after :meth:`close`)."""
        if self._conn is None:
            raise RuntimeError("ActiveAgentRegistry is closed")
        return self._conn

    def _ensure_schema(self) -> None:
        """Create ``active_agents`` if missing and upgrade pre-TTL databases.

        Idempotent: safe to call for a brand-new database, a database created
        by :func:`cerebrofy.db.schema.create_schema`, or an older Cerebrofy
        index that only has the original seven coordination columns.

        When the table already has every current column and no row has a NULL
        ``created_ts``, no DDL or write is issued at all — opening the registry
        is purely a read in that common case.
        """
        with self._lock:
            if (
                self._table_columns(self.conn) >= _REQUIRED_COLUMNS
                and not self._has_null_created_ts(self.conn)
            ):
                return

            with write_transaction(self.conn) as conn:
                for statement in ACTIVE_AGENTS_DDL.split(";"):
                    statement = statement.strip()
                    if statement:
                        conn.execute(statement)

                columns = self._table_columns(conn)
                if "ttl_minutes" not in columns:
                    conn.execute(
                        "ALTER TABLE active_agents "
                        "ADD COLUMN ttl_minutes INTEGER NOT NULL DEFAULT 60"
                    )
                if "expires_ts" not in columns:
                    conn.execute(
                        "ALTER TABLE active_agents ADD COLUMN expires_ts INTEGER"
                    )
                if "created_ts" not in columns:
                    conn.execute(
                        "ALTER TABLE active_agents ADD COLUMN created_ts INTEGER"
                    )
                # Backfill legacy rows so created_ts is never NULL after an
                # in-place upgrade (fresh tables get strftime('%s','now')).
                conn.execute(
                    "UPDATE active_agents SET created_ts = started_ts "
                    "WHERE created_ts IS NULL"
                )

    @staticmethod
    def _table_columns(conn: sqlite3.Connection) -> set[str]:
        return {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(active_agents)").fetchall()
        }

    @staticmethod
    def _has_null_created_ts(conn: sqlite3.Connection) -> bool:
        row = conn.execute(
            "SELECT 1 FROM active_agents WHERE created_ts IS NULL LIMIT 1"
        ).fetchone()
        return row is not None

    def close(self) -> None:
        """Close the SQLite connection.  Idempotent."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> ActiveAgentRegistry:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Row helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_agent(row: tuple[Any, ...], now: int) -> dict[str, Any]:
        """Convert a row selected with :data:`_AGENT_COLUMNS` to a dict."""
        (
            agent_id,
            agent_type,
            session_id,
            intent,
            claimed_neurons,
            started_ts,
            last_heartbeat,
            status,
            ttl_minutes,
            expires_ts,
        ) = row
        return {
            "agent_id": str(agent_id),
            "agent_type": str(agent_type),
            "session_id": session_id,
            "intent": intent or "",
            "claimed_neurons": _parse_neurons(claimed_neurons),
            "started_ts": int(started_ts),
            "last_heartbeat": int(last_heartbeat),
            "status": str(status or "active"),
            "ttl_minutes": int(ttl_minutes or 60),
            "expires_ts": int(expires_ts) if expires_ts is not None else None,
            "active_minutes": max(0, (now - int(started_ts)) // 60),
        }

    def _fetch_agent(
        self, conn: sqlite3.Connection, agent_id: str
    ) -> tuple[Any, ...] | None:
        row: tuple[Any, ...] | None = conn.execute(
            f"SELECT {_AGENT_COLUMNS} FROM active_agents WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        return row

    def _is_stale(self, row: tuple[Any, ...], now: int) -> bool:
        """Return True when the row's claim is expired or heartbeat-silent.

        Single staleness predicate shared by cleanup and the release/heartbeat
        guards: the claim TTL elapsed (``expires_ts < now``) **or** the agent
        has not sent a heartbeat for two full heartbeat intervals.
        """
        expires_ts = row[9]
        if expires_ts is not None and int(expires_ts) < now:
            return True
        return int(row[6]) < now - 2 * self.heartbeat_interval

    def _require_active(
        self, row: tuple[Any, ...] | None, agent_id: str, now: int
    ) -> tuple[Any, ...]:
        """Return *row* when it is an active, non-stale claim.

        Raises :class:`ClaimExpiredError` when the row exists but its claim is
        stale/expired (even if a sweep already marked it ``completed``) and
        :class:`NoActiveAgentError` for unknown or non-expired inactive rows.
        """
        if row is None:
            raise NoActiveAgentError(
                f"No active agent registered with id {agent_id!r}."
            )
        stale = self._is_stale(row, now)
        if str(row[7] or "active") != "active":
            if stale:
                raise ClaimExpiredError(
                    f"Claim for agent {agent_id!r} has expired — re-claim required."
                )
            raise NoActiveAgentError(
                f"No active agent registered with id {agent_id!r}."
            )
        if stale:
            raise ClaimExpiredError(
                f"Claim for agent {agent_id!r} has expired — re-claim required."
            )
        return row

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------

    def claim_neurons(
        self,
        agent_id: str,
        neurons: list[str],
        intent: str,
        *,
        agent_type: str | None = None,
        ttl_minutes: int = 60,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Claim *neurons* for *agent_id*, skipping neurons held by others.

        Returns ``{"claimed": [...], "conflicts": [...], "claim_id": "..."}``.
        If nothing could be claimed because another active agent holds every
        requested neuron, a top-level ``"error"`` key with
        :data:`~cerebrofy.errors.NEURON_ALREADY_CLAIMED` is included.
        """
        with self._lock:
            self.cleanup_stale_agents()
            now = int(time.time())
            requested = list(dict.fromkeys(neurons))
            claimed: list[str] = []
            conflicts: list[dict[str, Any]] = []

            with write_transaction(self.conn) as conn:
                others = conn.execute(
                    f"SELECT {_AGENT_COLUMNS} FROM active_agents "
                    "WHERE status = 'active' AND agent_id != ?",
                    (agent_id,),
                ).fetchall()

                holders: dict[str, tuple[Any, ...]] = {}
                for row in others:
                    for neuron in _parse_neurons(row[4]):
                        holders.setdefault(neuron, row)

                for neuron in requested:
                    holder = holders.get(neuron)
                    if holder is not None:
                        conflicts.append(
                            {
                                "neuron": neuron,
                                "existing_claimant": str(holder[0]),
                                "claimant_intent": holder[3] or "",
                                "claimant_active_minutes": max(
                                    0, (now - int(holder[5])) // 60
                                ),
                            }
                        )
                    else:
                        claimed.append(neuron)

                claim_id = _make_claim_id(
                    agent_id, claimed, intent or "", ttl_minutes
                )
                if not claimed:
                    result: dict[str, Any] = {
                        "claimed": [],
                        "conflicts": conflicts,
                        "claim_id": claim_id,
                    }
                    if conflicts:
                        result["error"] = NEURON_ALREADY_CLAIMED
                    return result

                existing = self._fetch_agent(conn, agent_id)
                if (
                    existing is not None
                    and str(existing[7] or "active") == "active"
                    and not self._is_stale(existing, now)
                ):
                    previous = _parse_neurons(existing[4])
                    merged = previous + [n for n in claimed if n not in previous]
                    effective_session = (
                        session_id if session_id is not None else existing[2]
                    )
                    # Only override the stored agent_type when explicitly given.
                    effective_type = (
                        agent_type if agent_type is not None else str(existing[1])
                    )
                    conn.execute(
                        "UPDATE active_agents SET agent_type = ?, session_id = ?, "
                        "intent = ?, claimed_neurons = ?, last_heartbeat = ?, "
                        "status = 'active', ttl_minutes = ?, expires_ts = ? "
                        "WHERE agent_id = ?",
                        (
                            effective_type,
                            effective_session,
                            intent or existing[3] or "",
                            _dump_neurons(merged),
                            now,
                            ttl_minutes,
                            now + ttl_minutes * 60,
                            agent_id,
                        ),
                    )
                else:
                    # New agent, or an expired/completed one re-claiming.
                    conn.execute(
                        "INSERT OR REPLACE INTO active_agents "
                        "(agent_id, agent_type, session_id, intent, claimed_neurons, "
                        "started_ts, last_heartbeat, status, ttl_minutes, expires_ts, "
                        "created_ts) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
                        (
                            agent_id,
                            agent_type or "claude",
                            session_id,
                            intent or "",
                            _dump_neurons(claimed),
                            now,
                            now,
                            ttl_minutes,
                            now + ttl_minutes * 60,
                            now,
                        ),
                    )

            if self._metrics:
                self._metrics.inc_claims_made(len(claimed))
                if conflicts:
                    self._metrics.inc_claim_conflicts(len(conflicts))
                if self._persistent_metrics:
                    self._persistent_metrics.record_claim(len(claimed), agent_id)
                    for conflict in conflicts:
                        self._persistent_metrics.record_claim_conflict(
                            conflict["neuron"], agent_id, conflict["existing_claimant"]
                        )

            return {"claimed": claimed, "conflicts": conflicts, "claim_id": claim_id}

    def release_neurons(self, agent_id: str, neurons: list[str]) -> dict[str, Any]:
        """Release specific *neurons* held by *agent_id*.

        Raises :class:`~cerebrofy.errors.NoActiveAgentError` for an unknown or
        inactive agent and :class:`~cerebrofy.errors.ClaimExpiredError` when the
        agent's claim TTL has elapsed.
        """
        with self._lock:
            now = int(time.time())
            with write_transaction(self.conn) as conn:
                row = self._require_active(
                    self._fetch_agent(conn, agent_id), agent_id, now
                )

                current = _parse_neurons(row[4])
                requested = list(dict.fromkeys(neurons))
                released = [neuron for neuron in requested if neuron in current]
                remaining = [neuron for neuron in current if neuron not in set(released)]

                if remaining:
                    ttl_minutes = int(row[8] or 60)
                    conn.execute(
                        "UPDATE active_agents SET claimed_neurons = ?, "
                        "last_heartbeat = ?, expires_ts = ? WHERE agent_id = ?",
                        (
                            _dump_neurons(remaining),
                            now,
                            now + ttl_minutes * 60,
                            agent_id,
                        ),
                    )
                else:
                    conn.execute(
                        "UPDATE active_agents SET claimed_neurons = '[]', "
                        "status = 'completed', last_heartbeat = ? WHERE agent_id = ?",
                        (now, agent_id),
                    )

            if self._metrics:
                self._metrics.inc_claims_released(len(released))
                if self._persistent_metrics:
                    self._persistent_metrics.record_release(len(released), agent_id)

            return {"released": released}

    def release_all(self, agent_id: str) -> dict[str, Any]:
        """Release every claim held by *agent_id* and mark it completed."""
        with self._lock:
            now = int(time.time())
            with write_transaction(self.conn) as conn:
                row = self._require_active(
                    self._fetch_agent(conn, agent_id), agent_id, now
                )

                released = _parse_neurons(row[4])
                conn.execute(
                    "UPDATE active_agents SET claimed_neurons = '[]', "
                    "status = 'completed', last_heartbeat = ? WHERE agent_id = ?",
                    (now, agent_id),
                )

            if self._metrics:
                self._metrics.inc_claims_released(len(released))
                if self._persistent_metrics:
                    self._persistent_metrics.record_release(len(released), agent_id)

            return {"released": released}

    def heartbeat(self, agent_id: str) -> dict[str, Any]:
        """Refresh an agent's heartbeat and extend its claim TTL."""
        with self._lock:
            now = int(time.time())
            with write_transaction(self.conn) as conn:
                row = self._require_active(
                    self._fetch_agent(conn, agent_id), agent_id, now
                )

                ttl_minutes = int(row[8] or 60)
                conn.execute(
                    "UPDATE active_agents SET last_heartbeat = ?, expires_ts = ? "
                    "WHERE agent_id = ?",
                    (now, now + ttl_minutes * 60, agent_id),
                )

            return {
                "agent_id": agent_id,
                "last_heartbeat": now,
                "status": "active",
            }

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_active_agents(
        self, cleanup: bool = True
    ) -> dict[str, dict[str, Any]]:
        """Return all active agents keyed by ``agent_id``.

        Stale claims are swept first when *cleanup* is true and the registry
        is writable; read-only handles never write during a query.
        """
        if cleanup and not self.readonly:
            self.cleanup_stale_agents()
        with self._lock:
            now = int(time.time())
            rows = self.conn.execute(
                f"SELECT {_AGENT_COLUMNS} FROM active_agents "
                "WHERE status = 'active' ORDER BY started_ts, agent_id"
            ).fetchall()

            result: dict[str, dict[str, Any]] = {}
            for row in rows:
                agent = self._row_to_agent(row, now)
                result[agent["agent_id"]] = {
                    "agent_type": agent["agent_type"],
                    "session_id": agent["session_id"],
                    "intent": agent["intent"],
                    "claimed_neurons": agent["claimed_neurons"],
                    "started_ts": agent["started_ts"],
                    "last_heartbeat": agent["last_heartbeat"],
                    "status": agent["status"],
                    "active_minutes": agent["active_minutes"],
                }
            return result

    def get_claims(self) -> list[dict[str, Any]]:
        """Return one row per (agent, neuron) claim."""
        agents = self.get_active_agents()
        claims: list[dict[str, Any]] = []
        for agent_id, data in agents.items():
            for neuron in data["claimed_neurons"]:
                claims.append(
                    {
                        "agent_id": agent_id,
                        "agent_type": data["agent_type"],
                        "intent": data["intent"],
                        "neuron": neuron,
                        "active_minutes": data["active_minutes"],
                    }
                )
        return claims

    def check_conflicts(
        self, requesting_agent: str, neuron: str
    ) -> dict[str, Any]:
        """Return other active agents claiming *neuron* (requester excluded)."""
        if not self.readonly:
            self.cleanup_stale_agents()
        with self._lock:
            now = int(time.time())
            rows = self.conn.execute(
                f"SELECT {_AGENT_COLUMNS} FROM active_agents "
                "WHERE status = 'active' AND agent_id != ?",
                (requesting_agent,),
            ).fetchall()

            claiming_agents: list[dict[str, Any]] = []
            for row in rows:
                if neuron in _parse_neurons(row[4]):
                    claiming_agents.append(
                        {
                            "agent_id": str(row[0]),
                            "agent_type": str(row[1]),
                            "intent": row[3] or "",
                            "active_minutes": max(0, (now - int(row[5])) // 60),
                        }
                    )

            return {
                "agent_id": requesting_agent,
                "neuron": neuron,
                "claiming_agents": claiming_agents,
                "conflict": len(claiming_agents) > 0,
            }

    def detect_overlapping_claims(self) -> list[dict[str, Any]]:
        """Return neurons claimed by more than one active agent."""
        agents = self.get_active_agents()
        by_neuron: dict[str, list[str]] = {}
        for agent_id, data in agents.items():
            for neuron in data["claimed_neurons"]:
                by_neuron.setdefault(neuron, []).append(agent_id)

        return [
            {"neuron": neuron, "agents": sorted(agent_ids)}
            for neuron, agent_ids in sorted(by_neuron.items())
            if len(agent_ids) > 1
        ]

    def detect_memory_conflicts(
        self, neuron: str | None = None
    ) -> list[dict[str, Any]]:
        """Detect contradicting memories in the sibling ``memories.db``."""
        from cerebrofy.coordination.conflict_detector import ConflictDetector

        detector = ConflictDetector(
            self, memories_db_path=self.db_path.parent / "memories.db"
        )
        return detector.detect_memory_conflicts(neuron)

    # ------------------------------------------------------------------
    # Stale claim cleanup
    # ------------------------------------------------------------------

    def cleanup_stale_agents(self) -> list[dict[str, Any]]:
        """Mark expired/stale agents ``completed`` and clear their claims.

        Returns the agents that were cleaned.  An agent is stale when its claim
        TTL elapsed (``expires_ts < now``) or when no heartbeat has arrived for
        two heartbeat intervals.
        """
        with self._lock:
            now = int(time.time())
            with write_transaction(self.conn) as conn:
                rows = conn.execute(
                    f"SELECT {_AGENT_COLUMNS} FROM active_agents "
                    "WHERE status = 'active'"
                ).fetchall()

                cleaned: list[dict[str, Any]] = []
                for row in rows:
                    if not self._is_stale(row, now):
                        continue
                    agent = self._row_to_agent(row, now)
                    conn.execute(
                        "UPDATE active_agents SET status = 'completed', "
                        "claimed_neurons = '[]' WHERE agent_id = ?",
                        (agent["agent_id"],),
                    )
                    agent["status"] = "completed"
                    agent["claimed_neurons"] = []
                    cleaned.append(agent)

            if cleaned and self._metrics:
                self._metrics.inc_stale_cleaned(len(cleaned))
                if self._persistent_metrics:
                    self._persistent_metrics.record_stale_cleanup(len(cleaned))

            return cleaned


def _parse_neurons(raw: object) -> list[str]:
    """Parse the JSON array stored in ``claimed_neurons`` defensively."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    try:
        decoded = json.loads(str(raw))
    except (TypeError, ValueError):
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded]


def _dump_neurons(neurons: list[str]) -> str:
    return json.dumps(list(dict.fromkeys(neurons)))


def _make_claim_id(
    agent_id: str, neurons: list[str], intent: str, ttl_minutes: int
) -> str:
    """Return a deterministic claim id for a (agent, neurons, intent, ttl) tuple.

    Determinism makes repeated/retried claims idempotent instead of minting a
    new id every time the clock ticks.
    """
    payload = json.dumps(
        {
            "agent_id": agent_id,
            "neurons": sorted(set(neurons)),
            "intent": intent,
            "ttl_minutes": ttl_minutes,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "claim_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


__all__ = ["ActiveAgentRegistry"]
