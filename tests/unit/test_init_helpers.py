"""Unit tests for cerebrofy.commands.init helpers."""

from __future__ import annotations

from pathlib import Path

from cerebrofy.commands.init import (
    copy_query_files,
    create_scaffold_directories,
    detect_lobes,
    write_cerebrofy_ignore,
)


# ---------------------------------------------------------------------------
# detect_lobes
# ---------------------------------------------------------------------------


def test_detect_lobes_src_layout(tmp_path: Path) -> None:
    """src/ layout → each sub-directory becomes a Lobe."""
    src = tmp_path / "src"
    (src / "api").mkdir(parents=True)
    (src / "core").mkdir(parents=True)
    lobes = detect_lobes(tmp_path)
    assert "api" in lobes
    assert "core" in lobes
    assert lobes["api"] == "src/api/"
    assert lobes["core"] == "src/core/"


def test_detect_lobes_monorepo_layout(tmp_path: Path) -> None:
    """Top-level dirs containing a manifest become Lobes."""
    pkg_a = tmp_path / "pkg-a"
    pkg_a.mkdir()
    (pkg_a / "package.json").write_text("{}", encoding="utf-8")
    pkg_b = tmp_path / "pkg-b"
    pkg_b.mkdir()
    (pkg_b / "pyproject.toml").write_text("", encoding="utf-8")
    lobes = detect_lobes(tmp_path)
    assert "pkg-a" in lobes
    assert "pkg-b" in lobes


def test_detect_lobes_fallback_single_root(tmp_path: Path) -> None:
    """No src/, no manifests → all non-hidden top dirs become Lobes."""
    (tmp_path / "mydir").mkdir()
    lobes = detect_lobes(tmp_path)
    assert "mydir" in lobes


def test_detect_lobes_ignores_dot_dirs(tmp_path: Path) -> None:
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "visible").mkdir()
    lobes = detect_lobes(tmp_path)
    assert ".hidden" not in lobes
    assert "visible" in lobes


def test_detect_lobes_empty_root_returns_root_fallback(tmp_path: Path) -> None:
    """Completely empty directory → single 'root' Lobe."""
    lobes = detect_lobes(tmp_path)
    assert lobes == {"root": "."}


def test_detect_lobes_depth2_monorepo(tmp_path: Path) -> None:
    """Monorepo with manifest at depth-2 should be discovered."""
    packages = tmp_path / "packages"
    packages.mkdir()
    sub = packages / "my-lib"
    sub.mkdir()
    (sub / "package.json").write_text("{}", encoding="utf-8")
    lobes = detect_lobes(tmp_path)
    assert "my-lib" in lobes
    assert lobes["my-lib"] == "packages/my-lib/"


# ---------------------------------------------------------------------------
# create_scaffold_directories
# ---------------------------------------------------------------------------


def test_create_scaffold_directories_creates_db(tmp_path: Path) -> None:
    create_scaffold_directories(tmp_path)
    assert (tmp_path / ".cerebrofy" / "db").is_dir()


def test_create_scaffold_directories_creates_queries(tmp_path: Path) -> None:
    create_scaffold_directories(tmp_path)
    assert (tmp_path / ".cerebrofy" / "queries").is_dir()


def test_create_scaffold_directories_creates_migrations(tmp_path: Path) -> None:
    create_scaffold_directories(tmp_path)
    assert (tmp_path / ".cerebrofy" / "scripts" / "migrations").is_dir()


def test_create_scaffold_directories_is_idempotent(tmp_path: Path) -> None:
    create_scaffold_directories(tmp_path)
    create_scaffold_directories(tmp_path)  # Second call should not raise


# ---------------------------------------------------------------------------
# copy_query_files
# ---------------------------------------------------------------------------


def test_copy_query_files_copies_scm_files(tmp_path: Path) -> None:
    create_scaffold_directories(tmp_path)
    copy_query_files(tmp_path)
    dst = tmp_path / ".cerebrofy" / "queries"
    # At least one .scm file should be copied from the package
    scm_files = list(dst.glob("*.scm"))
    assert len(scm_files) > 0


def test_copy_query_files_does_not_overwrite_by_default(tmp_path: Path) -> None:
    create_scaffold_directories(tmp_path)
    copy_query_files(tmp_path)
    # Create a custom file
    dst = tmp_path / ".cerebrofy" / "queries"
    existing_scm = next(dst.glob("*.scm"), None)
    if existing_scm:
        existing_scm.write_text("CUSTOM", encoding="utf-8")
        copy_query_files(tmp_path, force=False)
        assert existing_scm.read_text() == "CUSTOM"


def test_copy_query_files_force_overwrites(tmp_path: Path) -> None:
    create_scaffold_directories(tmp_path)
    copy_query_files(tmp_path)
    dst = tmp_path / ".cerebrofy" / "queries"
    existing_scm = next(dst.glob("*.scm"), None)
    if existing_scm:
        existing_scm.write_text("CUSTOM", encoding="utf-8")
        copy_query_files(tmp_path, force=True)
        assert existing_scm.read_text() != "CUSTOM"


# ---------------------------------------------------------------------------
# write_cerebrofy_ignore
# ---------------------------------------------------------------------------


def test_write_cerebrofy_ignore_creates_file(tmp_path: Path) -> None:
    write_cerebrofy_ignore(tmp_path)
    assert (tmp_path / ".cerebrofy-ignore").exists()


def test_write_cerebrofy_ignore_has_default_content(tmp_path: Path) -> None:
    write_cerebrofy_ignore(tmp_path)
    content = (tmp_path / ".cerebrofy-ignore").read_text()
    assert "node_modules" in content


def test_write_cerebrofy_ignore_does_not_overwrite(tmp_path: Path) -> None:
    target = tmp_path / ".cerebrofy-ignore"
    target.write_text("CUSTOM IGNORE\n", encoding="utf-8")
    write_cerebrofy_ignore(tmp_path)
    assert target.read_text() == "CUSTOM IGNORE\n"
