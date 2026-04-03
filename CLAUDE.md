# Cerebrofy Development Guidelines

Auto-generated from feature plans. Last updated: 2026-04-03

## Active Technologies

- **Language**: Python 3.11+
- **CLI Framework**: `click` ≥ 8.1
- **Parser**: `tree-sitter` ≥ 0.21 + `tree-sitter-languages` ≥ 1.10
- **Ignore matching**: `pathspec` ≥ 0.12 (gitignore dialect)
- **Config**: `PyYAML` ≥ 6.0
- **Testing**: `pytest` with `tmp_path` for filesystem isolation
- **Distribution**: pip package + platform bundles (Homebrew, Snap, winget)

## Project Structure

```text
src/
└── cerebrofy/
    ├── cli.py                   ← Click command group entry point
    ├── commands/init.py         ← cerebrofy init
    ├── parser/engine.py         ← Tree-sitter runner (.scm dispatch)
    ├── parser/neuron.py         ← Neuron dataclass + ParseResult
    ├── config/loader.py         ← CerebrофyConfig dataclass; config.yaml I/O
    ├── ignore/ruleset.py        ← IgnoreRuleSet (pathspec)
    ├── hooks/installer.py       ← Git hook append/create/idempotency
    ├── mcp/registrar.py         ← MCP registration, fallback snippet
    └── queries/                 ← Bundled default .scm files per language
tests/
├── unit/                        ← Per-module unit tests
└── integration/test_init_command.py
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
- **Law IV**: Hooks are WARN-only in Phase 1. The `cerebrofy validate --hook pre-push` command exits 0. Hard-block (exit 1) is Phase 3.
- **Law V**: Zero language-specific logic in `parser/engine.py`. All language rules live in `.scm` files.
- **Neuron dedup**: If two code units in the same file share the same name, keep only the first (by `line_start`).
- **Anonymous functions**: Always skip lambdas and anonymous arrow functions. Never produce a Neuron for them.

## Recent Changes

- **001-sensory-foundation** (2026-04-03): Phase 1 — Added `cerebrofy init` (scaffold, hooks,
  MCP registration) and Universal Parser (Tree-sitter + .scm queries → Neuron records).
  Introduced: Neuron schema, CerebrофyConfig, IgnoreRuleSet, LobE detection algorithm.

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
