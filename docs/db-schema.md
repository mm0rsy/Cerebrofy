# Cerebrofy DB — Schema & Transaction Model

This document describes the **transaction model** for `cerebrofy.db`
(`.cerebrofy/db/cerebrofy.db`). The schema itself — tables, indexes, virtual
tables, and DDL — lives in `src/cerebrofy/db/schema.py` and is created by
`create_schema()`. This file does **not** redefine the schema; it documents the
write-serialization contract that all writers must follow.

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
3. **Nesting is rejected.** If `conn.in_transaction` is already `True` when a
   `write_transaction` is entered, it raises
   `RuntimeError("write_transaction cannot be nested")` *before* acquiring the
   lock. This prevents a second transaction from being started on a connection
   that is already mid-transaction.
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
