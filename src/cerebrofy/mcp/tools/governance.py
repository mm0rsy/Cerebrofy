"""MCP handler for the cerebrofy_governance tool (Idea #18)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from collections.abc import Sequence
from typing import Any

from cerebrofy.mcp.errors import mcp_error as _err
from cerebrofy.utils.paths import find_repo_root as _find_repo_root_impl


def _find_root(cwd: Path) -> Path:
    root = _find_repo_root_impl(cwd)
    if root is None:
        raise FileNotFoundError("No Cerebrofy config found. Run 'cerebrofy init' first.")
    return root


def _render_reviewers(reviewers: Sequence[Any], fmt: str) -> str:
    payload = {"reviewers": [reviewer.to_dict() for reviewer in reviewers]}
    if fmt == "json":
        return json.dumps(payload, indent=2)
    if not reviewers:
        return "No reviewer suggestions — no ownership history yet."
    lines = [
        "## Suggested Reviewers",
        "",
        "| Role | Reviewer | Lobe | Reason |",
        "|------|----------|------|--------|",
    ]
    for reviewer in reviewers:
        lines.append(
            f"| {reviewer.role} | {reviewer.email} | {reviewer.lobe} | {reviewer.reason} |"
        )
    return "\n".join(lines)


def _render_rules(result: Any, fmt: str) -> str:
    if fmt == "json":
        return json.dumps(result.to_dict(), indent=2)
    lines = [
        f"## Governance Rules — {result.result}",
        "",
        f"_{result.rules_checked} rule(s) checked · "
        f"{len(result.failing)} failing · {len(result.warnings)} warning(s)_",
        "",
    ]
    icons = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}
    for item in result.evaluations:
        icon = icons.get(item.status, "•")
        lines.append(f"- {icon} **{item.name}** — {item.reason}")
    if not result.evaluations:
        lines.append("_No governance rules configured._")
    return "\n".join(lines)


def handle_governance(arguments: dict[str, Any]) -> list[Any]:
    """Ownership + CODEOWNERS + governance rules over the live index.

    Input: {action (required): generate-codeowners | suggest-reviewers |
    check-rules, pr?, lobe?, format?}.

    Error codes: NO_INDEX, NO_GIT_HISTORY, CONFIG_ERROR, GH_NOT_AUTHENTICATED,
    NO_GOVERNANCE_RULES.
    """
    from mcp.types import TextContent

    action = str(arguments.get("action") or "").strip().lower()
    if action not in ("generate-codeowners", "suggest-reviewers", "check-rules"):
        return _err(
            "[error] 'action' must be one of: generate-codeowners, "
            "suggest-reviewers, check-rules."
        )
    fmt = str(arguments.get("format") or "markdown").strip().lower()
    if fmt not in ("markdown", "json"):
        return _err("[error] 'format' must be 'markdown' or 'json'.")

    try:
        root = _find_root(Path.cwd())
    except Exception:
        return _err(
            "[NO_INDEX] No .cerebrofy directory found. "
            "Run 'cerebrofy init' and 'cerebrofy build' first."
        )
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        return _err("[NO_INDEX] Index not found. Run 'cerebrofy build' first.")

    from cerebrofy.config.loader import load_config

    try:
        config = load_config(root / ".cerebrofy" / "config.yaml")
    except Exception as exc:
        return _err(f"[CONFIG_ERROR] {exc}")

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        if action == "generate-codeowners":
            from cerebrofy.errors import ConfigError, NoGitHistoryError
            from cerebrofy.governance.codeowners import generate_codeowners

            try:
                result = generate_codeowners(conn, root, config)
            except NoGitHistoryError as exc:
                return _err(f"[NO_GIT_HISTORY] {exc}")
            except ConfigError as exc:
                return _err(f"[CONFIG_ERROR] {exc}")
            if fmt == "json":
                return [
                    TextContent(
                        type="text",
                        text=json.dumps(
                            {"codeowners_content": result.content}, indent=2
                        ),
                    )
                ]
            return [TextContent(type="text", text=result.content)]

        pr = arguments.get("pr")
        if pr is not None:
            try:
                pr_number = int(pr)
            except (TypeError, ValueError):
                return _err("[error] 'pr' must be an integer.")
        else:
            pr_number = None

        from cerebrofy.errors import (
            ConfigError,
            GitHubNotAuthenticatedError,
            NoGitHistoryError,
        )
        from cerebrofy.governance.reviewer import (
            changes_from_pr,
            detect_new_neurons,
            suggest_reviewers,
        )

        changes = None
        if pr_number is not None:
            try:
                changes = changes_from_pr(pr_number)
            except GitHubNotAuthenticatedError as exc:
                return _err(f"[GH_NOT_AUTHENTICATED] {exc}")

        lobe = arguments.get("lobe")
        lobe_filter = str(lobe).strip() if lobe else None
        if lobe_filter is not None and lobe_filter not in config.lobes:
            return _err(
                f"[error] Unknown lobe '{lobe_filter}'. "
                f"Available: {', '.join(sorted(config.lobes))}"
            )

        if action == "suggest-reviewers":
            try:
                reviewers = suggest_reviewers(
                    conn,
                    root,
                    config.lobes,
                    changes,
                    strategy=config.governance.strategy,
                    activity_days=config.governance.activity_days,
                )
            except NoGitHistoryError as exc:
                return _err(f"[NO_GIT_HISTORY] {exc}")
            except ConfigError as exc:
                return _err(f"[CONFIG_ERROR] {exc}")
            return [TextContent(type="text", text=_render_reviewers(reviewers, fmt))]

        from cerebrofy.arch.rules import RulesError
        from cerebrofy.config.loader import load_arch_rules
        from cerebrofy.governance.rules import evaluate_governance_rules

        try:
            rules = load_arch_rules(root)
        except RulesError as exc:
            return _err(f"[CONFIG_ERROR] {exc}")
        if rules is None or rules.governance is None or not rules.governance.rules:
            return _err(
                "[NO_GOVERNANCE_RULES] No governance.rules block found in "
                ".cerebrofy/arch-rules.yaml."
            )
        if changes is not None:
            changes = detect_new_neurons(conn, changes)
        try:
            governance_result = evaluate_governance_rules(
                rules.governance,
                conn,
                root,
                config.lobes,
                changes=changes,
                lobe=lobe_filter,
                strategy=config.governance.strategy,
                activity_days=config.governance.activity_days,
            )
        except NoGitHistoryError as exc:
            return _err(f"[NO_GIT_HISTORY] {exc}")
        except ConfigError as exc:
            return _err(f"[CONFIG_ERROR] {exc}")
        except ValueError as exc:
            return _err(f"[error] {exc}")
        return [TextContent(type="text", text=_render_rules(governance_result, fmt))]
    finally:
        conn.close()
