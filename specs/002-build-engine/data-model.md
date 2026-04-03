# Data Model: Phase 2 — The Build Engine

**Feature**: 002-build-engine
**Date**: 2026-04-03

---

## Overview

Phase 2 introduces `cerebrofy.db` — the single persistent artifact of `cerebrofy build`. All
entities below live in this one SQLite file. Entities from Phase 1 (`Neuron`, `ParseResult`,
`CerebrофyConfig`, `IgnoreRuleSet`) are unchanged; Phase 2 adds the persistence layer, graph
edges, embedding vectors, and documentation structures.

---

## SQLite Tables (Graph Layer)

### `nodes` table

Persisted representation of a Neuron from Phase 1. One row per indexed code unit.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | TEXT | PRIMARY KEY | `"{file}::{name}"` — unique across the entire index |
| `name` | TEXT | NOT NULL | Name of the code unit as declared in source |
| `file` | TEXT | NOT NULL | Relative path from repo root (forward slashes) |
| `type` | TEXT | | `"function"` \| `"class"` \| `"module"` |
| `line_start` | INTEGER | | 1-based start line (inclusive) |
| `line_end` | INTEGER | | 1-based end line (inclusive) |
| `signature` | TEXT | | Full declaration line; `NULL` for class/module types |
| `docstring` | TEXT | | First docstring/comment block; `NULL` if absent |
| `hash` | TEXT | | SHA-256 of the source span (lines `line_start`–`line_end`) |

**Invariants**:
- `id = file || '::' || name` — enforced at write time.
- `line_end >= line_start >= 1`.
- `type` is exactly one of `"function"`, `"class"`, `"module"`.
- `signature IS NULL` when `type != "function"`.

**Indexes**:
```sql
CREATE INDEX idx_nodes_file ON nodes(file);
CREATE INDEX idx_nodes_name ON nodes(name);
```

---

### `edges` table

A directed call relationship between two code units. One row per unique `(src_id, dst_id,
rel_type)` triple.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `src_id` | TEXT | REFERENCES nodes(id) | ID of the calling code unit |
| `dst_id` | TEXT | REFERENCES nodes(id) | ID of the called code unit |
| `rel_type` | TEXT | NOT NULL | `"LOCAL_CALL"` \| `"EXTERNAL_CALL"` \| `"IMPORT"` \| `"RUNTIME_BOUNDARY"` |
| `file` | TEXT | | Source file where the call expression appears |

**Primary key**: `(src_id, dst_id, rel_type)` — prevents duplicate edges of the same type.

**Edge type semantics**:

| rel_type | Condition |
|----------|-----------|
| `LOCAL_CALL` | `src_id` and `dst_id` are in the same file |
| `EXTERNAL_CALL` | `src_id` and `dst_id` are in different files; resolved via import statement |
| `IMPORT` | Import statement reference (dependency without a direct call) |
| `RUNTIME_BOUNDARY` | Call that cannot be statically resolved to a tracked Neuron |

**RUNTIME_BOUNDARY handling** (from Law II / Blueprint Section VI):
- `RUNTIME_BOUNDARY` edges are stored but NEVER traversed during Blast Radius BFS.
- They are surfaced as warnings in `cerebrofy plan` output (Phase 4).
- `dst_id` for `RUNTIME_BOUNDARY` edges references a synthetic "external" node whose `id`
  is the raw callee name (e.g., `"requests.get"`), not a real `nodes` row.

---

### `meta` table

Key-value store for build metadata. One row per key.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `key` | TEXT | PRIMARY KEY | Metadata key name |
| `value` | TEXT | | Metadata value (always stored as string) |

**Reserved keys**:

| Key | Value format | Description |
|-----|-------------|-------------|
| `state_hash` | 64-char hex string | SHA-256 of sorted per-file SHA-256 hashes for all tracked files |
| `last_build` | ISO-8601 (e.g., `"2026-04-03T14:22:00Z"`) | Timestamp of the last completed `cerebrofy build` |
| `schema_version` | Integer string (e.g., `"1"`) | Schema version; checked on every connection open |
| `embed_model` | String (e.g., `"local"`, `"openai"`, `"cohere"`) | Embedding model used to build `vec_neurons` |
| `embed_dim` | Integer string (e.g., `"768"`) | Vector dimension of `vec_neurons` at build time |

**State hash formula** (from Blueprint Section V + Constitution):
```
state_hash = SHA-256(
  sorted([SHA-256(file_content) for each tracked file])
  joined as hex strings with newlines
)
```
This is deterministic across machines because it depends only on file contents and sort order.

---

### `file_hashes` table

Per-file content fingerprint at the time of the last build or update. Consumed by
`cerebrofy validate` (Phase 3) to detect drift.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `file` | TEXT | PRIMARY KEY | Relative path from repo root (forward slashes, no leading `./`) |
| `hash` | TEXT | NOT NULL | SHA-256 of the file's content at last build/update |

**Invariant**: Every file that contributed to `state_hash` MUST have a row in `file_hashes`.

---

## SQLite Virtual Table (Vector Layer)

### `vec_neurons` virtual table

Stores one embedding vector per indexed Neuron. Uses the `sqlite-vec` extension
(`USING vec0`).

**DDL** (generated dynamically at `cerebrofy build` Step 0):
```sql
-- embed_dim is injected from config.yaml at build time, not hardcoded
CREATE VIRTUAL TABLE vec_neurons USING vec0(
  id         TEXT PRIMARY KEY,
  embedding  FLOAT[{embed_dim}]
);
```

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT | Foreign key into `nodes.id` — same `"{file}::{name}"` format |
| `embedding` | FLOAT[N] | Embedding vector at dimension N = `embed_dim` from `config.yaml` |

**Invariant**: Every row in `nodes` MUST have a corresponding row in `vec_neurons` after a
completed build.

**Model switch behaviour**: Changing `embedding_model` in `config.yaml` changes `embed_dim`.
`cerebrofy build` drops and recreates `vec_neurons` at the new dimension. No migration needed —
full rebuild always starts from scratch.

**KNN search example** (used in Phase 4):
```sql
SELECT n.id, n.name, n.file,
       vec_distance_cosine(v.embedding, ?) AS dist
FROM   vec_neurons v
JOIN   nodes n ON n.id = v.id
ORDER  BY dist
LIMIT  ?;  -- top_k from config.yaml
```

---

## In-Memory Structures (not persisted, used during build)

### `Edge` dataclass

Produced by the graph resolver during Steps 2–3. Written to the `edges` table in bulk.

```python
@dataclass(frozen=True)
class Edge:
    src_id:   str
    dst_id:   str
    rel_type: str   # "LOCAL_CALL" | "EXTERNAL_CALL" | "IMPORT" | "RUNTIME_BOUNDARY"
    file:     str   # source file where the call expression appears
```

### `BuildLock`

Manages the PID lock file at `.cerebrofy/db/cerebrofy.build.lock`.

| Attribute | Description |
|-----------|-------------|
| `lock_path` | `Path` to the lock file |
| `pid` | PID written to the lock file on acquire |

**Lock lifecycle**: acquired at build start → released (file deleted) on build success or
failure. Stale lock (dead PID) is silently cleared on next build start.

### `LobeSummary`

In-memory structure used to generate per-lobe Markdown files after the atomic swap.

| Field | Type | Description |
|-------|------|-------------|
| `name` | str | Lobe name (from `config.yaml`) |
| `path` | str | Lobe directory path |
| `neurons` | list[dict] | Rows from `nodes` table filtered to this lobe's file prefix |
| `inbound_counts` | dict[str, int] | Neuron ID → count of inbound call edges |
| `outbound_counts` | dict[str, int] | Neuron ID → count of outbound call edges |

### `BuildResult`

Final status record returned by the build orchestrator.

| Field | Type | Description |
|-------|------|-------------|
| `success` | bool | True if all 6 steps completed and swap succeeded |
| `neurons_indexed` | int | Total Neurons written to `nodes` |
| `files_parsed` | int | Total files processed (including those with warnings) |
| `files_skipped` | int | Files skipped due to ignore rules or unsupported extension |
| `warnings` | list[str] | All non-fatal warnings from parsing, resolution, and embedding |
| `state_hash` | str | Final state hash written to `meta` and `cerebrofy_map.md` |
| `duration_seconds` | float | Wall-clock build duration |

---

## State Transitions

```
cerebrofy init (Phase 1) → writes:
  .cerebrofy/config.yaml
  .cerebrofy/db/            (empty directory)
  .cerebrofy/queries/       (populated .scm files)
  .cerebrofy-ignore
  .git/hooks/pre-push, post-merge

cerebrofy build (Phase 2) → writes:
  .cerebrofy/db/cerebrofy.db.tmp   (during build — discarded on failure)
  .cerebrofy/db/cerebrofy.db       (atomically swapped from .tmp on success)
  .cerebrofy/db/cerebrofy.build.lock   (held during build, deleted on completion)
  docs/cerebrofy/{lobe}_lobe.md    (written AFTER swap, one per lobe)
  docs/cerebrofy/cerebrofy_map.md  (written AFTER swap)

cerebrofy update (Phase 3, future) → modifies:
  .cerebrofy/db/cerebrofy.db       (partial update within one transaction)
  docs/cerebrofy/{affected_lobe}_lobe.md
  docs/cerebrofy/cerebrofy_map.md
```

---

## Schema Version

**Current schema version**: `1`

Checked on every connection open via `SELECT value FROM meta WHERE key = 'schema_version'`.
`cerebrofy build` Step 0 always writes `schema_version = 1` into the new `.tmp` database.
`cerebrofy migrate` (Phase 3) handles upgrades for existing DBs opened by newer Cerebrofy versions.
