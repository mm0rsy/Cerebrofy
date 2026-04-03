# Cerebrofy Development Guidelines

Auto-generated from feature plans. Last updated: 2026-04-04

## Active Technologies

- **Language**: Python 3.11+
- **CLI Framework**: `click` ≥ 8.1
- **Parser**: `tree-sitter` ≥ 0.21 + `tree-sitter-languages` ≥ 1.10
- **Ignore matching**: `pathspec` ≥ 0.12 (gitignore dialect)
- **Config**: `PyYAML` ≥ 6.0
- **Vector storage**: `sqlite-vec` ≥ 0.5 (extends SQLite with `vec0` virtual table)
- **Embedding (local)**: `sentence-transformers` ≥ 2.2 — `nomic-embed-text-v1`, 768-dim, offline
- **Embedding (optional)**: `openai` ≥ 1.0 (1536-dim), `cohere` ≥ 4.0 (1024-dim)
- **Testing**: `pytest` with `tmp_path` for filesystem isolation
- **Distribution**: pip package + platform bundles (Homebrew, Snap, winget)

## Project Structure

```text
src/
└── cerebrofy/
    ├── cli.py                   ← Click command group entry point
    ├── commands/init.py         ← cerebrofy init
    ├── commands/build.py        ← cerebrofy build: 6-step atomic pipeline orchestrator
    ├── parser/engine.py         ← Tree-sitter runner (.scm dispatch)
    ├── parser/neuron.py         ← Neuron dataclass + ParseResult
    ├── config/loader.py         ← CerebrофyConfig dataclass; config.yaml I/O
    ├── ignore/ruleset.py        ← IgnoreRuleSet (pathspec)
    ├── hooks/installer.py       ← Git hook append/create/idempotency
    ├── mcp/registrar.py         ← MCP registration, fallback snippet
    ├── db/connection.py         ← open_db(): load sqlite-vec, schema version check
    ├── db/schema.py             ← DDL constants (CREATE TABLE / INDEX / VIRTUAL TABLE)
    ├── db/writer.py             ← write_nodes(), write_edges(), upsert_vectors(), write_file_hashes()
    ├── db/lock.py               ← BuildLock: PID lock file acquire/release/stale-check
    ├── graph/resolver.py        ← Two-pass name-lookup: build_name_registry(), resolve_edges()
    ├── graph/edges.py           ← Edge dataclass + rel_type constants
    ├── embedder/base.py         ← Embedder ABC: embed(texts) -> list[list[float]]
    ├── embedder/local.py        ← LocalEmbedder (sentence-transformers, batch_size=64)
    ├── embedder/openai_emb.py   ← OpenAIEmbedder (text-embedding-3-small, chunks of 512)
    ├── embedder/cohere_emb.py   ← CohereEmbedder (embed-english-v3.0, chunks of 96)
    ├── markdown/lobe.py         ← write_lobe_md(): [lobe]_lobe.md per Lobe (post-swap)
    ├── markdown/map.py          ← write_map_md(): cerebrofy_map.md (post-swap)
    ├── update/change_detector.py ← git commands + hash-comparison fallback → ChangeSet
    ├── update/scope_resolver.py  ← depth-2 BFS → UpdateScope (affected node IDs)
    ├── validate/drift_classifier.py ← hash scan + re-parse + Neuron diff → DriftRecord
    ├── commands/update.py       ← cerebrofy update: partial atomic re-index orchestrator
    ├── commands/validate.py     ← cerebrofy validate: drift classification command
    ├── commands/migrate.py      ← cerebrofy migrate: sequential schema migration runner
    ├── commands/specify.py      ← cerebrofy specify: hybrid search + LLM + spec writer
    ├── commands/plan.py         ← cerebrofy plan: hybrid search + Markdown/JSON reporter
    ├── commands/tasks.py        ← cerebrofy tasks: hybrid search + numbered task list
    ├── search/hybrid.py         ← HybridSearch: KNN + BFS, single read-only connection
    ├── llm/client.py            ← LLMClient: openai SDK wrapper, streaming + retry + timeout
    ├── llm/prompt_builder.py    ← PromptBuilder: string.Template, lobe context injection
    └── queries/                 ← Bundled default .scm files per language
tests/
├── unit/                        ← Per-module unit tests
└── integration/
    ├── test_init_command.py
    ├── test_build_command.py    ← Full cerebrofy build against tmp_path repos
    ├── test_update_command.py   ← Full cerebrofy update against tmp_path repos
    ├── test_validate_command.py ← Structural/minor drift scenarios
    ├── test_migrate_command.py  ← Schema migration with mock scripts
    ├── test_specify_command.py  ← cerebrofy specify with mock LLM endpoint
    ├── test_plan_command.py     ← cerebrofy plan: Markdown/JSON, --top-k, offline
    └── test_tasks_command.py    ← cerebrofy tasks: task list, RUNTIME_BOUNDARY notes
pyproject.toml
```

## Commands

```sh
# Install in dev mode
pip install -e ".[dev]"

# Run all tests
pytest

# Run unit tests only
pytest tests/unit/

# Run integration tests
pytest tests/integration/

# Type check
mypy src/

# Lint
ruff check src/ tests/

# Run the CLI locally
cerebrofy --help
cerebrofy init
cerebrofy init --force
cerebrofy parse <file-or-dir>
cerebrofy plan "add OAuth2 login"
cerebrofy plan --json "add OAuth2 login"
cerebrofy plan --top-k 20 "add rate limiting"
cerebrofy tasks "add OAuth2 login"
cerebrofy tasks --top-k 5 "add rate limiting"
cerebrofy specify "add OAuth2 login"
cerebrofy specify --top-k 5 "add OAuth2 login"
```

## Code Style

- Python: follow `ruff` defaults (PEP 8, line length 100)
- Type annotations: required on all public functions
- Dataclasses: use `@dataclass(frozen=True)` for Neuron and ParseResult (immutable value objects)
- No f-strings with complex logic — extract to a variable first
- Test isolation: always use `tmp_path` fixture; never touch the real filesystem in unit tests

## Key Invariants (from Constitution)

- **Law I**: `cerebrofy init` MUST NOT create `cerebrofy.db`. Never write to `.cerebrofy/db/` during init.
- **Law II**: All call edges stored in `edges` table. `RUNTIME_BOUNDARY` edges stored but NEVER traversed in BFS.
- **Law III**: Every Neuron in `nodes` MUST have a corresponding row in `vec_neurons` after a completed build.
- **Law IV**: Hooks are WARN-only in Phase 1. Hard-block (exit 1) is Phase 3 (after `cerebrofy update` verified).
- **Law V**: Zero language-specific logic in `parser/engine.py` or `graph/resolver.py`. All language rules in `.scm` files.
- **Atomic swap**: `cerebrofy build` writes to `cerebrofy.db.tmp`; swaps via `os.replace()` on success only.
- **Schema version check**: Every `open_db()` call MUST read `meta.schema_version` before any read or write.
- **Neuron dedup**: Keep only the first occurrence per `{file}::{name}` within a file (by `line_start`).
- **Anonymous functions**: Always skip lambdas and anonymous arrow functions. Never produce a Neuron for them.
- **Markdown post-swap**: Lobe `.md` files and `cerebrofy_map.md` are written AFTER the atomic swap (Step 5, post Step 6).
- **Partial re-index transaction**: `cerebrofy update` uses `BEGIN IMMEDIATE` wrapping all DML. `sqlite-vec` `vec0` does NOT support UPDATE — always DELETE+INSERT within same transaction.
- **Hook upgrade**: `hooks/installer.py` upgrades pre-push hook from WARN-only (version 1) to hard-block (version 2) using `# cerebrofy-hook-version: N` marker within `# BEGIN cerebrofy` / `# END cerebrofy` sentinels.
- **Hard-block gate**: Hard-block pre-push hook MUST NOT be activated until `cerebrofy update` < 2s is verified (FR-003/FR-014).
- **Drift classification**: `validate/drift_classifier.py` compares Neuron `name` + whitespace-normalized `signature`. Minor = no structural change. Structural = any Neuron added/removed/renamed/sig-changed, or import added/removed.
- **Git detection**: `update/change_detector.py` uses `subprocess.run()` with explicit arg lists (never `shell=True`). Handle fresh-repo edge case: check `git rev-parse --verify HEAD` before running `git diff` commands.
- **cerebrofy_map.md on update**: `cerebrofy update` rewrites `cerebrofy_map.md` with new `state_hash` on every successful run (same as `cerebrofy build`).
- **Hybrid search connection**: `search/hybrid.py` opens `cerebrofy.db` via `open_db()` with `?mode=ro` URI. KNN query and BFS traversal MUST share the same `sqlite3.Connection` object — zero IPC, zero serialization.
- **RUNTIME_BOUNDARY in BFS**: Phase 4 BFS excludes `RUNTIME_BOUNDARY` edges from traversal. They are collected as `RuntimeBoundaryWarning` and displayed separately — never counted in blast radius.
- **Embedding before LLM call**: `cerebrofy specify` embeds the description query (same as `cerebrofy plan`/`tasks`) BEFORE opening the DB connection. The embed model must match `embed_model` in `cerebrofy.db` meta (FR-018).
- **Spec file atomicity**: `cerebrofy specify` collects the full LLM response in memory before writing to disk. On timeout or error, no partial file is written.
- **`cerebrofy plan --json` schema**: Stable field names `matched_neurons`, `blast_radius`, `affected_lobes`, `reindex_scope` + `schema_version: 1`. All fields always present (empty `[]` if no results). No decorative text on stdout when `--json` is active.
- **System prompt template**: Resolved via `string.Template.safe_substitute()` with `$lobe_context`. File override path resolved relative to repo root. Built-in default lives in `llm/prompt_builder.py`.
- **Phase 4 read-only**: `cerebrofy specify`, `cerebrofy plan`, `cerebrofy tasks` MUST NOT write to `cerebrofy.db` or any tracked source file. The only permitted write is the spec output file in `docs/cerebrofy/specs/`.

## Recent Changes

- **004-ai-bridge** (2026-04-04): Phase 4 — Added `cerebrofy specify` (hybrid search + LLM +
  streaming spec writer), `cerebrofy plan` (hybrid search + Markdown/JSON impact reporter),
  `cerebrofy tasks` (hybrid search + numbered task list). Introduced: `search/hybrid.py`
  (HybridSearchResult, single read-only SQLite connection), `llm/client.py` (openai SDK
  wrapper, retry, timeout), `llm/prompt_builder.py` (string.Template, lobe context injection),
  `commands/specify.py`, `commands/plan.py`, `commands/tasks.py`.

- **003-autonomic-nervous-system** (2026-04-03): Phase 3 — Added `cerebrofy update` (partial
  atomic re-index, < 2s for single-file change), `cerebrofy validate` (tiered drift
  classification), `cerebrofy migrate` (sequential schema migration), and pre-push hook
  upgrade from WARN-only to hard-block. Introduced: ChangeSet, UpdateScope, DriftRecord,
  MigrationPlan, `update/`, `validate/` modules.

- **002-build-engine** (2026-04-03): Phase 2 — Added `cerebrofy build` (6-step atomic pipeline).
  Introduced: `cerebrofy.db` schema (nodes, edges, meta, file_hashes, vec_neurons), graph resolver,
  Embedder ABC (local/OpenAI/Cohere), Markdown generator, BuildLock, state_hash computation.

- **001-sensory-foundation** (2026-04-03): Phase 1 — Added `cerebrofy init` (scaffold, hooks,
  MCP registration) and Universal Parser (Tree-sitter + .scm queries → Neuron records).
  Introduced: Neuron schema, CerebrофyConfig, IgnoreRuleSet, Lobe detection algorithm.

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
