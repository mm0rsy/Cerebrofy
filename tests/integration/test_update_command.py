"""Integration tests for cerebrofy update (T037) and post-merge hook (T050)."""

from __future__ import annotations

import re
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from cerebrofy.cli import main
from cerebrofy.embedder.base import Embedder


class _FakeEmbedder(Embedder):
    """Returns zero vectors of dim 768 — avoids loading sentence-transformers."""

    @property
    def dim(self) -> int:
        return 768

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 768 for _ in texts]


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def _setup_git_repo(tmp_path: Path) -> None:
    """Initialize a git repo with one Python source file and an initial commit."""
    _git(["git", "init"], tmp_path)
    _git(["git", "config", "user.email", "test@cerebrofy.test"], tmp_path)
    _git(["git", "config", "user.name", "CerebrofyTest"], tmp_path)

    src = tmp_path / "src" / "mymodule"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "main.py").write_text(
        "def greet(name: str) -> str:\n    return f'Hello, {name}'\n",
        encoding="utf-8",
    )

    _git(["git", "add", "."], tmp_path)
    _git(["git", "commit", "-m", "initial"], tmp_path)


def _run_init_and_build(runner: CliRunner, repo_root: Path) -> None:
    """Run cerebrofy init (no-mcp) then build; commit all generated files so git is clean."""
    result = runner.invoke(main, ["init", "--no-mcp"])
    assert result.exit_code == 0, f"init failed:\n{result.output}"

    with patch("cerebrofy.commands.build.get_embedder", return_value=_FakeEmbedder()):
        result = runner.invoke(main, ["build"])
    assert result.exit_code == 0, f"build failed:\n{result.output}"

    # Commit all init-generated files (queries, config, ignore) so git is clean.
    # .cerebrofy/db/ is git-ignored; docs/ (map.md) should also be committed.
    _git(["git", "add", "."], repo_root)
    _git(["git", "commit", "-m", "cerebrofy init + build artifacts"], repo_root)


# ---------------------------------------------------------------------------
# T037: cerebrofy update — basic update flow
# ---------------------------------------------------------------------------


def test_update_detects_change_and_updates_state_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Edit one file, run update → state_hash changes; second run is a no-op."""
    monkeypatch.chdir(tmp_path)
    _setup_git_repo(tmp_path)
    runner = CliRunner()
    _run_init_and_build(runner, tmp_path)

    db_path = tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"
    conn = sqlite3.connect(str(db_path))
    hash_before = conn.execute(
        "SELECT value FROM meta WHERE key='state_hash'"
    ).fetchone()[0]
    conn.close()

    # Modify the file (unstaged — git diff HEAD picks it up)
    (tmp_path / "src" / "mymodule" / "main.py").write_text(
        "def greet(name: str) -> str:\n    return f'Hello, {name}'\n\n"
        "def farewell(name: str) -> str:\n    return f'Goodbye, {name}'\n",
        encoding="utf-8",
    )

    with patch("cerebrofy.commands.update.get_embedder", return_value=_FakeEmbedder()):
        result = runner.invoke(main, ["update"])
    assert result.exit_code == 0, f"update failed:\n{result.output}"
    assert "Update complete" in result.output

    conn = sqlite3.connect(str(db_path))
    hash_after = conn.execute(
        "SELECT value FROM meta WHERE key='state_hash'"
    ).fetchone()[0]
    conn.close()
    assert hash_after != hash_before, "state_hash should change after update"

    # Commit updated docs so git is clean for the no-op check
    _git(["git", "add", "."], tmp_path)
    _git(["git", "commit", "-m", "post-update docs"], tmp_path)

    # Second run: nothing new to detect → no-op
    with patch("cerebrofy.commands.update.get_embedder", return_value=_FakeEmbedder()):
        result = runner.invoke(main, ["update"])
    assert result.exit_code == 0
    assert "Nothing to update" in result.output


def test_update_then_validate_shows_no_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SC-002: after update, validate must report zero structural drift."""
    monkeypatch.chdir(tmp_path)
    _setup_git_repo(tmp_path)
    runner = CliRunner()
    _run_init_and_build(runner, tmp_path)

    # Add a new function
    (tmp_path / "src" / "mymodule" / "main.py").write_text(
        "def greet(name: str) -> str:\n    return f'Hello, {name}'\n\n"
        "def farewell(name: str) -> str:\n    return f'Goodbye, {name}'\n",
        encoding="utf-8",
    )

    with patch("cerebrofy.commands.update.get_embedder", return_value=_FakeEmbedder()):
        runner.invoke(main, ["update"])

    # validate must exit 0 after a successful update
    result = runner.invoke(main, ["validate"])
    assert result.exit_code == 0, f"validate should show no drift after update:\n{result.output}"
    assert "STRUCTURAL DRIFT" not in result.output


def test_update_no_changes_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no changed files, update should be a no-op."""
    monkeypatch.chdir(tmp_path)
    _setup_git_repo(tmp_path)
    runner = CliRunner()
    _run_init_and_build(runner, tmp_path)

    with patch("cerebrofy.commands.update.get_embedder", return_value=_FakeEmbedder()):
        result = runner.invoke(main, ["update"])
    assert result.exit_code == 0
    assert "Nothing to update" in result.output


def test_update_missing_index_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """update without a prior build should exit 1 with a clear error."""
    monkeypatch.chdir(tmp_path)
    _setup_git_repo(tmp_path)
    runner = CliRunner()

    result = runner.invoke(main, ["init", "--no-mcp"])
    assert result.exit_code == 0

    # No build → cerebrofy.db missing → exit 1
    result = runner.invoke(main, ["update"])
    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# T050: post-merge hook — state_hash sync check
# ---------------------------------------------------------------------------


def test_post_merge_hook_warns_on_hash_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Post-merge hook prints warning when cerebrofy_map.md state_hash differs from DB."""
    monkeypatch.chdir(tmp_path)
    _setup_git_repo(tmp_path)
    runner = CliRunner()
    _run_init_and_build(runner, tmp_path)

    hook_path = tmp_path / ".git" / "hooks" / "post-merge"
    assert hook_path.exists(), "post-merge hook should be installed by cerebrofy init"

    map_md = tmp_path / "docs" / "cerebrofy" / "cerebrofy_map.md"
    assert map_md.exists(), "cerebrofy_map.md should exist after build"

    # Replace the real state_hash with an all-zeros hash in the map file
    content = map_md.read_text(encoding="utf-8")
    fake_hash = "0" * 64
    new_content = re.sub(
        r"\*\*State Hash\*\*: `[a-f0-9]+'?",
        f"**State Hash**: `{fake_hash}`",
        content,
    )
    # Fallback: simple substitution if regex didn't match
    if new_content == content:
        new_content = content.replace(
            content.split("**State Hash**: `")[1][:64],
            fake_hash,
        )
    map_md.write_text(new_content, encoding="utf-8")

    result = subprocess.run(
        [str(hook_path)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, "post-merge hook must always exit 0 (WARN-only)"
    assert "Remote index state differs" in result.stderr, (
        f"Expected warning in stderr. Got: {result.stderr!r}"
    )


def test_post_merge_hook_silent_when_hashes_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Post-merge hook is silent when state_hashes agree."""
    monkeypatch.chdir(tmp_path)
    _setup_git_repo(tmp_path)
    runner = CliRunner()
    _run_init_and_build(runner, tmp_path)

    hook_path = tmp_path / ".git" / "hooks" / "post-merge"

    result = subprocess.run(
        [str(hook_path)],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stderr == "", f"No warning expected when hashes match. Got: {result.stderr!r}"
