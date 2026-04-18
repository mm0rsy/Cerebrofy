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


def create_schema(conn: sqlite3.Connection, embed_dim: int) -> None:
    """Execute all DDL statements to create the cerebrofy.db schema."""
    conn.executescript(NODES_DDL)
    conn.executescript(NODES_INDEX_DDL)
    conn.executescript(EDGES_DDL)
    conn.executescript(EDGES_INDEX_DDL)
    conn.executescript(META_DDL)
    conn.executescript(FILE_HASHES_DDL)
    if embed_dim > 0:
        vec_neurons_ddl = (
            f"CREATE VIRTUAL TABLE vec_neurons USING vec0("
            f"id TEXT PRIMARY KEY, embedding FLOAT[{embed_dim}])"
        )
        conn.execute(vec_neurons_ddl)
