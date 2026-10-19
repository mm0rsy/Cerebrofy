"""Thin MCP session-recording middleware (Idea #11).

Wired into ``mcp/server.py``'s tool dispatcher: every tool call is offered to
``SessionMiddleware.record()``, which records it when *and only when* opt-in
recording is enabled (``record_sessions: true``) and a session is currently
active. All recording logic lives in :mod:`cerebrofy.session.recorder` — this
module only owns connection caching, thread-safe session-db updates, and the
never-raises contract, so a recording failure can never break a tool call.

Per-request ``SessionMiddleware`` instances are created by the caller (the MCP
server) rather than via a shared singleton, avoiding global-state and
thread-safety issues.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from cerebrofy.session.recorder import (
    SessionRecord,
    active_session,
    open_sessions_db,
    record_event,
)
from cerebrofy.utils.paths import find_repo_root as _find_repo_root_impl

# The session-management tools are never recorded themselves: session_start
# creates the session, session_end closes it, and recording either inside the
# same session would break replay boundaries.
_SKIP_TOOLS: frozenset[str] = frozenset(
    {"cerebrofy_session_start", "cerebrofy_session_end", "cerebrofy_session_show"}
)

_MAX_RESULT_SAMPLE_CHARS = 1000


def find_repo_root(start: Path, *, root_boundary: Path | None = None) -> Path | None:
    """Walk up from *start* looking for ``.cerebrofy/config.yaml``; None if absent.

    Delegates to the single shared implementation in :mod:`cerebrofy.utils.paths`
    so there is one resolution code-path across the whole project. When a root
    has been explicitly bound by the MCP server (``set_bound_root``) it is
    returned immediately, ignoring *start* — this is what prevents a
    manipulated CWD from redirecting session recording at another project.

    If *root_boundary* is provided, the walk stops at that directory (useful for
    preventing cross-project access in multi-project environments).
    """
    return _find_repo_root_impl(start, boundary=root_boundary)


def summarize_result(result: object) -> str | None:
    """Extract a short text summary from an MCP tool result (list of TextContent)."""
    if isinstance(result, list) and result:
        first = result[0]
        text = getattr(first, "text", None)
        if isinstance(text, str) and text:
            return text[:_MAX_RESULT_SAMPLE_CHARS]
    return None


class SessionMiddleware:
    """Records dispatched MCP tool calls into the active session, best effort.

    Holds cached connections so the per-call cost is one indexed INSERT plus
    (for the first reference to each neuron) one depth-2 blast-radius lookup.

    Connections can be injected via factories for testing; when omitted, the
    middleware opens its own connections as before.
    """

    def __init__(
        self,
        root: Path,
        *,
        enabled: bool | None = None,
        sessions_conn_factory: Callable[[], sqlite3.Connection | None] | None = None,
        index_conn_factory: Callable[[], sqlite3.Connection | None] | None = None,
    ) -> None:
        self._root = root
        self._enabled_override = enabled
        self._enabled_cache: tuple[float, bool] | None = None
        self._sessions_conn: sqlite3.Connection | None = None
        self._index_conn: sqlite3.Connection | None = None
        self._index_fingerprint: tuple[int, int] | None = None
        # Optional factories for dependency injection (testing)
        self._sessions_conn_factory = sessions_conn_factory
        self._index_conn_factory = index_conn_factory
        # Lock for thread-safe session-db updates (race condition fix)
        self._sessions_lock = threading.Lock()

    @property
    def root(self) -> Path:
        return self._root

    # ── opt-in resolution ────────────────────────────────────────────────
    def is_recording(self) -> bool:
        """True when ``record_sessions`` is enabled (override wins over config)."""
        if self._enabled_override is not None:
            return self._enabled_override
        config_path = self._root / ".cerebrofy" / "config.yaml"
        try:
            mtime = config_path.stat().st_mtime
        except OSError:
            return False
        if self._enabled_cache is not None and self._enabled_cache[0] == mtime:
            return self._enabled_cache[1]
        try:
            from cerebrofy.config.loader import load_config

            enabled = bool(load_config(config_path).record_sessions)
        except Exception:
            enabled = False
        self._enabled_cache = (mtime, enabled)
        return enabled

    # ── connections ──────────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection | None:
        """Open/cached sessions.db connection, or None when unavailable."""
        if self._sessions_conn is not None:
            return self._sessions_conn
        try:
            if self._sessions_conn_factory is not None:
                conn = self._sessions_conn_factory()
            else:
                conn = open_sessions_db(self._root / ".cerebrofy")
                conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            return None
        self._sessions_conn = conn
        return conn

    def _index(self) -> sqlite3.Connection | None:
        """Open/cached read-only cerebrofy.db connection; reopens after a rebuild."""
        db_path = self._root / ".cerebrofy" / "db" / "cerebrofy.db"
        conn = None
        try:
            stat = db_path.stat()
            fingerprint = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            self._index_conn = None
            self._index_fingerprint = None
            return None
        if self._index_conn is not None and self._index_fingerprint == fingerprint:
            return self._index_conn
        self._close_index()
        try:
            if self._index_conn_factory is not None:
                conn = self._index_conn_factory()
            else:
                conn = sqlite3.connect(
                    f"file:{db_path}?mode=ro", uri=True, check_same_thread=False
                )
        except sqlite3.Error:
            return None
        self._index_conn = conn
        self._index_fingerprint = fingerprint
        return conn

    def _close_index(self) -> None:
        if self._index_conn is not None:
            try:
                self._index_conn.close()
            except sqlite3.Error:
                pass
            self._index_conn = None

    def close(self) -> None:
        """Close cached connections (tests / server shutdown)."""
        self._close_index()
        if self._sessions_conn is not None:
            try:
                self._sessions_conn.close()
            except sqlite3.Error:
                pass
            self._sessions_conn = None

    # ── recording ────────────────────────────────────────────────────────
    def current_session(self) -> SessionRecord | None:
        """Return the active session, or None when not recording / no session."""
        if not self.is_recording():
            return None
        conn = self._connect()
        if conn is None:
            return None
        try:
            return active_session(conn)
        except sqlite3.Error:
            return None

    def record(
        self,
        tool: str,
        arguments: Mapping[str, Any] | None = None,
        result: object | None = None,
    ) -> None:
        """Record one tool call. Never raises — recording must not break tools."""
        try:
            if tool in _SKIP_TOOLS:
                return
            session = self.current_session()
            if session is None:
                return
            conn = self._connect()
            if conn is None:
                return
            # Use lock for thread-safe session-db updates (race condition fix)
            with self._sessions_lock:
                record_event(
                    conn,
                    session.id,
                    tool=tool,
                    args=arguments or {},
                    result_summary=summarize_result(result),
                    index_conn=self._index(),
                )
        except Exception:
            return


