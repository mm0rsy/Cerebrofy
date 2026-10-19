"""Session + event storage for the Live Agent Session Recorder (Idea #11).

All state lives in ``.cerebrofy/db/sessions.db`` — a database separate from
``cerebrofy.db`` for the same reason memories.db is separate (#05): the index
is rebuilt atomically by ``cerebrofy build`` and written under
``BEGIN IMMEDIATE`` by ``cerebrofy update``, while the session log must survive
rebuilds and never contend with the index writer. Storage is local-only: no
network, no uploads.

Blast-radius metrics (#01): the first time a neuron is referenced during a
session, its depth-2 caller count is captured ("before"); at session end the
same metric is recomputed for the tracked set ("after"). Per-neuron lookups are
deduplicated and the tracked set is capped at ``MAX_TRACKED_NEURONS`` so the
per-tool-call recording overhead stays bounded.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Error codes surfaced by the MCP tools / CLI.
SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
NO_ACTIVE_SESSION = "NO_ACTIVE_SESSION"
RECORDING_DISABLED = "RECORDING_DISABLED"

VALID_OUTCOMES: frozenset[str] = frozenset({"success", "partial", "failed", "unknown"})

_SESSION_ID_PREFIX = "sess_"
_MAX_ARG_VALUE_CHARS = 300
_MAX_ARG_ITEMS = 20

# Bounding constants for the blast-radius tracking (overhead control).
MAX_TRACKED_NEURONS = 50
MAX_REFS_PER_EVENT = 3
_MAX_FILE_REFS = 5

_SESSION_COLS = (
    "id, started_at, ended_at, agent, task, outcome, outcome_notes, "
    "neurons_touched, blast_radius_before, blast_radius_after, event_count"
)

# Sensitive argument keys that should be redacted in stored events
_SENSITIVE_KEYS: frozenset[str] = frozenset({
    "api_key", "token", "secret", "password", "authorization",
    "access_token", "refresh_token", "client_secret", "private_key",
    "ssh_key", "cert", "credential", "bearer", "auth",
})


class SessionNotFoundError(LookupError):
    """Raised when a session id does not exist."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"[{SESSION_NOT_FOUND}] no session with id '{session_id}'")


@dataclass(frozen=True)
class SessionEvent:
    """A single recorded MCP tool call."""

    session_id: str
    ts: int
    tool: str
    args: dict[str, Any]
    result_summary: str | None


@dataclass(frozen=True)
class SessionRecord:
    """A recorded agent session."""

    id: str
    task: str
    agent: str | None
    started_at: int
    ended_at: int | None
    outcome: str
    outcome_notes: str | None
    neurons_touched: tuple[str, ...]
    blast_radius_before: int | None
    blast_radius_after: int | None
    event_count: int

    @property
    def duration_seconds(self) -> int:
        """Wall-clock duration; 0 for sessions that are still open."""
        if self.ended_at is None:
            return 0
        return max(0, int(self.ended_at - self.started_at))

    @property
    def is_active(self) -> bool:
        return self.ended_at is None

    @property
    def blast_radius_delta(self) -> int | None:
        """after − before, or None when either metric is unknown."""
        if self.blast_radius_before is None or self.blast_radius_after is None:
            return None
        return self.blast_radius_after - self.blast_radius_before


# ---------------------------------------------------------------------------
# Connection + schema
# ---------------------------------------------------------------------------

def open_sessions_db(cerebrofy_dir: Path) -> sqlite3.Connection:
    """Open (or create) sessions.db, load sqlite-vec, apply the schema idempotently."""
    import sqlite_vec  # type: ignore[import-untyped]

    db_path = cerebrofy_dir / "db" / "sessions.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False: the MCP middleware may touch this connection from
    # an SDK worker thread; access stays serialized in practice.
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")
    from cerebrofy.db.schema import create_session_schema

    create_session_schema(conn)
    return conn


# ---------------------------------------------------------------------------
# Argument / result truncation (storage bound: < 1 MB per coding hour)
# ---------------------------------------------------------------------------

def truncate_args(
    args: Mapping[str, Any],
    *,
    max_value_chars: int = _MAX_ARG_VALUE_CHARS,
    max_items: int = _MAX_ARG_ITEMS,
) -> dict[str, Any]:
    """Copy *args*, truncating long values and redacting sensitive keys.

    Sensitive keys (api_key, token, secret, password, etc.) are replaced with
    "[REDACTED]" to prevent credential leakage in session recordings.
    """
    out: dict[str, Any] = {}
    for key, value in list(args.items())[:max_items]:
        if key.lower() in _SENSITIVE_KEYS:
            out[key] = "[REDACTED]"
        elif isinstance(value, str) and len(value) > max_value_chars:
            out[key] = value[:max_value_chars] + "…"
        else:
            out[key] = value
    return out


def truncate_summary(text: str | None, *, max_chars: int = 500) -> str | None:
    """Collapse whitespace and truncate a tool result summary."""
    if text is None:
        return None
    collapsed = " ".join(text.split())
    if not collapsed:
        return None
    if len(collapsed) > max_chars:
        return collapsed[:max_chars] + "…"
    return collapsed


# ---------------------------------------------------------------------------
# Row mapping
# ---------------------------------------------------------------------------

def _row_to_session(row: Sequence[Any]) -> SessionRecord:
    touched_raw = row[7]
    touched: tuple[str, ...] = ()
    if touched_raw:
        try:
            loaded = json.loads(touched_raw)
            if isinstance(loaded, list):
                touched = tuple(str(item) for item in loaded)
        except (json.JSONDecodeError, TypeError):
            touched = ()
    return SessionRecord(
        id=str(row[0]),
        started_at=int(row[1]),
        ended_at=int(row[2]) if row[2] is not None else None,
        agent=row[3],
        task=str(row[4]),
        outcome=str(row[5] or "unknown"),
        outcome_notes=row[6],
        neurons_touched=touched,
        blast_radius_before=int(row[8]) if row[8] is not None else None,
        blast_radius_after=int(row[9]) if row[9] is not None else None,
        event_count=int(row[10] or 0),
    )


def _row_to_event(row: Sequence[Any]) -> SessionEvent:
    args: dict[str, Any] = {}
    if row[3]:
        try:
            loaded = json.loads(row[3])
            if isinstance(loaded, dict):
                args = loaded
        except (json.JSONDecodeError, TypeError):
            args = {}
    return SessionEvent(
        session_id=str(row[0]),
        ts=int(row[1]),
        tool=str(row[2]),
        args=args,
        result_summary=row[4],
    )


# ---------------------------------------------------------------------------
# Blast-radius metrics (Idea #01)
# ---------------------------------------------------------------------------

def neuron_blast_metric(
    index_conn: sqlite3.Connection, neuron_id: str, *, depth: int = 2
) -> int | None:
    """Depth-1 + depth-2 caller count for *neuron_id*; None when not in the index.

    Mirrors ``analysis.blast_radius.bfs_callers`` (RUNTIME_BOUNDARY edges are
    never traversed — Law II).
    """
    try:
        from cerebrofy.analysis.blast_radius import bfs_callers

        row = index_conn.execute(
            "SELECT 1 FROM nodes WHERE id = ? LIMIT 1", (neuron_id,)
        ).fetchone()
        if row is None:
            return None
        d1, d2, _boundaries = bfs_callers(neuron_id, index_conn, max_depth=depth)
        return len(d1) + len(d2)
    except sqlite3.Error:
        return None


def resolve_neuron_refs(
    index_conn: sqlite3.Connection,
    args: Mapping[str, Any],
    *,
    limit: int = MAX_REFS_PER_EVENT,
) -> list[str]:
    """Resolve neuron references inside tool *args* to node ids (best effort).

    Recognised keys: ``target`` / ``neuron`` / ``name`` (a neuron reference
    accepted by ``analysis.blast_radius.neuron_for_target``) and ``file`` /
    ``path`` (all non-module neurons defined in that file, capped).
    """
    from cerebrofy.analysis.blast_radius import neuron_for_target

    refs: list[str] = []

    def _add(node_id: str | None) -> None:
        if node_id and not node_id.startswith("external::") and node_id not in refs:
            refs.append(node_id)

    for key in ("target", "neuron", "name"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            try:
                neuron = neuron_for_target(value.strip(), index_conn)
            except sqlite3.Error:
                neuron = None
            _add(neuron.id if neuron is not None else None)

    for key in ("file", "path"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            try:
                rows = index_conn.execute(
                    "SELECT id FROM nodes WHERE file = ? AND type != 'module' LIMIT ?",
                    (value.strip(), _MAX_FILE_REFS),
                ).fetchall()
            except sqlite3.Error:
                rows = []
            for (node_id,) in rows:
                _add(str(node_id))

    return refs[:limit]


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def new_session_id() -> str:
    """Return a fresh, collision-resistant session id (``sess_<hex8>``)."""
    return f"{_SESSION_ID_PREFIX}{uuid.uuid4().hex[:8]}"


def start_session(
    conn: sqlite3.Connection,
    *,
    task: str,
    agent: str | None = None,
    now: int | None = None,
    embedding: list[float] | None = None,
) -> SessionRecord:
    """Insert a new open session. When *embedding* is given, index it for search."""
    session_id = new_session_id()
    ts = int(now if now is not None else time.time())
    conn.execute(
        "INSERT INTO sessions(id, started_at, agent, task, outcome, neurons_touched) "
        "VALUES (?,?,?,?,?,?)",
        (session_id, ts, agent, task, "unknown", "[]"),
    )
    if embedding is not None:
        rowid = conn.execute(
            "SELECT rowid FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if rowid is not None:
            conn.execute(
                "INSERT INTO vec_sessions(rowid, embedding) VALUES (?, vec_f32(?))",
                (int(rowid[0]), json.dumps(embedding)),
            )
    conn.commit()
    session = get_session(conn, session_id)
    assert session is not None  # inserted above
    return session


def record_event(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    tool: str,
    args: Mapping[str, Any] | None = None,
    result_summary: str | None = None,
    ts: int | None = None,
    index_conn: sqlite3.Connection | None = None,
) -> SessionEvent:
    """Append one tool-call event, bumping the session's event counter.

    When *index_conn* is provided, neuron references in *args* are resolved and
    their depth-2 caller counts are folded into ``blast_radius_before`` the
    first time each neuron is seen in this session.
    """
    event_args = truncate_args(args or {})
    summary = truncate_summary(result_summary)
    event_ts = int(ts if ts is not None else time.time())
    conn.execute(
        "INSERT INTO session_events(session_id, ts, tool, args, result_summary) "
        "VALUES (?,?,?,?,?)",
        (session_id, event_ts, tool, json.dumps(event_args), summary),
    )
    conn.execute(
        "UPDATE sessions SET event_count = event_count + 1 WHERE id = ?", (session_id,)
    )
    if index_conn is not None:
        _track_neuron_refs(conn, session_id, event_args, index_conn)
    conn.commit()
    return SessionEvent(
        session_id=session_id, ts=event_ts, tool=tool,
        args=event_args, result_summary=summary,
    )


# Thread-safe lock for session database updates (race condition fix)
_SESSION_LOCK = threading.Lock()


def _track_neuron_refs(
    conn: sqlite3.Connection,
    session_id: str,
    args: dict[str, Any],
    index_conn: sqlite3.Connection,
) -> None:
    """Fold newly-referenced neurons into ``neurons_touched`` / ``blast_radius_before``.

    This function acquires the global ``_SESSION_LOCK`` to serialise the
    read-modify-write on the session row, preventing lost updates when
    concurrent tool calls touch the same session.
    """
    with _SESSION_LOCK:
        row = conn.execute(
            "SELECT neurons_touched, blast_radius_before FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return
        try:
            touched_raw = json.loads(row[0]) if row[0] else []
        except (json.JSONDecodeError, TypeError):
            touched_raw = []
        touched: list[str] = [
            str(x) for x in touched_raw
        ] if isinstance(touched_raw, list) else []
        if len(touched) >= MAX_TRACKED_NEURONS:
            return

        before: int | None = int(row[1]) if row[1] is not None else None
        changed = False
        for node_id in resolve_neuron_refs(index_conn, args):
            if node_id in touched:
                continue
            metric = neuron_blast_metric(index_conn, node_id)
            if metric is None:
                continue
            touched.append(node_id)
            before = (before or 0) + metric
            changed = True
            if len(touched) >= MAX_TRACKED_NEURONS:
                break

        if changed:
            conn.execute(
                "UPDATE sessions SET neurons_touched = ?, blast_radius_before = ? WHERE id = ?",
                (json.dumps(touched), before, session_id),
            )


def write_session_summary_memory(
    cerebrofy_dir: Path,
    session: SessionRecord,
    *,
    author: str = "agent:session-recorder",
) -> bool:
    """Fold a closed session into the #05 memory layer as a single decision memory.

    The memory title is the session task; its body carries the outcome, duration,
    event count, neurons touched and the depth-2 blast-radius before->after delta
    so the cross-session synthesizer (#24) can pattern-match on agent outcomes —
    the Phase 2 loop #11 -> #05 -> #11.

    Non-fatal by contract: any failure (memories.db absent, #05 embedder offline,
    disk error) is swallowed and ``False`` is returned. This mirrors
    ``cerebrofy.arch.memory.write_violation_memories`` — the recording path must
    never fail because the memory layer did.
    """
    try:
        from cerebrofy.memory.embedder import embed_memory
        from cerebrofy.memory.store import Memory, open_memories_db, write_memory

        title = (session.task or "").strip()[:120] or "[no task]"
        blast = ""
        if session.blast_radius_before is not None or session.blast_radius_after is not None:
            blast = (
                f"; blast_radius_before={session.blast_radius_before} -> "
                f"after={session.blast_radius_after}"
            )
        body = (
            f"agent={session.agent or 'unknown'}; outcome={session.outcome}; "
            f"duration={session.duration_seconds}s; events={session.event_count}; "
            f"neurons_touched={len(session.neurons_touched)}{blast}"
        )
        if session.outcome_notes:
            body += f"\n\nnotes: {session.outcome_notes.strip()[:500]}"
        mem = Memory(
            id=str(uuid.uuid4()),
            neuron_id=None,
            lobe=None,
            type="decision",
            title=title,
            body=body,
            author=author,
            created_ts=int(session.ended_at or time.time()),
            tags=("session", f"outcome:{session.outcome}"),
            decay_score=1.0,
            status="active",
        )
        conn = open_memories_db(cerebrofy_dir)
        try:
            embedding = embed_memory(mem.title, mem.body)
            write_memory(conn, mem, embedding)
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        return False


def end_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    outcome: str | None = None,
    notes: str | None = None,
    now: int | None = None,
    index_conn: sqlite3.Connection | None = None,
    cerebrofy_dir: Path | None = None,
) -> SessionRecord:
    """Close a session: set ended_at / outcome / notes and the after-metric.

    ``outcome`` defaults to ``"unknown"``; an unknown value raises ValueError.
    When *index_conn* is provided and neurons were tracked, ``blast_radius_after``
    is recomputed over the tracked set against the current index.

    When *cerebrofy_dir* is provided (MCP/CLI context), the closed session is
    also folded into the #05 memory layer as a single decision memory via
    :func:`write_session_summary_memory` — the Phase 2 loop #11 -> #05 -> #11.
    This step is non-fatal: a memory-store failure never masks a closed session.

    TODO(integration-24): the cross-session synthesizer will read closed
    sessions (outcome + outcome_notes) from this table to detect patterns.
    """
    session = get_session(conn, session_id)
    if session is None:
        raise SessionNotFoundError(session_id)

    if session.ended_at is not None:
        raise ValueError(f"session '{session_id}' already ended")

    outcome_value = (outcome or "unknown").strip().lower() or "unknown"
    if outcome_value not in VALID_OUTCOMES:
        raise ValueError(
            f"invalid outcome '{outcome}'. Valid: {', '.join(sorted(VALID_OUTCOMES))}"
        )

    after: int | None = None
    if index_conn is not None and session.neurons_touched:
        total = 0
        present = 0
        for node_id in session.neurons_touched:
            metric = neuron_blast_metric(index_conn, node_id)
            if metric is not None:
                total += metric
                present += 1
        after = total if present else None

    ts = int(now if now is not None else time.time())
    # Use COALESCE for after only when it's not None; otherwise set explicitly
    if after is not None:
        conn.execute(
            "UPDATE sessions SET ended_at = ?, outcome = ?, outcome_notes = ?, "
            "blast_radius_after = ? WHERE id = ?",
            (ts, outcome_value, notes, after, session_id),
        )
    else:
        conn.execute(
            "UPDATE sessions SET ended_at = ?, outcome = ?, outcome_notes = ?, "
            "blast_radius_after = NULL WHERE id = ?",
            (ts, outcome_value, notes, session_id),
        )
    conn.commit()
    updated = get_session(conn, session_id)
    assert updated is not None  # session existed above
    if cerebrofy_dir is not None:
        # Phase 2 loop (#11 -> #05 -> #11): summarise the closed session as a
        # decision memory. Non-fatal — never let the memory layer fail a close.
        write_session_summary_memory(cerebrofy_dir, updated)
    return updated


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def get_session(conn: sqlite3.Connection, session_id: str) -> SessionRecord | None:
    """Return a session by id, or None."""
    row = conn.execute(
        f"SELECT {_SESSION_COLS} FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    return _row_to_session(row) if row else None


def latest_session(conn: sqlite3.Connection) -> SessionRecord | None:
    """Return the most recently started session, or None."""
    row = conn.execute(
        f"SELECT {_SESSION_COLS} FROM sessions ORDER BY started_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    return _row_to_session(row) if row else None


def active_session(conn: sqlite3.Connection) -> SessionRecord | None:
    """Return the most recent still-open session, or None."""
    row = conn.execute(
        f"SELECT {_SESSION_COLS} FROM sessions WHERE ended_at IS NULL "
        f"ORDER BY started_at DESC, rowid DESC LIMIT 1"
    ).fetchone()
    return _row_to_session(row) if row else None


def list_sessions(conn: sqlite3.Connection, *, limit: int = 20) -> list[SessionRecord]:
    """Return sessions newest-first, capped at *limit*."""
    rows = conn.execute(
        f"SELECT {_SESSION_COLS} FROM sessions "
        f"ORDER BY started_at DESC, rowid DESC LIMIT ?",
        (max(1, limit),),
    ).fetchall()
    return [_row_to_session(r) for r in rows]


def list_events(conn: sqlite3.Connection, session_id: str) -> list[SessionEvent]:
    """Return the events of a session in recording order.

    TODO(integration-21): the insight daemon will tail this stream to emit
    session_pattern insights; keep the (session_id, id) index for that reader.
    """
    rows = conn.execute(
        "SELECT session_id, ts, tool, args, result_summary FROM session_events "
        "WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    return [_row_to_event(r) for r in rows]


def count_events(conn: sqlite3.Connection, session_id: str) -> int:
    """Return the number of events recorded for a session."""
    row = conn.execute(
        "SELECT COUNT(*) FROM session_events WHERE session_id = ?", (session_id,)
    ).fetchone()
    return int(row[0]) if row else 0


@dataclass(frozen=True)
class SessionSearchHit:
    """One `cerebrofy session search` result."""

    session: SessionRecord
    score: float
    match_kind: str  # "semantic" | "task_text"


def search_sessions(
    conn: sqlite3.Connection,
    query_text: str,
    *,
    query_embedding: list[float] | None = None,
    limit: int = 10,
) -> list[SessionSearchHit]:
    """Search recorded sessions by task text.

    Semantic KNN over ``vec_sessions`` when *query_embedding* is given
    (embeddings produced by ``cerebrofy.search.hybrid.embed_query``); otherwise
    falls back to a case-insensitive substring match over task text so search
    still works when embeddings are disabled.
    """
    if query_embedding is not None:
        oversample_k = max(limit * 20, 100)
        vec_rows = conn.execute(
            "SELECT rowid, distance FROM vec_sessions "
            "WHERE embedding MATCH vec_f32(?) AND k = ?",
            (json.dumps(query_embedding), oversample_k),
        ).fetchall()
        if not vec_rows:
            return []
        distances = {int(r[0]): float(r[1]) for r in vec_rows}
        placeholders = ",".join("?" * len(distances))
        rows = conn.execute(
            f"SELECT rowid, {_SESSION_COLS} FROM sessions WHERE rowid IN ({placeholders})",
            list(distances.keys()),
        ).fetchall()
        hits = [
            SessionSearchHit(
                session=_row_to_session(r[1:]),
                score=round(max(0.0, 1.0 - (distances[int(r[0])] ** 2) / 2.0), 4),
                match_kind="semantic",
            )
            for r in rows
        ]
        hits.sort(key=lambda h: -h.score)
        return hits[:limit]

    if not query_text.strip():
        return []
    rows = conn.execute(
        f"SELECT {_SESSION_COLS} FROM sessions "
        f"WHERE task LIKE ? ORDER BY started_at DESC LIMIT ?",
        (f"%{query_text.strip()}%", max(1, limit)),
    ).fetchall()
    return [
        SessionSearchHit(session=_row_to_session(r), score=0.0, match_kind="task_text")
        for r in rows
    ]