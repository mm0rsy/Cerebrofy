"""Integration tests for cerebrofy changelog — CLI + MCP tool."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from cerebrofy.cli import main
from cerebrofy.embedder.base import Embedder


class _FakeEmbedder(Embedder):
    @property
    def dim(self) -> int:
        return 768

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 768 for _ in texts]


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture(scope="module")
def repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A git repo with a built Cerebrofy index tagged v1.0.0, then evolved."""
    root = tmp_path_factory.mktemp("clirepo")
    _git(["init", "-b", "main"], root)
    _git(["config", "user.email", "t@t.t"], root)
    _git(["config", "user.name", "t"], root)
    (root / "src").mkdir()
    (root / "src" / "m.py").write_text(
        "def existing(x: int) -> int:\n    return x\n", encoding="utf-8"
    )
    _git(["add", "."], root)
    _git(["commit", "-m", "init"], root)
    _git(["tag", "v1.0.0"], root)

    runner = CliRunner()
    orig = Path.cwd()
    os.chdir(root)
    try:
        r = runner.invoke(main, ["init", "--no-mcp"])
        assert r.exit_code == 0, r.output
        with patch("cerebrofy.commands.build.get_embedder", return_value=_FakeEmbedder()):
            r = runner.invoke(main, ["build"])
        assert r.exit_code == 0, r.output
    finally:
        os.chdir(orig)

    # Evolve: change a signature + add a new neuron, then commit (no re-index).
    (root / "src" / "m.py").write_text(
        "def existing(x: int, strict: bool = False) -> int:\n    return x\n"
        "def new_feature() -> int:\n    return 1\n",
        encoding="utf-8",
    )
    _git(["add", "."], root)
    _git(["commit", "-m", "feat: add new_feature, strict mode"], root)
    return root


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_changelog_no_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _git(["init", "-b", "main"], tmp_path)
    _git(["config", "user.email", "t@t.t"], tmp_path)
    _git(["config", "user.name", "t"], tmp_path)
    runner = CliRunner()
    runner.invoke(main, ["init", "--no-mcp"])
    result = runner.invoke(main, ["changelog", "--since", "v1.0.0"])
    assert result.exit_code == 1
    assert "[NO_INDEX]" in result.output


def test_cli_changelog_success(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo)
    runner = CliRunner()
    result = runner.invoke(main, ["changelog", "--since", "v1.0.0"])
    assert result.exit_code == 0, result.output
    assert "## Changelog" in result.output
    assert "new_feature" in result.output


def test_cli_changelog_ref_not_found(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo)
    runner = CliRunner()
    result = runner.invoke(main, ["changelog", "--since", "nope"])
    assert result.exit_code == 1
    assert "[REF_NOT_FOUND]" in result.output


def test_cli_changelog_format_github(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo)
    runner = CliRunner()
    result = runner.invoke(main, ["changelog", "--since", "v1.0.0", "--format", "github"])
    assert result.exit_code == 0, result.output
    assert "What's Changed" in result.output


def test_cli_changelog_format_slack(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo)
    runner = CliRunner()
    result = runner.invoke(main, ["changelog", "--since", "v1.0.0", "--format", "slack"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("*📦 Release")


def test_cli_changelog_invalid_audience(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo)
    runner = CliRunner()
    result = runner.invoke(main, ["changelog", "--since", "v1.0.0", "--audience", "boardroom"])
    assert result.exit_code == 2  # click rejects invalid choice


def test_cli_changelog_narrative_writes_events(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo)
    runner = CliRunner()
    result = runner.invoke(main, ["changelog", "--narrative", "--since", "v1.0.0"])
    assert result.exit_code == 0, result.output
    assert "narrative event" in result.output

    db = repo / ".cerebrofy" / "db" / "cerebrofy.db"
    conn = sqlite3.connect(db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM narrative_events").fetchone()[0]
    finally:
        conn.close()
    assert count > 0


def test_cli_changelog_narrative_idempotent(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running --narrative twice for the same range must not duplicate rows."""
    monkeypatch.chdir(repo)
    runner = CliRunner()
    runner.invoke(main, ["changelog", "--narrative", "--since", "v1.0.0"])
    runner.invoke(main, ["changelog", "--narrative", "--since", "v1.0.0"])
    db = repo / ".cerebrofy" / "db" / "cerebrofy.db"
    conn = sqlite3.connect(db)
    try:
        count = conn.execute("SELECT COUNT(*) FROM narrative_events").fetchone()[0]
    finally:
        conn.close()
    assert count > 0
    # Re-running replaced rows (INSERT OR REPLACE), not appended.
    runner.invoke(main, ["changelog", "--narrative", "--since", "v1.0.0"])
    conn = sqlite3.connect(db)
    try:
        count2 = conn.execute("SELECT COUNT(*) FROM narrative_events").fetchone()[0]
    finally:
        conn.close()
    assert count2 == count


# ---------------------------------------------------------------------------
# MCP tool
# ---------------------------------------------------------------------------


def test_mcp_changelog_no_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp.tools.changelog import handle_changelog

    monkeypatch.chdir(tmp_path)  # no .cerebrofy at all
    result = handle_changelog({"since": "v1.0.0"})
    assert "[NO_INDEX]" in result[0].text


def test_mcp_changelog_missing_since(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp.tools.changelog import handle_changelog

    monkeypatch.chdir(tmp_path)
    result = handle_changelog({})
    assert "[error]" in result[0].text and "since" in result[0].text.lower()


def test_mcp_changelog_invalid_audience(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp.tools.changelog import handle_changelog

    monkeypatch.chdir(repo)
    result = handle_changelog({"since": "v1.0.0", "audience": "boardroom"})
    assert "[error]" in result[0].text


def test_mcp_changelog_ref_not_found(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp.tools.changelog import handle_changelog

    monkeypatch.chdir(repo)
    result = handle_changelog({"since": "nope"})
    assert "[REF_NOT_FOUND]" in result[0].text


def test_mcp_changelog_returns_spec_schema(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp.tools.changelog import handle_changelog

    monkeypatch.chdir(repo)
    result = handle_changelog({"since": "v1.0.0", "audience": "pm", "format": "github"})
    data = json.loads(result[0].text)
    assert set(data) == {"since", "until", "entries", "breaking_changes", "health_delta", "full_text"}
    assert data["since"] == "v1.0.0"
    assert isinstance(data["entries"], list)
    assert isinstance(data["breaking_changes"], list)
    assert set(data["health_delta"]) == {"coupling", "avg_blast"}
    assert "What's Changed" in data["full_text"]
    if data["entries"]:
        assert set(data["entries"][0]) == {
            "type", "title", "description", "neurons", "blast_radius", "audience_text"
        }
