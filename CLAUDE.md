# Cerebrofy Development Guidelines

Auto-generated from feature plans. Last updated: 2026-04-03

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
    └── queries/                 ← Bundled default .scm files per language
tests/
├── unit/                        ← Per-module unit tests
└── integration/
    ├── test_init_command.py
    └── test_build_command.py    ← Full cerebrofy build against tmp_path repos
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

## Recent Changes

- **002-build-engine** (2026-04-03): Phase 2 — Added `cerebrofy build` (6-step atomic pipeline).
  Introduced: `cerebrofy.db` schema (nodes, edges, meta, file_hashes, vec_neurons), graph resolver,
  Embedder ABC (local/OpenAI/Cohere), Markdown generator, BuildLock, state_hash computation.

- **001-sensory-foundation** (2026-04-03): Phase 1 — Added `cerebrofy init` (scaffold, hooks,
  MCP registration) and Universal Parser (Tree-sitter + .scm queries → Neuron records).
  Introduced: Neuron schema, CerebrофyConfig, IgnoreRuleSet, Lobe detection algorithm.

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
