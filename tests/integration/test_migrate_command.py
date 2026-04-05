"""Integration tests for cerebrofy migrate (T055)."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlite_vec  # type: ignore[import-untyped]
from click.testing import CliRunner

from cerebrofy.cli import main
from cerebrofy.embedder.base import Embedder


class _FakeEmbedder(Embedder):
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * 768 for _ in texts]


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def _open_db(db_path: Path) -> sqlite3.Connection:
    """Open DB with sqlite-vec extension loaded."""
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _setup_indexed_repo(tmp_path: Path, runner: CliRunner) -> Path:
    """Create a git repo, run init + build, return the db_path."""
    _git(["git", "init"], tmp_path)
    _git(["git", "config", "user.email", "test@cerebrofy.test"], tmp_path)
    _git(["git", "config", "user.name", "CerebrofyTest"], tmp_path)

    src = tmp_path / "src" / "mymodule"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (src / "utils.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8"
    )
    _git(["git", "add", "."], tmp_path)
    _git(["git", "commit", "-m", "initial"], tmp_path)

    result = runner.invoke(main, ["init", "--no-mcp"])
    assert result.exit_code == 0, f"init failed:\n{result.output}"

    with patch("cerebrofy.commands.build.get_embedder", return_value=_FakeEmbedder()):
        result = runner.invoke(main, ["build"])
    assert result.exit_code == 0, f"build failed:\n{result.output}"

    return tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"


def _write_migration_script(migrations_dir: Path, from_v: int, to_v: int, sql: str = "") -> Path:
    """Write a minimal migration script."""
    migrations_dir.mkdir(parents=True, exist_ok=True)
    script = migrations_dir / f"v{from_v}_to_v{to_v}.py"
    body = sql if sql else "# no-op migration"
    script.write_text(
        f"def upgrade(conn):\n    conn.execute('SELECT 1')  # {body}\n",
        encoding="utf-8",
    )
    return script


# ---------------------------------------------------------------------------
# T055 scenario 1: successful migration
# ---------------------------------------------------------------------------


def test_migrate_applies_script_and_updates_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Downgrade schema to 0, write v0→v1 script, run migrate → schema_version = 1."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    db_path = _setup_indexed_repo(tmp_path, runner)

    # Downgrade schema_version to 0 for the test
    conn = _open_db(db_path)
    conn.execute("UPDATE meta SET value='0' WHERE key='schema_version'")
    conn.commit()
    conn.close()

    # Write the migration script
    migrations_dir = tmp_path / ".cerebrofy" / "scripts" / "migrations"
    _write_migration_script(migrations_dir, from_v=0, to_v=1)

    result = runner.invoke(main, ["migrate"])
    assert result.exit_code == 0, f"migrate failed:\n{result.output}"
    assert "v0" in result.output and "v1" in result.output

    # Confirm schema_version is now 1
    conn = _open_db(db_path)
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    conn.close()
    assert row is not None and row[0] == "1", f"Expected schema_version='1', got {row}"


# ---------------------------------------------------------------------------
# T055 scenario 2: already at target version
# ---------------------------------------------------------------------------


def test_migrate_already_current_exits_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Schema already at version 1 → migrate reports already current and exits 0."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    _setup_indexed_repo(tmp_path, runner)

    result = runner.invoke(main, ["migrate"])
    assert result.exit_code == 0, f"Expected exit 0:\n{result.output}"
    assert "Cerebrofy: Schema already at version" in result.output
    assert "Nothing to migrate" in result.output


def test_migrate_downgrade_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Schema newer than target → migrate exits 1 with a downgrade error."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    db_path = _setup_indexed_repo(tmp_path, runner)

    # Bump schema_version above the default target (1)
    conn = _open_db(db_path)
    conn.execute("UPDATE meta SET value='5' WHERE key='schema_version'")
    conn.commit()
    conn.close()

    result = runner.invoke(main, ["migrate", "--target", "1"])
    assert result.exit_code == 1
    assert "newer" in result.output.lower() or "newer" in str(result.exception).lower()


# ---------------------------------------------------------------------------
# T055 scenario 3: missing migration script → exit 1
# ---------------------------------------------------------------------------


def test_migrate_missing_script_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing migration script → migrate exits 1 with a clear error."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    db_path = _setup_indexed_repo(tmp_path, runner)

    # Downgrade schema_version to 0 but DON'T write the migration script
    conn = _open_db(db_path)
    conn.execute("UPDATE meta SET value='0' WHERE key='schema_version'")
    conn.commit()
    conn.close()

    result = runner.invoke(main, ["migrate"])
    assert result.exit_code == 1, f"Expected exit 1 for missing script:\n{result.output}"


# ---------------------------------------------------------------------------
# T055 scenario 4: missing index → exit 1
# ---------------------------------------------------------------------------


def test_migrate_missing_index_exits_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running migrate without a cerebrofy.db → exits 1."""
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(main, ["migrate"])
    assert result.exit_code == 1
