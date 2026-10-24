# Contributing

Welcome to Cerebrofy! This guide covers how to contribute to the project, understand the architecture, and get your changes merged.

## Architecture Guide

Start with [Architecture](../concepts/architecture.md) — it covers the module map, data flow, key invariants, database schema, and extension points. Every contributor should read it before making changes.

## Setting Up the Development Environment

```bash
git clone https://github.com/mm0rsy/Cerebrofy
cd cerebrofy
uv sync --group dev
```

## Running Tests

```bash
# All tests
uv run pytest

# Unit tests only (fast, no filesystem)
uv run pytest tests/unit/

# Integration tests (use tmp_path, build real cerebrofy.db)
uv run pytest tests/integration/

# Full suite including MCP integration tests
uv sync --extra mcp --group dev
uv run pytest
```

Integration tests use `pytest`'s `tmp_path` fixture exclusively — they never touch the real filesystem outside `tmp_path`. No mocking of the database; tests build a real `cerebrofy.db` in a temporary directory.

## Linting

```bash
uv run ruff check src/ tests/
```

## Type Checking

```bash
uv run mypy src/
```

## Key Architectural Laws

These rules are invariants. No PR may violate them:

| # | Invariant |
|---|-----------|
| I | `cerebrofy init` MUST NOT create `cerebrofy.db`. The database is created exclusively by `cerebrofy build`. |
| II | All call edges are stored in the `edges` table. `RUNTIME_BOUNDARY` edges are stored but NEVER traversed in BFS. |
| III | Every Neuron in `nodes` MUST have a corresponding row in `vec_neurons` after a completed build. |
| IV | Git hooks start warn-only (v1). Hard-block (v2) activates only after `cerebrofy update` is verified to run in < 2s. |
| V | Zero language-specific logic in `parser/engine.py` or `graph/resolver.py`. All language rules live in `.scm` files. |

## Adding a New CLI Command

1. Create `src/cerebrofy/commands/<name>.py` with a Click command function
2. Register it in `src/cerebrofy/cli.py` (`main.add_command(...)`)
3. Add documentation under `docs/features/` or `docs/reference/`
4. Add tests under `tests/unit/` or `tests/integration/`

## Adding a New MCP Tool

1. Create `src/cerebrofy/mcp/tools/<name>.py` with a handler function
2. Register the tool spec in `src/cerebrofy/mcp/tool_specs.py`
3. Add documentation under `docs/reference/mcp-tools.md` and the relevant feature guide
4. Add tests under `tests/integration/`

## Adding Language Support

Cerebrofy is designed so that new language support requires zero changes to the Python engine. You only need to provide a Tree-sitter `.scm` query file:

1. Verify the language is in `EXTENSION_TO_LANGUAGE` in `parser/engine.py`
2. Create `.cerebrofy/queries/<lang>.scm` with captures for `definition.name`, `definition.node`, `call.name`, and `import.path`
3. Add the extension to `tracked_extensions` in `.cerebrofy/config.yaml`
4. Run `cerebrofy build` to index the new language

## Pull Request Process

1. Fork the repository and create a feature branch
2. Make your changes following the architectural laws above
3. Add or update tests
4. Run `uv run pytest`, `uv run ruff check`, and `uv run mypy`
5. Update documentation under `docs/` if your change affects user-facing behavior
6. Open a pull request with a clear description of the changes

## License

MIT