# Feature Specification: Phase 3 — Autonomic Nervous System

**Feature Branch**: `003-autonomic-nervous-system`
**Created**: 2026-04-03
**Status**: Draft
**Input**: User description: "Read @cerebrofy_blueprint_v5_0.md and specify the next feature based on phase 3"

## Clarifications

### Session 2026-04-03

- Q: Should `cerebrofy update` auto-detect changes via git commands (blueprint), content-hash comparison (spec draft), or both? → A: Both — git commands when `.git/` is present (matches blueprint, more efficient); hash comparison fallback when git is absent (consistent with Phase 2 building without git).
- Q: Should `cerebrofy update` rewrite `cerebrofy_map.md` with the new `state_hash` on success? → A: Yes — `cerebrofy update` rewrites `cerebrofy_map.md` with the new `state_hash` and `last_build` timestamp on every successful run, so pushed copies always reflect the post-update index state.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Incremental Index Update (Priority: P1)

A developer has just edited one or two files in a repository that already has a complete
Cerebrofy index. Rather than waiting for a full rebuild, they run `cerebrofy update` and the
index is refreshed in under 2 seconds — only the affected code units and their immediate
structural neighbors are re-indexed. The developer can then push their changes without
triggering a stale-index block.

**Why this priority**: `cerebrofy update` is the fast sync remedy that MUST exist before the
pre-push hard-block is activated. Blocking pushes without a sub-2-second remedy is a
constitution violation. This is the gating story for the entire phase — nothing else in
Phase 3 is safe to activate until US1 is verified at the SC-001 latency target.

**Independent Test**: Edit one tracked source file in an initialized, built repository. Run
`cerebrofy update`. Confirm it completes in under 2 seconds and the index reflects the change.
Query the index to confirm only the changed file's code units and their depth-2 structural
neighbors were re-indexed. Run `cerebrofy update` again immediately — confirm it exits cleanly
with no writes.

**Acceptance Scenarios**:

1. **Given** an indexed repository and one modified source file, **When** the developer runs
   `cerebrofy update`, **Then** the index is updated to reflect the file's changes, all code
   units within structural depth-2 of any changed code unit are re-indexed, and the command
   completes in under 2 seconds.

2. **Given** multiple modified files, **When** the developer runs `cerebrofy update`, **Then**
   all changed files and their depth-2 structural neighbors are re-indexed in a single atomic
   operation — no partial update is visible at any point.

3. **Given** a newly added (previously untracked) source file, **When** the developer runs
   `cerebrofy update`, **Then** all code units in the new file are indexed and the overall
   index fingerprint is updated to include the new file.

4. **Given** a deleted tracked source file, **When** the developer runs `cerebrofy update`,
   **Then** all code units from the deleted file are removed from the index, all call
   relationship records referencing those code units are cleaned up, and their depth-2
   structural neighbors are re-indexed.

5. **Given** `cerebrofy update` fails mid-run due to any error, **Then** the index remains
   in its exact prior state — the update is fully rolled back with no partial changes visible.

6. **Given** no index exists, **When** the developer runs `cerebrofy update`, **Then**
   Cerebrofy prints a clear error directing the developer to run `cerebrofy build` first,
   and exits without modifying any file.

---

### User Story 2 - Tiered Drift Enforcement (Priority: P2)

A developer pushes code to a remote branch. The pre-push hook runs automatically. If the
developer's changes are structural (new or renamed functions, changed signatures, added
imports) and the index has not been updated, the push is blocked with a clear message listing
exactly which code units are out of sync. If only whitespace or comments changed, the push
proceeds with a non-blocking warning suggesting `cerebrofy update`.

**Why this priority**: Drift enforcement is what makes Cerebrofy a trust mechanism, not just a
tool. However, it MUST only activate after US1 is verified — blocking without a sub-2-second
remedy is a constitution violation. P2 enforces this gate ordering.

**Independent Test**: Run `cerebrofy validate` directly (not via hook) after adding a new
function without updating the index. Confirm exit code 1 and a message listing the unsynced
function. Then run `cerebrofy validate` after making only a comment change — confirm exit
code 0 and a non-blocking warning. Verify the same behavior when triggered via `git push`.

**Acceptance Scenarios**:

1. **Given** a new function is added to a tracked file without running `cerebrofy update`,
   **When** the developer runs `git push`, **Then** the pre-push hook blocks the push (exit 1)
   and prints the name and file of the unsynced function.

2. **Given** a function is renamed or its signature is changed without running
   `cerebrofy update`, **When** the developer runs `git push`, **Then** the push is blocked
   with a message identifying the structurally changed code unit by name, file, and drift type.

3. **Given** only comments or whitespace are changed without running `cerebrofy update`,
   **When** the developer runs `git push`, **Then** the push proceeds (exit 0) and a
   non-blocking warning suggests `cerebrofy update`.

4. **Given** no Cerebrofy index exists on the machine, **When** the developer runs
   `git push`, **Then** the hook prints a WARN-only message and NEVER blocks the push.

5. **Given** `cerebrofy validate` is run as a standalone command, **Then** its output and
   exit code are identical to when it is invoked by the git hook.

6. **Given** the developer runs `cerebrofy update` after making structural changes and then
   runs `git push`, **Then** no warning or block is triggered.

---

### User Story 3 - Post-Merge Sync Check (Priority: P3)

After a `git pull` or merge, a developer's local Cerebrofy index may be out of date relative
to teammates' changes in the remote branch. The post-merge hook automatically compares the
index fingerprint from the pulled `cerebrofy_map.md` against the local index. If they differ,
the developer is warned and prompted to resync.

**Why this priority**: This is a passive, warn-only quality gate — no work is blocked. It
prevents developers from silently working with a stale index after merging remote changes.
P3 because it is independently safe to deploy (no blocking) and does not depend on US2.

**Independent Test**: Simulate a remote update by modifying `cerebrofy_map.md` to contain a
different `state_hash`. Run `git merge`. Confirm the post-merge hook detects the mismatch,
prints a warning suggesting `cerebrofy build`, and makes no changes to any file.

**Acceptance Scenarios**:

1. **Given** the pulled `cerebrofy_map.md` contains a `state_hash` that differs from the
   local index, **When** a `git pull` or merge completes, **Then** the post-merge hook
   prints a warning identifying the sync gap and suggests `cerebrofy build`. No files are
   modified and no push is blocked.

2. **Given** the pulled `cerebrofy_map.md` contains the same `state_hash` as the local
   index, **When** a `git pull` or merge completes, **Then** the post-merge hook takes no
   action.

3. **Given** no local Cerebrofy index exists, **When** a `git pull` or merge completes,
   **Then** the hook prints a message suggesting `cerebrofy init && cerebrofy build` and
   exits cleanly without blocking.

---

### User Story 4 - Schema Migration (Priority: P4)

After a Cerebrofy version upgrade, a developer's existing index may be at an older schema
version. `cerebrofy migrate` applies the minimal set of sequential migration scripts needed
to bring the index schema up to the current version — preserving all existing indexed data.

**Why this priority**: Migration is only needed when Cerebrofy itself is upgraded to a
schema-changing version. Zero impact on day-to-day use. P4 because it affects no users until
a schema-changing release is published.

**Independent Test**: Manually set the index schema version to 0 (simulating an older
version). Run `cerebrofy migrate`. Confirm the schema is updated to the current version and
all pre-existing indexed data is intact. Confirm that a missing migration script produces a
clear error suggesting `cerebrofy build`.

**Acceptance Scenarios**:

1. **Given** the index is one schema version behind, **When** the developer runs
   `cerebrofy migrate`, **Then** the migration script for that version gap is applied and
   the schema version is updated to the current version.

2. **Given** the index is multiple schema versions behind, **When** the developer runs
   `cerebrofy migrate`, **Then** all necessary migration scripts are applied sequentially in
   version order.

3. **Given** a migration script fails mid-run, **Then** the index remains at its prior schema
   version — the migration is fully rolled back. A clear error identifies the failed step.

4. **Given** no migration script exists for the required version gap, **Then**
   `cerebrofy migrate` reports the gap and suggests `cerebrofy build` as the recovery path.

5. **Given** the index is already at the current schema version, **When** the developer runs
   `cerebrofy migrate`, **Then** Cerebrofy reports "Already at current schema version" and
   exits cleanly with no changes.

---

### Edge Cases

- What happens when `cerebrofy update` is run with no changes since the last build/update? → Completes immediately with "Nothing to update" message; exit 0; no index writes.
- What happens when `cerebrofy update` is run outside a git repository? → Auto-detection falls back to content-hash comparison against the `file_hashes` table. Behavior is otherwise identical.
- What happens when `cerebrofy update` detects that the entire codebase has changed? → Reports the scope and suggests `cerebrofy build` as a more efficient alternative if the number of changed files exceeds a reasonable threshold.
- What happens when a deleted file had many caller code units at depth-2? → All depth-2 neighbors are re-indexed; if the operation scope exceeds the 2-second target, the developer is warned of the scope before it proceeds.
- What happens when `cerebrofy validate` runs with no index and structural changes exist? → WARN-only (missing-index case always warns, never blocks).
- What happens when the post-merge hook runs but `cerebrofy_map.md` was deleted or never committed? → WARN-only; suggest `cerebrofy build`.
- What happens when `cerebrofy migrate` encounters an index schema newer than the installed Cerebrofy (downgrade scenario)? → Error: schema is newer than this installation; upgrade Cerebrofy or run `cerebrofy build` to reset.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `cerebrofy update` MUST accept an explicit list of file paths OR auto-detect changed files. When a git repository is present, auto-detection MUST use three git commands that together cover all change types: modified/deleted tracked files (`git diff --name-status HEAD`), unstaged changes (`git diff --name-status`), and new untracked files (`git ls-files --others --exclude-standard`). When no git repository is present, auto-detection MUST fall back to content-hash comparison against the index's per-file hash records.
- **FR-002**: `cerebrofy update` MUST re-index only the changed files plus all code units within structural depth-2 of any code unit in the changed files — not the full codebase.
- **FR-003**: `cerebrofy update` MUST complete in under 2 seconds for a single-file change on a fully indexed repository. This latency target is the Phase 3 gate condition for enabling hard-block enforcement.
- **FR-004**: `cerebrofy update` MUST execute all index writes in a single atomic transaction. On any failure, the entire update MUST be rolled back to the prior index state.
- **FR-005**: `cerebrofy update` MUST update the per-file content hash record, recompute the overall index fingerprint, and update the last-sync timestamp in the index on each successful run.
- **FR-006**: `cerebrofy update` MUST update the lobe Markdown file for any Lobe containing code units affected by the update, AND MUST rewrite `cerebrofy_map.md` with the new `state_hash` and last-sync timestamp. This ensures the committed `cerebrofy_map.md` always reflects the post-update index state for cross-developer sync checks.
- **FR-007**: `cerebrofy update` MUST require a complete index to already exist. If no index is found, it MUST exit with a clear error directing the developer to run `cerebrofy build` first.
- **FR-008**: `cerebrofy validate` MUST identify all tracked files that have changed since the last build or update by comparing their current content against the index's per-file hash records.
- **FR-009**: `cerebrofy validate` MUST re-parse only the changed files and diff the resulting code unit list against the index to classify each file's drift as minor or structural.
- **FR-010**: Minor drift (only comments or whitespace changed — no code unit added, removed, renamed, or signature changed; no import added or removed) MUST produce a non-blocking warning and exit code 0.
- **FR-011**: Structural drift (any code unit added, removed, renamed, or signature changed; or any import added or removed in any changed file) MUST produce a blocking error listing all affected code units by name and file, and exit code 1.
- **FR-012**: A missing or absent index MUST produce a WARN-only message and exit code 0. `cerebrofy validate` MUST NEVER block a push due to a missing index.
- **FR-013**: The pre-push git hook MUST invoke `cerebrofy validate`. Exit code 1 MUST block the push. Exit code 0 MUST allow it.
- **FR-014**: The pre-push hard-block (exit 1) MUST NOT be enabled in the git hook until `cerebrofy update` is verified to meet FR-003. Until then, the hook remains in WARN-only mode.
- **FR-015**: `cerebrofy validate` as a standalone command MUST produce identical output and exit behavior to `cerebrofy validate` invoked by the git hook — single implementation, two call paths.
- **FR-016**: The post-merge git hook MUST run after every `git pull` or `git merge`. It MUST compare the `state_hash` in the pulled `cerebrofy_map.md` against the `state_hash` in the local index.
- **FR-017**: If the post-merge state hashes differ, the hook MUST print a warning suggesting `cerebrofy build`. It MUST NOT block the merge or modify any file.
- **FR-018**: `cerebrofy migrate` MUST read `schema_version` from the current index and apply all sequential migration scripts in version order until the schema reaches the current version.
- **FR-019**: Schema migration MUST be atomic. If any migration script fails, the entire migration MUST be rolled back and the schema version MUST remain unchanged.
- **FR-020**: If no migration script exists for the required version gap, `cerebrofy migrate` MUST report the gap and suggest `cerebrofy build` as the recovery path.

### Key Entities

- **Change Set**: The set of tracked files that have changed since the last successful build or update, classified as modified, deleted, or added. Computed by comparing current content against per-file hash records.
- **Update Scope**: The set of code units that must be re-indexed for a given change set — the changed files' code units plus all depth-2 structural neighbors. Excludes unresolvable boundary edges from scope computation.
- **Drift Record**: A per-file classification of whether its changes are minor (non-structural only) or structural. A single structural drift record triggers a hard block.
- **Migration Script**: A versioned, sequential script that upgrades an index schema from version N to version N+1. Applied atomically.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `cerebrofy update` completes in under 2 seconds for a single-file change on a 10,000-file fully indexed repository on a standard developer machine (8-core CPU, 16 GB RAM). This is the Phase 3 gate condition for enabling hard-block enforcement.
- **SC-002**: After `cerebrofy update`, 100% of re-indexed code units match the current source files — a subsequent `cerebrofy validate` finds zero drift for the updated files.
- **SC-003**: `cerebrofy validate` correctly classifies drift in 100% of tested cases: whitespace/comment-only changes always exit 0; structural changes (function add/remove/rename/signature change or import change) always exit 1. Zero false positives; zero false negatives.
- **SC-004**: After hard-block is enabled, 100% of pushes containing unsynced structural drift are blocked. Zero pushes with only minor drift are blocked.
- **SC-005**: The post-merge hook completes in under 1 second after any `git pull` or `git merge` regardless of repository size.
- **SC-006**: `cerebrofy migrate` successfully upgrades the schema across all documented version transitions without data loss. After migration, `cerebrofy validate` finds zero drift on the migrated index for an unchanged codebase.

## Assumptions

- Phase 2 (`cerebrofy build`) has been completed and a valid index exists before any Phase 3 command is invoked.
- `cerebrofy update` uses the same file tracking definition (extension filter + ignore rules) as `cerebrofy build`. When auto-detecting in a git repository, changed files are identified via git status commands (more efficient than hashing all files). Outside a git repository, changed files are detected by content-hash comparison against the `file_hashes` table (timestamps are unreliable across platforms and are never used).
- The depth-2 structural BFS used by `cerebrofy update` uses the same algorithm as Blast Radius BFS. Unresolvable boundary edges are excluded from traversal.
- Hard-block hook enforcement is off by default (WARN-only from Phase 1). Phase 3 activates it by updating the hook script only after `cerebrofy update` meets SC-001.
- `cerebrofy validate` re-parses only changed files for drift classification — not the full codebase. The Phase 1 parser is reused unchanged.
- The post-merge hook reads `cerebrofy_map.md` from the working tree. No network call is made.
- `cerebrofy migrate` applies only explicit migration scripts from the migrations directory. Gaps with no script always direct users to `cerebrofy build`.
- Concurrent execution of `cerebrofy update` in the same repository is prevented by the same lock mechanism used by `cerebrofy build`.
- `cerebrofy validate` is a read-only operation and requires no lock.
- `cerebrofy update` does not re-embed code units whose source content and call relationships are unchanged. Unchanged neighbors of changed nodes are structurally re-evaluated but their embedding vectors are only updated if their content changed.
