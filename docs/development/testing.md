# Testing

Cerebrofy has a comprehensive test suite covering unit tests, integration tests, and MCP integration tests.

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

## Test Philosophy

- **No mocking of the database.** Integration tests build a real `cerebrofy.db` in a temporary directory.
- **`tmp_path` fixture exclusively.** Integration tests never touch the real filesystem outside `tmp_path`.
- **Deterministic fixture graphs.** Caller-update lists and plan sequencing are asserted against deterministic fixture graphs.

## Test Structure

```
tests/
├── unit/                  # Fast tests, no filesystem or database
└── integration/           # Tests that build real cerebrofy.db in tmp_path
    ├── test_update_command.py
    ├── test_validate_command.py
    ├── test_migrate_command.py
    └── ...                # Additional MCP integration tests
```

## Writing Tests

### Unit Tests

Unit tests should be fast and not require the filesystem or database. They test pure functions and logic.

### Integration Tests

Integration tests use `pytest`'s `tmp_path` fixture to create temporary directories. They build real `cerebrofy.db` databases and test end-to-end flows:

```python
import pytest
from cerebrofy.commands.build import cerebrofy_build

def test_build_creates_database(tmp_path, runner):
    result = runner.invoke(cerebrofy_build, [], standalone_mode=False)
    assert result.exit_code == 0
    assert (tmp_path / ".cerebrofy" / "db" / "cerebrofy.db").exists()
```

## MCP Integration Tests

MCP integration tests require the `mcp` extra:

```bash
uv sync --extra mcp --group dev
uv run pytest
```

These tests verify that MCP tools are properly registered and return correct schemas.

## Related

- [Architecture](../concepts/architecture.md) — module map and data flow
- [Contributing](./contributing.md) — how to contribute to the project