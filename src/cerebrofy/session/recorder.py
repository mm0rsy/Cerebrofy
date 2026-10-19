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
import logging
import re
import sqlite3
import time
import uuid
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

# Lightweight, non-cyclic collaborators hoisted from function scope (m9).
# None of these modules import ``cerebrofy.session``, so eager module-level
# imports introduce no import cycle and make this file's true dependency graph
# visible at a glance. Heavy / native-backed collaborators — sqlite_vec (a native
# C extension), the fastembed-backed embedder, and the monkeypatch-targeted
# memory-store openers — remain imported inside their functions; see the inline
# comments on open_sessions_db, write_memory_if_possible and
# write_session_summary_memory for why they stay lazy.
from cerebrofy.analysis.blast_radius import bfs_callers, neuron_for_target
from cerebrofy.config.loader import SessionConfig
from cerebrofy.db.schema import create_session_schema
from cerebrofy.memory.store import Memory

# Error codes surfaced by the MCP tools / CLI.
SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
NO_ACTIVE_SESSION = "NO_ACTIVE_SESSION"
RECORDING_DISABLED = "RECORDING_DISABLED"

# Allowed session-outcome values, ordered by the severity ladder used in
# reports (success -> partial -> failed -> unknown). end_session() lower-cases
# and strips any user-supplied outcome before testing membership, so ``in``
# checks still work; the error message uses sorted() + ', '.join() which is
# identical for a tuple. Kept as a tuple (not frozenset) so the allowed set is
# ordered and self-documenting.
VALID_OUTCOMES: tuple[str, ...] = (
    "success",
    "partial",
    "failed",
    "unknown",
)

_SESSION_ID_PREFIX = "sess_"
_MAX_ARG_VALUE_CHARS = 300
_MAX_ARG_ITEMS = 20

# Bounding constants for the blast-radius tracking (overhead control).
# Their default values originate from ``cerebrofy.config.loader.SessionConfig``
# (which reads ``.cerebrofy/config.yaml``) so the knobs are configurable. They
# are retained as module-level constants for backward compatibility (re-exported
# via ``cerebrofy.session``); new callers should pass the explicit keyword-only
# ``max_tracked_neurons`` / ``max_refs_per_event`` params on record_event()
# instead of depending on these defaults.
MAX_TRACKED_NEURONS: int = SessionConfig().max_tracked_neurons  # 50
MAX_REFS_PER_EVENT: int = SessionConfig().max_refs_per_event    # 3
_MAX_FILE_REFS = 5

_SESSION_COLS = (
    "id, started_at, ended_at, agent, task, outcome, outcome_notes, "
    "neurons_touched, blast_radius_before, blast_radius_after, event_count"
)

_logger = logging.getLogger(__name__)

# Sensitive-key *patterns* redacted from stored arguments. Matching is
# case-insensitive and substring-based (after normalizing separators) so keys
# like ``API-Key``, ``my_token`` or ``userAuthorization`` are caught even when
# nested inside argument dicts. Bare ``auth`` is intentionally omitted: its
# substring would false-positive on legitimate keys such as ``author``.
_SENSITIVE_PATTERNS: tuple[str, ...] = tuple(sorted({
    "api_key", "apikey", "access_token", "refresh_token", "token", "secret",
    "password", "passwd", "pwd", "authorization", "client_secret",
    "private_key", "ssh_key", "cert", "credential", "bearer",
}))

# Normalize separators (``-``, ``_``, ``.``, whitespace) to ``_`` before matching
# so ``api-key`` / ``api.key`` line up with the ``api_key`` pattern.
_SEP_RE = re.compile(r"[-_.\s]+")

# Cap recursion so redaction can't be abused to walk a pathological structure.
_MAX_NESTING_DEPTH = 10


def _normalize_key(key: str) -> str:
    """Lower-case *key* and collapse separators to ``_`` for pattern matching."""
    return _SEP_RE.sub("_", key).lower()


def _is_sensitive_key(key: Any) -> bool:
    """Case-insensitive substring match against sensitive-key patterns.

    Returns ``False`` for non-str keys so integers / ``None`` keys are never
    accidentally treated as sensitive. Robust to separator variants
    (``api-key`` == ``api_key`` == ``apikey``).
    """
    if not isinstance(key, str):
        return False
    normalized = _normalize_key(key)
    return any(pattern in normalized for pattern in _SENSITIVE_PATTERNS)


def _truncate_leaf(value: Any, max_value_chars: int) -> Any:
    """Bound a scalar's length when it is a string; pass other types through."""
    if isinstance(value, str) and len(value) > max_value_chars:
        return value[:max_value_chars] + "…"
    return value


def _redact_structure(
    value: Any,
    *,
    max_value_chars: int,
    max_items: int,
    depth: int,
) -> Any:
    """Recursively redact sensitive keys and bound lengths, preserving types.

    Dict keys whose normalized form matches a sensitive pattern are replaced
    with ``"[REDACTED]"`` regardless of the (possibly nested) value type. Lists
    and tuples are walked element-wise; mappings are reduced. Recursion is
    capped by *depth* so deeply nested input can't drive unbounded work.
    Non-str keys/values are passed through untouched.
    """
    if depth <= 0:
        # Never pass nested containers through unredacted: a secret buried
        # deeper than the recursion cap would otherwise be persisted raw.
        if isinstance(value, (Mapping, list, tuple)):
            return "[MAX_DEPTH]"
        return _truncate_leaf(value, max_value_chars)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, val in list(value.items())[:max_items]:
            out[key] = (
                "[REDACTED]"
                if _is_sensitive_key(key)
                else _redact_structure(
                    val,
                    max_value_chars=max_value_chars,
                    max_items=max_items,
                    depth=depth - 1,
                )
            )
        return out
    if isinstance(value, (list, tuple)):
        factory = type(value)
        return factory(
            _redact_structure(
                v,
                max_value_chars=max_value_chars,
                max_items=max_items,
                depth=depth - 1,
            )
            for v in list(value)[:max_items]
        )
    return _truncate_leaf(value, max_value_chars)


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
    # Lazy: sqlite_vec is a native C extension. Import at call time rather than
    # module scope so importing this module — which ``cerebrofy.commands.session``
    # imports unconditionally for *every* CLI command — stays free of native-load
    # cost. Mirrors the same deferral in ``cerebrofy.memory.store``.
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
    """Copy *args*, redacting sensitive keys and truncating long values.

    Redaction is applied **recursively** before truncation/serialization:
    sensitive keys (``api_key``, ``access_token``, ``authorization``,
    ``client_secret``, ``password`` …) are replaced with ``"[REDACTED]"``
    even when nested inside dicts/lists/tuples, using case-insensitive
    pattern matching so variant spellings (``API-Key``, ``my_token``) are
    caught. Non-str keys/values are passed through untouched; recursion is
    capped at :data:`_MAX_NESTING_DEPTH` to bound work on deep structures.
    """
    return cast(
        dict[str, Any],
        _redact_structure(
            args,
            max_value_chars=max_value_chars,
            max_items=max_items,
            depth=_MAX_NESTING_DEPTH,
        ),
    )


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
            # Corrupted/malformed session JSON must never break a read path.
            _logger.warning(
                "corrupt neurons_touched JSON for session '%s'; "
                "falling back to empty", row[0],
            )
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
            # Corrupted/malformed session JSON must never break a read path.
            _logger.warning(
                "corrupt args JSON for session event (session_id='%s', tool='%s'); "
                "falling back to empty", row[0], row[2],
            )
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
    max_tracked_neurons: int = MAX_TRACKED_NEURONS,
    max_refs_per_event: int = MAX_REFS_PER_EVENT,
) -> SessionEvent:
    """Append one tool-call event, bumping the session's event counter.

    When *index_conn* is provided, neuron references in *args* are resolved and
    their depth-2 caller counts are folded into ``blast_radius_before`` the
    first time each neuron is seen in this session.

    *max_tracked_neurons* (default ``MAX_TRACKED_NEURONS`` / ``SessionConfig``)
    bounds the total number of neurons tracked per session, and
    *max_refs_per_event* (default ``MAX_REFS_PER_EVENT`` / ``SessionConfig``)
    bounds how many neuron references a single event may resolve. Omitting both
    preserves the existing behavior.
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
        _track_neuron_refs(
            conn, session_id, event_args, index_conn,
            max_tracked_neurons=max_tracked_neurons,
            max_refs_per_event=max_refs_per_event,
        )
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
    *,
    max_tracked_neurons: int,
    max_refs_per_event: int,
) -> None:
    """Fold newly-referenced neurons into ``neurons_touched`` / ``blast_radius_before``.

    This function acquires the global ``_SESSION_LOCK`` to serialise the
    read-modify-write on the session row, preventing lost updates when
    concurrent tool calls touch the same session.

    *max_tracked_neurons* caps the total number of neurons recorded for the
    session (bounding blast-radius lookup cost); *max_refs_per_event* caps how
    many neuron references a single event may resolve. Both flow from
    :func:`record_event` (whose defaults are the SessionConfig-backed module
    constants) so callers can override the bounds without touching module state.
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
            # Corrupted/malformed session JSON must never break a write path.
            _logger.warning(
                "corrupt neurons_touched JSON while tracking refs for session '%s'; "
                "falling back to empty", session_id,
            )
            touched_raw = []
        touched: list[str] = [
            str(x) for x in touched_raw
        ] if isinstance(touched_raw, list) else []
        if len(touched) >= max_tracked_neurons:
            return

        before: int | None = int(row[1]) if row[1] is not None else None
        changed = False
        for node_id in resolve_neuron_refs(index_conn, args, limit=max_refs_per_event):
            if node_id in touched:
                continue
            metric = neuron_blast_metric(index_conn, node_id)
            if metric is None:
                continue
            touched.append(node_id)
            before = (before or 0) + metric
            changed = True
            if len(touched) >= max_tracked_neurons:
                break

        if changed:
            conn.execute(
                "UPDATE sessions SET neurons_touched = ?, blast_radius_before = ? WHERE id = ?",
                (json.dumps(touched), before, session_id),
            )


def build_session_memory(
    session: SessionRecord,
    *,
    author: str = "agent:session-recorder",
) -> Memory:
    """Build the #05 decision :class:`Memory` for a closed session (pure, no IO).

    The memory title is the session task; its body carries the outcome, duration,
    event count, neurons touched and the depth-2 blast-radius before->after delta
    so the cross-session synthesizer (#24) can pattern-match on agent outcomes —
    the Phase 2 loop #11 -> #05 -> #11.

    Split out from :func:`write_session_summary_memory` so the memory
    construction is unit-testable without mocking the memory store.
    """
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
    return Memory(
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


def write_memory_if_possible(
    cerebrofy_dir: Path,
    memory: Memory,
    embedder: Callable[[str, str], list[float]],
) -> bool:
    """Persist *memory* to the #05 store, embedding via *embedder*.

    The #05 dependency is imported lazily at call time so tests can patch
    ``cerebrofy.memory.store.open_memories_db`` / ``write_memory``. Non-fatal
    by contract — any failure (memories.db absent, #05 embedder offline,
    disk error) is logged and ``False`` is returned, mirroring
    ``cerebrofy.arch.memory.write_violation_memories``: the recording path must
    never fail because the memory layer did.
    """
    try:
        # Lazy: kept at call site (not module scope) so tests can monkeypatch
        # ``cerebrofy.memory.store.open_memories_db`` / ``write_memory``; a
        # module-level ``from`` would bind these names at import time and defeat
        # that patching. Not a true import cycle — this is a deliberate test
        # seam for the #05 memory integration.
        from cerebrofy.memory.store import open_memories_db, write_memory

        conn = open_memories_db(cerebrofy_dir)
        try:
            embedding = embedder(memory.title, memory.body)
            write_memory(conn, memory, embedding)
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        _logger.warning(
            "failed to write session summary memory (title=%r) to %s",
            memory.title, cerebrofy_dir, exc_info=True,
        )
        return False


def write_session_summary_memory(
    cerebrofy_dir: Path,
    session: SessionRecord,
    *,
    author: str = "agent:session-recorder",
    embed_memory_fn: Callable[[str, str], list[float]] | None = None,
) -> bool:
    """Fold a closed session into the #05 memory layer as a single decision memory.

    Thin orchestrator: :func:`build_session_memory` constructs the pure
    :class:`Memory`, then :func:`write_memory_if_possible` persists it. The
    memory write is non-fatal — a ``False`` return never masks a closed session.

    *embed_memory_fn* overrides the embedder used to embed the memory (defaults
    to the fastembed-backed ``cerebrofy.memory.embedder.embed_memory`` when
    omitted, preserving existing behavior). Injecting a fake here lets callers —
    and tests — avoid any model/network initialization.
    """
    if embed_memory_fn is None:
        # Lazy: the default embed_memory pulls in the fastembed model provider
        # at import time, so defer it to call time. This keeps importing this
        # module — which every CLI command does via ``cerebrofy.commands.session``
        # — free of the heavy ONNX model load, and lets callers fully override
        # the embedder via *embed_memory_fn* to avoid model/network init.
        from cerebrofy.memory.embedder import embed_memory

        embed_memory_fn = embed_memory
    memory = build_session_memory(session, author=author)
    return write_memory_if_possible(cerebrofy_dir, memory, embed_memory_fn)


def end_session(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    outcome: str | None = None,
    notes: str | None = None,
    now: int | None = None,
    index_conn: sqlite3.Connection | None = None,
    cerebrofy_dir: Path | None = None,
    embed_memory_fn: Callable[[str, str], list[float]] | None = None,
) -> SessionRecord:
    """Close a session: set ended_at / outcome / notes and the after-metric.

    ``outcome`` defaults to ``"unknown"``; an unknown value raises ValueError.
    When *index_conn* is provided and neurons were tracked, ``blast_radius_after``
    is recomputed over the tracked set against the current index.

    When *cerebrofy_dir* is provided (MCP/CLI context), the closed session is
    also folded into the #05 memory layer as a single decision memory via
    :func:`write_session_summary_memory` — the Phase 2 loop #11 -> #05 -> #11.
    This step is non-fatal: a memory-store failure never masks a closed session.
    *embed_memory_fn* is forwarded to :func:`write_session_summary_memory` to
    override the default embedder (defaults to the current import when omitted).

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
        write_session_summary_memory(
            cerebrofy_dir, updated, embed_memory_fn=embed_memory_fn
        )
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