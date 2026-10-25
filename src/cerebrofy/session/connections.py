"""Connection handles for :class:`SessionMiddleware` (Idea #11).

Extracted from ``middleware.py`` (m9 maintainability split): these small handles
own the cached sqlite3 connections, their per-root keys, and the connection
lock.  The middleware delegates to them so connection lifecycle is separated
from recording logic.

``check_same_thread=False`` semantics are preserved for the default
connections (the MCP middleware may touch sessions.db from an SDK worker thread).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path

# Re-exported logger name preserved for caplog-based tests.
_logger = logging.getLogger("cerebrofy.session.recorder")


class SessionsHandle:
    """Owns the cached sessions.db connection for a given root.

    ``get()`` opens (or returns the cached) ``sessions.db`` connection.  The
    connection is opened lazily so a missing / unreadable database does not
    break tool calls — ``get()`` returns ``None`` on failure instead of raising.

    Injection points (for testing):
    * ``conn_factory`` — a callable returning a pre-configured connection (or
      ``None``).  Takes precedence over the default opener.
    * ``open_fn`` — a custom ``sessions_db`` opener with the same signature as
      :func:`cerebrofy.session.recorder.open_sessions_db`.
    """

    def __init__(
        self,
        root: Path,
        *,
        conn_factory: Callable[[], sqlite3.Connection | None] | None = None,
        open_fn: Callable[[Path], sqlite3.Connection] | None = None,
    ) -> None:
        self._root = root
        self._conn_factory = conn_factory
        self._open_fn = open_fn
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def get(self) -> sqlite3.Connection | None:
        """Return the cached sessions.db connection, opening it if needed."""
        if self._conn is not None:
            return self._conn
        with self._lock:
            if self._conn is not None:
                return self._conn
            conn: sqlite3.Connection | None = None
            try:
                if self._conn_factory is not None:
                    conn = self._conn_factory()
                elif self._open_fn is not None:
                    conn = self._open_fn(self._root / ".cerebrofy")
                else:
                    # Lazy import: preserved so tests that patch
                    # ``cerebrofy.session.recorder.open_sessions_db`` still take
                    # effect.  A module-level import would bind the name at
                    # import time and defeat that patching.
                    from cerebrofy.session.recorder import open_sessions_db

                    conn = open_sessions_db(self._root / ".cerebrofy")
                    conn.execute("PRAGMA synchronous=NORMAL")
            except Exception as exc:  # noqa: BLE001
                return None
            self._conn = conn
            return conn

    def close(self) -> None:
        """Close the cached connection (tests / server shutdown)."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
                self._conn = None


class IndexHandle:
    """Owns the cached read-only ``cerebrofy.db`` connection for a given root.

    The connection is reopened when the on-disk file's fingerprint
    (``st_mtime_ns``, ``st_size``) changes — i.e. after a ``cerebrofy build`` /
    ``cerebrofy update`` rebuild.  ``check_same_thread=False`` is preserved for
    the default opener to match the MCP middleware's worker-thread usage.

    Injection point (for testing):
    * ``conn_factory`` — a callable returning a pre-configured connection (or
      ``None``).  Takes precedence over the default opener.
    """

    def __init__(
        self,
        root: Path,
        *,
        conn_factory: Callable[[], sqlite3.Connection | None] | None = None,
    ) -> None:
        self._root = root
        self._conn_factory = conn_factory
        self._conn: sqlite3.Connection | None = None
        self._fingerprint: tuple[int, int] | None = None

    @property
    def _db_path(self) -> Path:
        return self._root / ".cerebrofy" / "db" / "cerebrofy.db"

    def get(self) -> sqlite3.Connection | None:
        """Return the cached index connection, reopening if the file changed."""
        db_path = self._db_path
        try:
            stat = db_path.stat()
            fingerprint = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            self._reset()
            return None
        if self._conn is not None and self._fingerprint == fingerprint:
            return self._conn
        self._reset()
        conn: sqlite3.Connection | None = None
        try:
            if self._conn_factory is not None:
                conn = self._conn_factory()
            else:
                conn = sqlite3.connect(
                    f"file:{db_path}?mode=ro", uri=True, check_same_thread=False
                )
        except sqlite3.Error:
            return None
        self._conn = conn
        self._fingerprint = fingerprint
        return conn

    def _reset(self) -> None:
        """Close the cached connection and clear the fingerprint."""
        if self._conn is not None:
            try:
                self._conn.close()
            except sqlite3.Error:
                pass
            self._conn = None
        self._fingerprint = None

    def close(self) -> None:
        """Close the cached connection (tests / server shutdown)."""
        self._reset()
