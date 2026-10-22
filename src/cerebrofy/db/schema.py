"""DDL constants and schema creation for cerebrofy.db (schema version 1)."""

from __future__ import annotations

import sqlite3

NODES_DDL = """
CREATE TABLE IF NOT EXISTS nodes (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  file        TEXT NOT NULL,
  type        TEXT,
  line_start  INTEGER,
  line_end    INTEGER,
  signature   TEXT,
  docstring   TEXT,
  hash        TEXT
);
"""

NODES_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
"""

EDGES_DDL = """
CREATE TABLE IF NOT EXISTS edges (
  src_id    TEXT REFERENCES nodes(id),
  dst_id    TEXT,
  rel_type  TEXT NOT NULL,
  file      TEXT,
  PRIMARY KEY (src_id, dst_id, rel_type)
);
"""

EDGES_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id);
"""

META_DDL = """
CREATE TABLE IF NOT EXISTS meta (
  key    TEXT PRIMARY KEY,
  value  TEXT
);
"""

FILE_HASHES_DDL = """
CREATE TABLE IF NOT EXISTS file_hashes (
  file  TEXT PRIMARY KEY,
  hash  TEXT NOT NULL
);
"""


HEALTH_SNAPSHOTS_DDL = """
CREATE TABLE IF NOT EXISTS health_snapshots (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  build_ts          INTEGER NOT NULL,
  commit_hash       TEXT,
  coupling          REAL,
  avg_blast         REAL,
  dead_code_pct     REAL,
  cohesion          REAL,
  test_surface      REAL,
  drift_velocity    REAL,
  hub_concentration REAL,
  neuron_count      INTEGER,
  edge_count        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_health_ts ON health_snapshots(build_ts DESC);
"""


NARRATIVE_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS narrative_events (
  id                 TEXT PRIMARY KEY,
  ts                 INTEGER NOT NULL,
  commit_ref         TEXT,
  type               TEXT,
  title              TEXT,
  body               TEXT,
  lobes_affected     TEXT,   -- JSON array
  blast_radius_delta REAL,
  health_delta       TEXT    -- JSON object
);
CREATE INDEX IF NOT EXISTS idx_narrative_ts ON narrative_events(ts DESC);
"""


#: Active-agent registry for multi-agent coordination (Idea #25).
#:
#: Coordination state is intentionally ephemeral: it lives in cerebrofy.db,
#: which is recreated by an index rebuild.  Durable knowledge belongs in
#: memories.db.  ``ttl_minutes``/``expires_ts`` back claim expiry; ``created_ts``
#: is kept for diagnostics and migration parity with 007_coordination.sql.
ACTIVE_AGENTS_DDL = """
CREATE TABLE IF NOT EXISTS active_agents (
  agent_id        TEXT PRIMARY KEY,
  agent_type      TEXT NOT NULL,
  session_id      TEXT,
  intent          TEXT,
  claimed_neurons TEXT NOT NULL DEFAULT '[]',
  started_ts      INTEGER NOT NULL,
  last_heartbeat  INTEGER NOT NULL,
  status          TEXT DEFAULT 'active',
  ttl_minutes     INTEGER NOT NULL DEFAULT 60,
  expires_ts      INTEGER,
  created_ts      INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS idx_active_agents_status ON active_agents(status);
CREATE INDEX IF NOT EXISTS idx_active_agents_heartbeat ON active_agents(last_heartbeat);
"""


def ensure_health_schema(conn: sqlite3.Connection) -> None:
    """Create health_snapshots table if it doesn't exist (idempotent, handles old DBs)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS health_snapshots (
          id                INTEGER PRIMARY KEY AUTOINCREMENT,
          build_ts          INTEGER NOT NULL,
          commit_hash       TEXT,
          coupling          REAL,
          avg_blast         REAL,
          dead_code_pct     REAL,
          cohesion          REAL,
          test_surface      REAL,
          drift_velocity    REAL,
          hub_concentration REAL,
          neuron_count      INTEGER,
          edge_count        INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_health_ts ON health_snapshots(build_ts DESC);
        """
    )


def ensure_narrative_schema(conn: sqlite3.Connection) -> None:
    """Create narrative_events table if it doesn't exist (idempotent, handles old DBs)."""
    conn.executescript(NARRATIVE_EVENTS_DDL)


def create_schema(conn: sqlite3.Connection, embed_dim: int) -> None:
    """Execute all DDL to create the cerebrofy.db schema.

    Contract — **single transaction per creation**: every statement (tables,
    indexes and the ``vec_neurons`` virtual table) runs inside one
    ``BEGIN IMMEDIATE`` … ``COMMIT`` transaction. If any statement fails the
    whole creation is rolled back, so a half-created schema is never left
    behind. All statements use ``CREATE ... IF NOT EXISTS``, so calling this
    repeatedly is idempotent.
    """
    vec_neurons_ddl = (
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_neurons USING vec0("
        f"id TEXT PRIMARY KEY, embedding FLOAT[{embed_dim}])"
    )
    conn.execute("BEGIN IMMEDIATE")
    with conn:
        _run_ddl(conn, NODES_DDL)
        _run_ddl(conn, NODES_INDEX_DDL)
        _run_ddl(conn, EDGES_DDL)
        _run_ddl(conn, EDGES_INDEX_DDL)
        _run_ddl(conn, META_DDL)
        _run_ddl(conn, FILE_HASHES_DDL)
        _run_ddl(conn, HEALTH_SNAPSHOTS_DDL)
        _run_ddl(conn, NARRATIVE_EVENTS_DDL)
        _run_ddl(conn, ACTIVE_AGENTS_DDL)
        if embed_dim > 0:
            conn.execute(vec_neurons_ddl)


def create_session_schema(conn: sqlite3.Connection) -> None:
    """Create sessions, session_events, and vec_sessions tables (idempotent).

    Applied to sessions.db on every open (fresh-create and upgrade paths are
    the same code path, mirroring create_memory_schema for memories.db).

    Like :func:`create_schema`, the whole creation runs in one
    ``BEGIN IMMEDIATE`` transaction so a failure rolls everything back rather
    than leaving a partial sessions schema; ``IF NOT EXISTS`` makes repeated
    calls idempotent.

    TODO(integration-25): sessions.id will be foreign-key-referenced by the
    active agent registry (multi-agent coordination) once that lands.
    """
    script = """
        CREATE TABLE IF NOT EXISTS sessions (
            id                   TEXT PRIMARY KEY,
            started_at           INTEGER NOT NULL,
            ended_at             INTEGER,
            agent                TEXT,
            task                 TEXT NOT NULL,
            outcome              TEXT NOT NULL DEFAULT 'unknown',
            outcome_notes        TEXT,
            neurons_touched      TEXT,
            blast_radius_before  INTEGER,
            blast_radius_after   INTEGER,
            event_count          INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
        CREATE INDEX IF NOT EXISTS idx_sessions_ended   ON sessions(ended_at);
        CREATE TABLE IF NOT EXISTS session_events (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id     TEXT NOT NULL REFERENCES sessions(id),
            ts             INTEGER NOT NULL,
            tool           TEXT NOT NULL,
            args           TEXT,
            result_summary TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_session_events_session ON session_events(session_id, id);
        """
    conn.execute("BEGIN IMMEDIATE")
    with conn:
        _run_ddl(conn, script)
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS vec_sessions "
            "USING vec0(rowid integer primary key, embedding float[384])"
        )


def create_memory_schema(conn: sqlite3.Connection) -> None:
    """Create memories, vec_memories, and memory_edges tables (idempotent).

    Single ``BEGIN IMMEDIATE`` transaction — see :func:`create_schema` for the
    atomicity/idempotency contract.
    """
    script = """
        CREATE TABLE IF NOT EXISTS memories (
            id          TEXT PRIMARY KEY,
            neuron_id   TEXT,
            lobe        TEXT,
            type        TEXT NOT NULL,
            title       TEXT NOT NULL,
            body        TEXT NOT NULL,
            author      TEXT,
            created_ts  INTEGER NOT NULL,
            tags        TEXT,
            decay_score REAL NOT NULL DEFAULT 1.0,
            status      TEXT NOT NULL DEFAULT 'active'
        );
        CREATE INDEX IF NOT EXISTS idx_memories_neuron ON memories(neuron_id);
        CREATE INDEX IF NOT EXISTS idx_memories_lobe   ON memories(lobe);
        CREATE INDEX IF NOT EXISTS idx_memories_type   ON memories(type);
        CREATE TABLE IF NOT EXISTS memory_edges (
            from_memory_id  TEXT NOT NULL REFERENCES memories(id),
            to_memory_id    TEXT NOT NULL REFERENCES memories(id),
            rel_type        TEXT NOT NULL,
            created_ts      INTEGER NOT NULL,
            author          TEXT,
            PRIMARY KEY (from_memory_id, to_memory_id, rel_type)
        );
        """
    conn.execute("BEGIN IMMEDIATE")
    with conn:
        _run_ddl(conn, script)
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories "
            "USING vec0(rowid integer primary key, embedding float[384])"
        )


def _run_ddl(conn: sqlite3.Connection, script: str) -> None:
    """Execute each statement of *script* within the surrounding transaction.

    ``conn.executescript`` is deliberately **not** used: it issues an implicit
    ``COMMIT`` first, which would break the single-transaction atomicity that
    the ``create_*_schema`` wrappers establish. Splitting on ``;`` and calling
    ``conn.execute`` per statement keeps every DDL inside the caller's
    ``BEGIN IMMEDIATE`` … ``COMMIT`` (rolled back by ``with conn`` on error).

    The DDL constants here never embed ``;`` inside string literals, so a plain
    split is safe.
    """
    for stmt in script.split(";"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
