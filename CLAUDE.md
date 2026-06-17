# Cerebrofy Development Guidelines

Last updated: 2026-06-14

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
    └── mcp/server.py            ← MCPServer: 6 registered tools; all operational (cerebrofy_build,
                                    cerebrofy_update, cerebrofy_validate, get_neuron, list_lobes, search_code)
                                    — hybrid KNN + BFS search via search/hybrid.py
    └── queries/                 ← Bundled default .scm files per language
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
cerebrofy viz


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
- **Law IV**: Pre-push hook (v1) auto-runs `cerebrofy update` on drift, then proceeds. Only blocks if `cerebrofy update` itself fails. Hard-block mode (v2, no auto-update) is Phase 3.
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
- **Hybrid search connection**: `search/hybrid.py` opens `cerebrofy.db` via `?mode=ro` URI. KNN query and BFS traversal share the same `sqlite3.Connection` object — zero IPC, zero serialization.
- **RUNTIME_BOUNDARY in BFS**: BFS exclude `RUNTIME_BOUNDARY` edges from traversal. They are collected as `RuntimeBoundaryWarning` and displayed separately — never counted in blast radius.
- **MCP dispatcher**: `cerebrofy mcp` uses CWD routing — reads `os.getcwd()` at each tool call to find the active repo's `.cerebrofy/config.yaml`. Exactly one MCP entry (`mcpServers.cerebrofy`) per machine, shared across all repos.
- **.gitignore on init**: `cerebrofy init` MUST append `.cerebrofy/db/` to the repository's `.gitignore` (creating the file if needed, no duplicate if already present). This prevents `cerebrofy.db` from being staged (FR-019).
- **Hook sentinel format** (FR-020): The pre-push hook block MUST use `# BEGIN cerebrofy` / `# cerebrofy-hook-version: N` / `# END cerebrofy` sentinels. The incorrect `# cerebrofy-hook-start` / `# cerebrofy-hook-end` format in earlier cli-init.md is superseded by this invariant.

## Recent Changes

- **SpecKit removal** (2026-06-14): Removed dead plan/tasks/specify/parse/LLM coupling.
  Deleted `_handle_plan()`, `_handle_tasks()`, `_FEATURE_SCHEMA` from `mcp/server.py`.
  Fixed `_handle_get_neuron()` (table `neurons`→`nodes`, columns `node_type`→`type`,
  `start_line`/`end_line`→`line_start`/`line_end`) and `_handle_list_lobes()` (replaced
  crashing SQL with filesystem scan of `.cerebrofy/lobes/*_lobe.md`). Replaced
  `_handle_search_code()` crash-import with honest "not yet available" stub. Removed
  `llm_endpoint`/`llm_model`/`llm_timeout` from `CerebrофyConfig`. Archived
  `specs/004-ai-bridge/` → `specs/_archive/`. MCP server now has 6 registered tools:
  5 operational + 1 stub (search_code). `search/hybrid.py` is the sole remaining
  NOT YET IMPLEMENTED item.

- **cerebrofy viz + dead code removal** (2026-06-18): Added `cerebrofy viz` command — interactive
  3D brain visualization of the codebase call graph served at `http://localhost:7331`. Nodes use
  a flow-based red→green HSL gradient (red = pure sources, green = leaves) computed from
  `in_degree`/`out_degree`; source nodes placed at the cortex surface, interior nodes fill the
  full brain volume via uniform sphere sampling. Entry point detection is topology-based
  (`in_degree==0 && out_degree>0`), making viz portable to any Python project.
  Removed 4 confirmed dead-code items: `UpdateResult`, `_compute_new_state_hash`,
  `ValidationResult`, `read_mcp_config`. Fixed pre-push hook to auto-run `cerebrofy update`
  on drift instead of just blocking. Key files: `viz/graph_export.py`, `viz/server.py`,
  `viz/static/index.html`, `commands/viz.py`.

- **AI enforcement layer** (2026-06-14): Added `skills/installer.py` — `install_instructions()`
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


<!-- cerebrofy:start -->
## Codebase Navigation — Cerebrofy Index

This project's codebase is indexed by [Cerebrofy](https://github.com/mm0rsy/Cerebrofy).
The semantic index lives at `.cerebrofy/db/cerebrofy.db`.

**Navigation rules (enforced):**

1. **NEVER glob-read or recursively open source files** to understand the codebase.
   The index already contains every function, class, and module with embeddings.

2. **ALWAYS start with an MCP tool call** when asked about code structure or behaviour:
   - `search_code` — find code by meaning (semantic + graph search)
   - `get_neuron` — fetch a specific function or class by name or file:line
   - `list_lobes` — get the list of all modules with summary file paths

3. Use the pre-built summaries for orientation — no parsing needed:
   - `.cerebrofy/cerebrofy_map.md` — full codebase map
   - `.cerebrofy/lobes/<name>_lobe.md` — per-module summaries

4. **Only open a specific source file** after cerebrofy has returned its file path and
   line number — and only to read or edit *that exact location*.
<!-- cerebrofy:end -->
