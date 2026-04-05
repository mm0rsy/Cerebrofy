"""Integration tests for cerebrofy parse (T077)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from cerebrofy.cli import main


def _setup_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@cerebrofy.test"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "CerebrofyTest"],
        cwd=tmp_path, check=True, capture_output=True,
    )


def _init_repo(tmp_path: Path) -> None:
    """Run cerebrofy init in tmp_path."""
    runner = CliRunner()
    result = runner.invoke(main, ["init", "--no-mcp"], catch_exceptions=False)
    assert result.exit_code == 0, f"cerebrofy init failed:\n{result.output}"


# ---------------------------------------------------------------------------
# T077: test_parse_single_file
# ---------------------------------------------------------------------------


def test_parse_single_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """cerebrofy parse on a single Python file → NDJSON with expected function name."""
    monkeypatch.chdir(tmp_path)
    _setup_git_repo(tmp_path)

    src = tmp_path / "src" / "mymodule"
    src.mkdir(parents=True)
    py_file = src / "auth.py"
    py_file.write_text(
        "def authenticate(user: str, password: str) -> bool:\n"
        "    return user == 'admin' and password == 'secret'\n",
        encoding="utf-8",
    )

    _init_repo(tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["parse", str(py_file)], catch_exceptions=False)

    assert result.exit_code == 0, f"parse failed:\n{result.output}\n{result.output}"
    lines = [line for line in result.output.strip().split("\n") if line.strip()]
    assert len(lines) >= 1
    obj = json.loads(lines[0])
    assert obj["name"] == "authenticate"
    # Neuron uses "type" field; contract calls it "kind" — test against actual dataclass
    assert obj.get("type") in ("function", "async_function") or obj.get("kind") in ("function", "async_function")
    assert "line_start" in obj
    assert "file" in obj


def test_parse_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """cerebrofy parse on a directory → NDJSON from all tracked files."""
    monkeypatch.chdir(tmp_path)
    _setup_git_repo(tmp_path)

    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "a.py").write_text("def func_a(): pass\n", encoding="utf-8")
    (src / "b.py").write_text("def func_b(): pass\n", encoding="utf-8")

    _init_repo(tmp_path)

    runner = CliRunner()
    result = runner.invoke(main, ["parse", str(src)], catch_exceptions=False)

    assert result.exit_code == 0
    lines = [line for line in result.output.strip().split("\n") if line.strip()]
    names = {json.loads(line)["name"] for line in lines}
    assert "func_a" in names
    assert "func_b" in names


def test_parse_no_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """cerebrofy parse without .cerebrofy/config.yaml → exits with error."""
    monkeypatch.chdir(tmp_path)
    _setup_git_repo(tmp_path)

    py_file = tmp_path / "main.py"
    py_file.write_text("def main(): pass\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(main, ["parse", str(py_file)])
    assert result.exit_code != 0


def test_parse_does_not_create_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """cerebrofy parse MUST NOT create or modify cerebrofy.db (read-only invariant)."""
    monkeypatch.chdir(tmp_path)
    _setup_git_repo(tmp_path)

    py_file = tmp_path / "module.py"
    py_file.write_text("def my_func(): pass\n", encoding="utf-8")

    _init_repo(tmp_path)

    db_path = tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"
    assert not db_path.exists(), "cerebrofy.db should not exist before parse"

    runner = CliRunner()
    runner.invoke(main, ["parse", str(py_file)])

    assert not db_path.exists(), "cerebrofy parse MUST NOT create cerebrofy.db"
