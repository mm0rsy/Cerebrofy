# Cerebrofy DB — Schema & Transaction Model

This document describes the **transaction model** for `cerebrofy.db`
(`.cerebrofy/db/cerebrofy.db`). The schema itself — tables, indexes, virtual
tables, and DDL — lives in `src/cerebrofy/db/schema.py` and is created by
`create_schema()`. This file does **not** redefine the schema; it documents the
write-serialization contract that all writers must follow and the shape of the
coordination registry (`active_agents`).

## Connections

* `open_db(path)` — opens `cerebrofy.db` for read/write (used by the CLI and
  `cerebrofy build`/`update`), loads the `sqlite-vec` extension, and enables
  **WAL** journal mode. Does **not** check the schema version — callers must
  call `check_schema_version(conn)` first.
* `open_db_readonly(path)` — opens the index in read-only mode
  (`?mode=ro` URI) for concurrent searchers (hybrid search, MCP tools). Safe
  to run alongside builders/updaters.
* The session middleware opens `sessions.db` / `memories.db` connections with
  `check_same_thread=False` so a single `sqlite3.Connection` can be shared
  across threads. **`check_same_thread=False` only disables the thread-affinity
  guard in the Python `sqlite3` driver; it does NOT make writes safe.** Every
  multi-statement writer on a shared connection must still go through
  `write_transaction`.

## Coordination registry (`active_agents`)

Multi-agent coordination (Idea #25) stores its registry in `cerebrofy.db` as the
`active_agents` table. The DDL lives in `db/schema.py::ACTIVE_AGENTS_DDL` and is
also applied by `migrations/007_coordination.sql`; the registry is created
idempotently by `coordination/registry.py`.

| Column | Type | Notes |
|--------|------|-------|
| `agent_id` | TEXT | Primary key. Unique agent instance. |
| `agent_type` | TEXT | NOT NULL. `claude`, `cursor`, `devin`, `human`, `ci`. |
| `session_id` | TEXT | Nullable Idea #11 session id. **Not a foreign key yet** — adding the constraint is an Idea #11 TODO. |
| `intent` | TEXT | Natural-language description of the planned work. |
| `claimed_neurons` | TEXT | NOT NULL JSON array, default `'[]'`. |
| `started_ts` | INTEGER | NOT NULL unix timestamp when the agent registered. |
| `last_heartbeat` | INTEGER | NOT NULL unix timestamp of the last heartbeat. |
| `status` | TEXT | `active` (default) or `completed`. |
| `ttl_minutes` | INTEGER | NOT NULL, default `60`, valid range `1..1440`. |
| `expires_ts` | INTEGER | Nullable TTL deadline; refreshed by a heartbeat. |
| `created_ts` | INTEGER | NOT NULL row creation timestamp. |

Indexes: `idx_active_agents_status` (`status`) and
`idx_active_agents_heartbeat` (`last_heartbeat`). There is no index on
`claimed_neurons`.

**Read/write split.** `cerebrofy_who`, `cerebrofy_conflicts`, and the optional
MCP conflict/heartbeat hooks open the registry **read-only** and never create
`cerebrofy.db`; a missing index yields `NO_INDEX` (or no notice) instead of a new
database. Only explicit `claim` / `release` / `heartbeat` mutations write, and
every one of them goes through `write_transaction` (`BEGIN IMMEDIATE`) in
`coordination/registry.py`.

**Ephemeral by design.** `active_agents` lives in `cerebrofy.db`, which
`cerebrofy build` recreates atomically. A full rebuild discards every claim and
registration, so agents must re-claim afterwards. Durable knowledge remains in
`memories.db`, which is not rebuilt.

## Write serialization contract

> **`write_transaction(conn)` is the single required entry point for any
> multi-statement write that must be atomic.**

It is defined in `src/cerebrofy/db/connection.py` and is used by:

* `commands.update._run_update_transaction` — the partial-reindex DML.
* `commands.build.build_step5_commit` — the final file-hash + build-meta commit.

The contract:

1. **Process-wide writer lock.** A module-level `threading.RLock`
   (`_WRITE_LOCK`) serializes all in-process writers. Only one
   `write_transaction` is ever active at a time.
2. **Reads are lock-free.** `SELECT` queries (including the depth-2 BFS in the
   scope resolver, hybrid search, and MCP reads) never touch `_WRITE_LOCK`.
   WAL mode allows concurrent readers while a writer holds the reserved lock.
3. **Nesting is rejected.** `write_transaction` acquires the process-wide
   writer lock first, then raises
   `RuntimeError("write_transaction cannot be nested")` when
   `conn.in_transaction` is already `True`. Checking after acquiring the lock
   makes a concurrent second writer serialize and fail with that explicit
   error, rather than racing the check and hitting SQLite's generic
   "cannot start a transaction within a transaction".
4. **`BEGIN IMMEDIATE` is required.** The helper issues `BEGIN IMMEDIATE`
   (acquires a SQLite reserved lock up-front) rather than the default deferred
   begin, avoiding late `database is locked` errors and ensuring the writer
   fails fast if another process holds the write lock.
5. **Atomicity.** `commit()` on clean exit; `rollback()` on any exception from
   the `with` body, then the exception is re-raised. The `_WRITE_LOCK` is always
   released (via the `with _WRITE_LOCK` block), even on exception.
6. **No `executescript` for atomic DDL.** Schema creation lives in
   `cerebrofy.db.schema` (`create_schema`, `create_session_schema`,
   `create_memory_schema`). Each runs all DDL in a single `BEGIN IMMEDIATE …
   COMMIT` using `conn.execute` per statement (never `executescript`, which
   would issue an implicit `COMMIT` and break the single-transaction
   atomicity). `write_transaction` is intentionally **not** used for schema
   creation because the schema functions manage their own single-transaction
   DDL lifecycle and must not be interleaved with data writes.

## Embedding-before-lock contract

For `cerebrofy update`, embedding generation is a potentially slow, blocking
call. It is performed **before** entering `write_transaction`, so the
SQLite write lock (and `_WRITE_LOCK`) is never held during model inference.
`_run_update_transaction` only receives pre-computed `new_vectors` and merely
upserts them.

## Scope of this contract

The files in scope for this contract are:

* `src/cerebrofy/db/connection.py` — `open_db`, `open_db_readonly`,
  `check_schema_version`, `write_transaction`.
* `src/cerebrofy/db/writer.py` — row-level writers invoked *inside* a
  `write_transaction`.
* `src/cerebrofy/commands/build.py` — `build_step5_commit`.
* `src/cerebrofy/commands/update.py` — `_run_update_transaction`.

Out of scope (single-writer or non-index DBs, not migrated here):
`commands/migrate.py` (schema migration runner), `src/cerebrofy/analysis/`,
`src/cerebrofy/arch/`, `src/cerebrofy/changelog/`, `src/cerebrofy/skill/`,
and the `memories.db` / `sessions.db` / audit-trail writers, each of which has
its own connection and transaction boundaries.

## Health snapshots and narrative history

`health_snapshots` carries a `lobe_count` column (the number of configured
lobes at build time), used by the Narrative Engine (#26) to detect era
boundaries. `ensure_health_schema()` creates the column on fresh databases and
adds it in place (`ALTER TABLE ... ADD COLUMN`) on older ones, so existing
indexes upgrade lazily on the next health write. Both `cerebrofy build` and
`cerebrofy update` populate it via `record_snapshot(..., lobe_count=...)`.

Rows in `health_snapshots` and `narrative_events` are **durable history**, not
rebuildable index state. Although `cerebrofy build` creates a fresh database
and swaps it in with `os.replace`, `commands/build.py::_preserve_history` copies
both tables from the old database into the new one (`INSERT OR REPLACE`, with a
missing old DB or missing tables ignored) before the swap. This keeps health
trends, era detection, and changelog narrative events intact across full
rebuilds; `cerebrofy update` accumulates them in place as before. Only the
index-derived tables (`nodes`, `edges`, `vec_neurons`, `file_hashes`, `meta`,
`active_agents`) are recreated from scratch.
