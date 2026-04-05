# Implementation Plan: Phase 2 — The Build Engine

**Branch**: `002-build-engine` | **Date**: 2026-04-03 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/002-build-engine/spec.md`

---

## Summary

Build `cerebrofy build` — the single command that creates `cerebrofy.db` via a strictly ordered,
atomic 6-step pipeline: (0) create the database, (1) parse all tracked files via the Phase 1
parser, (2) build the local call graph, (3) resolve cross-module calls, (4) batch-embed all
Neurons via the configured embedding model, (5) write Markdown lobe documentation, (6) compute
`state_hash`, populate `file_hashes`, and atomically swap `.tmp → .db`. Markdown files are
written post-swap to guarantee consistency. The build is interruptible at any point — the prior
index is never corrupted.

---

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**:
  - `tree-sitter` ≥ 0.21 + `tree-sitter-languages` ≥ 1.10 — Phase 1 parser (reused as-is)
  - `sqlite-vec` ≥ 0.5 — sqlite-vec extension for `vec_neurons` virtual table
  - `sentence-transformers` ≥ 2.2 — local embedding model (`nomic-embed-text`, 768-dim)
  - `openai` ≥ 1.0 — optional OpenAI embedding (`text-embedding-3-small`, 1536-dim)
  - `cohere` ≥ 4.0 — optional Cohere embedding (`embed-english-v3.0`, 1024-dim)
  - `click` ≥ 8.1 — CLI framework (from Phase 1)
  - `PyYAML` ≥ 6.0 — config (from Phase 1)
  - `pathspec` ≥ 0.12 — ignore rules (from Phase 1)
**Storage**: Single SQLite file `.cerebrofy/db/cerebrofy.db` (graph + vector in one connection)
**Testing**: `pytest` with `tmp_path` fixture for filesystem isolation
**Target Platform**: macOS 12+, Linux (glibc ≥ 2.17), Windows 10/11
**Project Type**: CLI tool (pip package + platform bundles)
**Performance Goals**:
  - `cerebrofy build` completes on 10,000-file repo in under 5 minutes (SC-001)
  - Batch embedding: 10k neurons → ~30s (sentence-transformers at batch_size=64)
  - State hash computation: deterministic, < 1s for 10k files
**Constraints**:
  - MUST NOT open any write connection without checking `schema_version` (Constitution)
  - Atomic swap via `os.replace()` — both `.tmp` and `.db` in `.cerebrofy/db/` (same FS)
  - `RUNTIME_BOUNDARY` edges stored but NEVER traversed during BFS (Law II)
  - No language-specific logic in graph resolver — name-based lookup only (Law V)

---

## Constitution Check

*GATE: Must pass before implementation begins. Re-checked after Phase 1 design.*

### Law I — Law of Precedence ✅
`cerebrofy build` IS the creator of `cerebrofy.db`. Once this phase is complete, the index
exists and Phase 4 (`cerebrofy specify`) can operate. The spec explicitly states `cerebrofy build`
is the "sole creator" (FR-001). `cerebrofy init` MUST NOT create `cerebrofy.db` (Phase 1 plan
confirmed). **PASS.**

### Law II — Law of Structural Truth ✅
All call relationships are stored as typed edges in `cerebrofy.db` (`LOCAL_CALL`,
`EXTERNAL_CALL`, `IMPORT`, `RUNTIME_BOUNDARY`). O(1) per-edge lookup via indexed queries on
`(src_id)` and `(dst_id)`. `RUNTIME_BOUNDARY` edges are stored but explicitly excluded from
BFS traversal. The two-pass cross-module resolver is name-based and deterministic — no LLM
guessing. **PASS.**

### Law III — Law of Semantic Intent ✅
Every Neuron in `nodes` gets a corresponding vector in `vec_neurons` (Invariant 1+2 in
`db-schema.md`). `vec_neurons` lives in the same `cerebrofy.db` as the graph — same SQLite
connection, zero IPC. `embed_dim` is read from `config.yaml` at build time and injected into
the `CREATE VIRTUAL TABLE` DDL. Model switches require a full rebuild (drop + recreate
`vec_neurons`). **PASS.**

### Law IV — Law of Autonomic Health ✅
Phase 2 does not activate hard-block enforcement. The git hooks installed by Phase 1 are
WARN-only and call `cerebrofy validate --hook pre-push`. `cerebrofy validate` is implemented in
Phase 3 after `cerebrofy update` is verified. Phase 2 only creates the index that Phase 3
validation will diff against. **PASS — deferred correctly to Phase 3.**

### Law V — Law of Agnosticism ✅
The graph resolver uses name-based lookup only — no language-specific import semantics. The
Phase 1 parser engine (unchanged) handles all language-specific parsing via `.scm` files.
The `Embedder` ABC dispatches to three provider implementations but none contain
language-specific logic. **PASS.**

**Constitution Check: ALL 5 LAWS PASS. Implementation may proceed.**

---

## Project Structure

### Documentation (this feature)

```
specs/002-build-engine/
├── plan.md              ← This file
├── spec.md              ← Feature specification
├── research.md          ← Technology decisions and rationale
├── data-model.md        ← SQLite schema, Edge, BuildLock, LobeSummary, BuildResult entities
├── quickstart.md        ← End-to-end validation guide
├── contracts/
│   ├── cli-build.md     ← cerebrofy build CLI interface contract
│   └── db-schema.md     ← cerebrofy.db SQL schema contract (DDL + invariants)
└── checklists/
    └── requirements.md  ← Specification quality checklist
```

### Source Code (repository root)

```
src/
└── cerebrofy/
    ├── __init__.py
    ├── cli.py                       ← Add: register cerebrofy_build command
    ├── commands/
    │   ├── __init__.py
    │   ├── init.py                  ← Phase 1 (unchanged)
    │   └── build.py                 ← cerebrofy build: 6-step orchestrator + progress output
    ├── parser/
    │   ├── __init__.py
    │   ├── engine.py                ← Phase 1 (unchanged)
    │   └── neuron.py                ← Phase 1 (unchanged)
    ├── config/
    │   ├── __init__.py
    │   └── loader.py                ← Phase 1 (unchanged)
    ├── ignore/
    │   ├── __init__.py
    │   └── ruleset.py               ← Phase 1 (unchanged)
    ├── hooks/
    │   ├── __init__.py
    │   └── installer.py             ← Phase 1 (unchanged)
    ├── mcp/
    │   ├── __init__.py
    │   └── registrar.py             ← Phase 1 (unchanged)
    ├── db/                          ← NEW: database layer
    │   ├── __init__.py
    │   ├── connection.py            ← open_db(): load sqlite-vec, version check, WAL mode
    │   ├── schema.py                ← DDL constants: CREATE TABLE / INDEX statements
    │   ├── writer.py                ← write_nodes(), write_edges(), upsert_vectors(), write_file_hashes()
    │   └── lock.py                  ← BuildLock: acquire(), release(), check_stale()
    ├── graph/                       ← NEW: call graph resolver
    │   ├── __init__.py
    │   ├── resolver.py              ← two-pass name-lookup: build_name_registry(), resolve_edges()
    │   └── edges.py                 ← Edge dataclass + rel_type constants
    ├── embedder/                    ← NEW: embedding pipeline
    │   ├── __init__.py
    │   ├── base.py                  ← Embedder ABC: embed(texts: list[str]) -> list[list[float]]
    │   ├── local.py                 ← LocalEmbedder: sentence-transformers, batch_size=64
    │   ├── openai_emb.py            ← OpenAIEmbedder: text-embedding-3-small, chunks of 512
    │   └── cohere_emb.py            ← CohereEmbedder: embed-english-v3.0, chunks of 96
    ├── markdown/                    ← NEW: Markdown documentation generator
    │   ├── __init__.py
    │   ├── lobe.py                  ← write_lobe_md(conn, lobe_name, lobe_path, out_dir)
    │   └── map.py                   ← write_map_md(conn, lobes, state_hash, out_dir)
    └── queries/                     ← Phase 1 (unchanged)
        └── ...

tests/
├── unit/
│   ├── test_neuron.py               ← Phase 1 (unchanged)
│   ├── test_engine.py               ← Phase 1 (unchanged)
│   ├── test_config.py               ← Phase 1 (unchanged)
│   ├── test_ignore.py               ← Phase 1 (unchanged)
│   ├── test_hooks.py                ← Phase 1 (unchanged)
│   ├── test_mcp.py                  ← Phase 1 (unchanged)
│   ├── test_db_connection.py        ← sqlite-vec load, schema create, version check
│   ├── test_db_writer.py            ← node/edge/vector/hash write functions
│   ├── test_db_lock.py              ← lock acquire/release/stale-detection
│   ├── test_graph_resolver.py       ← name registry, LOCAL/EXTERNAL/BOUNDARY edge resolution
│   ├── test_embedder.py             ← all 3 embedder implementations (mock API calls)
│   └── test_markdown.py             ← lobe.md + cerebrofy_map.md generation
└── integration/
    ├── test_init_command.py         ← Phase 1 (unchanged)
    └── test_build_command.py        ← Full cerebrofy build against tmp_path repos

pyproject.toml                       ← Add new deps: sqlite-vec, sentence-transformers, openai, cohere
```

**Structure Decision**: Extend the Phase 1 single-project layout with four new domain modules
(`db/`, `graph/`, `embedder/`, `markdown/`). Each module is independently testable. The build
orchestrator in `commands/build.py` wires them together in the 6-step pipeline.

---

## Complexity Tracking

> No constitution violations. No unjustified complexity. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
