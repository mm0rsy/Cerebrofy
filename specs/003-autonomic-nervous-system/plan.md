# Implementation Plan: Phase 3 — Autonomic Nervous System

**Branch**: `003-autonomic-nervous-system` | **Date**: 2026-04-03 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/003-autonomic-nervous-system/spec.md`

---

## Summary

Build `cerebrofy update`, `cerebrofy validate`, `cerebrofy migrate`, and upgrade the pre-push
git hook from WARN-only to hard-block. `cerebrofy update` performs a partial atomic re-index
(depth-2 BFS scope, single `BEGIN IMMEDIATE` transaction) in under 2 seconds for a single-file
change. `cerebrofy validate` classifies drift at the Neuron-signature level (minor vs.
structural) and exits 1 on structural drift. The pre-push hard-block is activated ONLY after
`cerebrofy update` meets the < 2-second gate condition. `cerebrofy migrate` applies sequential
schema migration scripts atomically.

---

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**:
  - All Phase 2 deps reused as-is (`sqlite-vec`, `sentence-transformers`, `openai`, `cohere`,
    `click`, `PyYAML`, `pathspec`, `tree-sitter`, `tree-sitter-languages`)
  - No new dependencies required for Phase 3
**Storage**: `.cerebrofy/db/cerebrofy.db` — partial `BEGIN IMMEDIATE` transaction for update;
  read-only for validate; in-place DDL migration for migrate
**Testing**: `pytest` with `tmp_path` fixture; git subprocess calls mocked in unit tests;
  integration tests create real git repos in `tmp_path`
**Target Platform**: macOS 12+, Linux (glibc ≥ 2.17), Windows 10/11
**Project Type**: CLI tool (pip package + platform bundles)
**Performance Goals**:
  - `cerebrofy update` < 2s for single-file change, 10k-file repo (SC-001)
  - `cerebrofy validate` < 500ms for hash-scan pass (no re-parse needed on clean repos)
  - Post-merge hook < 1s regardless of repo size (SC-005)
**Constraints**:
  - `sqlite-vec` `vec0` virtual table: DELETE+INSERT only (no UPDATE). Always inside same
    `BEGIN IMMEDIATE` transaction.
  - Hard-block hook MUST NOT activate before `cerebrofy update` verified (FR-014, Law IV)
  - No language-specific logic in `change_detector.py` or `drift_classifier.py` (Law V)
  - `cerebrofy validate` is read-only — MUST NOT write to `cerebrofy.db` (FR-008 behavior)
  - `git` subprocess calls use explicit arg lists, never `shell=True`
  - Fresh-repo edge case: `git rev-parse --verify HEAD` nonzero → skip `git diff` commands

---

## Constitution Check

*GATE: Must pass before implementation begins.*

### Law I — Law of Precedence ✅
All Phase 3 commands require an existing `cerebrofy.db` from `cerebrofy build`. No Phase 3
command creates a new index. `cerebrofy validate` enforces the index-before-spec invariant
at the git hook level. Hard-block activation depends on `cerebrofy update` being verified
(Phase 3 gate condition respected). **PASS.**

### Law II — Law of Structural Truth ✅
`cerebrofy update`'s partial re-index maintains all edge types (LOCAL_CALL, EXTERNAL_CALL,
IMPORT, RUNTIME_BOUNDARY). Depth-2 BFS uses O(1)-per-edge indexed queries, same as Blast
Radius BFS. `drift_classifier.py` diffs Neuron lists by name+signature — zero LLM guessing,
zero graph inference. RUNTIME_BOUNDARY edges excluded from BFS traversal. **PASS.**

### Law III — Law of Semantic Intent ✅
`cerebrofy update` maintains the invariant: every node in `nodes` has a row in `vec_neurons`.
The DELETE+INSERT transaction includes `vec_neurons` in scope. Unchanged neighbors' vectors
are preserved (skip embed if content hash unchanged). The invariant holds at COMMIT. **PASS.**

### Law IV — Law of Autonomic Health ✅
This phase IS the implementation of Law IV. Hard-block enforcement only activates after
`cerebrofy update` < 2s is verified (FR-003/FR-014). Post-merge hook is WARN-only.
`cerebrofy validate` classifies MINOR → WARN (exit 0) and STRUCTURAL → BLOCK (exit 1).
Missing index → WARN only (never block). **PASS — core delivery of this law.**

### Law V — Law of Agnosticism ✅
`change_detector.py` uses git status + hash comparison — no language-specific logic.
`drift_classifier.py` compares Neuron name+signature strings — no language-specific checks.
`scope_resolver.py` uses generic BFS on the `edges` table. All language rules remain in `.scm`
files (Phase 1, unchanged). **PASS.**

**Constitution Check: ALL 5 LAWS PASS. Implementation may proceed.**

---

## Project Structure

### Documentation (this feature)

```
specs/003-autonomic-nervous-system/
├── plan.md              ← This file
├── spec.md              ← Feature specification
├── research.md          ← Technology decisions and rationale
├── data-model.md        ← ChangeSet, UpdateScope, DriftRecord, MigrationPlan entities
├── quickstart.md        ← End-to-end validation guide
├── contracts/
│   ├── cli-update.md    ← cerebrofy update CLI contract
│   ├── cli-validate.md  ← cerebrofy validate CLI contract
│   └── cli-migrate.md   ← cerebrofy migrate CLI contract
└── checklists/
    └── requirements.md  ← Specification quality checklist
```

### Source Code (repository root)

```
src/
└── cerebrofy/
    ├── __init__.py
    ├── cli.py                        ← Add: register update, validate, migrate commands
    ├── commands/
    │   ├── __init__.py
    │   ├── init.py                   ← Phase 1 (unchanged)
    │   ├── build.py                  ← Phase 2 (unchanged)
    │   ├── update.py                 ← NEW: cerebrofy update orchestrator
    │   ├── validate.py               ← NEW: cerebrofy validate command
    │   └── migrate.py                ← NEW: cerebrofy migrate command
    ├── parser/                       ← Phase 1 (unchanged)
    ├── config/                       ← Phase 1 (unchanged)
    ├── ignore/                       ← Phase 1 (unchanged)
    ├── hooks/
    │   ├── __init__.py
    │   └── installer.py              ← MODIFIED: add upgrade_to_hard_block(),
    │                                            downgrade_to_warn_only()
    ├── mcp/                          ← Phase 1 (unchanged)
    ├── db/                           ← Phase 2 (unchanged)
    ├── graph/                        ← Phase 2 (unchanged)
    ├── embedder/                     ← Phase 2 (unchanged)
    ├── markdown/                     ← Phase 2 (unchanged)
    ├── update/                       ← NEW: update pipeline modules
    │   ├── __init__.py
    │   ├── change_detector.py        ← git commands + hash-comparison fallback
    │   └── scope_resolver.py         ← depth-2 BFS → UpdateScope
    └── validate/                     ← NEW: validation pipeline
        ├── __init__.py
        └── drift_classifier.py       ← hash scan + re-parse + Neuron diff

tests/
├── unit/
│   ├── test_neuron.py                ← Phase 1 (unchanged)
│   ├── test_engine.py                ← Phase 1 (unchanged)
│   ├── test_config.py                ← Phase 1 (unchanged)
│   ├── test_ignore.py                ← Phase 1 (unchanged)
│   ├── test_hooks.py                 ← Phase 1 (partially extended)
│   ├── test_mcp.py                   ← Phase 1 (unchanged)
│   ├── test_db_connection.py         ← Phase 2 (unchanged)
│   ├── test_db_writer.py             ← Phase 2 (unchanged)
│   ├── test_db_lock.py               ← Phase 2 (unchanged)
│   ├── test_graph_resolver.py        ← Phase 2 (unchanged)
│   ├── test_embedder.py              ← Phase 2 (unchanged)
│   ├── test_markdown.py              ← Phase 2 (unchanged)
│   ├── test_change_detector.py       ← NEW: git commands + hash fallback
│   ├── test_scope_resolver.py        ← NEW: BFS scope expansion
│   └── test_drift_classifier.py      ← NEW: minor vs structural classification
└── integration/
    ├── test_init_command.py          ← Phase 1 (unchanged)
    ├── test_build_command.py         ← Phase 2 (unchanged)
    ├── test_update_command.py        ← NEW: full cerebrofy update against tmp_path repos
    ├── test_validate_command.py      ← NEW: structural/minor drift scenarios
    └── test_migrate_command.py       ← NEW: schema migration with mock scripts

pyproject.toml                        ← No new deps required
```

**Structure Decision**: Extend the Phase 2 single-project layout with two new domain modules
(`update/`, `validate/`) and three new command files. `hooks/installer.py` is the only Phase 1
file modified. All Phase 2 modules remain unchanged.

---

## Complexity Tracking

> No constitution violations. No unjustified complexity. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
