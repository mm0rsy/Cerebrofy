"""Unit tests for cerebrofy.update.change_detector (expanded)."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

from cerebrofy.update.change_detector import (
    ChangeSet,
    FileChange,
    _detect_via_hash,
    _is_git_repo,
    _run_git_cmd,
    detect_changes,
)


# ---------------------------------------------------------------------------
# _is_git_repo
# ---------------------------------------------------------------------------


def test_is_git_repo_false_for_plain_dir(tmp_path: Path) -> None:
    assert not _is_git_repo(tmp_path)


def test_is_git_repo_true_when_git_dir_exists(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    assert _is_git_repo(tmp_path)


# ---------------------------------------------------------------------------
# _run_git_cmd
# ---------------------------------------------------------------------------


def test_run_git_cmd_valid_command(tmp_path: Path) -> None:
    rc, out = _run_git_cmd(["git", "--version"], tmp_path)
    assert rc == 0
    assert "git" in out


def test_run_git_cmd_invalid_command(tmp_path: Path) -> None:
    rc, _ = _run_git_cmd(["git", "invalid-subcommand-xyz"], tmp_path)
    assert rc != 0


# ---------------------------------------------------------------------------
# _detect_via_hash
# ---------------------------------------------------------------------------


def test_detect_via_hash_finds_new_file(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"x=1")
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE file_hashes (file TEXT PRIMARY KEY, hash TEXT NOT NULL)")

    class Cfg:
        tracked_extensions = {".py"}

    result = _detect_via_hash(tmp_path, conn, Cfg())
    assert any(fc.path == "a.py" and fc.status == "A" for fc in result.changes)
    assert result.detected_via == "hash_comparison"


def test_detect_via_hash_finds_modified_file(tmp_path: Path) -> None:
    (tmp_path / "b.py").write_bytes(b"x=2")
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE file_hashes (file TEXT PRIMARY KEY, hash TEXT NOT NULL)")
    conn.execute("INSERT INTO file_hashes VALUES ('b.py', 'oldhash')")

    class Cfg:
        tracked_extensions = {".py"}

    result = _detect_via_hash(tmp_path, conn, Cfg())
    assert any(fc.path == "b.py" and fc.status == "M" for fc in result.changes)


def test_detect_via_hash_finds_deleted_file(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE file_hashes (file TEXT PRIMARY KEY, hash TEXT NOT NULL)")
    conn.execute("INSERT INTO file_hashes VALUES ('gone.py', 'oldhash')")

    class Cfg:
        tracked_extensions = {".py"}

    result = _detect_via_hash(tmp_path, conn, Cfg())
    assert any(fc.path == "gone.py" and fc.status == "D" for fc in result.changes)


def test_detect_via_hash_no_changes_when_hashes_match(tmp_path: Path) -> None:
    content = b"x=1"
    (tmp_path / "c.py").write_bytes(content)
    file_hash = hashlib.sha256(content).hexdigest()
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE file_hashes (file TEXT PRIMARY KEY, hash TEXT NOT NULL)")
    conn.execute("INSERT INTO file_hashes VALUES ('c.py', ?)", (file_hash,))

    class Cfg:
        tracked_extensions = {".py"}

    result = _detect_via_hash(tmp_path, conn, Cfg())
    assert not any(fc.path == "c.py" for fc in result.changes)


# ---------------------------------------------------------------------------
# detect_changes — explicit mode
# ---------------------------------------------------------------------------


def test_detect_changes_explicit_existing_file(tmp_path: Path) -> None:
    (tmp_path / "file.py").write_bytes(b"x=1")
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE file_hashes (file TEXT PRIMARY KEY, hash TEXT NOT NULL)")

    class Cfg:
        tracked_extensions = {".py"}

    result = detect_changes(tmp_path, conn, Cfg(), explicit_files=["file.py"])
    assert result.detected_via == "explicit"
    assert any(fc.path == "file.py" and fc.status == "M" for fc in result.changes)


def test_detect_changes_explicit_missing_file(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE file_hashes (file TEXT PRIMARY KEY, hash TEXT NOT NULL)")

    class Cfg:
        tracked_extensions = {".py"}

    result = detect_changes(tmp_path, conn, Cfg(), explicit_files=["missing.py"])
    assert result.detected_via == "explicit"
    assert any(fc.path == "missing.py" and fc.status == "D" for fc in result.changes)


def test_detect_changes_falls_back_to_hash_without_git(tmp_path: Path) -> None:
    (tmp_path / "z.py").write_bytes(b"z=0")
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE file_hashes (file TEXT PRIMARY KEY, hash TEXT NOT NULL)")

    class Cfg:
        tracked_extensions = {".py"}

    result = detect_changes(tmp_path, conn, Cfg(), explicit_files=None)
    assert result.detected_via == "hash_comparison"


# ---------------------------------------------------------------------------
# ChangeSet dataclass
# ---------------------------------------------------------------------------


def test_changeset_is_frozen() -> None:
    cs = ChangeSet(changes=(FileChange("a.py", "M"),), detected_via="git")
    with pytest.raises(Exception):
        cs.detected_via = "manual"  # type: ignore[misc]
