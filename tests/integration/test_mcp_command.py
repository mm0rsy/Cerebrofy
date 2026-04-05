"""Integration tests for cerebrofy mcp (T078)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from cerebrofy.cli import main


# ---------------------------------------------------------------------------
# T078a: import guard — exits 1 with clear error when mcp package absent
# ---------------------------------------------------------------------------


def test_mcp_import_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """cerebrofy mcp without `mcp` package installed → exit 1 with helpful error."""
    import builtins
    real_import = builtins.__import__

    def import_blocker(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    runner = CliRunner()
    with patch("builtins.__import__", side_effect=import_blocker):
        result = runner.invoke(main, ["mcp"])

    assert result.exit_code == 1
    assert "mcp" in result.output.lower() or "mcp" in (result.exception or "")
    assert "pip install" in result.output or "cerebrofy[mcp]" in result.output


# ---------------------------------------------------------------------------
# T078b: plan tool returns schema_version: 1 (mocked transport)
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path, embed_dim: int = 2) -> Path:
    """Create a minimal valid cerebrofy.db."""
    import sqlite_vec  # type: ignore[import-untyped]
    from cerebrofy.db.connection import open_db
    from cerebrofy.db.schema import create_schema

    db_dir = tmp_path / ".cerebrofy" / "db"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "cerebrofy.db"

    conn = open_db(db_path)
    create_schema(conn, embed_dim=embed_dim)
    conn.execute("INSERT INTO meta VALUES (?, ?)", ("schema_version", "1"))
    conn.execute("INSERT INTO meta VALUES (?, ?)", ("embed_model", "local"))
    conn.execute("INSERT INTO meta VALUES (?, ?)", ("state_hash", "abc123"))
    conn.execute(
        "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("auth/login.py::login", "login", "auth/login.py",
         "function", 1, 10, "def login(user):", None, "h1"),
    )
    v = sqlite_vec.serialize_float32([1.0, 0.0])
    conn.execute("INSERT INTO vec_neurons VALUES (?, ?)", ("auth/login.py::login", v))
    conn.commit()
    conn.close()
    return db_path


def _make_config(tmp_path: Path) -> None:
    config_dir = tmp_path / ".cerebrofy"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(
        "lobes:\n  root: .\n"
        "tracked_extensions: [.py]\n"
        "embedding_model: local\n"
        "embed_dim: 2\n",
        encoding="utf-8",
    )


def test_mcp_plan_tool_schema_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP plan tool response contains schema_version: 1."""
    import sqlite_vec  # type: ignore[import-untyped]

    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)

    fake_embedding = sqlite_vec.serialize_float32([1.0, 0.0])

    with patch("cerebrofy.search.hybrid._embed_query", return_value=fake_embedding):
        from cerebrofy.mcp.server import _handle_plan
        result = _handle_plan({"description": "add login", "top_k": 2})

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert data["schema_version"] == 1
    assert "matched_neurons" in data
    assert "blast_radius" in data


def test_mcp_tasks_tool_returns_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP tasks tool returns a JSON object with 'tasks' array."""
    import sqlite_vec  # type: ignore[import-untyped]

    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)

    fake_embedding = sqlite_vec.serialize_float32([1.0, 0.0])

    with patch("cerebrofy.search.hybrid._embed_query", return_value=fake_embedding):
        from cerebrofy.mcp.server import _handle_tasks
        result = _handle_tasks({"description": "add login"})

    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "tasks" in data
    assert isinstance(data["tasks"], list)
