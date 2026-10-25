"""Unit tests for the review pipeline: diff resolution, checks, and degradation."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from cerebrofy.errors import GH_NOT_AUTHENTICATED, NO_DIFF_PROVIDED, NO_INDEX
from cerebrofy.review.pipeline import (
    ReviewError,
    normalize_changed_files,
    open_index,
    resolve_changed_files,
    review_diff_or_pr,
    run_review,
)
from tests.unit.review_helpers import (
    MEMORIES_WARNING,
    change_tracked_files,
    make_index_db,
    make_repo,
    setup_git_repo,
    write_config,
    write_memories,
    write_rules,
)

ALL_CHECKS = {
    "arch_rule",
    "blast_radius",
    "coverage_gap",
    "coupling",
    "knowledge_silo",
    "memory_violation",
    "missing_caller_update",
}


def _blame() -> dict[int, str]:
    return {line: "alice@co.com" for line in range(1, 200)}


# ---------------------------------------------------------------------------
# Input normalisation
# ---------------------------------------------------------------------------


def test_normalize_changed_files() -> None:
    assert normalize_changed_files(
        [" ./auth/tokens.py ", "auth\\tokens.py", "", "./billing/charge.py"]
    ) == ["auth/tokens.py", "billing/charge.py"]


def test_normalize_changed_files_handles_duplicates() -> None:
    assert normalize_changed_files(["a.py", "a.py", "b.py"]) == ["a.py", "b.py"]


# ---------------------------------------------------------------------------
# Index and diff resolution
# ---------------------------------------------------------------------------


def test_open_index_missing(tmp_path: Path) -> None:
    with pytest.raises(ReviewError) as excinfo:
        open_index(tmp_path)
    assert excinfo.value.code == NO_INDEX


def test_open_index_unreadable(tmp_path: Path) -> None:
    db_dir = tmp_path / ".cerebrofy" / "db"
    db_dir.mkdir(parents=True)
    (db_dir / "cerebrofy.db").write_text("not a database", encoding="utf-8")

    with pytest.raises(ReviewError) as excinfo:
        open_index(tmp_path)
    assert excinfo.value.code == NO_INDEX


def test_open_index_read_only(tmp_path: Path) -> None:
    make_index_db(tmp_path).close()
    conn = open_index(tmp_path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("DELETE FROM nodes")
    finally:
        conn.close()


def test_resolve_requires_diff_or_pr(tmp_path: Path) -> None:
    with pytest.raises(ReviewError) as excinfo:
        resolve_changed_files(repo_root=tmp_path)
    assert excinfo.value.code == NO_DIFF_PROVIDED


def test_resolve_local_diff(tmp_path: Path) -> None:
    setup_git_repo(tmp_path)
    change_tracked_files(tmp_path)

    assert resolve_changed_files(diff="HEAD", repo_root=tmp_path) == [
        "auth/tokens.py",
        "billing/charge.py",
    ]


def test_resolve_unknown_ref(tmp_path: Path) -> None:
    setup_git_repo(tmp_path)

    with pytest.raises(ReviewError) as excinfo:
        resolve_changed_files(diff="does-not-exist", repo_root=tmp_path)
    assert excinfo.value.code == "REF_NOT_FOUND"


def test_resolve_pr_when_gh_missing(tmp_path: Path) -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError("gh")):
        with pytest.raises(ReviewError) as excinfo:
            resolve_changed_files(pr=7, repo_root=tmp_path)
    assert excinfo.value.code == GH_NOT_AUTHENTICATED


def test_resolve_pr_when_gh_fails(tmp_path: Path) -> None:
    failed = subprocess.CompletedProcess(
        args=["gh"], returncode=1, stdout="", stderr="not logged in"
    )
    with patch("subprocess.run", return_value=failed), pytest.raises(ReviewError) as excinfo:
        resolve_changed_files(pr=7, repo_root=tmp_path)
    assert excinfo.value.code == GH_NOT_AUTHENTICATED
    assert "not logged in" in str(excinfo.value)


def test_resolve_pr_success(tmp_path: Path) -> None:
    completed = subprocess.CompletedProcess(
        args=["gh"],
        returncode=0,
        stdout="auth/tokens.py\nbilling/charge.py\nauth/tokens.py\n",
        stderr="",
    )
    with patch("subprocess.run", return_value=completed) as run:
        files = resolve_changed_files(pr=7, repo_root=tmp_path)

    assert files == ["auth/tokens.py", "billing/charge.py"]
    command = run.call_args.args[0]
    assert command[:4] == ["gh", "pr", "diff", "7"]
    assert command[-1] == "--name-only"


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


def test_run_review_runs_all_checks(tmp_path: Path) -> None:
    conn = make_repo(tmp_path)
    setup_git_repo(tmp_path)
    try:
        with patch("cerebrofy.review.pipeline._blame_file", return_value=_blame()):
            report = run_review(
                changed_files=["auth/tokens.py", "billing/charge.py"],
                conn=conn,
                root=tmp_path,
            )
    finally:
        conn.close()

    check_types = {finding.check_type for finding in report.findings}
    assert check_types == ALL_CHECKS
    assert report.files_changed == 2
    assert report.neurons_changed == 3
    assert report.error_count == 2
    assert report.max_blast_radius == 6
    assert report.skipped_checks == []

    memory = next(f for f in report.findings if f.check_type == "memory_violation")
    assert memory.severity == "warning"
    assert "Use server_time" in memory.message
    assert MEMORIES_WARNING.split(" — ")[-1] in memory.message

    arch = next(f for f in report.findings if f.check_type == "arch_rule")
    assert arch.severity == "error"
    assert arch.neuron == "validate_token"
    assert "no-auth-to-billing" in arch.message

    coverage = {
        f.neuron for f in report.findings if f.check_type == "coverage_gap"
    }
    assert coverage == {"charge", "refresh_token"}

    caller_updates = {
        f.neuron for f in report.findings if f.check_type == "missing_caller_update"
    }
    assert caller_updates == {"validate_token", "charge"}

    assert report.suggested_reviewers[0].email == "alice@co.com"
    assert report.health_delta.avg_blast == 3.33
    assert report.health_delta.coupling == 0.0
    assert "Cerebrofy Review Summary" in report.summary


def test_run_review_severity_filter(tmp_path: Path) -> None:
    conn = make_repo(tmp_path)
    setup_git_repo(tmp_path)
    try:
        with patch("cerebrofy.review.pipeline._blame_file", return_value=_blame()):
            report = run_review(
                changed_files=["auth/tokens.py", "billing/charge.py"],
                conn=conn,
                root=tmp_path,
                severity="error",
            )
    finally:
        conn.close()

    assert report.findings
    assert {finding.severity for finding in report.findings} == {"error"}


def test_run_review_without_optional_integrations(tmp_path: Path) -> None:
    """Missing memories/rules still produce a review plus skipped-check notes."""
    write_config(tmp_path)
    conn = make_index_db(tmp_path)
    try:
        report = run_review(
            changed_files=["auth/tokens.py", "billing/charge.py"],
            conn=conn,
            root=tmp_path,
        )
    finally:
        conn.close()

    assert not any(
        finding.check_type == "memory_violation" for finding in report.findings
    )
    assert any("architecture rules" in note for note in report.skipped_checks)
    # A missing memories.db is absence, not an unreadable store: no skip noise.
    assert not any("memories.db" in note for note in report.skipped_checks)
    # Coverage falls back to graph topology rather than failing.
    assert not any("coverage" in note for note in report.skipped_checks)


def test_run_review_with_invalid_rules(tmp_path: Path) -> None:
    write_config(tmp_path)
    (tmp_path / ".cerebrofy" / "arch-rules.yaml").write_text(
        "rules: [not-valid", encoding="utf-8"
    )
    conn = make_index_db(tmp_path)
    try:
        report = run_review(changed_files=["auth/tokens.py"], conn=conn, root=tmp_path)
    finally:
        conn.close()

    assert any(
        "invalid arch-rules.yaml" in note for note in report.skipped_checks
    )


def test_run_review_with_unreadable_memories(tmp_path: Path) -> None:
    write_config(tmp_path)
    conn = make_index_db(tmp_path)
    (tmp_path / ".cerebrofy" / "db" / "memories.db").write_text(
        "not a database", encoding="utf-8"
    )
    try:
        report = run_review(changed_files=["auth/tokens.py"], conn=conn, root=tmp_path)
    finally:
        conn.close()

    assert any(
        "memories.db is unreadable" in note for note in report.skipped_checks
    )


def _insert_warning_memory(root: Path, created_ts: object) -> None:
    conn = sqlite3.connect(root / ".cerebrofy" / "db" / "memories.db")
    try:
        conn.execute(
            "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "mem-bad",
                "auth/tokens.py::validate_token",
                "auth",
                "warning",
                "Malformed timestamp",
                "This row has a bad created_ts",
                "bob@co.com",
                created_ts,
                "auth",
                1.0,
                "active",
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_run_review_with_null_memory_timestamp(tmp_path: Path) -> None:
    """A NULL created_ts must degrade to a skipped check, not abort the review."""
    conn = make_repo(tmp_path)
    _insert_warning_memory(tmp_path, None)
    try:
        with patch("cerebrofy.review.pipeline._blame_file", return_value={}):
            report = run_review(
                changed_files=["auth/tokens.py"], conn=conn, root=tmp_path
            )
    finally:
        conn.close()

    assert any(
        "memories.db is unreadable" in note for note in report.skipped_checks
    )
    assert not any(
        finding.check_type == "memory_violation" for finding in report.findings
    )
    # The rest of the review still ran.
    assert report.findings


def test_run_review_propagates_unexpected_memory_errors(tmp_path: Path) -> None:
    """Only storage/parse failures degrade; programming bugs must surface."""
    conn = make_repo(tmp_path)
    try:
        with patch(
            "cerebrofy.review.pipeline.list_memories",
            side_effect=RuntimeError("boom"),
        ), pytest.raises(RuntimeError, match="boom"):
            run_review(
                changed_files=["auth/tokens.py"], conn=conn, root=tmp_path
            )
    finally:
        conn.close()


def test_run_review_with_out_of_range_memory_timestamp(tmp_path: Path) -> None:
    """Bad timestamps fall back to a date label instead of raising."""
    conn = make_repo(tmp_path)
    _insert_warning_memory(tmp_path, 10**18)
    try:
        with patch("cerebrofy.review.pipeline._blame_file", return_value={}):
            report = run_review(
                changed_files=["auth/tokens.py"], conn=conn, root=tmp_path
            )
    finally:
        conn.close()

    assert not any(
        "memories.db is unreadable" in note for note in report.skipped_checks
    )
    memory_findings = [
        finding
        for finding in report.findings
        if finding.check_type == "memory_violation"
    ]
    assert memory_findings
    assert any("unknown date" in finding.message for finding in memory_findings)


def test_run_review_empty_diff(tmp_path: Path) -> None:
    conn = make_repo(tmp_path)
    try:
        report = run_review(changed_files=[], conn=conn, root=tmp_path)
    finally:
        conn.close()

    assert report.files_changed == 0
    assert report.neurons_changed == 0
    assert report.findings == []
    assert "No findings" in report.summary


def test_run_review_skips_files_without_neurons(tmp_path: Path) -> None:
    conn = make_repo(tmp_path)
    try:
        report = run_review(changed_files=["README.md"], conn=conn, root=tmp_path)
    finally:
        conn.close()

    assert report.files_changed == 1
    assert report.neurons_changed == 0
    assert report.findings == []


# ---------------------------------------------------------------------------
# review_diff_or_pr
# ---------------------------------------------------------------------------


def test_review_diff_or_pr_end_to_end(tmp_path: Path) -> None:
    make_repo(tmp_path).close()
    setup_git_repo(tmp_path)
    change_tracked_files(tmp_path)

    with patch("cerebrofy.review.pipeline._blame_file", return_value=_blame()):
        report = review_diff_or_pr(root=tmp_path, diff="HEAD", record_session=False)

    assert report.files_changed == 2
    assert report.neurons_changed == 3
    assert report.findings


def test_review_diff_or_pr_empty_diff_does_not_require_index(tmp_path: Path) -> None:
    setup_git_repo(tmp_path)

    report = review_diff_or_pr(root=tmp_path, diff="HEAD")

    assert report.files_changed == 0
    assert "No findings" in report.summary


def test_review_diff_or_pr_requires_index(tmp_path: Path) -> None:
    setup_git_repo(tmp_path)
    change_tracked_files(tmp_path)

    with pytest.raises(ReviewError) as excinfo:
        review_diff_or_pr(root=tmp_path, diff="HEAD")
    assert excinfo.value.code == NO_INDEX


def test_review_diff_or_pr_requires_diff(tmp_path: Path) -> None:
    with pytest.raises(ReviewError) as excinfo:
        review_diff_or_pr(root=tmp_path)
    assert excinfo.value.code == NO_DIFF_PROVIDED


# ---------------------------------------------------------------------------
# Session recording is best-effort
# ---------------------------------------------------------------------------


def test_record_session_failure_does_not_break_review(tmp_path: Path) -> None:
    conn = make_repo(tmp_path)
    try:
        with patch(
            "cerebrofy.session.middleware.SessionMiddleware",
            side_effect=RuntimeError("no session support"),
        ):
            report = run_review(
                changed_files=["auth/tokens.py"],
                conn=conn,
                root=tmp_path,
                record_session=True,
            )
    finally:
        conn.close()

    assert report.findings


def test_write_memories_helper_is_optional(tmp_path: Path) -> None:
    write_memories(tmp_path)
    assert (tmp_path / ".cerebrofy" / "db" / "memories.db").exists()
    write_rules(tmp_path)
    assert (tmp_path / ".cerebrofy" / "arch-rules.yaml").exists()
