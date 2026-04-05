# Implementation Plan: Phase 4 — AI Bridge

**Branch**: `004-ai-bridge` | **Date**: 2026-04-04 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/004-ai-bridge/spec.md`

---

## Summary

Phase 4 implements `cerebrofy specify`, `cerebrofy plan`, and `cerebrofy tasks` — three CLI
commands that apply hybrid search (KNN cosine similarity on `vec_neurons` + BFS depth-2 on
`edges`) to a plain-language feature description and produce structured Markdown output. All
three commands share an identical search kernel running on a single read-only SQLite connection.
`cerebrofy specify` extends the search with an OpenAI-compatible LLM call that receives
selective lobe `.md` context, streams the response to stdout, and writes it to a timestamped
spec file. `cerebrofy plan` and `cerebrofy tasks` are fully offline — zero LLM, zero network.

**Research decisions applied**: Hybrid search executes in a single read-only SQLite connection
(Decision 1). LLM calls use the `openai` SDK with a `base_url` override (already an optional
dep from Phase 2) — no new dependency (Decision 2). System prompt uses Python `string.Template`
with `$lobe_context` variable; file override via `system_prompt_template` in config.yaml
(Decision 3). Output files: `YYYY-MM-DDTHH-MM-SS_spec.md` (hyphens for Windows compat)
(Decision 4). `--json` schema uses stable fields + `schema_version: 1` (Decision 5).
LLM timeout covers full wall-clock window from request to last token (Decision 6).

---

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: `click` ≥ 8.1, `sqlite-vec` ≥ 0.5, `openai` ≥ 1.0 (already optional dep from Phase 2 embeddings), `sentence-transformers` ≥ 2.2 (already required dep for local embedder)
**Storage**: SQLite via `cerebrofy.db` (read-only for all Phase 4 commands); single write: `docs/cerebrofy/specs/` output files
**Testing**: `pytest` with `tmp_path` for filesystem isolation; mock `openai` SDK for LLM unit tests
**Target Platform**: Linux, macOS, Windows (cross-platform file naming enforced by Decision 4)
**Project Type**: CLI tool (pip package)
**Performance Goals**: Hybrid search < 50ms on 10,000-node index (SC-001); first LLM token within 3s of invocation (SC-004)
**Constraints**: Zero new dependencies added to `pyproject.toml` (openai already optional); all Phase 4 commands strictly read-only on the index; no file-level locking needed (write-once distinct filenames)
**Scale/Scope**: Designed for repositories up to 10,000+ Neurons; `top_k` defaults to 10; lobe context must be ≤ 10% of total raw token count (SC-005)

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Design Gates

| Law | Requirement | Phase 4 Compliance |
|-----|-------------|-------------------|
| **Law I** (Law of Precedence) | Index MUST exist before spec is written; `cerebrofy specify` blocked without valid `cerebrofy.db` | ✅ FR-019 mandates schema version check + index existence check before any query; exit 1 with `cerebrofy build` direction if absent |
| **Law II** (Law of Structural Truth) | `RUNTIME_BOUNDARY` edges surfaced as warnings, never traversed during BFS | ✅ FR-002 explicitly excludes `RUNTIME_BOUNDARY` from BFS traversal; FR-009 requires separate warning output |
| **Law III** (Law of Semantic Intent) | KNN + BFS MUST run in same SQLite connection; zero IPC | ✅ FR-003 mandates single read-only SQLite connection; Decision 1 confirms single `open_db()` shared by both query phases |
| **Law IV** (Law of Autonomic Health) | Phase 4 commands must not write to the index | ✅ FR-020 mandates read-only access to index; only permitted write is spec output file |
| **Law V** (Law of Agnosticism) | No language-specific logic in core engine | ✅ Phase 4 operates only on existing `nodes`/`edges`/`vec_neurons` tables — no parser involvement |

**Storage & Data Architecture**:
- Single DB: Phase 4 uses existing `cerebrofy.db` via `open_db()` (read-only mode) ✅
- Atomic build: Not applicable (Phase 4 reads only) ✅
- `cerebrofy.db` is local: Phase 4 does not commit the DB ✅
- Schema versioning: FR-019 requires schema version check before any query ✅
- `cerebrofy init` scope: Not affected ✅

**Phase Gate**: Phase 4 requires Phase 2 (valid `cerebrofy.db`) and Phase 3 (`cerebrofy update` verified < 2s) to be complete before hard-block hook activates. Phase 4 itself does not affect hook behavior.

**Post-Design Re-check**: All laws satisfied. No constitution violations.

---

## Project Structure

### Documentation (this feature)

```text
specs/004-ai-bridge/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 — 6 research decisions
├── checklists/
│   └── requirements.md  # Spec quality checklist (all ✅)
├── data-model.md        # Phase 1 — in-memory data structures
├── quickstart.md        # Phase 1 — developer quickstart
├── contracts/           # Phase 1 — CLI contracts
│   ├── cli-specify.md
│   ├── cli-plan.md
│   └── cli-tasks.md
└── tasks.md             # Phase 2 — task list (created by /speckit.tasks)
```

### Source Code (repository root)

```text
src/cerebrofy/
├── search/
│   └── hybrid.py           ← NEW: HybridSearch — KNN + BFS, single read-only connection
├── llm/
│   ├── client.py           ← NEW: LLMClient — openai SDK wrapper, streaming + retry + timeout
│   └── prompt_builder.py   ← NEW: PromptBuilder — string.Template, lobe context injection
├── commands/
│   ├── specify.py          ← NEW: cerebrofy specify — hybrid search + LLM + file writer
│   ├── plan.py             ← NEW: cerebrofy plan — hybrid search + Markdown/JSON reporter
│   └── tasks.py            ← NEW: cerebrofy tasks — hybrid search + task list formatter
└── cli.py                  ← MODIFIED: register specify, plan, tasks commands

tests/
├── unit/
│   ├── test_hybrid_search.py    ← KNN + BFS logic, RUNTIME_BOUNDARY exclusion
│   ├── test_llm_client.py       ← streaming/non-streaming, retry, timeout (mock openai)
│   └── test_prompt_builder.py   ← template substitution, file override, missing file
└── integration/
    ├── test_specify_command.py  ← end-to-end with mock LLM endpoint
    ├── test_plan_command.py     ← end-to-end, --json, --top-k, offline
    └── test_tasks_command.py    ← end-to-end, RUNTIME_BOUNDARY notes, --top-k

docs/cerebrofy/specs/           ← OUTPUT: spec files written by cerebrofy specify
```

**Structure Decision**: Single-project layout extending the existing `src/cerebrofy/` tree.
New top-level modules `search/` and `llm/` are added alongside existing modules (`commands/`,
`parser/`, `db/`, `embedder/`, `graph/`). Three new `commands/*.py` files follow the existing
pattern (one file per CLI command). No new packages or sub-projects needed.

---

## Complexity Tracking

> No constitution violations requiring justification. All laws satisfied.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| N/A | — | — |
