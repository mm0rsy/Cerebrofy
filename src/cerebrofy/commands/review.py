"""cerebrofy review — graph-aware AI review copilot for diffs and PRs."""

from __future__ import annotations

import sys
from pathlib import Path

import rich_click as click

from cerebrofy.review.pipeline import ReviewError, review_diff_or_pr


@click.command("review")
@click.option(
    "--pr",
    "pr_number",
    type=int,
    default=None,
    help="GitHub PR number to review via `gh pr diff` (requires gh auth).",
)
@click.option(
    "--diff",
    "diff_ref",
    default=None,
    help="Git ref to diff against (e.g. HEAD, HEAD~1, main). Supports uncommitted changes with HEAD.",
)
@click.option(
    "--severity",
    type=click.Choice(["error", "warning", "all"]),
    default="all",
    show_default=True,
    help="Minimum severity to report.",
)
@click.option(
    "--post-comments",
    is_flag=True,
    default=False,
    help="Post findings as inline GitHub comments plus a PR summary (requires --pr and gh auth).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    show_default=True,
    help="Output format.",
)
def cerebrofy_review(
    pr_number: int | None,
    diff_ref: str | None,
    severity: str,
    post_comments: bool,
    output_format: str,
) -> None:
    """Review a diff or PR with blast radius, memories, arch rules, coverage and silos.

    \b
    Examples:
      cerebrofy review --diff HEAD~1                # local pre-merge review
      cerebrofy review --diff HEAD                  # uncommitted changes
      cerebrofy review --pr 142                     # dry-run PR review
      cerebrofy review --pr 142 --post-comments     # post inline + summary comments
      cerebrofy review --pr 142 --severity error    # only blocking findings
    """
    if pr_number is None and not diff_ref:
        click.echo(
            "[NO_DIFF_PROVIDED] Provide --diff <ref> or --pr <number>."
        )
        sys.exit(1)

    from cerebrofy.review.github_poster import post_report

    root = Path.cwd()
    try:
        report = review_diff_or_pr(
            root=root,
            diff=diff_ref,
            pr=pr_number,
            severity=severity,
            record_session=True,
        )
    except ReviewError as exc:
        click.echo(f"[{exc.code}] {exc}")
        sys.exit(1)

    if output_format == "json":
        click.echo(report.to_json())
    else:
        click.echo(report.summary, nl=False)

    if not post_comments:
        return

    if pr_number is None:
        click.echo(
            "[GH_NOT_AUTHENTICATED] --post-comments requires --pr <number>.",
            err=True,
        )
        sys.exit(1)

    try:
        result = post_report(pr_number, report, repo_root=root)
    except ReviewError as exc:
        click.echo(f"[{exc.code}] {exc}", err=True)
        sys.exit(1)

    report.post_result = result.to_dict()
    if result.summary_posted:
        click.echo(
            f"Posted {result.posted_inline} inline comment(s) and a summary to "
            f"PR #{pr_number}.",
            err=True,
        )
    for error in result.errors:
        click.echo(f"Cerebrofy: comment failed — {error}", err=True)
