"""Unit tests for GitHub posting — opt-in, dry-run, and failure handling."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from cerebrofy.errors import GH_NOT_AUTHENTICATED
from cerebrofy.review.finding import Finding, ReviewReport
from cerebrofy.review.github_poster import (
    check_gh_auth,
    post_inline_comment,
    post_report,
    post_summary_comment,
)
from cerebrofy.review.pipeline import ReviewError


def _report() -> ReviewReport:
    report = ReviewReport(
        files_changed=1,
        neurons_changed=1,
        findings=[
            Finding(
                check_type="blast_radius",
                neuron="validate_token",
                file="auth/tokens.py",
                line=10,
                severity="error",
                message="Wide blast radius",
                suggestion="Review callers",
            ),
            Finding(
                check_type="coverage_gap",
                neuron="charge",
                file="billing/charge.py",
                line=0,
                severity="warning",
                message="No coverage",
                suggestion="Add tests",
            ),
        ],
    )
    report.summary = "summary body\n"
    return report


def _completed(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["gh"], returncode=returncode, stdout=stdout, stderr=stderr
    )


# ---------------------------------------------------------------------------
# Dry run and auth
# ---------------------------------------------------------------------------


def test_dry_run_executes_no_subprocess(tmp_path: Path) -> None:
    with patch("subprocess.run", side_effect=AssertionError("must not run")):
        result = post_report(
            7, _report(), repo_root=tmp_path, dry_run=True
        )

    assert result.posted_inline == 0
    assert result.summary_posted is False
    assert result.errors == []


def test_check_gh_auth_success(tmp_path: Path) -> None:
    with patch("subprocess.run", return_value=_completed()):
        assert check_gh_auth(tmp_path) is True


def test_check_gh_auth_unauthenticated(tmp_path: Path) -> None:
    with patch("subprocess.run", return_value=_completed(returncode=1)):
        assert check_gh_auth(tmp_path) is False


def test_check_gh_auth_missing_cli(tmp_path: Path) -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError("gh")):
        assert check_gh_auth(tmp_path) is False


def test_check_gh_auth_timeout(tmp_path: Path) -> None:
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["gh"], timeout=30),
    ):
        assert check_gh_auth(tmp_path) is False


def test_post_report_requires_gh_auth(tmp_path: Path) -> None:
    with patch("cerebrofy.review.github_poster.check_gh_auth", return_value=False):
        with pytest.raises(ReviewError) as excinfo:
            post_report(7, _report(), repo_root=tmp_path)

    assert excinfo.value.code == GH_NOT_AUTHENTICATED


# ---------------------------------------------------------------------------
# Inline and summary comments
# ---------------------------------------------------------------------------


def test_post_inline_comment_rejects_missing_line(tmp_path: Path) -> None:
    with patch("subprocess.run", side_effect=AssertionError("must not run")):
        ok, message = post_inline_comment(
            7, "auth/tokens.py", 0, "body", repo_root=tmp_path
        )

    assert ok is False
    assert "line number" in message


def test_post_inline_comment_uses_repo_endpoint(tmp_path: Path) -> None:
    with patch("subprocess.run", return_value=_completed(stdout="{}")) as run:
        ok, _ = post_inline_comment(
            7,
            "auth/tokens.py",
            10,
            "body",
            repo_root=tmp_path,
            repo="acme/widgets",
        )

    assert ok is True
    args = run.call_args.args[0]
    assert args[:3] == ["gh", "api", "repos/acme/widgets/pulls/7/comments"]
    assert "--field" in args
    assert "line=10" in args
    assert "side=RIGHT" in args


def test_post_inline_comment_uses_default_repo(tmp_path: Path) -> None:
    with patch("subprocess.run", return_value=_completed()) as run:
        post_inline_comment(7, "a.py", 1, "body", repo_root=tmp_path)

    assert run.call_args.args[0][2] == "repos/:owner/:repo/pulls/7/comments"


def test_post_inline_comment_failure_reports_stderr(tmp_path: Path) -> None:
    with patch(
        "subprocess.run",
        return_value=_completed(returncode=1, stderr="422 Unprocessable Entity"),
    ):
        ok, message = post_inline_comment(7, "a.py", 1, "body", repo_root=tmp_path)

    assert ok is False
    assert message == "422 Unprocessable Entity"


def test_post_inline_comment_missing_gh(tmp_path: Path) -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError("gh")):
        ok, message = post_inline_comment(7, "a.py", 1, "body", repo_root=tmp_path)

    assert ok is False
    assert "gh CLI not found" in message


def test_post_inline_comment_timeout(tmp_path: Path) -> None:
    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["gh"], timeout=30),
    ):
        ok, message = post_inline_comment(7, "a.py", 1, "body", repo_root=tmp_path)

    assert ok is False
    assert "timed out" in message


def test_post_summary_comment_includes_repo(tmp_path: Path) -> None:
    with patch("subprocess.run", return_value=_completed()) as run:
        ok, _ = post_summary_comment(
            7, "summary", repo_root=tmp_path, repo="acme/widgets"
        )

    assert ok is True
    args = run.call_args.args[0]
    assert args == ["gh", "pr", "comment", "7", "--body", "summary", "--repo", "acme/widgets"]


def test_post_summary_comment_failure(tmp_path: Path) -> None:
    with patch(
        "subprocess.run",
        return_value=_completed(returncode=1, stderr="not authenticated"),
    ):
        ok, message = post_summary_comment(7, "summary", repo_root=tmp_path)

    assert ok is False
    assert message == "not authenticated"


def test_post_summary_comment_missing_gh(tmp_path: Path) -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError("gh")):
        ok, message = post_summary_comment(7, "summary", repo_root=tmp_path)

    assert ok is False
    assert "gh CLI not found" in message


# ---------------------------------------------------------------------------
# Full posting
# ---------------------------------------------------------------------------


def test_post_report_posts_inline_and_summary(tmp_path: Path) -> None:
    with (
        patch("cerebrofy.review.github_poster.check_gh_auth", return_value=True),
        patch(
            "cerebrofy.review.github_poster._run_gh", return_value=_completed()
        ) as run,
    ):
        result = post_report(7, _report(), repo_root=tmp_path)

    assert result.posted_inline == 1  # the line=0 finding is skipped
    assert result.summary_posted is True
    assert result.errors == []
    # one inline comment + one summary comment
    assert run.call_count == 2


def test_post_report_collects_failures(tmp_path: Path) -> None:
    with (
        patch("cerebrofy.review.github_poster.check_gh_auth", return_value=True),
        patch(
            "cerebrofy.review.github_poster._run_gh",
            return_value=_completed(returncode=1, stderr="boom"),
        ),
    ):
        result = post_report(7, _report(), repo_root=tmp_path)

    assert result.posted_inline == 0
    assert result.summary_posted is False
    assert result.ok is False
    assert any(error.startswith("auth/tokens.py:10:") for error in result.errors)
    assert any(error.startswith("summary:") for error in result.errors)


def test_post_report_success_payload(tmp_path: Path) -> None:
    with (
        patch("cerebrofy.review.github_poster.check_gh_auth", return_value=True),
        patch("cerebrofy.review.github_poster._run_gh", return_value=_completed()),
    ):
        result = post_report(7, _report(), repo_root=tmp_path)

    assert result.to_dict()["posted_inline"] == 1
    assert result.to_dict()["summary_posted"] is True
