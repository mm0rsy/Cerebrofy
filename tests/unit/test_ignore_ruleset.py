"""Unit tests for cerebrofy.ignore.ruleset."""

from __future__ import annotations

from pathlib import Path

from cerebrofy.ignore.ruleset import DEFAULT_IGNORE_CONTENT, IgnoreRuleSet


# ---------------------------------------------------------------------------
# Basic matching
# ---------------------------------------------------------------------------


def test_empty_ruleset_never_matches() -> None:
    rs = IgnoreRuleSet()
    assert not rs.matches("src/foo.py")
    assert not rs.matches("node_modules/index.js")


def test_matches_simple_pattern() -> None:
    rs = IgnoreRuleSet(cerebrofy_lines=["*.pyc"])
    assert rs.matches("src/__pycache__/foo.cpython-311.pyc")
    assert not rs.matches("src/foo.py")


def test_matches_directory_pattern() -> None:
    rs = IgnoreRuleSet(cerebrofy_lines=["node_modules/"])
    assert rs.matches("node_modules/react/index.js")
    assert not rs.matches("src/main.js")


def test_matches_combines_both_sources() -> None:
    rs = IgnoreRuleSet(
        cerebrofy_lines=["*.pyc"],
        git_lines=["dist/"],
    )
    assert rs.matches("src/foo.pyc")
    assert rs.matches("dist/bundle.js")
    assert not rs.matches("src/main.js")


def test_matches_git_lines_only() -> None:
    rs = IgnoreRuleSet(git_lines=["build/"])
    assert rs.matches("build/output.js")
    assert not rs.matches("src/output.js")


def test_default_ignore_content_covers_node_modules(tmp_path: Path) -> None:
    """The bundled DEFAULT_IGNORE_CONTENT should ignore node_modules/."""
    ignore_file = tmp_path / ".cerebrofy-ignore"
    ignore_file.write_text(DEFAULT_IGNORE_CONTENT, encoding="utf-8")
    rs = IgnoreRuleSet.from_directory(tmp_path)
    assert rs.matches("node_modules/lodash/index.js")


def test_default_ignore_content_covers_pycache(tmp_path: Path) -> None:
    ignore_file = tmp_path / ".cerebrofy-ignore"
    ignore_file.write_text(DEFAULT_IGNORE_CONTENT, encoding="utf-8")
    rs = IgnoreRuleSet.from_directory(tmp_path)
    assert rs.matches("__pycache__/foo.pyc")


def test_default_ignore_content_does_not_ignore_src(tmp_path: Path) -> None:
    ignore_file = tmp_path / ".cerebrofy-ignore"
    ignore_file.write_text(DEFAULT_IGNORE_CONTENT, encoding="utf-8")
    rs = IgnoreRuleSet.from_directory(tmp_path)
    assert not rs.matches("src/main.py")


# ---------------------------------------------------------------------------
# from_directory
# ---------------------------------------------------------------------------


def test_from_directory_reads_cerebrofy_ignore(tmp_path: Path) -> None:
    (tmp_path / ".cerebrofy-ignore").write_text("*.log\n", encoding="utf-8")
    rs = IgnoreRuleSet.from_directory(tmp_path)
    assert rs.matches("server.log")
    assert not rs.matches("server.py")


def test_from_directory_reads_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("secret.txt\n", encoding="utf-8")
    rs = IgnoreRuleSet.from_directory(tmp_path)
    assert rs.matches("secret.txt")


def test_from_directory_missing_files_produces_empty_ruleset(tmp_path: Path) -> None:
    # Neither .cerebrofy-ignore nor .gitignore exists
    rs = IgnoreRuleSet.from_directory(tmp_path)
    assert not rs.matches("anything.py")


def test_from_directory_merges_both_files(tmp_path: Path) -> None:
    (tmp_path / ".cerebrofy-ignore").write_text("*.min.js\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    rs = IgnoreRuleSet.from_directory(tmp_path)
    assert rs.matches("app.min.js")
    assert rs.matches(".env")
    assert not rs.matches("app.js")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_matches_dot_git() -> None:
    rs = IgnoreRuleSet(cerebrofy_lines=[".git/"])
    assert rs.matches(".git/config")
    assert not rs.matches("src/.git_notes")


def test_comment_lines_are_ignored() -> None:
    """Lines starting with # in pathspec are comments, not patterns."""
    rs = IgnoreRuleSet(cerebrofy_lines=["# this is a comment", "*.pyc"])
    assert rs.matches("foo.pyc")
    # The comment line itself should not produce a match
    assert not rs.matches("# this is a comment")
