"""Integration tests for cerebrofy plan (T048, T050, T054)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlite_vec  # type: ignore[import-untyped]
from click.testing import CliRunner

from cerebrofy.cli import main
from cerebrofy.search.hybrid import MatchedNeuron


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path, embed_dim: int = 2) -> Path:
    """Create a minimal valid cerebrofy.db."""
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
    v = sqlite_vec.serialize_float32([1.0, 0.0])
    conn.execute("INSERT INTO vec_neurons VALUES (?, ?)", ("auth/login.py::validate_token", v))
    conn.execute("INSERT INTO vec_neurons VALUES (?, ?)", ("auth/session.py::create_session", v))
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


def _two_neurons() -> list[MatchedNeuron]:
    return [
        MatchedNeuron(
            id="auth/login.py::validate_token", name="validate_token",
            file="auth/login.py", line_start=10, similarity=0.91,
        ),
        MatchedNeuron(
            id="auth/session.py::create_session", name="create_session",
            file="auth/session.py", line_start=5, similarity=0.85,
        ),
    ]


# ---------------------------------------------------------------------------
# T048: cerebrofy plan integration
# ---------------------------------------------------------------------------


def test_plan_markdown_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Default output: all 4 Markdown sections present, query in header."""
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)

    runner = CliRunner()
    with patch("cerebrofy.search.hybrid._embed_query", return_value=_fake_embedding()):
        result = runner.invoke(main, ["plan", "add user authentication"])

    assert result.exit_code == 0, f"plan failed:\n{result.output}"
    assert "# Cerebrofy Plan: add user authentication" in result.output
    assert "## Matched Neurons" in result.output
    assert "## Blast Radius" in result.output
    assert "## Affected Lobes" in result.output
    assert "## Re-index Scope" in result.output


def test_plan_json_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--json: valid JSON with all fields + schema_version=1; no decorative text."""
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)

    runner = CliRunner()
    with patch("cerebrofy.search.hybrid._embed_query", return_value=_fake_embedding()):
        result = runner.invoke(main, ["plan", "--json", "add user authentication"])

    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["schema_version"] == 1
    assert "matched_neurons" in parsed
    assert "blast_radius" in parsed
    assert "affected_lobes" in parsed
    assert "reindex_scope" in parsed


def test_plan_top_k_limits_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--top-k 1: at most 1 matched neuron row in output."""
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)

    runner = CliRunner()
    with patch("cerebrofy.search.hybrid._embed_query", return_value=_fake_embedding()):
        result = runner.invoke(main, ["plan", "--top-k", "1", "add user authentication"])

    assert result.exit_code == 0
    parsed_lines = [line for line in result.output.split("\n") if line.startswith("| 1 |") or line.startswith("| 2 |")]
    assert not any(line.startswith("| 2 |") for line in parsed_lines), "Should have at most 1 row"


def test_plan_no_network_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """plan makes zero network calls (offline, mock embedder)."""
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)

    def no_network(*args, **kwargs):
        raise AssertionError(f"plan made a network call: {args}")

    runner = CliRunner()
    with (
        patch("cerebrofy.search.hybrid._embed_query", return_value=_fake_embedding()),
        patch("socket.getaddrinfo", side_effect=no_network),
    ):
        result = runner.invoke(main, ["plan", "add user authentication"])

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# T050: Read-only invariant (FR-020)
# ---------------------------------------------------------------------------


def test_plan_does_not_modify_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """cerebrofy plan must not modify cerebrofy.db (FR-020)."""
    monkeypatch.chdir(tmp_path)
    db_path = _make_db(tmp_path)
    _make_config(tmp_path)

    mtime_before = db_path.stat().st_mtime

    runner = CliRunner()
    with patch("cerebrofy.search.hybrid._embed_query", return_value=_fake_embedding()):
        runner.invoke(main, ["plan", "add user authentication"])

    mtime_after = db_path.stat().st_mtime
    assert mtime_before == mtime_after, "cerebrofy plan must not write to cerebrofy.db"


def test_tasks_does_not_modify_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """cerebrofy tasks must not modify cerebrofy.db (FR-020)."""
    monkeypatch.chdir(tmp_path)
    db_path = _make_db(tmp_path)
    _make_config(tmp_path)

    mtime_before = db_path.stat().st_mtime

    runner = CliRunner()
    with patch("cerebrofy.search.hybrid._embed_query", return_value=_fake_embedding()):
        runner.invoke(main, ["tasks", "add user authentication"])

    mtime_after = db_path.stat().st_mtime
    assert mtime_before == mtime_after, "cerebrofy tasks must not write to cerebrofy.db"


# ---------------------------------------------------------------------------
# T054: SC-003 — plan/tasks parity
# ---------------------------------------------------------------------------


def test_plan_tasks_matched_neurons_parity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """plan and tasks with same query + --top-k return identical matched neuron IDs."""
    monkeypatch.chdir(tmp_path)
    _make_db(tmp_path)
    _make_config(tmp_path)

    runner = CliRunner()

    with patch("cerebrofy.search.hybrid._embed_query", return_value=_fake_embedding()):
        plan_result = runner.invoke(main, ["plan", "--json", "--top-k", "2", "add user authentication"])

    with patch("cerebrofy.search.hybrid._embed_query", return_value=_fake_embedding()):
        tasks_result = runner.invoke(main, ["tasks", "--top-k", "2", "add user authentication"])

    assert plan_result.exit_code == 0
    assert tasks_result.exit_code == 0

    plan_json = json.loads(plan_result.output)
    # Extract neuron names from tasks output
    import re
    tasks_names = re.findall(r"\d+\. Modify (\S+) in", tasks_result.output)

    plan_names = {n["name"] for n in plan_json["matched_neurons"]}
    assert set(tasks_names) == plan_names, (
        f"plan matched {plan_names}, tasks matched {set(tasks_names)}"
    )
