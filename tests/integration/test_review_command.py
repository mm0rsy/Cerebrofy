"""Integration tests for ``cerebrofy review`` (Idea #17)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from cerebrofy.cli import main
from cerebrofy.errors import GH_NOT_AUTHENTICATED
from cerebrofy.review.finding import Finding, ReviewReport
from cerebrofy.review.pipeline import ReviewError
from tests.unit.review_helpers import (
    change_tracked_files,
    make_repo,
    setup_git_repo,
)


def _output(result: object) -> str:
    """Click 8.2+ splits stdout/stderr; combine them for assertions."""
    output = getattr(result, "output", "")
    stderr = getattr(result, "stderr", "")
    return output + stderr


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    make_repo(tmp_path).close()
    setup_git_repo(tmp_path)
    change_tracked_files(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_review_requires_diff_or_pr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["review"])

    assert result.exit_code == 1
    assert "[NO_DIFF_PROVIDED]" in _output(result)


def test_review_local_diff_markdown(repo: Path) -> None:
    with patch("cerebrofy.review.github_poster.post_report") as post:
        result = CliRunner().invoke(main, ["review", "--diff", "HEAD"])

    assert result.exit_code == 0, _output(result)
    output = _output(result)
    assert "🧠 Cerebrofy Review Summary — diff HEAD" in output
    assert "Files Changed: **2**" in output
    assert "`blast_radius`" in output
    assert "`memory_violation`" in output
    assert "`arch_rule`" in output
    post.assert_not_called()


def test_review_default_never_posts_with_pr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    report = ReviewReport(files_changed=1, neurons_changed=1, summary="summary\n")

    with (
        patch(
            "cerebrofy.commands.review.review_diff_or_pr", return_value=report
        ),
        patch("cerebrofy.review.github_poster.post_report") as post,
    ):
        result = CliRunner().invoke(main, ["review", "--pr", "42"])

    assert result.exit_code == 0, _output(result)
    post.assert_not_called()


def test_review_json_output(repo: Path) -> None:
    authors = {line: "alice@co.com" for line in range(1, 200)}
    with patch("cerebrofy.review.pipeline._blame_file", return_value=authors):
        result = CliRunner().invoke(
            main, ["review", "--diff", "HEAD", "--format", "json"]
        )

    assert result.exit_code == 0, _output(result)
    payload = json.loads(_output(result))
    assert payload["files_changed"] == 2
    assert payload["neurons_changed"] == 3
    assert any(finding["check_type"] == "arch_rule" for finding in payload["findings"])
    assert payload["suggested_reviewers"][0]["email"] == "alice@co.com"


def test_review_severity_error_only(repo: Path) -> None:
    result = CliRunner().invoke(
        main, ["review", "--diff", "HEAD", "--severity", "error", "--format", "json"]
    )

    assert result.exit_code == 0, _output(result)
    payload = json.loads(_output(result))
    assert payload["findings"]
    assert {finding["severity"] for finding in payload["findings"]} == {"error"}


def test_review_post_comments_requires_pr(repo: Path) -> None:
    with patch("cerebrofy.review.github_poster.post_report") as post:
        result = CliRunner().invoke(
            main, ["review", "--diff", "HEAD", "--post-comments"]
        )

    assert result.exit_code == 1
    assert "[GH_NOT_AUTHENTICATED]" in _output(result)
    assert "requires --pr" in _output(result)
    post.assert_not_called()


def test_review_posts_when_opted_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    finding = Finding(
        check_type="blast_radius",
        neuron="validate_token",
        file="auth/tokens.py",
        line=10,
        severity="error",
        message="Wide blast radius",
        suggestion="Review callers",
    )
    report = ReviewReport(
        files_changed=1, neurons_changed=1, findings=[finding], summary="summary\n"
    )

    class _Result:
        posted_inline = 1
        summary_posted = True
        errors: list[str] = []

        def to_dict(self) -> dict[str, object]:
            return {
                "posted_inline": 1,
                "summary_posted": True,
                "errors": [],
            }

    with (
        patch(
            "cerebrofy.commands.review.review_diff_or_pr", return_value=report
        ),
        patch(
            "cerebrofy.review.github_poster.post_report", return_value=_Result()
        ) as post,
    ):
        result = CliRunner().invoke(
            main, ["review", "--pr", "42", "--post-comments"]
        )

    assert result.exit_code == 0, _output(result)
    post.assert_called_once()
    assert post.call_args.args[0] == 42
    assert "Posted 1 inline comment(s)" in _output(result)


def test_review_post_auth_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    report = ReviewReport(files_changed=1, neurons_changed=1, summary="summary\n")

    with (
        patch(
            "cerebrofy.commands.review.review_diff_or_pr", return_value=report
        ),
        patch(
            "cerebrofy.review.github_poster.post_report",
            side_effect=ReviewError("gh auth required", code=GH_NOT_AUTHENTICATED),
        ),
    ):
        result = CliRunner().invoke(
            main, ["review", "--pr", "42", "--post-comments"]
        )

    assert result.exit_code == 1
    assert "[GH_NOT_AUTHENTICATED] gh auth required" in _output(result)


def test_review_reports_no_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_git_repo(tmp_path)
    change_tracked_files(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["review", "--diff", "HEAD"])

    assert result.exit_code == 1
    assert "[NO_INDEX]" in _output(result)


def test_review_reports_bad_ref(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    setup_git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(main, ["review", "--diff", "does-not-exist"])

    assert result.exit_code == 1
    assert "[REF_NOT_FOUND]" in _output(result)


def test_review_records_no_comments_by_default(repo: Path) -> None:
    with patch("subprocess.run", wraps=__import__("subprocess").run) as run:
        result = CliRunner().invoke(main, ["review", "--diff", "HEAD"])

    assert result.exit_code == 0, _output(result)
    commands = [call.args[0] for call in run.call_args_list if call.args]
    assert not any(command[:2] == ["gh", "pr"] for command in commands)
    assert not any(
        command[:3] == ["gh", "api", "repos"] for command in commands
    )
