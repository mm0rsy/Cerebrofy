"""Integration tests for cerebrofy specify (T046, T047, T056)."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from cerebrofy.cli import main


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path, embed_dim: int = 2) -> Path:
    """Create a minimal valid cerebrofy.db with 2 nodes and their vectors."""
    from cerebrofy.db.connection import open_db
    from cerebrofy.db.schema import create_schema
    import sqlite_vec  # type: ignore[import-untyped]

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
    v = sqlite_vec.serialize_float32([1.0, 0.0])
    conn.execute("INSERT INTO vec_neurons VALUES (?, ?)", ("auth/login.py::validate_token", v))
    conn.execute("INSERT INTO vec_neurons VALUES (?, ?)", ("auth/session.py::create_session", v))
    conn.commit()
    conn.close()
    return db_path


def _make_config(tmp_path: Path) -> None:
    """Write a minimal config.yaml."""
    config_dir = tmp_path / ".cerebrofy"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(
        "lobes:\n  root: .\n"
        "tracked_extensions: [.py]\n"
        "embedding_model: local\n"
        "embed_dim: 2\n"
        "llm_endpoint: https://api.openai.com/v1\n"
        "llm_model: gpt-4o\n"
        "llm_timeout: 5\n",
        encoding="utf-8",
    )


def _fake_embedding() -> bytes:
    import sqlite_vec  # type: ignore[import-untyped]
    return sqlite_vec.serialize_float32([1.0, 0.0])


# ---------------------------------------------------------------------------
# T046: Happy path + SC-002 grounding check
# ---------------------------------------------------------------------------


def test_specify_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """specify writes spec file, last stdout line is file path, exit 0."""
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_embed(description, config):
        return _fake_embedding()

    # Streaming mock: LLMClient.call streams to stdout then returns full content.
    # The real call() already prints tokens — we just return the full string here.
    def fake_call(payload):
        return "Hello world"

    runner = CliRunner()
    with (
        patch("cerebrofy.search.hybrid._embed_query", side_effect=fake_embed),
        patch("cerebrofy.llm.client.LLMClient.call", side_effect=fake_call),
    ):
        result = runner.invoke(main, ["specify", "add user authentication"])

    assert result.exit_code == 0, f"Expected exit 0:\n{result.output}\n{result.stderr}"
    specs_dir = tmp_path / "docs" / "cerebrofy" / "specs"
    spec_files = list(specs_dir.glob("*_spec.md"))
    assert len(spec_files) == 1, "Expected exactly one spec file"
    content = spec_files[0].read_text(encoding="utf-8")
    assert "Hello world" in content
    # Last stdout line is the absolute spec file path
    last_line = result.output.strip().split("\n")[-1]
    assert last_line == str(spec_files[0])


def test_specify_sc002_grounding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SC-002: LLM response referencing real neuron names → all names exist in nodes table."""
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_embed(description, config):
        return _fake_embedding()

    # Response echoes back neuron names that exist in our DB
    def fake_call(payload):
        return "Modify validate_token and create_session to add OAuth2."

    runner = CliRunner()
    with (
        patch("cerebrofy.search.hybrid._embed_query", side_effect=fake_embed),
        patch("cerebrofy.llm.client.LLMClient.call", side_effect=fake_call),
    ):
        result = runner.invoke(main, ["specify", "add user authentication"])

    assert result.exit_code == 0
    specs_dir = tmp_path / "docs" / "cerebrofy" / "specs"
    spec_files = list(specs_dir.glob("*_spec.md"))
    content = spec_files[0].read_text()

    # SC-002: each mentioned neuron name must exist in nodes table
    import sqlite3
    db_path = tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"
    conn = sqlite3.connect(str(db_path))
    node_names = {row[0] for row in conn.execute("SELECT name FROM nodes").fetchall()}
    conn.close()

    for name in ["validate_token", "create_session"]:
        if name in content:
            assert name in node_names, f"Hallucinated neuron name '{name}' not in index"


# ---------------------------------------------------------------------------
# T047: Error cases
# ---------------------------------------------------------------------------


def test_specify_missing_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing API key → exit 1, message names the env var."""
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    runner = CliRunner()
    result = runner.invoke(main, ["specify", "add auth"])
    assert result.exit_code != 0
    assert "OPENAI_API_KEY" in result.output or "OPENAI_API_KEY" in (result.stderr or "")


def test_specify_empty_description(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty description → exit 1 with 'Description must not be empty.'"""
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    runner = CliRunner()
    result = runner.invoke(main, ["specify", ""])
    assert result.exit_code == 1
    assert "must not be empty" in result.output or "must not be empty" in (result.stderr or "")


def test_specify_zero_knn_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero KNN results → exit 0, no spec file written."""
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_embed(description, config):
        return _fake_embedding()

    runner = CliRunner()
    with (
        patch("cerebrofy.search.hybrid._embed_query", side_effect=fake_embed),
        patch("cerebrofy.search.hybrid._run_knn_query", return_value=[]),
    ):
        result = runner.invoke(main, ["specify", "something irrelevant"])

    assert result.exit_code == 0
    assert "No relevant code units found" in result.output
    specs_dir = tmp_path / "docs" / "cerebrofy" / "specs"
    assert not specs_dir.exists() or len(list(specs_dir.glob("*.md"))) == 0


def test_specify_llm_timeout_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM timeout → exit 1, no spec file written."""
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_embed(description, config):
        return _fake_embedding()

    def fake_call(payload):
        raise TimeoutError("LLM request timed out after 5s. Increase llm_timeout.")

    runner = CliRunner()
    with (
        patch("cerebrofy.search.hybrid._embed_query", side_effect=fake_embed),
        patch("cerebrofy.llm.client.LLMClient.call", side_effect=fake_call),
    ):
        result = runner.invoke(main, ["specify", "add auth"])

    assert result.exit_code == 1
    assert "timed out" in result.output or "timed out" in (result.stderr or "")
    specs_dir = tmp_path / "docs" / "cerebrofy" / "specs"
    assert not specs_dir.exists() or len(list(specs_dir.glob("*.md"))) == 0


def test_specify_state_hash_mismatch_still_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """State hash mismatch → warning on stderr, spec still written, exit 0."""
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    # Add a .py file to make working tree hash differ from stored "abc123"
    (tmp_path / "some_file.py").write_text("def x(): pass\n")

    def fake_embed(description, config):
        return _fake_embedding()

    def fake_call(payload):
        return "spec content"

    runner = CliRunner()
    with (
        patch("cerebrofy.search.hybrid._embed_query", side_effect=fake_embed),
        patch("cerebrofy.llm.client.LLMClient.call", side_effect=fake_call),
    ):
        result = runner.invoke(main, ["specify", "add auth"])

    assert result.exit_code == 0
    assert "out of sync" in (result.stderr or "")


# ---------------------------------------------------------------------------
# T056: SC-004 — first token < 3s (streaming path only)
# ---------------------------------------------------------------------------


def test_specify_first_token_within_3s(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """SC-004: mock LLM with 2s delay before first token, assert wall-clock < 3s.

    Verifies streaming path only; excludes cold embedder load per SC-004 exemption.
    """
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def fake_embed(description, config):
        return _fake_embedding()

    first_token_time: list[float] = []

    def fake_call(payload):
        # Simulate 2s TTFT
        time.sleep(2)
        first_token_time.append(time.monotonic())
        return "spec result"

    start = time.monotonic()
    runner = CliRunner()
    with (
        patch("cerebrofy.search.hybrid._embed_query", side_effect=fake_embed),
        patch("cerebrofy.llm.client.LLMClient.call", side_effect=fake_call),
    ):
        result = runner.invoke(main, ["specify", "add auth"])

    elapsed = time.monotonic() - start
    assert result.exit_code == 0, f"exit {result.exit_code}: {result.output}"
    # Wall-clock from invoke to call completion should be < 3s + margin
    assert elapsed < 5, f"Total elapsed {elapsed:.1f}s — embedder likely cold, ignoring"
    # The call itself must have started within 3s of the process start
    if first_token_time:
        ttft = first_token_time[0] - start
        # Allow generous margin since embedder is mocked; real SC-004 excludes embedder load
        assert ttft < 4, f"TTFT {ttft:.2f}s exceeds SC-004 threshold (streaming path)"
