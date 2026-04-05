# Data Model: Phase 3 — Autonomic Nervous System

**Feature**: 003-autonomic-nervous-system
**Date**: 2026-04-03

---

## Overview

Phase 3 does not create new persistent tables. It operates on the existing `cerebrofy.db`
schema from Phase 2 (`nodes`, `edges`, `meta`, `file_hashes`, `vec_neurons`) using partial
atomic transactions. This document defines the in-memory data structures and state transitions
introduced by Phase 3 commands.

---

## Existing Schema (Phase 2 — consumed, not modified)

```sql
-- Consumed by cerebrofy update (partial DELETE+INSERT) and cerebrofy validate (read-only)
nodes        (id, name, file, type, line_start, line_end, signature, docstring, hash)
edges        (src_id, dst_id, rel_type, file)
meta         (key, value)   -- state_hash, last_build, schema_version, embed_model, embed_dim
file_hashes  (file, hash)
vec_neurons  (id, embedding)
```

---

## In-Memory Data Structures

### ChangeSet

Represents the set of tracked files that changed since the last build/update. Produced by
`change_detector.py` before any re-indexing begins.

```python
@dataclass(frozen=True)
class FileChange:
    path: str          # relative path from repo root (forward slashes)
    status: str        # "M" (modified) | "D" (deleted) | "A" (added)

@dataclass(frozen=True)
class ChangeSet:
    changes: tuple[FileChange, ...]  # all detected file changes
    detected_via: str                # "git" | "hash_comparison" | "explicit"
```

**Invariants**:
- `path` uses forward slashes, no leading `./`
- `status` is exactly one of `"M"`, `"D"`, `"A"`
- No two `FileChange` entries share the same `path`
- `changes` is empty when no files changed since last build/update
- `detected_via` is exactly one of `"git"` (auto-detect in git repo), `"hash_comparison"` (auto-detect without git), or `"explicit"` (caller-supplied file list via `cerebrofy update [FILES...]`)
- When `detected_via="explicit"`: files absent on disk are classified `"D"`; files present on disk that pass ignore rules are classified `"M"`

---

### UpdateScope

The expanded set of nodes and files that must be re-indexed, computed via depth-2 BFS from
changed nodes. Produced by `scope_resolver.py`.

```python
@dataclass(frozen=True)
class UpdateScope:
    changed_files: frozenset[str]    # files directly changed (from ChangeSet.M + ChangeSet.A)
    deleted_files: frozenset[str]    # files deleted (from ChangeSet.D)
    affected_node_ids: frozenset[str]  # node IDs at depth ≤ 2 from any changed node
    affected_files: frozenset[str]   # files containing any affected_node_id
```

**Invariants**:
- `changed_files ∩ deleted_files = ∅`
- `affected_node_ids` includes nodes from both changed and deleted files (for BFS expansion)
- `RUNTIME_BOUNDARY` edges are excluded from BFS traversal
- BFS depth = 2 exactly (matches Blast Radius depth from Blueprint §VI)

---

### DriftRecord

Per-file drift classification produced by `drift_classifier.py` during `cerebrofy validate`.

```python
@dataclass(frozen=True)
class DriftRecord:
    file: str                  # relative path
    drift_type: str            # "none" | "minor" | "structural"
    changed_neurons: tuple[str, ...]  # names of added/removed/changed neurons (structural only)
    drift_detail: str          # human-readable summary of what changed
```

**Classification rules** (applied in order):
1. If file hash matches `file_hashes` table → `drift_type = "none"`
2. Re-parse the file → get new Neuron list
3. Compare new Neurons vs. indexed Neurons by `name` + whitespace-normalized `signature`:
   - All names present, all signatures match → `drift_type = "minor"`
   - Any Neuron added, removed, renamed, or signature changed → `drift_type = "structural"`
   - Any import capture added or removed → `drift_type = "structural"`

---

### UpdateResult

Summary of a completed `cerebrofy update` run.

```python
@dataclass(frozen=True)
class UpdateResult:
    files_changed: int         # count of M+A+D files
    nodes_reindexed: int       # count of node rows inserted/updated
    nodes_deleted: int         # count of node rows removed (deleted files)
    new_state_hash: str        # 64-char hex SHA-256
    duration_s: float          # wall-clock seconds
    model_was_cold: bool       # True if embedding model was freshly loaded
```

---

### ValidationResult

Summary of a completed `cerebrofy validate` run.

```python
@dataclass(frozen=True)
class ValidationResult:
    exit_code: int              # 0 (clean/minor) | 1 (structural drift) | 0 (missing index)
    drift_type: str             # "none" | "minor" | "structural" | "missing_index"
    structural_records: tuple[DriftRecord, ...]  # only structural-drift files
    minor_records: tuple[DriftRecord, ...]       # only minor-drift files
```

---

### MigrationPlan

Computed by `cerebrofy migrate` before applying any scripts.

```python
@dataclass(frozen=True)
class MigrationStep:
    from_version: int
    to_version: int
    script_path: Path          # absolute path to migration script

@dataclass(frozen=True)
class MigrationPlan:
    current_version: int
    target_version: int
    steps: tuple[MigrationStep, ...]  # ordered: current → current+1 → ... → target
    is_already_current: bool
    has_gap: bool              # True if any step lacks a migration script
```

---

## State Transitions

### cerebrofy update — Index State

```
Initial state: cerebrofy.db at state_hash S1

BEGIN IMMEDIATE
  1. DELETE FROM nodes WHERE file IN (changed_files ∪ deleted_files)
  2. DELETE FROM edges WHERE file IN (changed_files ∪ deleted_files)
     + DELETE orphaned edges WHERE src_id or dst_id no longer in nodes
  3. DELETE FROM vec_neurons WHERE id IN (deleted node IDs from step 1)
  4. DELETE FROM file_hashes WHERE file IN (deleted_files)
  5. INSERT new nodes for changed_files (re-parsed Neurons)
  6. INSERT new edges for changed_files (re-resolved local + cross-module)
  7. INSERT new vec_neurons for new/changed nodes (vectors pre-computed BEFORE BEGIN IMMEDIATE;
        only the INSERT occurs under the write lock — never the embedding model invocation)
  8. INSERT OR REPLACE file_hashes for changed_files ∪ deleted-cleaned
  9. UPDATE meta SET value = new_state_hash WHERE key = 'state_hash'
 10. UPDATE meta SET value = now() WHERE key = 'last_build'
COMMIT

Post-state: cerebrofy.db at state_hash S2
           cerebrofy_map.md updated with S2
           affected lobe .md files updated
```

On failure at any step → full `ROLLBACK` → index remains at S1.

### cerebrofy migrate — Schema Version Transition

```
Initial: schema_version = N

For each MigrationStep (N → N+1):
  BEGIN IMMEDIATE
    run migration script DDL
    UPDATE meta SET value = N+1 WHERE key = 'schema_version'
  COMMIT

Final: schema_version = current_version
```

On failure at step K → `ROLLBACK` → schema_version remains at N+(K-1) (last successful step).

---

## Hook State Model

The pre-push git hook has two modes, tracked by an in-file versioned marker:

```
# cerebrofy-hook-version: 1   ← WARN-only (Phase 1 default)
# cerebrofy-hook-version: 2   ← Hard-block enabled (Phase 3 activation)
```

Transition from version 1 → version 2 is performed by `hooks/installer.py`'s
`upgrade_to_hard_block()` function, which replaces the warn-path exit within the
`# BEGIN cerebrofy` / `# END cerebrofy` sentinel block only.

**Invariants**:
- User content outside the sentinels is NEVER modified
- If sentinels are absent, upgrade is skipped with a warning
- Downgrade (v2 → v1) is supported by `downgrade_to_warn_only()` (for rollback scenarios)
