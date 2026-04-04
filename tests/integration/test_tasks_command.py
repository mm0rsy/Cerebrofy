"""Integration tests for cerebrofy tasks (T049)."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlite_vec  # type: ignore[import-untyped]
from click.testing import CliRunner

from cerebrofy.cli import main
from cerebrofy.graph.edges import RUNTIME_BOUNDARY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path, embed_dim: int = 2, add_runtime_edge: bool = False) -> Path:
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
        ("auth/login.py::validate_token", "validate_token", "auth/login.py",
         "function", 10, 20, "def validate_token(token):", None, "h1"),
    )
    conn.execute(
        "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("auth/session.py::create_session", "create_session", "auth/session.py",
         "function", 5, 15, "def create_session(user):", None, "h2"),
    )
    conn.execute(
        "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("ext::handler", "handler", "ext/handler.js", "function", 1, 10, None, None, "h3"),
    )
    v = sqlite_vec.serialize_float32([1.0, 0.0])
    conn.execute("INSERT INTO vec_neurons VALUES (?, ?)", ("auth/login.py::validate_token", v))
    conn.execute("INSERT INTO vec_neurons VALUES (?, ?)", ("auth/session.py::create_session", v))

    if add_runtime_edge:
        conn.execute(
            "INSERT INTO edges VALUES (?, ?, ?, ?)",
            ("auth/login.py::validate_token", "ext::handler", RUNTIME_BOUNDARY, "auth/login.py"),
        )

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


def _fake_embedding() -> bytes:
    return sqlite_vec.serialize_float32([1.0, 0.0])


# ---------------------------------------------------------------------------
# T049: cerebrofy tasks integration
# ---------------------------------------------------------------------------


def test_tasks_header(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Output starts with '# Cerebrofy Tasks: {description}'."""
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)

    runner = CliRunner()
    with patch("cerebrofy.search.hybrid._embed_query", return_value=_fake_embedding()):
        result = runner.invoke(main, ["tasks", "add user authentication"])

    assert result.exit_code == 0, f"tasks failed:\n{result.output}"
    assert result.output.startswith("# Cerebrofy Tasks: add user authentication")


def test_tasks_numbered_item_format(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each numbered item matches expected format regex."""
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)

    runner = CliRunner()
    with patch("cerebrofy.search.hybrid._embed_query", return_value=_fake_embedding()):
        result = runner.invoke(main, ["tasks", "add user authentication"])

    assert result.exit_code == 0
    pattern = re.compile(
        r"^\d+\. Modify \S+ in \[\[.+\]\] \(.+:\d+\) — blast radius: \d+ nodes$"
    )
    numbered_lines = [ln for ln in result.output.split("\n") if re.match(r"^\d+\.", ln)]
    assert len(numbered_lines) > 0
    for line in numbered_lines:
        assert pattern.match(line), f"Line does not match expected format: {line!r}"


def test_tasks_runtime_boundary_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """RUNTIME_BOUNDARY edge in DB → Note: line appears after numbered list."""
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path, add_runtime_edge=True)
    _make_config(tmp_path)

    runner = CliRunner()
    with patch("cerebrofy.search.hybrid._embed_query", return_value=_fake_embedding()):
        result = runner.invoke(main, ["tasks", "add user authentication"])

    assert result.exit_code == 0
    lines = result.output.split("\n")
    note_lines = [ln for ln in lines if ln.startswith("Note:")]
    assert len(note_lines) >= 1
    # Note lines must come after the numbered list
    numbered_positions = [i for i, ln in enumerate(lines) if re.match(r"^\d+\.", ln)]
    note_positions = [i for i, ln in enumerate(lines) if ln.startswith("Note:")]
    if numbered_positions and note_positions:
        assert max(numbered_positions) < min(note_positions)


def test_tasks_top_k_limits_items(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--top-k 1: exactly 1 task item in output."""
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)

    runner = CliRunner()
    with patch("cerebrofy.search.hybrid._embed_query", return_value=_fake_embedding()):
        result = runner.invoke(main, ["tasks", "--top-k", "1", "add user authentication"])

    assert result.exit_code == 0
    numbered_lines = [ln for ln in result.output.split("\n") if re.match(r"^\d+\.", ln)]
    assert len(numbered_lines) == 1
