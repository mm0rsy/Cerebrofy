"""MCP handler for the ``cerebrofy_review`` tool (Idea #17)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cerebrofy.mcp.errors import mcp_error as _err
from cerebrofy.review.pipeline import (
    ReviewError,
    review_diff_or_pr,
)
from cerebrofy.utils.paths import find_repo_root as _find_repo_root_impl


def _find_root(cwd: Path) -> Path:
    root = _find_repo_root_impl(cwd)
    if root is None:
        raise FileNotFoundError("No Cerebrofy config found. Run 'cerebrofy init' first.")
    return root


def handle_review(arguments: dict[str, Any]) -> list[Any]:
    """Run the graph-aware review pipeline.

    Input: {diff?, pr?, severity? (all), post_comments? (false), format? (markdown)}
    Output: the spec review payload — files_changed, neurons_changed, findings,
    suggested_reviewers, health_delta, summary.

    Error codes: NO_INDEX, NO_DIFF_PROVIDED, GH_NOT_AUTHENTICATED.
    """
    from mcp.types import TextContent

    diff = str(arguments.get("diff") or "").strip() or None
    pr_raw = arguments.get("pr")
    pr: int | None = None
    if pr_raw is not None and pr_raw != "":
        try:
            pr = int(pr_raw)
        except (TypeError, ValueError):
            return _err("[error] 'pr' must be an integer PR number.")
    severity = str(arguments.get("severity") or "all").lower()
    if severity not in ("error", "warning", "all"):
        return _err(
            f"[error] Invalid severity '{severity}'. Choose from: error, warning, all."
        )
    post_comments = bool(arguments.get("post_comments", False))
    output_format = str(arguments.get("format") or "markdown").lower()
    if output_format not in ("markdown", "json"):
        return _err(
            f"[error] Invalid format '{output_format}'. Choose from: markdown, json."
        )

    if diff is None and pr is None:
        return _err("[NO_DIFF_PROVIDED] Provide a 'diff' ref or a 'pr' number.")

    if post_comments and pr is None:
        return _err("[NO_DIFF_PROVIDED] 'post_comments' requires the 'pr' parameter.")

    try:
        root = _find_root(Path.cwd())
    except Exception:  # noqa: BLE001
        return _err(
            "[NO_INDEX] No .cerebrofy directory found. "
            "Run 'cerebrofy init' and 'cerebrofy build' first."
        )

    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        return _err("[NO_INDEX] Index not found. Run 'cerebrofy build' first.")

    try:
        report = review_diff_or_pr(
            root=root,
            diff=diff,
            pr=pr,
            severity=severity,
        )
    except ReviewError as exc:
        return _err(f"[{exc.code}] {exc}")
    except Exception as exc:  # noqa: BLE001
        return _err(f"cerebrofy_review failed: {exc}")

    if post_comments and pr is not None:
        from cerebrofy.review.github_poster import post_report

        try:
            result = post_report(pr, report, repo_root=root)
        except ReviewError as exc:
            return _err(f"[{exc.code}] {exc}")
        report.post_result = result.to_dict()
        if result.errors:
            report.summary = report.summary.rstrip() + (
                "\n> ⚠️ Some comments could not be posted: " + "; ".join(result.errors)
            )

    if output_format == "json":
        return [TextContent(type="text", text=json.dumps(report.to_dict(), indent=2))]
    return [TextContent(type="text", text=report.summary)]
