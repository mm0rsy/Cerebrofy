"""Thin MCP session-recording middleware (Idea #11).

Wired into ``mcp/server.py``'s tool dispatcher: every tool call is offered to
:func:`record_tool_call`, which records it when *and only when* opt-in recording
is enabled (``record_sessions: true``) and a session is currently active. All
recording logic lives in :mod:`cerebrofy.session.recorder` — this module only
owns connection caching and the never-raises contract, so a recording failure
can never break a tool call.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from cerebrofy.session.recorder import (
    SessionRecord,
    active_session,
    open_sessions_db,
    record_event,
)

# The session-management tools are never recorded themselves: session_start
# creates the session, session_end closes it, and recording either inside the
# same session would break replay boundaries.
_SKIP_TOOLS: frozenset[str] = frozenset(
    {"cerebrofy_session_start", "cerebrofy_session_end", "cerebrofy_session_show"}
)

_MAX_RESULT_SAMPLE_CHARS = 1000


def find_repo_root(start: Path) -> Path | None:
    """Walk up from *start* looking for ``.cerebrofy/config.yaml``; None if absent."""
    current = start if start.is_dir() else start.parent
    for candidate in (current, *current.parents):
        if (candidate / ".cerebrofy" / "config.yaml").exists():
            return candidate
    return None


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
    """

    def __init__(self, root: Path, *, enabled: bool | None = None) -> None:
        self._root = root
        self._enabled_override = enabled
        self._enabled_cache: tuple[float, bool] | None = None
        self._sessions_conn: sqlite3.Connection | None = None
        self._index_conn: sqlite3.Connection | None = None
        self._index_fingerprint: tuple[int, int] | None = None

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
            conn = open_sessions_db(self._root / ".cerebrofy")
            conn.execute("PRAGMA synchronous=NORMAL")
        except Exception:
            return None
        self._sessions_conn = conn
        return conn

    def _index(self) -> sqlite3.Connection | None:
        """Open/cached read-only cerebrofy.db connection; reopens after a rebuild."""
        db_path = self._root / ".cerebrofy" / "db" / "cerebrofy.db"
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


_default_middleware: SessionMiddleware | None = None


def record_tool_call(
    cwd: Path,
    *,
    tool: str,
    arguments: Mapping[str, Any] | None = None,
    result: object | None = None,
) -> None:
    """Module-level hook used by ``mcp/server.py`` (thin, never raises)."""
    global _default_middleware
    try:
        root = find_repo_root(cwd)
        if root is None:
            return
        if _default_middleware is None or _default_middleware.root != root:
            if _default_middleware is not None:
                _default_middleware.close()
            _default_middleware = SessionMiddleware(root)
        _default_middleware.record(tool, arguments, result)
    except Exception:
        return


def reset_default_middleware() -> None:
    """Drop the cached middleware (tests)."""
    global _default_middleware
    if _default_middleware is not None:
        _default_middleware.close()
        _default_middleware = None
