# Implementation Plan: Phase 1 — Sensory Foundation

**Branch**: `001-sensory-foundation` | **Date**: 2026-04-03 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/001-sensory-foundation/spec.md`

---

## Summary

Build the two foundational Phase 1 components of Cerebrofy: the `cerebrofy init` command (which
scaffolds the `.cerebrofy/` directory, installs WARN-only git hooks, and auto-registers an MCP
server entry) and the Universal Parser (a Tree-sitter-based engine that extracts normalized
Neuron records from source files in any configured language via `.scm` query files, with no
language-specific logic in the core engine).

No `cerebrofy.db` is created in this phase. All parser output is in-memory, ready to be
consumed by `cerebrofy build` (Phase 2).

---

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**:
  - `tree-sitter` ≥ 0.21 — Query API for executing `.scm` captures
  - `tree-sitter-languages` ≥ 1.10 — Pre-compiled grammar wheels, 40+ languages, no C compiler needed
  - `pathspec` ≥ 0.12 — Full gitignore-dialect pattern matching for `.cerebrofy-ignore` + `.gitignore`
  - `PyYAML` ≥ 6.0 — `config.yaml` read/write
  - `click` ≥ 8.1 — CLI framework (entry point, command group, flags)
**Storage**: None in Phase 1 (no `cerebrofy.db`; that is Phase 2)
**Testing**: `pytest` with `tmp_path` fixture for filesystem isolation
**Target Platform**: macOS 12+, Linux (glibc ≥ 2.17), Windows 10/11
**Project Type**: CLI tool (distributed as pip package + platform-specific bundles)
**Performance Goals**: `cerebrofy init` completes in under 30 seconds on any size repo (SC-001)
**Constraints**:
  - MUST NOT create `cerebrofy.db` (Law I / FR-003)
  - Tree-sitter is the ONLY parser — no language-specific logic in engine code (Law V / FR-013)
  - Git hooks installed in WARN-only mode — hard-block NOT activated (Law IV / FR-004)

---

## Constitution Check

*GATE: Must pass before implementation begins. Re-checked after Phase 1 design.*

### Law I — Law of Precedence ✅
`cerebrofy init` MUST NOT create `cerebrofy.db`. The database is the sole product of
`cerebrofy build` (Phase 2). This plan: FR-003 explicitly prohibits DB creation; the contract
(`cli-init.md`) lists `cerebrofy.db` under "NOT created by cerebrofy init". **PASS.**

### Law II — Law of Structural Truth ✅
Phase 1 produces Neurons (raw data) but does not build the graph. No edges, no graph queries.
No hallucination risk in this phase — the parser reads source directly. The Neuron schema
(`neuron-schema.md`) is the contract that Phase 2 will consume to build the graph.
**PASS — deferred to Phase 2 where graph integrity is enforced.**

### Law III — Law of Semantic Intent ✅
No embedding in Phase 1. `vec_neurons` is created exclusively by `cerebrofy build` (Phase 2).
The `embed_dim` field in `config.yaml` is written by `cerebrofy init` but only consumed by
Phase 2. **PASS — deferred correctly to Phase 2.**

### Law IV — Law of Autonomic Health ✅
Git hooks installed in WARN-only mode (`cerebrofy validate --hook pre-push` exits 0 in this
mode). Hard-block (exit 1) MUST NOT be activated until `cerebrofy update` is implemented and
verified in Phase 3. The hook marker pattern (`# cerebrofy-hook-start`) is designed to allow
Phase 3 to upgrade the hook call without breaking idempotency. **PASS.**

### Law V — Law of Agnosticism ✅
Tree-sitter is the only parser. All language-specific extraction logic lives in `.scm` query
files in `.cerebrofy/queries/`. The engine (parser/engine.py) dispatches to query files; it
contains zero language-specific conditionals. Adding a new language requires only a new `.scm`
file — verified by FR-013 and SC-003. **PASS.**

**Constitution Check: ALL 5 LAWS PASS. Implementation may proceed.**

---

## Project Structure

### Documentation (this feature)

```
specs/001-sensory-foundation/
├── plan.md              ← This file
├── spec.md              ← Feature specification (with clarifications)
├── research.md          ← Technology decisions and rationale
├── data-model.md        ← Neuron, Lobe, Config, IgnoreRuleSet entities
├── quickstart.md        ← End-to-end validation guide
├── contracts/
│   ├── cli-init.md      ← cerebrofy init CLI interface contract
│   └── neuron-schema.md ← Parser output Neuron schema contract
└── checklists/
    └── requirements.md  ← Specification quality checklist
```

### Source Code (repository root)

```
src/
└── cerebrofy/
    ├── __init__.py
    ├── cli.py                   ← Click command group entry point
    ├── commands/
    │   ├── __init__.py
    │   └── init.py              ← cerebrofy init: scaffold + hooks + MCP
    ├── parser/
    │   ├── __init__.py
    │   ├── engine.py            ← Tree-sitter runner: loads .scm, runs queries, emits Neurons
    │   └── neuron.py            ← Neuron dataclass + ParseResult; extraction + dedup logic
    ├── config/
    │   ├── __init__.py
    │   └── loader.py            ← CerebrоfyConfig dataclass; config.yaml read/write/validate
    ├── ignore/
    │   ├── __init__.py
    │   └── ruleset.py           ← IgnoreRuleSet; merges .cerebrofy-ignore + .gitignore via pathspec
    ├── hooks/
    │   ├── __init__.py
    │   └── installer.py         ← Git hook append/create with idempotency marker
    ├── mcp/
    │   ├── __init__.py
    │   └── registrar.py         ← MCP config path detection, entry write, fallback snippet
    └── queries/                 ← Bundled default .scm files (copied to user repo by init)
        ├── python.scm
        ├── javascript.scm
        ├── typescript.scm
        ├── tsx.scm
        ├── jsx.scm
        ├── go.scm
        ├── rust.scm
        ├── java.scm
        ├── ruby.scm
        ├── c.scm
        ├── cpp.scm
        └── c_header.scm

tests/
├── unit/
│   ├── test_neuron.py           ← Neuron schema, dedup, type assignment rules
│   ├── test_engine.py           ← Parser engine: per-language extraction, anon skip
│   ├── test_config.py           ← Config read/write/validation
│   ├── test_ignore.py           ← IgnoreRuleSet: pathspec matching
│   ├── test_hooks.py            ← Hook append, create, idempotency marker
│   └── test_mcp.py              ← MCP path detection, idempotency, fallback snippet
└── integration/
    └── test_init_command.py     ← Full cerebrofy init run against tmp_path repos

pyproject.toml                   ← Build config, dependencies, entry point: cerebrofy=cerebrofy.cli:main
```

**Structure Decision**: Single project layout. Cerebrofy is a CLI tool with no frontend or
separate API layer. Modules are grouped by domain (parser, config, ignore, hooks, mcp) for
clear separation. The `queries/` directory inside the package acts as bundled resource files
copied to user repos during init.

---

## Complexity Tracking

> No constitution violations. No unjustified complexity. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| — | — | — |
