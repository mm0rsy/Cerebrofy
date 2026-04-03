# Tasks: Phase 3 — Autonomic Nervous System

**Input**: Design documents from `specs/003-autonomic-nervous-system/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

**Organization**: Tasks are grouped by user story to enable independent implementation and
testing of each story. Each task is scoped to a single function or small logical unit so it
can be handled independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US4)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the new module directories and command file stubs for Phase 3.

- [ ] T001 Create `src/cerebrofy/update/__init__.py` (empty file with module docstring)
- [ ] T002 Create `src/cerebrofy/validate/__init__.py` (empty file with module docstring)
- [ ] T003 Create `src/cerebrofy/commands/update.py` as empty stub with module docstring and imports placeholder
- [ ] T004 Create `src/cerebrofy/commands/validate.py` as empty stub with module docstring and imports placeholder
- [ ] T005 Create `src/cerebrofy/commands/migrate.py` as empty stub with module docstring and imports placeholder

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Define all frozen dataclasses consumed by every Phase 3 pipeline. These are
pure data containers with no logic — implement them first so all later tasks can import them.

**⚠️ CRITICAL**: No user story work can begin until all dataclasses exist.

- [ ] T006 [P] Add `FileChange` frozen dataclass to `src/cerebrofy/update/change_detector.py` — fields: `path: str`, `status: str` ("M"/"D"/"A")
- [ ] T007 [P] Add `ChangeSet` frozen dataclass to `src/cerebrofy/update/change_detector.py` — fields: `changes: tuple[FileChange, ...]`, `detected_via: str` ("git"/"hash_comparison")
- [ ] T008 [P] Add `UpdateScope` frozen dataclass to `src/cerebrofy/update/scope_resolver.py` — fields: `changed_files: frozenset[str]`, `deleted_files: frozenset[str]`, `affected_node_ids: frozenset[str]`, `affected_files: frozenset[str]`
- [ ] T009 [P] Add `DriftRecord` frozen dataclass to `src/cerebrofy/validate/drift_classifier.py` — fields: `file: str`, `drift_type: str` ("none"/"minor"/"structural"), `changed_neurons: tuple[str, ...]`, `drift_detail: str`
- [ ] T010 [P] Add `UpdateResult` frozen dataclass to `src/cerebrofy/commands/update.py` — fields: `files_changed: int`, `nodes_reindexed: int`, `nodes_deleted: int`, `new_state_hash: str`, `duration_s: float`, `model_was_cold: bool`
- [ ] T011 [P] Add `ValidationResult` frozen dataclass to `src/cerebrofy/commands/validate.py` — fields: `exit_code: int`, `drift_type: str`, `structural_records: tuple[DriftRecord, ...]`, `minor_records: tuple[DriftRecord, ...]`
- [ ] T012 [P] Add `MigrationStep` frozen dataclass to `src/cerebrofy/commands/migrate.py` — fields: `from_version: int`, `to_version: int`, `script_path: Path`
- [ ] T013 [P] Add `MigrationPlan` frozen dataclass to `src/cerebrofy/commands/migrate.py` — fields: `current_version: int`, `target_version: int`, `steps: tuple[MigrationStep, ...]`, `is_already_current: bool`, `has_gap: bool`

**Checkpoint**: Foundation ready — all dataclasses importable. User story work can begin.

---

## Phase 3: User Story 1 — Incremental Index Update (Priority: P1) 🎯 MVP

**Goal**: Implement `cerebrofy update` — partial atomic re-index scoped to depth-2 BFS
neighbors of changed files. Must complete in < 2 seconds for a single-file change.

**Independent Test**: Edit one tracked file in an indexed repo. Run `cerebrofy update`.
Confirm it completes in < 2s, the index reflects the change, and a second run is a no-op.

### Implementation: Change Detector (`src/cerebrofy/update/change_detector.py`)

- [ ] T014 [P] [US1] Write `_is_git_repo(repo_root: Path) -> bool` in `change_detector.py` — checks whether `.git/` directory exists under `repo_root`
- [ ] T015 [P] [US1] Write `_has_commits(repo_root: Path) -> bool` in `change_detector.py` — runs `["git", "rev-parse", "--verify", "HEAD"]` via `subprocess.run`; returns True only if exit code is 0
- [ ] T016 [US1] Write `_run_git_cmd(args: list[str], cwd: Path) -> tuple[int, str]` in `change_detector.py` — runs `subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, check=False)`; returns `(returncode, stdout)`; never uses `shell=True`
- [ ] T017 [US1] Write `_parse_name_status(output: str) -> list[FileChange]` in `change_detector.py` — splits output on newlines; for each non-empty line splits on tab; handles M/A/D prefix (2 fields) and R prefix (3 fields: old→deleted, new→added); returns list of `FileChange` objects
- [ ] T018 [US1] Write `_detect_via_git(repo_root: Path) -> ChangeSet` in `change_detector.py` — calls `_has_commits`; if True calls `git diff --name-status HEAD` and `git diff --name-status`; always calls `git ls-files --others --exclude-standard`; deduplicates results; returns `ChangeSet(detected_via="git")`
- [ ] T019 [US1] Write `_detect_via_hash(repo_root: Path, conn: sqlite3.Connection, config: CerebrофyConfig) -> ChangeSet` in `change_detector.py` — walks all tracked files using `IgnoreRuleSet`; computes `SHA-256` of each file's content; compares against `file_hashes` table rows; classifies M/A/D; returns `ChangeSet(detected_via="hash_comparison")`
- [ ] T020 [US1] Write `detect_changes(repo_root: Path, conn: sqlite3.Connection, config: CerebrофyConfig, explicit_files: list[str] | None) -> ChangeSet` in `change_detector.py` — if `explicit_files` is not None wraps them as `ChangeSet`; elif `_is_git_repo(repo_root)` calls `_detect_via_git`; else calls `_detect_via_hash`

### Implementation: Scope Resolver (`src/cerebrofy/update/scope_resolver.py`)

- [ ] T021 [US1] Write `_get_node_ids_for_files(conn: sqlite3.Connection, files: frozenset[str]) -> set[str]` in `scope_resolver.py` — `SELECT id FROM nodes WHERE file IN (...)` for the given file set
- [ ] T022 [US1] Write `_bfs_depth2(seed_ids: set[str], conn: sqlite3.Connection) -> set[str]` in `scope_resolver.py` — BFS over `edges` table (both `src_id` and `dst_id` directions) for exactly 2 hops; excludes `RUNTIME_BOUNDARY` edges; returns all visited node IDs including seeds
- [ ] T023 [US1] Write `_get_files_for_node_ids(conn: sqlite3.Connection, node_ids: set[str]) -> set[str]` in `scope_resolver.py` — `SELECT DISTINCT file FROM nodes WHERE id IN (...)`
- [ ] T024 [US1] Write `resolve_scope(changeset: ChangeSet, conn: sqlite3.Connection) -> UpdateScope` in `scope_resolver.py` — gets seed node IDs for changed+deleted files; runs `_bfs_depth2`; gets file set for all affected nodes; returns `UpdateScope`

### Implementation: Partial Delete Functions (`src/cerebrofy/db/writer.py` additions)

- [ ] T025 [US1] Add `delete_nodes_for_files(conn: sqlite3.Connection, files: frozenset[str]) -> set[str]` to `src/cerebrofy/db/writer.py` — `DELETE FROM nodes WHERE file IN (...)`; returns the set of deleted `id` values (needed for vec_neurons cleanup)
- [ ] T026 [US1] Add `delete_edges_for_files(conn: sqlite3.Connection, files: frozenset[str], deleted_node_ids: set[str]) -> None` to `src/cerebrofy/db/writer.py` — deletes edges `WHERE file IN (...)` AND orphaned edges `WHERE src_id IN (deleted_node_ids) OR dst_id IN (deleted_node_ids)`
- [ ] T027 [US1] Add `delete_vec_neurons(conn: sqlite3.Connection, node_ids: set[str]) -> None` to `src/cerebrofy/db/writer.py` — `DELETE FROM vec_neurons WHERE id IN (...)`; must run inside the same `BEGIN IMMEDIATE` transaction as node deletion
- [ ] T028 [US1] Add `delete_file_hashes(conn: sqlite3.Connection, files: frozenset[str]) -> None` to `src/cerebrofy/db/writer.py` — `DELETE FROM file_hashes WHERE file IN (...)`

### Implementation: Update Orchestrator (`src/cerebrofy/commands/update.py`)

- [ ] T029 [US1] Write `_check_index_exists(repo_root: Path) -> Path` in `commands/update.py` — returns path to `.cerebrofy/db/cerebrofy.db`; prints `Error: No index found. Run 'cerebrofy build' first.` to stderr and raises `SystemExit(1)` if missing
- [ ] T030 [US1] Write `_compute_new_state_hash(conn: sqlite3.Connection) -> str` in `commands/update.py` — `SELECT file, hash FROM file_hashes ORDER BY file`; computes `SHA-256` over joined `file:hash` lines; returns 64-char hex string
- [ ] T031 [US1] Write `_run_update_transaction(conn, scope, new_neurons, new_edges, file_hash_map, embedder, new_state_hash) -> tuple[int, int]` in `commands/update.py` — executes `BEGIN IMMEDIATE`; calls delete functions (T025–T028) for affected files; inserts new nodes, edges, vec_neurons, file_hashes; updates `meta` state_hash and last_build; `COMMIT`; returns `(nodes_reindexed, nodes_deleted)`
- [ ] T032 [US1] Write `_rewrite_markdown_after_update(scope, conn, config, repo_root) -> None` in `commands/update.py` — rewrites affected lobe `.md` files using `write_lobe_md` from Phase 2; rewrites `cerebrofy_map.md` with new `state_hash`
- [ ] T033 [US1] Write the `@click.command("update")` handler in `commands/update.py` — acquires `BuildLock`; calls detect → resolve_scope → parse changed files → resolve edges → embed → `_run_update_transaction` → `_rewrite_markdown_after_update`; prints progress messages per contract; prints `Nothing to update.` if `ChangeSet.changes` is empty
- [ ] T034 [US1] Register `from cerebrofy.commands.update import update` and `cli.add_command(update)` in `src/cerebrofy/cli.py`

### Unit Tests for User Story 1

- [ ] T035 [P] [US1] Write unit tests for `_parse_name_status` in `tests/unit/test_change_detector.py` — test M/A/D lines; test renamed file lines (R prefix with 3 fields); test empty output
- [ ] T036 [P] [US1] Write unit tests for `_bfs_depth2` in `tests/unit/test_scope_resolver.py` — test depth exactly 2 hops; test RUNTIME_BOUNDARY excluded; test disconnected nodes; mock `conn` with in-memory SQLite

### Integration Test for User Story 1

- [ ] T037 [US1] Write integration test for `cerebrofy update` in `tests/integration/test_update_command.py` — create `tmp_path` git repo; run `cerebrofy build`; edit one file; run `cerebrofy update`; assert exit 0 and state_hash changed; assert second run is no-op

**Checkpoint**: `cerebrofy update` fully functional. Verify SC-001 (< 2s single-file change).

---

## Phase 4: User Story 2 — Tiered Drift Enforcement (Priority: P2)

**Goal**: Implement `cerebrofy validate` for tiered drift classification (minor exit 0,
structural exit 1). Upgrade pre-push hook to hard-block mode.

**Independent Test**: Run `cerebrofy validate` after adding a new function without updating.
Confirm exit 1 listing the new function. Run after a comment-only change — confirm exit 0.

### Implementation: Drift Classifier (`src/cerebrofy/validate/drift_classifier.py`)

- [ ] T038 [P] [US2] Write `_normalize_sig(sig: str) -> str` in `drift_classifier.py` — returns `" ".join(sig.split())` to eliminate whitespace-formatting differences
- [ ] T039 [US2] Write `_get_indexed_neurons(conn: sqlite3.Connection, file: str) -> list[dict]` in `drift_classifier.py` — `SELECT name, signature FROM nodes WHERE file = ?`; returns list of `{"name": ..., "sig": _normalize_sig(...)}` dicts
- [ ] T040 [US2] Write `_classify_file_drift(file: str, conn: sqlite3.Connection, config: CerebrофyConfig) -> DriftRecord` in `drift_classifier.py` — re-parses file using Phase 1 engine; computes normalized name+sig set for new Neurons; compares against indexed Neurons from `_get_indexed_neurons`; classifies as "none"/"minor"/"structural"; catches parse errors and emits stderr warning
- [ ] T041 [US2] Write `classify_drift(changed_files: list[str], conn: sqlite3.Connection, config: CerebrофyConfig) -> list[DriftRecord]` in `drift_classifier.py` — first filters by file hash against `file_hashes` table (skip hash-matching files); calls `_classify_file_drift` for each truly changed file; returns all `DriftRecord` objects

### Implementation: Hook Upgrade (`src/cerebrofy/hooks/installer.py` additions)

- [ ] T042 [US2] Add `upgrade_to_hard_block(hook_path: Path) -> None` to `src/cerebrofy/hooks/installer.py` — reads hook file; checks for `# BEGIN cerebrofy` / `# END cerebrofy` sentinels; replaces `# cerebrofy-hook-version: 1` with `# cerebrofy-hook-version: 2` and updates exit logic to honor `cerebrofy validate` exit code; emits warning if sentinels absent
- [ ] T043 [US2] Add `downgrade_to_warn_only(hook_path: Path) -> None` to `src/cerebrofy/hooks/installer.py` — inverse of `upgrade_to_hard_block`; replaces version 2 marker with version 1; restores WARN-only exit behavior inside sentinels

### Implementation: Validate Command (`src/cerebrofy/commands/validate.py`)

- [ ] T044 [US2] Write the `@click.command("validate")` handler in `commands/validate.py` — opens `cerebrofy.db` read-only; if missing prints WARN and exits 0; calls `classify_drift`; prints output per contract (no-drift / minor warning / structural block message with neuron list); exits 0 or 1
- [ ] T045 [US2] Register `from cerebrofy.commands.validate import validate` and `cli.add_command(validate)` in `src/cerebrofy/cli.py`

### Unit Tests for User Story 2

- [ ] T046 [P] [US2] Write unit tests for `_classify_file_drift` in `tests/unit/test_drift_classifier.py` — test minor drift (comment-only change); test structural drift (new function); test no drift (hash match); use `tmp_path` for real file + in-memory SQLite for mocked index

### Integration Test for User Story 2

- [ ] T047 [US2] Write integration test for `cerebrofy validate` in `tests/integration/test_validate_command.py` — three scenarios: structural drift exits 1; minor drift exits 0; missing index exits 0

**Checkpoint**: `cerebrofy validate` functional. Pre-push hook upgrade available.

---

## Phase 5: User Story 3 — Post-Merge Sync Check (Priority: P3)

**Goal**: Install a post-merge git hook that compares `state_hash` in pulled
`cerebrofy_map.md` against the local index. WARN-only, never blocks.

**Independent Test**: Simulate a remote state_hash by modifying `cerebrofy_map.md`. Run
`git merge`. Confirm hook prints warning. Confirm exit 0 (never blocks).

### Implementation

- [ ] T048 [P] [US3] Write `_generate_post_merge_script() -> str` in `src/cerebrofy/hooks/installer.py` — returns the shell script body for the post-merge hook; script reads `state_hash` from `docs/cerebrofy/cerebrofy_map.md`; queries local `cerebrofy.db` meta table; prints warning if hashes differ; always exits 0
- [ ] T049 [US3] Update `install_hooks(repo_root: Path, config: CerebrофyConfig) -> None` in `src/cerebrofy/hooks/installer.py` — in addition to pre-push hook, also writes `post-merge` hook using `_generate_post_merge_script()`; uses same idempotency logic (sentinel append/skip)

### Integration Test for User Story 3

- [ ] T050 [US3] Write integration test for post-merge hook in `tests/integration/test_update_command.py` — create `tmp_path` git repo with cerebrofy index; modify `cerebrofy_map.md` state_hash; trigger post-merge hook script directly; assert warning printed and exit code 0

**Checkpoint**: Post-merge hook installed and warn-only behavior verified.

---

## Phase 6: User Story 4 — Schema Migration (Priority: P4)

**Goal**: Implement `cerebrofy migrate` — reads current schema version, applies sequential
migration scripts from `.cerebrofy/scripts/migrations/` atomically.

**Independent Test**: Manually set schema_version to 0. Run `cerebrofy migrate`. Confirm
schema updated and data intact. Confirm missing script produces clear error.

### Implementation

- [ ] T051 [US4] Write `_load_migration_plan(conn: sqlite3.Connection, migrations_dir: Path, target_version: int) -> MigrationPlan` in `commands/migrate.py` — reads `schema_version` from `meta` table; scans `migrations_dir` for files named `v{N}_to_v{N+1}.py`; builds ordered `tuple[MigrationStep, ...]`; sets `has_gap=True` if any step in the range lacks a script
- [ ] T052 [US4] Write `_apply_migration_step(conn: sqlite3.Connection, step: MigrationStep) -> None` in `commands/migrate.py` — opens `BEGIN IMMEDIATE`; imports and runs the migration script passing `conn`; updates `meta schema_version`; `COMMIT`; rolls back on exception and re-raises
- [ ] T053 [US4] Write the `@click.command("migrate")` handler in `commands/migrate.py` — checks index exists; calls `_load_migration_plan`; if `is_already_current` prints "Schema already at version N" and exits 0; if `has_gap` prints error and exits 1; otherwise applies steps sequentially; prints per-step progress per contract
- [ ] T054 [US4] Register `from cerebrofy.commands.migrate import migrate` and `cli.add_command(migrate)` in `src/cerebrofy/cli.py`

### Integration Test for User Story 4

- [ ] T055 [US4] Write integration test for `cerebrofy migrate` in `tests/integration/test_migrate_command.py` — create tmp index; downgrade schema_version to 0; write a v0_to_v1.py migration script; run `cerebrofy migrate`; assert schema_version is 1 and exit 0; assert missing script path produces exit 1

**Checkpoint**: All four user stories are independently functional and testable.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Extend existing test files, verify latency gate (SC-001), and run the
quickstart validation.

- [ ] T056 [P] Extend `tests/unit/test_hooks.py` — add tests for `upgrade_to_hard_block` (verifies version marker replaced, sentinels respected, absent-sentinel warning) and `downgrade_to_warn_only`
- [ ] T057 Run `cerebrofy update` against a real 1-file change in a 10k-file repo and verify wall-clock time < 2s (SC-001 gate condition for enabling hard-block in FR-014)
- [ ] T058 Run the full quickstart.md validation steps 1–9 end to end in a fresh tmp repo to confirm all Phase 3 acceptance scenarios pass
- [ ] T059 [P] Run `ruff check src/ tests/` and `mypy src/` and fix any issues in Phase 3 files

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Phase 2 — prerequisite for US2 (hook gate)
- **User Story 2 (Phase 4)**: Depends on US1 being verified at SC-001 latency (FR-014)
- **User Story 3 (Phase 5)**: Depends on Phase 2 only — can proceed in parallel with US2
- **User Story 4 (Phase 6)**: Depends on Phase 2 only — can proceed in parallel with US2/US3
- **Polish (Phase 7)**: Depends on all desired user stories complete

### Within Each User Story

- Dataclasses (Phase 2) before any implementation
- Helper functions before orchestrators
- Orchestrators before CLI command registration
- Unit tests can be written in parallel with implementation of the same function

### Parallel Opportunities

- T006–T013 (all dataclasses) can run in parallel
- T014–T016 (`_is_git_repo`, `_has_commits`, `_run_git_cmd`) can run in parallel
- T021–T023 (BFS helpers) can run in parallel within scope_resolver
- T025–T028 (partial delete functions) can run in parallel in db/writer.py
- T035–T036 (unit tests for US1) can run in parallel
- T038 (`_normalize_sig`) can run in parallel with T039
- T042–T043 (hook upgrade/downgrade) can run in parallel
- T048 (post-merge script generator) can run in parallel with T049
- T056 and T059 can run in parallel in the polish phase

---

## Parallel Example: User Story 1 Foundation

```
# Phase 2 (all parallel):
Task T006: FileChange dataclass
Task T007: ChangeSet dataclass
Task T008: UpdateScope dataclass
Task T009: DriftRecord dataclass
Task T010: UpdateResult dataclass
...

# Phase 3 change_detector helpers (after T006, T007):
Task T014: _is_git_repo
Task T015: _has_commits
(both can run in parallel — different functions in same file)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001–T005)
2. Complete Phase 2: Dataclasses (T006–T013)
3. Complete Phase 3 US1: Change Detector + Scope Resolver + Update Command (T014–T037)
4. **STOP and verify SC-001**: `cerebrofy update` < 2s on single-file change
5. Only then proceed to US2 (hard-block enforcement) per FR-014

### Incremental Delivery

1. Foundation (Phases 1–2) → dataclasses ready
2. US1 → incremental update works → verify latency gate
3. US2 → drift enforcement + hard-block activated
4. US3/US4 (independent, can proceed in parallel) → merge/migrate hooks
5. Polish → lint, type check, quickstart validation

---

## Notes

- `[P]` tasks operate on different functions or files — no shared write conflicts
- `[USn]` label maps each task to its user story for traceability
- Hard-block hook (US2) MUST NOT be activated before SC-001 is verified (FR-014, Law IV)
- `cerebrofy validate` is read-only — MUST NOT write to `cerebrofy.db` (FR-008)
- `git` subprocess calls MUST use explicit arg lists, never `shell=True` (research.md Decision 2)
- `vec0` virtual table: DELETE + INSERT only inside same `BEGIN IMMEDIATE` transaction (research.md Decision 1)
- `RUNTIME_BOUNDARY` edges MUST be excluded from BFS traversal in `_bfs_depth2` (Law II)
