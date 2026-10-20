"""Unit tests for governance reviewer suggestions and change-set parsing."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from cerebrofy.db.schema import EDGES_DDL, NODES_DDL
from cerebrofy.errors import GitHubNotAuthenticatedError
from cerebrofy.governance import reviewer
from cerebrofy.governance.ownership import AuthorShare, LobeOwnership
from cerebrofy.governance.reviewer import (
    ChangeSet,
    NewNeuron,
    _parse_patch,
    _parse_reviews,
    _run_gh,
    changes_from_diff,
    changes_from_pr,
    detect_new_neurons,
    suggest_reviewers,
)

_DIFF = """diff --git a/auth/a.py b/auth/a.py
index 1111111..2222222 100644
--- a/auth/a.py
+++ b/auth/a.py
@@ -1,2 +1,4 @@
 def a1():
-    return 1
+    return 2
+
diff --git a/auth/new.py b/auth/new.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/auth/new.py
@@ -0,0 +1,2 @@
+def fresh():
+    pass
"""


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
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")


def _commit(repo: Path, message: str, author: str, email: str) -> None:
    when = (datetime.now(timezone.utc) - timedelta(days=30)).strftime(
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


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(NODES_DDL)
    conn.execute(EDGES_DDL)
    conn.executemany(
        "INSERT INTO nodes (id, name, file, type, line_start, line_end) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("auth/a.py::a1", "a1", "auth/a.py", "function", 1, 2),
            ("api/b.py::b1", "b1", "api/b.py", "function", 1, 2),
            ("tests/test_a.py::test_a", "test_a", "tests/test_a.py", "function", 1, 2),
        ],
    )
    conn.execute(
        "INSERT INTO edges (src_id, dst_id, rel_type) "
        "VALUES ('api/b.py::b1', 'auth/a.py::a1', 'EXTERNAL_CALL')"
    )
    return conn


def _profile(lobe: str, author: str, *, share: float = 1.0) -> LobeOwnership:
    return LobeOwnership(
        lobe=lobe,
        strategy="explicit",
        path=lobe,
        authors=(AuthorShare(author=author, lines=10, score=share, share=share),),
        total_lines=10,
    )


# ---------------------------------------------------------------------------
# Diff parsing
# ---------------------------------------------------------------------------


def test_parse_patch_extracts_added_lines_and_new_files() -> None:
    added_lines, added_files = _parse_patch(_DIFF)
    assert added_files == {"auth/new.py"}
    assert added_lines["auth/a.py"] == ((1, 4),)
    assert added_lines["auth/new.py"] == ((1, 2),)


def test_changes_from_diff_uses_real_git(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "auth").mkdir()
    (repo / "auth" / "a.py").write_text("def a1():\n    return 1\n", encoding="utf-8")
    _commit(repo, "base", "Alice", "alice@example.com")

    (repo / "auth" / "a.py").write_text(
        "def a1():\n    return 2\n", encoding="utf-8"
    )
    (repo / "auth" / "new.py").write_text("def fresh():\n    pass\n", encoding="utf-8")
    _git(repo, "add", "-A")

    changes = changes_from_diff(repo, "HEAD")
    assert changes.source == "diff"
    assert "auth/a.py" in changes.files
    assert "auth/new.py" in changes.files
    assert changes.added_files == ("auth/new.py",)
    assert changes.added_lines["auth/new.py"] == ((1, 2),)


def test_changes_from_diff_rejects_unknown_ref(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    with pytest.raises(ValueError, match="bad revision"):
        changes_from_diff(repo, "does-not-exist")


# ---------------------------------------------------------------------------
# PR mode (gh mocked; deterministic and offline)
# ---------------------------------------------------------------------------


def test_parse_reviews_counts_latest_state() -> None:
    raw = json.dumps(
        {
            "reviews": [
                {"author": {"login": "alice"}, "state": "COMMENTED"},
                {"author": {"login": "alice"}, "state": "APPROVED"},
                {"author": {"login": "bob"}, "state": "CHANGES_REQUESTED"},
            ]
        }
    )
    reviewers, approvals = _parse_reviews(raw)
    assert reviewers == ("alice", "bob")
    assert approvals == 1


def test_parse_reviews_tolerates_bad_payload() -> None:
    assert _parse_reviews("not json") == ((), 0)
    assert _parse_reviews('{"reviews": "nope"}') == ((), 0)


def test_changes_from_pr_uses_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_gh(args: list[str]) -> str:
        calls.append(args)
        if args[:2] == ["pr", "diff"]:
            return _DIFF
        return json.dumps(
            {"reviews": [{"author": {"login": "alice"}, "state": "APPROVED"}]}
        )

    monkeypatch.setattr(reviewer, "_run_gh", fake_gh)
    changes = changes_from_pr(42)
    assert changes.source == "pr"
    assert changes.approvals == 1
    assert changes.reviewers == ("alice",)
    assert "auth/new.py" in changes.files
    assert calls[0] == ["pr", "diff", "42"]
    assert calls[1] == ["pr", "view", "42", "--json", "reviews"]


def test_run_gh_reports_not_authenticated() -> None:
    fake = type("R", (), {"returncode": 1, "stdout": "", "stderr": "auth required"})()
    with patch("subprocess.run", return_value=fake):
        with pytest.raises(GitHubNotAuthenticatedError, match="gh auth login"):
            _run_gh(["pr", "view", "1"])


def test_run_gh_reports_missing_binary() -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(GitHubNotAuthenticatedError, match="unavailable"):
            _run_gh(["pr", "view", "1"])


# ---------------------------------------------------------------------------
# New-neuron detection
# ---------------------------------------------------------------------------


def test_detect_new_neurons_from_added_file_and_hunk() -> None:
    conn = _db()
    try:
        changes = ChangeSet(
            source="diff",
            files=("auth/a.py", "tests/test_a.py"),
            added_files=("tests/test_a.py",),
            added_lines={"auth/a.py": ((1, 2),)},
        )
        enriched = detect_new_neurons(conn, changes)
        ids = {neuron.id for neuron in enriched.new_neurons}
        assert ids == {"auth/a.py::a1", "tests/test_a.py::test_a"}
        assert enriched.new_neurons[0].file == "auth/a.py"
    finally:
        conn.close()


def test_detect_new_neurons_no_files_is_noop() -> None:
    conn = _db()
    try:
        changes = ChangeSet(source="all")
        assert detect_new_neurons(conn, changes) is changes
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Reviewer suggestions
# ---------------------------------------------------------------------------


def test_suggest_reviewers_roles(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    conn = _db()
    profiles = {
        "auth": _profile("auth", "alice@example.com"),
        "api": _profile("api", "bob@example.com"),
    }
    monkeypatch.setattr(
        reviewer,
        "recent_contributors",
        lambda *args, **kwargs: (("carol@example.com", 3),),
    )
    try:
        suggestions = suggest_reviewers(
            conn,
            tmp_path,
            {"auth": "auth", "api": "api"},
            ChangeSet(source="diff", files=("auth/a.py",)),
            ownership=profiles,
        )
    finally:
        conn.close()

    roles = [(item.email, item.role) for item in suggestions]
    assert roles == [
        ("alice@example.com", "primary"),
        ("bob@example.com", "secondary"),
        ("carol@example.com", "backup"),
    ]
    assert "calls into auth" in suggestions[1].reason
    assert suggestions[0].to_dict()["role"] == "primary"


def test_suggest_reviewers_excludes_active_agents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    conn = _db()
    profiles = {
        "auth": _profile("auth", "alice@example.com"),
        "api": _profile("api", "bob@example.com"),
    }
    monkeypatch.setattr(reviewer, "_active_agent_emails", lambda: frozenset({"bob@example.com"}))
    monkeypatch.setattr(reviewer, "recent_contributors", lambda *args, **kwargs: ())
    try:
        suggestions = suggest_reviewers(
            conn,
            tmp_path,
            {"auth": "auth", "api": "api"},
            ChangeSet(source="diff", files=("auth/a.py",)),
            ownership=profiles,
        )
    finally:
        conn.close()
    assert [item.email for item in suggestions] == ["alice@example.com"]


def test_suggest_reviewers_without_changes_covers_all_lobes(tmp_path: Path) -> None:
    conn = _db()
    profiles = {
        "auth": _profile("auth", "alice@example.com"),
        "api": _profile("api", "bob@example.com"),
    }
    try:
        with patch.object(reviewer, "recent_contributors", return_value=()):
            suggestions = suggest_reviewers(
                conn,
                tmp_path,
                {"auth": "auth", "api": "api"},
                None,
                ownership=profiles,
            )
    finally:
        conn.close()
    assert {item.email for item in suggestions} == {
        "alice@example.com",
        "bob@example.com",
    }


def test_reviewer_suggestion_to_dict_roundtrip() -> None:
    from cerebrofy.governance.reviewer import ReviewerSuggestion

    item = ReviewerSuggestion(
        email="alice@example.com", lobe="auth", reason="primary", role="primary"
    )
    assert item.to_dict() == {
        "email": "alice@example.com",
        "lobe": "auth",
        "reason": "primary",
        "role": "primary",
    }
    assert NewNeuron(id="n", name="n", file="f.py").file == "f.py"
