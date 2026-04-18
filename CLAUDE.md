# Cerebrofy Development Guidelines

Auto-generated from feature plans. Last updated: 2026-04-04

## Active Technologies

- **Language**: Python 3.11+
- **CLI Framework**: `rich-click` ≥ 1.9.7
- **Parser**: `tree-sitter` ≥ 0.21 + `tree-sitter-languages` ≥ 1.10
- **Ignore matching**: `pathspec` ≥ 0.12 (gitignore dialect)
- **Config**: `PyYAML` ≥ 6.0
- **Vector storage**: `sqlite-vec` ≥ 0.5 (extends SQLite with `vec0` virtual table)
- **Embedding (local)**: `fastembed` ≥ 0.3 — `BAAI/bge-small-en-v1.5`, 384-dim, ONNX, offline, bundled in base install
- **Testing**: `pytest` with `tmp_path` for filesystem isolation
- **Distribution**: pip package + platform bundles (Homebrew, Snap, winget)
- **MCP server**: `mcp` ≥ 1.0 (optional extra: `uv tool install cerebrofy[mcp]`) — MCP stdio server for AI tool integration

## Project Structure

```text
src/
└── cerebrofy/
    ├── cli.py                   ← Click command group entry point
    ├── commands/init.py         ← cerebrofy init
    ├── commands/build.py        ← cerebrofy build: 6-step atomic pipeline orchestrator
    ├── parser/engine.py         ← Tree-sitter runner (.scm dispatch)
    ├── parser/neuron.py         ← Neuron dataclass + ParseResult
    ├── config/loader.py         ← CerebrоfyConfig dataclass; config.yaml I/O
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
    ├── embedder/local.py        ← LocalEmbedder (fastembed, BAAI/bge-small-en-v1.5, 384-dim, batch_size=64)
    ├── markdown/lobe.py         ← write_lobe_md(): [lobe]_lobe.md per Lobe (post-swap)
    ├── markdown/map.py          ← write_map_md(): cerebrofy_map.md (post-swap)
    ├── update/change_detector.py ← git commands + hash-comparison fallback → ChangeSet
    ├── update/scope_resolver.py  ← depth-2 BFS → UpdateScope (affected node IDs)
    ├── validate/drift_classifier.py ← hash scan + re-parse + Neuron diff → DriftRecord
    ├── commands/update.py       ← cerebrofy update: partial atomic re-index orchestrator
    ├── commands/validate.py     ← cerebrofy validate: drift classification command
    ├── commands/migrate.py      ← cerebrofy migrate: sequential schema migration runner
    ├── commands/mcp.py          ← cerebrofy mcp: MCP stdio server entry point
    └── mcp/server.py            ← MCPServer: 8 registered tools; 3 operational (cerebrofy_build,
                                    cerebrofy_update, cerebrofy_validate); 5 WIP stubs
                                    (search_code, get_neuron, list_lobes, plan, tasks —
                                    require search/hybrid.py and commands/plan.py etc.)
    └── queries/                 ← Bundled default .scm files per language
    # ⚠️ NOT YET IMPLEMENTED (referenced by MCP server stubs):
    #   search/hybrid.py        ← HybridSearch: KNN + BFS
    #   commands/plan.py        ← blast-radius reporter
    #   commands/tasks.py       ← numbered task list
    #   commands/specify.py     ← hybrid search + LLM spec writer
    #   commands/parse.py       ← diagnostic NDJSON parser
    #   llm/client.py           ← LLMClient: openai SDK wrapper
    #   llm/prompt_builder.py   ← PromptBuilder: string.Template
src/cerebrofy/skills/
├── installer.py             ← install_skills() + install_instructions(): skill templates + AI client navigation rules
└── templates/
    ├── cerebrofy-search/    ← search_code skill + slash command; ⚠️ never glob-read source files
    ├── cerebrofy-build/     ← full re-index skill
    ├── cerebrofy-update/    ← incremental re-index skill
    └── cerebrofy-validate/  ← drift check skill
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
    ├── test_tasks_command.py    ← cerebrofy tasks: task list, RUNTIME_BOUNDARY notes
    ├── test_parse_command.py    ← cerebrofy parse: NDJSON output, ignore rules, read-only
    └── test_mcp_command.py      ← cerebrofy mcp: tool call simulation, CWD routing, no-index error
packaging/
├── snap/snapcraft.yaml           ← Snap package (classic confinement, core22)
├── windows/nuitka_build.bat      ← Windows Nuitka build script
├── windows/installer.nsi         ← NSIS installer (adds %PATH%)
└── macos/build_bottle.sh         ← macOS binary build for Homebrew bottle
.github/
└── workflows/release.yml         ← Multi-platform release pipeline (matrix, fail-fast: false)
pyproject.toml
```

## Commands

```sh
# Install in dev mode (syncs all deps including dev group)
uv sync --group dev

# Run all tests
uv run pytest

# Run unit tests only
uv run pytest tests/unit/

# Run integration tests
uv run pytest tests/integration/

# Type check
uv run mypy src/

# Lint
uv run ruff check src/ tests/

# Run the CLI locally
cerebrofy --help
cerebrofy init .
cerebrofy init --here
cerebrofy init --here --ai [claude|copilot|opencode|vscode]
cerebrofy init --here --no-mcp
cerebrofy build
cerebrofy update --all
cerebrofy update <path>
cerebrofy validate


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
- **Neuron dedup**: Keep only the first occurrence per `{file}::{name}` within a file (by `line_start`). DB table: `nodes`.
- **Anonymous functions**: Always skip lambdas and anonymous arrow functions. Never produce a Neuron for them.
- **Markdown post-swap**: Lobe `.md` files and `cerebrofy_map.md` are written AFTER the atomic swap (Step 5, post Step 6).
- **Partial re-index transaction**: `cerebrofy update` uses `BEGIN IMMEDIATE` wrapping all DML. `sqlite-vec` `vec0` does NOT support UPDATE — always DELETE+INSERT within same transaction.
- **Hook upgrade**: `hooks/installer.py` upgrades pre-push hook from WARN-only (version 1) to hard-block (version 2) using `# cerebrofy-hook-version: N` marker within `# BEGIN cerebrofy` / `# END cerebrofy` sentinels.
- **Hard-block gate**: Hard-block pre-push hook MUST NOT be activated until `cerebrofy update` < 2s is verified (FR-003/FR-014).
- **Drift classification**: `validate/drift_classifier.py` compares Neuron `name` + whitespace-normalized `signature`. Minor = no structural change. Structural = any Neuron added/removed/renamed/sig-changed, or import added/removed.
- **Git detection**: `update/change_detector.py` uses `subprocess.run()` with explicit arg lists (never `shell=True`). Handle fresh-repo edge case: check `git rev-parse --verify HEAD` before running `git diff` commands.
- **cerebrofy_map.md on update**: `cerebrofy update` rewrites `cerebrofy_map.md` with new `state_hash` on every successful run (same as `cerebrofy build`).
- **Hybrid search connection** (⚠️ NOT YET IMPLEMENTED): When implemented, `search/hybrid.py` will open `cerebrofy.db` via `open_db()` with `?mode=ro` URI. KNN query and BFS traversal MUST share the same `sqlite3.Connection` object — zero IPC, zero serialization.
- **RUNTIME_BOUNDARY in BFS** (⚠️ NOT YET IMPLEMENTED): Phase 4 BFS will exclude `RUNTIME_BOUNDARY` edges from traversal. They are collected as `RuntimeBoundaryWarning` and displayed separately — never counted in blast radius.
- **Embedding before LLM call** (⚠️ NOT YET IMPLEMENTED): `cerebrofy specify` will embed the description query (same as `cerebrofy plan`/`tasks`) BEFORE opening the DB connection. The embed model must match `embed_model` in `cerebrofy.db` meta (FR-018).
- **Spec file atomicity** (⚠️ NOT YET IMPLEMENTED): `cerebrofy specify` will collect the full LLM response in memory before writing to disk. On timeout or error, no partial file is written.
- **`cerebrofy plan --json` schema**: Stable field names `matched_neurons`, `blast_radius`, `affected_lobes`, `reindex_scope` + `schema_version: 1`. All fields always present (empty `[]` if no results). No decorative text on stdout when `--json` is active.
- **System prompt template**: Resolved via `string.Template.safe_substitute()` with `$lobe_context`. File override path resolved relative to repo root. Built-in default lives in `llm/prompt_builder.py`.
- **Phase 4 read-only**: `cerebrofy specify`, `cerebrofy plan`, `cerebrofy tasks` MUST NOT write to `cerebrofy.db` or any tracked source file. The only permitted write is the spec output file in `docs/cerebrofy/specs/`.
- **cerebrofy parse read-only**: `cerebrofy parse` MUST NOT create or modify `cerebrofy.db` or any file. It uses `parser/engine.py` and `ignore/ruleset.py` directly. Output is NDJSON to stdout (one Neuron JSON per line).
- **MCP dispatcher**: `cerebrofy mcp` uses CWD routing — reads `os.getcwd()` at each tool call to find the active repo's `.cerebrofy/config.yaml`. Exactly one MCP entry (`mcpServers.cerebrofy`) per machine, shared across all repos.
- **MCP plan/tasks offline** (⚠️ NOT YET IMPLEMENTED): The MCP `plan` and `tasks` tools MUST NOT make network calls even if `llm_endpoint` is in `config.yaml`. LLM config is silently ignored (FR-027).
- **blast_count per-Neuron** (⚠️ NOT YET IMPLEMENTED): In `cerebrofy tasks` and `cerebrofy plan --json`, `blast_count` for each matched Neuron = count of BFS neighbors reachable from **that specific Neuron** (depth-2, excluding RUNTIME_BOUNDARY). NOT the total across all matched Neurons.
- **schema_version in plan --json** (⚠️ NOT YET IMPLEMENTED): The `cerebrofy plan --json` output MUST include `"schema_version": 1` as the first top-level field. This is a breaking addition from Phase 5 (FR-023).
- **Phase 4 read-only** (⚠️ NOT YET IMPLEMENTED): `cerebrofy specify`, `cerebrofy plan`, `cerebrofy tasks` MUST NOT write to `cerebrofy.db` or any tracked source file.
- **cerebrofy parse read-only** (⚠️ NOT YET IMPLEMENTED): `cerebrofy parse` MUST NOT create or modify `cerebrofy.db` or any file. Output is NDJSON to stdout (one Neuron JSON per line).
- **System prompt template** (⚠️ NOT YET IMPLEMENTED): Resolved via `string.Template.safe_substitute()` with `$lobe_context`. Built-in default lives in `llm/prompt_builder.py`.
- **.gitignore on init**: `cerebrofy init` MUST append `.cerebrofy/db/` to the repository's `.gitignore` (creating the file if needed, no duplicate if already present). This prevents `cerebrofy.db` from being staged (FR-019).
- **Hook sentinel format** (FR-020): The pre-push hook block MUST use `# BEGIN cerebrofy` / `# cerebrofy-hook-version: N` / `# END cerebrofy` sentinels. The incorrect `# cerebrofy-hook-start` / `# cerebrofy-hook-end` format in earlier cli-init.md is superseded by this invariant.

## Recent Changes

- **MCP server rewrite** (current): Rewrote `mcp/server.py` from scratch. Removed duplicate
  `run_mcp_server()` definition (second silently shadowed first). Registers **8 tools** but
  only 3 are fully operational: `cerebrofy_build`, `cerebrofy_update`, `cerebrofy_validate`
  (these shell out to the CLI). Five tools are stubs that fail at runtime: `search_code`,
  `get_neuron`, `list_lobes`, `plan`, `tasks` — they require `search/hybrid.py`,
  `commands/plan.py`, `commands/tasks.py` (not yet implemented), and `get_neuron`/`list_lobes`
  also query wrong table (`neurons` vs actual `nodes`) with wrong column names. Added
  `_open_db_ro()` helper. `_run_cerebrofy()` uses `sys.executable -m cerebrofy` (never shell).
  Added `_resolve_mcp_command()` to `mcp/registrar.py` — resolves absolute binary path at
  registration time (sys.argv[0] → shutil.which → sys.executable fallback). `--force` in
  `commands/init.py` now bypasses `has_cerebrofy_mcp_entry` check and always rewrites.
  `has_cerebrofy_mcp_entry` check and always rewrites. MCP extra install: `uv tool install
  "cerebrofy[mcp]"` (pip install also works).

- **AI enforcement layer** (current): Added `skills/installer.py` — `install_instructions()`
  writes a fenced navigation rules block (never glob-read, always use search_code, use
  cerebrofy_map.md and lobe summaries) to AI client instructions files (CLAUDE.md,
  .github/copilot-instructions.md, .opencode/instructions.md). Block is idempotent
  (marker-fenced replace). Added `cerebrofy-search/SKILL.md` and
  `cerebrofy-search/cerebrofy-search.prompt.md` skill templates. Added `--ai <client>` flag
  to `cerebrofy init`. Added `## ⚠️ Navigation rule` sections to existing skill SKILL.md files.

- **fastembed migration** (prior): Replaced `sentence-transformers` with `fastembed`.
  Model changed from `nomic-embed-text-v1` (768-dim) to `BAAI/bge-small-en-v1.5` (384-dim).
  Removed `embed_dim` from config schema (dimension fixed at 384). Removed `openai` and
  `cohere` embedding backends (`openai_emb.py`, `cohere_emb.py` deleted). Only extras
  remaining: `[mcp]`. `fastembed` is a base dependency (no extra required for embeddings).

- **005-distribution-release** (2026-04-04): Phase 5 — Added `cerebrofy parse` and initial
  `cerebrofy mcp` (3-tool version). Distribution packaging: Homebrew, Snap, winget, PyPI.
  GitHub Actions matrix pipeline. MCP registration auto-detection.

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
