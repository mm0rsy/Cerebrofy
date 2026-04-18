"""Integration tests for cerebrofy validate (T047)."""

from __future__ import annotations

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
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def _setup_git_repo(tmp_path: Path) -> None:
    _git(["git", "init"], tmp_path)
    _git(["git", "config", "user.email", "test@cerebrofy.test"], tmp_path)
    _git(["git", "config", "user.name", "CerebrofyTest"], tmp_path)

    src = tmp_path / "src" / "mymodule"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "module.py").write_text(
        "def existing(x: int) -> int:\n    return x + 1\n",
        encoding="utf-8",
    )

    _git(["git", "add", "."], tmp_path)
    _git(["git", "commit", "-m", "initial"], tmp_path)


def _init_and_build(runner: CliRunner) -> None:
    result = runner.invoke(main, ["init", "--no-mcp"])
    assert result.exit_code == 0, f"init failed:\n{result.output}"

    with patch("cerebrofy.commands.build.get_embedder", return_value=_FakeEmbedder()):
        result = runner.invoke(main, ["build"])
    assert result.exit_code == 0, f"build failed:\n{result.output}"


# ---------------------------------------------------------------------------
# T047 scenario 1: structural drift → exit 1
# ---------------------------------------------------------------------------


def test_validate_exits_1_on_structural_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Adding a new function without updating → validate exits 1 (structural drift)."""
    monkeypatch.chdir(tmp_path)
    _setup_git_repo(tmp_path)
    runner = CliRunner()
    _init_and_build(runner)

    # Add a new function without running update
    (tmp_path / "src" / "mymodule" / "module.py").write_text(
        "def existing(x: int) -> int:\n    return x + 1\n\n"
        "def new_function(y: int) -> int:\n    return y * 2\n",
        encoding="utf-8",
    )

    result = runner.invoke(main, ["validate"])
    assert result.exit_code == 1, f"Expected exit 1 on structural drift:\n{result.output}"
    assert "STRUCTURAL DRIFT" in result.output
    assert "new_function" in result.output


# ---------------------------------------------------------------------------
# T047 scenario 2: comment-only change → exit 0
# ---------------------------------------------------------------------------


def test_validate_exits_0_on_comment_only_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Comment-only change → minor drift only → validate exits 0."""
    monkeypatch.chdir(tmp_path)
    _setup_git_repo(tmp_path)
    runner = CliRunner()
    _init_and_build(runner)

    # Add only a comment — no new Neuron
    (tmp_path / "src" / "mymodule" / "module.py").write_text(
        "# A comment was added here\ndef existing(x: int) -> int:\n    return x + 1\n",
        encoding="utf-8",
    )

    result = runner.invoke(main, ["validate"])
    assert result.exit_code == 0, f"Expected exit 0 for comment-only change:\n{result.output}"
    assert "STRUCTURAL DRIFT" not in result.output
    # File hash changed but neurons unchanged → minor drift message
    assert "Minor drift" in result.output or "Index is current" in result.output


# ---------------------------------------------------------------------------
# T047 scenario 3: missing index → exit 0 (WARN-only)
# ---------------------------------------------------------------------------


def test_validate_exits_0_when_index_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing cerebrofy.db → validate exits 0 with a warning message (never blocks)."""
    monkeypatch.chdir(tmp_path)
    _setup_git_repo(tmp_path)
    runner = CliRunner()

    # init but no build → cerebrofy.db does not exist
    result = runner.invoke(main, ["init", "--no-mcp"])
    assert result.exit_code == 0

    result = runner.invoke(main, ["validate"])
    assert result.exit_code == 0, "Missing index must exit 0 (WARN-only, never blocks)"
    assert "No index found" in result.output
