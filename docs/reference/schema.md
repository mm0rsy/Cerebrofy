# Database Schema & Transaction Model

This document describes the **transaction model** for `cerebrofy.db` (`.cerebrofy/db/cerebrofy.db`). The schema itself — tables, indexes, virtual tables, and DDL — lives in `src/cerebrofy/db/schema.py` and is created by `create_schema()`. This file documents the write-serialization contract that all writers must follow and the shape of the coordination registry (`active_agents`).

## Core Tables

### `nodes`

Named code units (functions, classes, modules).

| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PRIMARY KEY | `"{file}::{name}"` — globally unique |
| `name` | TEXT NOT NULL | Function/class/module name |
| `file` | TEXT NOT NULL | Path relative to repo root |
| `type` | TEXT | `"function" \| "class" \| "module"` |
| `line_start` | INTEGER | 1-based |
| `line_end` | INTEGER | 1-based, inclusive |
| `signature` | TEXT | — |
| `docstring` | TEXT | — |
| `hash` | TEXT | SHA-256 of the source span |

Indexes: `idx_nodes_file` (`file`), `idx_nodes_name` (`name`).

### `edges`

Typed call/import edges between Neurons.

| Column | Type | Notes |
|--------|------|-------|
| `src_id` | TEXT REFERENCES nodes(id) | Source neuron |
| `dst_id` | TEXT | Destination neuron |
| `rel_type` | TEXT NOT NULL | `LOCAL_CALL` \| `EXTERNAL_CALL` \| `IMPORT` \| `RUNTIME_BOUNDARY` |
| `file` | TEXT | — |

Primary key: `(src_id, dst_id, rel_type)`. Indexes: `idx_edges_src` (`src_id`), `idx_edges_dst` (`dst_id`).

### `meta`

Key-value metadata. Keys: `schema_version`, `embed_model`, `embed_dim`, `state_hash`, `last_build`.

| Column | Type | Notes |
|--------|------|-------|
| `key` | TEXT PRIMARY KEY | — |
| `value` | TEXT | — |

### `file_hashes`

Per-file content hashes for drift detection.

| Column | Type | Notes |
|--------|------|-------|
| `file` | TEXT PRIMARY KEY | — |
| `hash` | TEXT NOT NULL | SHA-256 of file content at last build/update |

### `vec_neurons`

sqlite-vec virtual table for KNN search (384-dim for BAAI/bge-small-en-v1.5).

```sql
CREATE VIRTUAL TABLE vec_neurons USING vec0(
  id          TEXT PRIMARY KEY,
  embedding   FLOAT[384]
);
```

Every `nodes` row has a corresponding `vec_neurons` row after a completed build (Law III). The `vec_neurons` table cannot be updated in-place — `cerebrofy update` always DELETE+INSERT within the same transaction.

## Coordination Registry (`active_agents`)

Multi-agent coordination (Idea #25) stores its registry in `cerebrofy.db` as the `active_agents` table. The DDL lives in `db/schema.py::ACTIVE_AGENTS_DDL` and is also applied by `migrations/007_coordination.sql`; the registry is created idempotently by `coordination/registry.py`.

| Column | Type | Notes |
|--------|------|-------|
| `agent_id` | TEXT PRIMARY KEY | Unique agent instance |
| `agent_type` | TEXT NOT NULL | `claude`, `cursor`, `devin`, `human`, `ci` |
| `session_id` | TEXT | Nullable Idea #11 session id. **Not a foreign key yet** — adding the constraint is an Idea #11 TODO. |
| `intent` | TEXT | Natural-language description of the planned work |
| `claimed_neurons` | TEXT | NOT NULL JSON array, default `'[]'` |
| `started_ts` | INTEGER NOT NULL | Unix timestamp when the agent registered |
| `last_heartbeat` | INTEGER NOT NULL | Unix timestamp of the last heartbeat |
| `status` | TEXT | `active` (default) or `completed` |
| `ttl_minutes` | INTEGER NOT NULL | Default `60`, valid range `1..1440` |
| `expires_ts` | INTEGER | Nullable TTL deadline; refreshed by a heartbeat |
| `created_ts` | INTEGER NOT NULL | Row creation timestamp |

Indexes: `idx_active_agents_status` (`status`) and `idx_active_agents_heartbeat` (`last_heartbeat`). There is no index on `claimed_neurons`.

## Separate Databases

The following databases live alongside `cerebrofy.db` under `.cerebrofy/db/` and are **not** rebuilt by `cerebrofy build`:

- `memories.db` — structured memories, synthesized patterns, insights
- `sessions.db` — agent session recordings (Idea #11)

## Write Serialization Contract

> **`write_transaction(conn)` is the single required entry point for any multi-statement write that must be atomic.**

It is defined in `src/cerebrofy/db/connection.py` and is used by:
- `commands.update._run_update_transaction` — the partial-reindex DML.
- `commands.build.build_step5_commit` — the final file-hash + build-meta commit.

The contract:

1. **Process-wide writer lock.** A module-level `threading.RLock` (`_WRITE_LOCK`) serializes all in-process writers. Only one `write_transaction` is ever active at a time.
2. **Reads are lock-free.** `SELECT` queries (including the depth-2 BFS in the scope resolver, hybrid search, and MCP reads) never touch `_WRITE_LOCK`. WAL mode allows concurrent readers while a writer holds the reserved lock.
3. **Nesting is rejected.** `write_transaction` acquires the process-wide writer lock first, then raises `RuntimeError("write_transaction cannot be nested")` when `conn.in_transaction` is already `True`.
4. **`BEGIN IMMEDIATE` is required.** The helper issues `BEGIN IMMEDIATE` (acquires a SQLite reserved lock up-front) rather than the default deferred begin, avoiding late `database is locked` errors and ensuring the writer fails fast if another process holds the write lock.
5. **Atomicity.** `commit()` on clean exit; `rollback()` on any exception from the `with` body, then the exception is re-raised. The `_WRITE_LOCK` is always released (via the `with _WRITE_LOCK` block), even on exception.
6. **No `executescript` for atomic DDL.** Schema creation lives in `cerebrofy.db.schema` (`create_schema`, `create_session_schema`, `create_memory_schema`). Each runs all DDL in a single `BEGIN IMMEDIATE … COMMIT` using `conn.execute` per statement (never `executescript`, which would issue an implicit `COMMIT` and break the single-transaction atomicity). `write_transaction` is intentionally **not** used for schema creation.

## Embedding-Before-Lock Contract

For `cerebrofy update`, embedding generation is a potentially slow, blocking call. It is performed **before** entering `write_transaction`, so the SQLite write lock (and `_WRITE_LOCK`) is never held during model inference. `_run_update_transaction` only receives pre-computed `new_vectors` and merely upserts them.

## Connections

| Connection | Mode | Usage |
|------------|------|-------|
| `open_db(path)` | read/write | CLI and `cerebrofy build`/`update`; loads sqlite-vec, enables WAL |
| `open_db_readonly(path)` | `?mode=ro` | Concurrent searchers (hybrid search, MCP tools); safe alongside builders/updaters |
| `sessions.db` / `memories.db` | `check_same_thread=False` | Shared across threads; writers still go through `write_transaction` |

`check_same_thread=False` only disables the thread-affinity guard in the Python `sqlite3` driver; it does NOT make writes safe. Every multi-statement writer on a shared connection must still go through `write_transaction`.

## Health Snapshots and Narrative History

`health_snapshots` carries a `lobe_count` column (the number of configured lobes at build time), used by the [Narrative Engine](../features/narrative.md) to detect era boundaries. `ensure_health_schema()` creates the column on fresh databases and adds it in place (`ALTER TABLE ... ADD COLUMN`) on older ones, so existing indexes upgrade lazily on the next health write. Both `cerebrofy build` and `cerebrofy update` populate it via `record_snapshot(..., lobe_count=...)`.

Rows in `health_snapshots` and `narrative_events` are **durable history**, not rebuildable index state. Although `cerebrofy build` creates a fresh database and swaps it in with `os.replace`, `commands/build.py::_preserve_history` copies both tables from the old database into the new one (`INSERT OR REPLACE`, with a missing old DB or missing tables ignored) before the swap. This keeps health trends, era detection, and changelog narrative events intact across full rebuilds; `cerebrofy update` accumulates them in place as before. Only the index-derived tables (`nodes`, `edges`, `vec_neurons`, `file_hashes`, `meta`, `active_agents`) are recreated from scratch.