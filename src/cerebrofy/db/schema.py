"""DDL constants and schema creation for cerebrofy.db (schema version 1)."""

from __future__ import annotations

import sqlite3

NODES_DDL = """
CREATE TABLE nodes (
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
CREATE INDEX idx_nodes_file ON nodes(file);
CREATE INDEX idx_nodes_name ON nodes(name);
"""

EDGES_DDL = """
CREATE TABLE edges (
  src_id    TEXT REFERENCES nodes(id),
  dst_id    TEXT,
  rel_type  TEXT NOT NULL,
  file      TEXT,
  PRIMARY KEY (src_id, dst_id, rel_type)
);
"""

EDGES_INDEX_DDL = """
CREATE INDEX idx_edges_src ON edges(src_id);
CREATE INDEX idx_edges_dst ON edges(dst_id);
"""

META_DDL = """
CREATE TABLE meta (
  key    TEXT PRIMARY KEY,
  value  TEXT
);
"""

FILE_HASHES_DDL = """
CREATE TABLE file_hashes (
  file  TEXT PRIMARY KEY,
  hash  TEXT NOT NULL
);
"""


HEALTH_SNAPSHOTS_DDL = """
CREATE TABLE health_snapshots (
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
CREATE INDEX idx_health_ts ON health_snapshots(build_ts DESC);
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


def create_schema(conn: sqlite3.Connection, embed_dim: int) -> None:
    """Execute all DDL statements to create the cerebrofy.db schema."""
    conn.executescript(NODES_DDL)
    conn.executescript(NODES_INDEX_DDL)
    conn.executescript(EDGES_DDL)
    conn.executescript(EDGES_INDEX_DDL)
    conn.executescript(META_DDL)
    conn.executescript(FILE_HASHES_DDL)
    conn.executescript(HEALTH_SNAPSHOTS_DDL)
    if embed_dim > 0:
        vec_neurons_ddl = (
            f"CREATE VIRTUAL TABLE vec_neurons USING vec0("
            f"id TEXT PRIMARY KEY, embedding FLOAT[{embed_dim}])"
        )
        conn.execute(vec_neurons_ddl)


def create_memory_schema(conn: sqlite3.Connection) -> None:
    """Create memories, vec_memories, and memory_edges tables (idempotent)."""
    conn.executescript("""
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
    """)
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories "
        "USING vec0(rowid integer primary key, embedding float[384])"
    )
    conn.commit()
