"""GitHub posting for review findings via the authenticated ``gh`` CLI.

No tokens are stored or read by Cerebrofy: authentication is delegated entirely
to ``gh``.  Posting is opt-in — callers must pass ``--post-comments`` (CLI) or
``post_comments: true`` (MCP); the default path is a local print/dry-run.

Individual comment failures are captured in :class:`PostResult` and never abort
the review.  A missing/unauthenticated ``gh`` raises
:class:`cerebrofy.review.pipeline.ReviewError` with ``GH_NOT_AUTHENTICATED``
because nothing can be posted in that state.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from cerebrofy.errors import GH_NOT_AUTHENTICATED
from cerebrofy.review.finding import ReviewReport, format_inline_comment
from cerebrofy.review.pipeline import ReviewError

_GH_TIMEOUT = 30


@dataclass
class PostResult:
    """Outcome of attempting to post a review to GitHub."""

    posted_inline: int = 0
    summary_posted: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "posted_inline": self.posted_inline,
            "summary_posted": self.summary_posted,
            "errors": list(self.errors),
        }


def _run_gh(
    args: list[str],
    *,
    repo_root: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=_GH_TIMEOUT,
        check=False,
    )


def check_gh_auth(repo_root: Path) -> bool:
    """Return True when the ``gh`` CLI is installed and authenticated."""
    try:
        completed = _run_gh(["auth", "status"], repo_root=repo_root)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def post_inline_comment(
    pr: int,
    file: str,
    line: int,
    body: str,
    *,
    repo_root: Path,
    repo: str | None = None,
) -> tuple[bool, str]:
    """Post one inline review comment. Returns ``(success, output_or_error)``."""
    if line <= 0:
        return False, f"cannot anchor a comment to {file} without a line number"
    endpoint = (
        f"repos/{repo}/pulls/{pr}/comments"
        if repo
        else f"repos/:owner/:repo/pulls/{pr}/comments"
    )
    args = [
        "api",
        endpoint,
        "--method",
        "POST",
        "--field",
        f"body={body}",
        "--field",
        f"path={file}",
        "--field",
        f"line={line}",
        "--field",
        "side=RIGHT",
    ]
    try:
        completed = _run_gh(args, repo_root=repo_root)
    except FileNotFoundError:
        return False, "gh CLI not found. Install it from https://cli.github.com/"
    except subprocess.TimeoutExpired:
        return False, "gh CLI timed out while posting an inline comment."
    if completed.returncode == 0:
        return True, completed.stdout.strip()
    return False, completed.stderr.strip() or "gh api returned a non-zero exit code"


def post_summary_comment(
    pr: int,
    body: str,
    *,
    repo_root: Path,
    repo: str | None = None,
) -> tuple[bool, str]:
    """Post the PR-level summary comment. Returns ``(success, output_or_error)``."""
    args = ["pr", "comment", str(pr), "--body", body]
    if repo:
        args.extend(["--repo", repo])
    try:
        completed = _run_gh(args, repo_root=repo_root)
    except FileNotFoundError:
        return False, "gh CLI not found. Install it from https://cli.github.com/"
    except subprocess.TimeoutExpired:
        return False, "gh CLI timed out while posting the review summary."
    if completed.returncode == 0:
        return True, completed.stdout.strip()
    return False, completed.stderr.strip() or "gh pr comment returned a non-zero exit code"


def post_report(
    pr: int,
    report: ReviewReport,
    *,
    repo_root: Path,
    repo: str | None = None,
    dry_run: bool = False,
) -> PostResult:
    """Post inline comments plus one summary comment for *report*.

    ``dry_run=True`` is a strict no-op: no subprocess is executed and nothing is
    posted.  Callers should skip this function entirely when the user did not
    explicitly opt in.
    """
    result = PostResult()
    if dry_run:
        return result

    if not check_gh_auth(repo_root):
        raise ReviewError(
            "Posting review comments requires an authenticated gh CLI. "
            "Install gh and run 'gh auth login'.",
            code=GH_NOT_AUTHENTICATED,
        )

    for finding in report.findings:
        if finding.line <= 0:
            continue
        ok, message = post_inline_comment(
            pr,
            finding.file,
            finding.line,
            format_inline_comment(finding),
            repo_root=repo_root,
            repo=repo,
        )
        if ok:
            result.posted_inline += 1
        else:
            result.errors.append(
                f"{finding.file}:{finding.line}: {message}"
            )

    summary_ok, summary_message = post_summary_comment(
        pr,
        report.summary,
        repo_root=repo_root,
        repo=repo,
    )
    result.summary_posted = summary_ok
    if not summary_ok:
        result.errors.append(f"summary: {summary_message}")

    return result
