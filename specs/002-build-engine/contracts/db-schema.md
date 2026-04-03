# Contract: `cerebrofy.db` Schema

**Feature**: 002-build-engine
**Date**: 2026-04-03
**Stability**: Draft — consumed by Phase 3 (`cerebrofy update`, `cerebrofy validate`) and
Phase 4 (`cerebrofy specify`, `cerebrofy plan`, `cerebrofy tasks`)

---

## Overview

`cerebrofy.db` is the single SQLite file created exclusively by `cerebrofy build`. It contains:
- **Graph layer**: `nodes`, `edges`, `meta`, `file_hashes` tables
- **Vector layer**: `vec_neurons` virtual table (sqlite-vec `USING vec0`)

The schema version is `1`. All future phases that open `cerebrofy.db` MUST check
`SELECT value FROM meta WHERE key = 'schema_version'` before any read or write.

---

## Full DDL (Schema Version 1)

```sql
-- ─────────────────────────────────────────────
-- Graph Layer
-- ─────────────────────────────────────────────

CREATE TABLE nodes (
  id          TEXT PRIMARY KEY,   -- "{relative_file_path}::{name}"
  name        TEXT NOT NULL,
  file        TEXT NOT NULL,      -- relative path, forward slashes, no leading "./"
  type        TEXT,               -- "function" | "class" | "module"
  line_start  INTEGER,            -- 1-based, inclusive
  line_end    INTEGER,            -- 1-based, inclusive
  signature   TEXT,               -- NULL when type != "function"
  docstring   TEXT,               -- NULL if no docstring present
  hash        TEXT                -- SHA-256 of source lines line_start..line_end
);

CREATE INDEX idx_nodes_file ON nodes(file);
CREATE INDEX idx_nodes_name ON nodes(name);

CREATE TABLE edges (
  src_id    TEXT REFERENCES nodes(id),
  dst_id    TEXT,                 -- may reference a synthetic "external" id for RUNTIME_BOUNDARY
  rel_type  TEXT NOT NULL,        -- "LOCAL_CALL" | "EXTERNAL_CALL" | "IMPORT" | "RUNTIME_BOUNDARY"
  file      TEXT,                 -- source file where the call expression appears
  PRIMARY KEY (src_id, dst_id, rel_type)
);

CREATE INDEX idx_edges_src ON edges(src_id);
CREATE INDEX idx_edges_dst ON edges(dst_id);

CREATE TABLE meta (
  key    TEXT PRIMARY KEY,
  value  TEXT
);
-- Required meta rows inserted by cerebrofy build Step 0 / Step 6:
--   INSERT INTO meta VALUES ('schema_version', '1');
--   INSERT INTO meta VALUES ('embed_model', <value from config.yaml>);
--   INSERT INTO meta VALUES ('embed_dim', <value from config.yaml>);
--   (state_hash, last_build inserted at Step 6 commit)

CREATE TABLE file_hashes (
  file  TEXT PRIMARY KEY,   -- relative path from repo root (forward slashes)
  hash  TEXT NOT NULL       -- SHA-256 of file content at last build/update
);

-- ─────────────────────────────────────────────
-- Vector Layer (sqlite-vec extension required)
-- ─────────────────────────────────────────────

-- IMPORTANT: {embed_dim} is NOT hardcoded.
-- cerebrofy build reads embed_dim from config.yaml and generates this statement dynamically.
-- Example for local model (768-dim):
--   CREATE VIRTUAL TABLE vec_neurons USING vec0(
--     id TEXT PRIMARY KEY, embedding FLOAT[768])
--
-- Changing embedding_model in config.yaml and running cerebrofy build drops and recreates
-- this table at the new dimension. No manual migration needed.

CREATE VIRTUAL TABLE vec_neurons USING vec0(
  id         TEXT PRIMARY KEY,     -- same "{file}::{name}" as nodes.id
  embedding  FLOAT[{embed_dim}]    -- dimension resolved from config at build time
);
```

---

## Invariants

The following invariants MUST hold for every `cerebrofy.db` produced by `cerebrofy build`:

1. Every row in `vec_neurons` has a corresponding row in `nodes` with the same `id`.
2. Every row in `nodes` has a corresponding row in `vec_neurons` with the same `id`.
3. `nodes.id = nodes.file || '::' || nodes.name` for all rows.
4. `nodes.line_end >= nodes.line_start >= 1` for all rows.
5. `nodes.type` is exactly one of `"function"`, `"class"`, `"module"` for all rows.
6. `nodes.signature IS NULL` for all rows where `nodes.type != 'function'`.
7. For every tracked file at build time: exactly one row in `file_hashes` with that file's path.
8. `meta` contains rows for all five required keys: `state_hash`, `last_build`,
   `schema_version`, `embed_model`, `embed_dim`.
9. `meta.schema_version = '1'` for all databases produced by this phase.
10. No two rows in `nodes` share the same `id` (enforced by PRIMARY KEY).
11. No two rows in `edges` share the same `(src_id, dst_id, rel_type)` triple (enforced by PK).
12. `RUNTIME_BOUNDARY` edges in `edges` are NEVER traversed during Blast Radius BFS (Phase 3).

---

## State Hash Formula

```
state_hash = SHA-256(
    "\n".join(sorted([
        SHA-256(content_bytes_of_file).hexdigest()
        for each tracked file (in tracking order)
    ]))
).hexdigest()
```

- "tracked file" = file whose extension is in `tracked_extensions` AND not matched by any
  ignore rule (`.cerebrofy-ignore` or `.gitignore`).
- All SHA-256 values are lowercase hex strings (64 chars).
- Sorting is lexicographic on the per-file SHA-256 hex strings.
- The outer SHA-256 is computed on the newline-joined sorted list as UTF-8 bytes.

This formula is deterministic: the same file contents always produce the same `state_hash`
regardless of filesystem order or OS.

---

## Connection Open Sequence

Every Cerebrofy command that opens `cerebrofy.db` MUST follow this sequence:

```python
import sqlite3
import sqlite_vec

conn = sqlite3.connect(db_path)
conn.enable_load_extension(True)
sqlite_vec.load(conn)
conn.enable_load_extension(False)  # disable after loading for safety

# Version check (MUST be first read after open):
row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
if row is None or int(row[0]) != EXPECTED_SCHEMA_VERSION:
    raise SchemaMismatchError(f"Expected schema v{EXPECTED_SCHEMA_VERSION}, got {row}")
```

If `schema_version` does not match, `cerebrofy migrate` must be run before any other operation.
No write may occur without a successful version check.

---

## Hybrid Search Pattern (Phase 4 Reference)

The canonical hybrid KNN + BFS search used by Phase 4 commands:

```sql
-- Step 1: KNN semantic search (top_k from config)
SELECT n.id, n.name, n.file,
       vec_distance_cosine(v.embedding, ?) AS dist
FROM   vec_neurons v
JOIN   nodes n ON n.id = v.id
ORDER  BY dist
LIMIT  ?;

-- Step 2: BFS Blast Radius from each matched id (see Blueprint Section VI)
-- Traverses LOCAL_CALL and EXTERNAL_CALL edges only; skips RUNTIME_BOUNDARY.
SELECT src_id, dst_id FROM edges
WHERE  (src_id = ? OR dst_id = ?)
AND    rel_type != 'RUNTIME_BOUNDARY';
```

Both queries run in the same `conn` object — zero IPC, zero network.
