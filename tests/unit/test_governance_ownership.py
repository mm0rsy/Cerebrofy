"""Unit tests for governance ownership + CODEOWNERS generation (Idea #18).

Git repos are created under ``tmp_path`` with explicit author/date env vars so
blame and activity-window assertions are deterministic and offline.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cerebrofy.config.loader import CerebrоfyConfig, GovernanceConfig
from cerebrofy.db.schema import EDGES_DDL, NODES_DDL
from cerebrofy.errors import NoGitHistoryError
from cerebrofy.governance.codeowners import (
    generate_codeowners,
    is_generated_codeowners,
    write_codeowners,
)
from cerebrofy.governance.ownership import (
    compute_all_lobe_ownership,
    compute_lobe_ownership,
    cross_lobe_callers,
    lobe_for_file,
    max_blast_radius,
)


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")


def _commit(
    repo: Path,
    message: str,
    author: str,
    email: str,
    *,
    days_ago: int = 400,
) -> None:
    when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime(
        "%Y-%m-%dT%H:%M:%S+00:00"
    )
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": author,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_AUTHOR_DATE": when,
            "GIT_COMMITTER_NAME": author,
            "GIT_COMMITTER_EMAIL": email,
            "GIT_COMMITTER_DATE": when,
        }
    )
    _git(repo, "add", "-A", env=env)
    _git(repo, "commit", "-q", "-m", message, env=env)


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "auth").mkdir()
    (repo / "auth" / "a.py").write_text(
        "def a1():\n    return 1\n\n\ndef a2():\n    return 2\n", encoding="utf-8"
    )
    _commit(repo, "auth", "Alice", "alice@example.com")
    (repo / "api").mkdir()
    (repo / "api" / "b.py").write_text(
        "def b1():\n    return 1\n\ndef b2():\n    return 2\n\ndef b3():\n    return 3\n",
        encoding="utf-8",
    )
    (repo / "auth" / "a.py").write_text(
        "def a1():\n    return 1\n\n\ndef a2():\n    return 3\n", encoding="utf-8"
    )
    _commit(repo, "api + tweak", "Bob", "bob@example.com", days_ago=10)
    return repo


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(NODES_DDL)
    conn.execute(EDGES_DDL)
    return conn


def _seed_nodes(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO nodes (id, name, file, type, line_start, line_end) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("auth/a.py::a1", "a1", "auth/a.py", "function", 1, 2),
            ("auth/a.py::a2", "a2", "auth/a.py", "function", 5, 6),
            ("api/b.py::b1", "b1", "api/b.py", "function", 1, 2),
            ("api/b.py::b2", "b2", "api/b.py", "function", 4, 5),
            ("api/b.py::b3", "b3", "api/b.py", "function", 7, 8),
        ],
    )


def _seed_edges(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO edges (src_id, dst_id, rel_type) VALUES (?, ?, ?)",
        [
            ("api/b.py::b1", "auth/a.py::a1", "EXTERNAL_CALL"),
            ("api/b.py::b2", "auth/a.py::a1", "EXTERNAL_CALL"),
            ("api/b.py::b3", "auth/a.py::a2", "EXTERNAL_CALL"),
        ],
    )


def _config() -> CerebrоfyConfig:
    return CerebrоfyConfig(
        lobes={"auth": "auth", "api": "api", "tests": "tests", "payments": "payments"},
        tracked_extensions=[".py"],
        governance=GovernanceConfig(),
    )


# ---------------------------------------------------------------------------
# Ownership strategies
# ---------------------------------------------------------------------------


def test_lobe_for_file_uses_longest_prefix(tmp_path: Path) -> None:
    lobes = {"src": "src", "auth": "src/auth"}
    assert lobe_for_file("src/auth/token.py", lobes) == "auth"
    assert lobe_for_file("src/other.py", lobes) == "src"
    assert lobe_for_file("README.md", lobes) == "__unknown__"


def test_git_blame_ownership_and_bus_factor(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    conn = _db()
    _seed_nodes(conn)
    ownership = compute_lobe_ownership(
        conn, repo, {"auth": "auth", "api": "api"}, "auth"
    )
    assert ownership.primary == "alice@example.com"
    assert ownership.primary_share == pytest.approx(0.75, abs=0.01)
    assert ownership.bus_factor == 1
    assert ownership.total_lines == 4
    authors = {item.author: item for item in ownership.authors}
    assert authors["bob@example.com"].lines == 1


def test_hybrid_weights_recent_activity(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    conn = _db()
    _seed_nodes(conn)
    ownership = compute_lobe_ownership(
        conn,
        repo,
        {"auth": "auth", "api": "api"},
        "auth",
        strategy="hybrid",
        activity_days=90,
    )
    authors = {item.author: item for item in ownership.authors}
    assert authors["bob@example.com"].recent_commits == 1
    assert authors["alice@example.com"].recent_commits == 0
    # Bob's single line is boosted by 1.5x for recent activity.
    assert authors["bob@example.com"].score == pytest.approx(1.5)


def test_explicit_ownership_from_team_yaml(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / ".cerebrofy").mkdir(parents=True)
    (repo / ".cerebrofy" / "team.yaml").write_text(
        "default_owner: '@tech-leads'\n"
        "lobes:\n"
        "  auth:\n"
        "    owners: ['alice@example.com', '@alice']\n",
        encoding="utf-8",
    )
    conn = _db()
    _seed_nodes(conn)
    ownership = compute_lobe_ownership(
        conn,
        repo,
        {"auth": "auth", "api": "api"},
        "auth",
        strategy="explicit",
    )
    assert ownership.primary == "alice@example.com"
    assert ownership.bus_factor == 2
    assert [item.author for item in ownership.authors] == [
        "alice@example.com",
        "@alice",
    ]


def test_no_git_history_raises(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    conn = _db()
    _seed_nodes(conn)
    with pytest.raises(NoGitHistoryError):
        compute_lobe_ownership(conn, repo, {"auth": "auth"}, "auth")


def test_unknown_strategy_raises(tmp_path: Path) -> None:
    conn = _db()
    with pytest.raises(ValueError, match="Unknown ownership strategy"):
        compute_lobe_ownership(conn, tmp_path, {"auth": "auth"}, "auth", strategy="magic")


def test_compute_all_returns_every_lobe(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    conn = _db()
    _seed_nodes(conn)
    profiles = compute_all_lobe_ownership(
        conn, repo, {"auth": "auth", "api": "api", "payments": "payments"}
    )
    assert set(profiles) == {"auth", "api", "payments"}
    assert profiles["payments"].primary is None


# ---------------------------------------------------------------------------
# Graph-derived context
# ---------------------------------------------------------------------------


def test_cross_lobe_callers_counts_edges() -> None:
    conn = _db()
    _seed_nodes(conn)
    _seed_edges(conn)
    callers = cross_lobe_callers(conn, {"auth": "auth", "api": "api"})
    assert callers["auth"][0].caller_lobe == "api"
    assert callers["auth"][0].count == 3


def test_max_blast_radius_limited_to_changed_files() -> None:
    conn = _db()
    _seed_nodes(conn)
    _seed_edges(conn)
    lobes = {"auth": "auth", "api": "api"}
    assert max_blast_radius(conn, lobes, changed_files=frozenset({"auth/a.py"})) == 2
    assert max_blast_radius(conn, lobes, changed_files=frozenset({"api/b.py"})) == 0


# ---------------------------------------------------------------------------
# CODEOWNERS
# ---------------------------------------------------------------------------


def _generate(tmp_path: Path) -> object:
    repo = _make_repo(tmp_path)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    _commit(repo, "tests", "Carol", "carol@example.com", days_ago=5)
    conn = _db()
    _seed_nodes(conn)
    _seed_edges(conn)
    conn.execute(
        "INSERT INTO nodes (id, name, file, type, line_start, line_end) "
        "VALUES ('tests/test_a.py::test_a', 'test_a', 'tests/test_a.py', 'function', 1, 2)"
    )
    return generate_codeowners(
        conn, repo, _config(), as_of="2026-06-19"
    )


def test_codeowners_header_and_lobe_blocks(tmp_path: Path) -> None:
    result = _generate(tmp_path)
    content = result.content
    assert content.startswith("# Auto-generated by cerebrofy governance — 2026-06-19")
    assert "DO NOT EDIT MANUALLY" in content
    assert "# auth/ — Bus Factor: 1 (critical) — Primary: alice@example.com" in content
    assert "auth/ @alice" in content
    # Cross-lobe: api calls into auth, so bob is a co-reviewer on auth.
    assert "Cross-lobe: api/ makes 3 call(s) here" in content
    assert "auth/ @alice @bob" in content


def test_codeowners_new_lobe_uses_fallback(tmp_path: Path) -> None:
    result = _generate(tmp_path)
    assert "payments" in result.fallback_lobes
    assert "# payments/ — New module (no commit history)" in result.content
    assert "payments/ @tech-leads" in result.content


def test_codeowners_tests_dir_shared(tmp_path: Path) -> None:
    result = _generate(tmp_path)
    assert "# tests/ — Shared ownership" in result.content
    assert "tests/ @alice @bob @carol" in (
        result.content
    )


def test_codeowners_root_lobe_pattern_is_first(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    conn = _db()
    _seed_nodes(conn)
    config = CerebrоfyConfig(
        lobes={"auth": "auth", "root": "."},
        tracked_extensions=[".py"],
    )
    result = generate_codeowners(conn, repo, config, as_of="2026-06-19")
    lines = result.content.splitlines()
    root_line = next(i for i, line in enumerate(lines) if line.startswith("* "))
    auth_line = next(i for i, line in enumerate(lines) if line.startswith("auth/ "))
    # CODEOWNERS is last-match-wins: the root fallback must precede specifics.
    assert root_line < auth_line


def test_codeowners_specific_patterns_follow_least_to_most_specific(
    tmp_path: Path,
) -> None:
    repo = _make_repo(tmp_path)
    conn = _db()
    _seed_nodes(conn)
    config = CerebrоfyConfig(
        lobes={"root": ".", "auth": "auth", "nested": "auth/nested"},
        tracked_extensions=[".py"],
        governance=GovernanceConfig(strategy="explicit"),
    )
    result = generate_codeowners(conn, repo, config, as_of="2026-06-19")
    lines = result.content.splitlines()
    root_line = next(i for i, line in enumerate(lines) if line.startswith("* "))
    auth_line = next(i for i, line in enumerate(lines) if line.startswith("auth/ "))
    nested_line = next(
        i for i, line in enumerate(lines) if line.startswith("auth/nested/ ")
    )
    assert root_line < auth_line < nested_line


def test_is_tests_lobe_requires_exact_segment() -> None:
    from cerebrofy.governance.codeowners import _is_tests_lobe

    assert _is_tests_lobe("", "tests")
    assert _is_tests_lobe("", "tests/unit/test_a.py")
    assert not _is_tests_lobe("", "testing")
    assert not _is_tests_lobe("testing", "testing")
    assert not _is_tests_lobe("", "tests_helpers")


def test_generate_codeowners_no_git_history_raises(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    conn = _db()
    _seed_nodes(conn)
    with pytest.raises(NoGitHistoryError):
        generate_codeowners(conn, repo, _config())


def test_write_codeowners_refuses_manual_file(tmp_path: Path) -> None:
    target = tmp_path / "CODEOWNERS"
    target.write_text("# hand maintained\n* @alice\n", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_codeowners(target, "# generated\n")
    assert "hand maintained" in target.read_text(encoding="utf-8")


def test_write_codeowners_replaces_generated_file(tmp_path: Path) -> None:
    target = tmp_path / "CODEOWNERS"
    target.write_text("# Auto-generated by cerebrofy governance\nold\n", encoding="utf-8")
    write_codeowners(target, "# Auto-generated by cerebrofy governance\nnew\n")
    assert target.read_text(encoding="utf-8").endswith("new\n")
    assert is_generated_codeowners(target.read_text(encoding="utf-8"))


def test_write_codeowners_force_overwrites_manual_file(tmp_path: Path) -> None:
    target = tmp_path / "CODEOWNERS"
    target.write_text("# hand maintained\n", encoding="utf-8")
    write_codeowners(target, "# Auto-generated by cerebrofy governance\n", force=True)
    assert target.read_text(encoding="utf-8").startswith("# Auto-generated")


def test_write_codeowners_rejects_path_escaping_repo_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "escaped-CODEOWNERS"
    with pytest.raises(ValueError, match="outside the repository root"):
        write_codeowners(
            outside,
            "# Auto-generated by cerebrofy governance\n",
            repo_root=tmp_path,
        )
    assert not outside.exists()


def test_write_codeowners_resolves_relative_path_against_repo_root(
    tmp_path: Path,
) -> None:
    write_codeowners(
        Path(".github/CODEOWNERS"),
        "# Auto-generated by cerebrofy governance\n",
        repo_root=tmp_path,
    )
    assert (tmp_path / ".github" / "CODEOWNERS").exists()
