"""Thin MCP session-recording middleware (Idea #11).

Wired into ``mcp/server.py``'s tool dispatcher: every tool call is offered to
``SessionMiddleware.record()``, which records it when *and only when* opt-in
recording is enabled (``record_sessions: true``) and a session is currently
active.  All recording logic lives in :mod:`cerebrofy.session.recorder` — this
module only owns connection caching (via :class:`SessionsHandle` /
:class:`IndexHandle`), thread-safe session-db updates, and the never-raises
contract, so a recording failure can never break a tool call.

Per-request ``SessionMiddleware`` instances are created by the caller (the MCP
server) rather than via a shared singleton, avoiding global-state and
thread-safety issues.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from cerebrofy.session.connections import IndexHandle, SessionsHandle
from cerebrofy.session.recorder import (
    MAX_REFS_PER_EVENT,
    MAX_TRACKED_NEURONS,
    SessionRecord,
    active_session,
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
    so there is one resolution code-path across the whole project.  When a root
    has been explicitly bound by the MCP server (``set_bound_root``) it is
    returned immediately, ignoring *start* — this is what prevents a
    manipulated CWD from redirecting session recording at another project.

    If *root_boundary* is provided, the walk stops at that directory (useful for
    preventing cross-project access in multi-project environments).
    """
    return _find_repo_root_impl(start, boundary=root_boundary)


def summarize_result(result: object) -> str | None:
    """Extract a short text sample from an MCP tool result (list of TextContent)."""
    if isinstance(result, list) and result:
        first = result[0]
        text = getattr(first, "text", None)
        if isinstance(text, str) and text:
            return text[:_MAX_RESULT_SAMPLE_CHARS]
    return None


def _config_cache_key(path: Path) -> tuple[int, int]:
    """Compute a config-cache invalidation fingerprint for *path*.

    Uses ``(st_mtime_ns, st_size)`` instead of the legacy ``st_mtime`` float:
    ``st_mtime`` is a lossy float and on some filesystems a content-preserving
    edit may leave it unchanged while ``st_size`` catches the difference.
    The index handle already used ``(st_mtime_ns, st_size)``; this brings the
    enabled/config cache to the same precision.
    """
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)


class SessionMiddleware:
    """Records dispatched MCP tool calls into the active session, best effort.

    Holds cached connections (via :class:`SessionsHandle` / :class:`IndexHandle`)
    so the per-call cost is one indexed INSERT plus (for the first reference to
    each neuron) one depth-2 blast-radius lookup.

    Connections can be injected via factories for testing; when omitted, the
    middleware opens its own connections as before.
    """

    def __init__(
        self,
        root: Path,
        *,
        enabled: bool | None = None,
        config_loader: Callable[[Path], Any] | None = None,
        sessions_conn_factory: Callable[[], sqlite3.Connection | None] | None = None,
        index_conn_factory: Callable[[], sqlite3.Connection | None] | None = None,
    ) -> None:
        self._root = root
        self._enabled_override = enabled
        self._config_loader = config_loader
        # Cache: (fingerprint, config_or_None).  fingerprint is (st_mtime_ns, st_size).
        self._config_cache: tuple[tuple[int, int], Any | None] | None = None
        self._sessions_handle = SessionsHandle(
            root,
            conn_factory=sessions_conn_factory,
        )
        self._index_handle = IndexHandle(
            root,
            conn_factory=index_conn_factory,
        )
        # Serializes *all* access to the cached sessions.db connection.
        # check_same_thread=False only lifts sqlite3's own thread check; it does
        # not make concurrent reads/writes on one connection safe.  Readers that
        # open, read, or write must run under this lock.  It is re-entrant so
        # ``record()`` can hold it across ``current_session()``.
        self._sessions_lock = threading.RLock()

    @property
    def root(self) -> Path:
        return self._root

    # ── config resolution ───────────────────────────────────────────────────

    def _load_config(self, config_path: Path) -> Any | None:
        """Load config via the injected loader or the default ``load_config``.

        When ``config_loader`` is ``None`` the default ``cerebrofy.config.loader.load_config``
        is imported lazily at call time — this preserves test patchability
        (tests ``patch("cerebrofy.config.loader.load_config")``) and avoids
        loading the config module at middleware import time.
        """
        try:
            if self._config_loader is not None:
                return self._config_loader(config_path)
            # Lazy import preserves test patchability and avoids pulling in
            # the config module (yaml, etc.) at middleware import time.
            from cerebrofy.config.loader import load_config

            return load_config(config_path)
        except Exception:  # noqa: BLE001
            return None

    def _get_config(self) -> Any | None:
        """Return the cached config for this root, or ``None`` when unavailable.

        The cache is invalidated when the config file's ``(st_mtime_ns, st_size)``
        fingerprint changes (m10).
        """
        config_path = self._root / ".cerebrofy" / "config.yaml"
        try:
            fingerprint = _config_cache_key(config_path)
        except OSError:
            self._config_cache = None
            return None
        if self._config_cache is not None and self._config_cache[0] == fingerprint:
            return self._config_cache[1]
        config = self._load_config(config_path)
        self._config_cache = (fingerprint, config)
        return config

    # ── opt-in resolution ───────────────────────────────────────────────────

    def is_recording(self) -> bool:
        """True when ``record_sessions`` is enabled (override wins over config)."""
        if self._enabled_override is not None:
            return self._enabled_override
        config = self._get_config()
        if config is None:
            return False
        return bool(config.record_sessions)

    # ── connections (delegated to handles) ──────────────────────────────────

    def _connect(self) -> sqlite3.Connection | None:
        """Return the cached sessions.db connection, or ``None`` when unavailable."""
        return self._sessions_handle.get()

    def _index(self) -> sqlite3.Connection | None:
        """Return the cached read-only cerebrofy.db connection; reopens after a rebuild."""
        return self._index_handle.get()

    def _close_index(self) -> None:
        self._index_handle._reset()

    def close(self) -> None:
        """Close cached connections (tests / server shutdown)."""
        self._sessions_handle.close()
        self._index_handle.close()

    # ── recording ───────────────────────────────────────────────────────────

    def current_session(self) -> SessionRecord | None:
        """Return the active session, or None when not recording / no session."""
        if not self.is_recording():
            return None
        with self._sessions_lock:
            conn = self._connect()
            if conn is None:
                return None
            try:
                return active_session(conn)
            except sqlite3.Error:
                return None

    def _recording_caps(self) -> tuple[int, int]:
        """Return ``(max_tracked_neurons, max_refs_per_event)`` from config.

        Falls back to the module-level defaults when config is unavailable or
        the session section is absent — recording must never be skipped merely
        because a cap couldn't be read.
        """
        config = self._get_config()
        session_cfg = getattr(config, "session", None) if config else None
        max_tracked = getattr(session_cfg, "max_tracked_neurons", MAX_TRACKED_NEURONS)
        max_refs = getattr(session_cfg, "max_refs_per_event", MAX_REFS_PER_EVENT)
        return max_tracked, max_refs

    def record(
        self,
        tool: str,
        arguments: Mapping[str, Any] | None = None,
        result: object | None = None,
    ) -> None:
        """Record one tool call.  Never raises — recording must not break tools."""
        try:
            if tool in _SKIP_TOOLS:
                return
            max_tracked_neurons, max_refs_per_event = self._recording_caps()
            # Hold the lock across the active-session read *and* the write: the
            # cached sessions.db connection is shared across worker threads, and
            # a read that interleaves with another thread's in-flight write can
            # see no row or a partially updated one.  ``current_session()``
            # re-enters the lock, which is why it is an RLock.
            with self._sessions_lock:
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
                    max_tracked_neurons=max_tracked_neurons,
                    max_refs_per_event=max_refs_per_event,
                )
        except Exception:  # noqa: BLE001
            return
