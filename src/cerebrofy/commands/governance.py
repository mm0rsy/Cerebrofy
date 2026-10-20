"""cerebrofy governance — lobe ownership, CODEOWNERS, and review governance."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import rich_click as click

from cerebrofy.config.loader import CerebrоfyConfig
from cerebrofy.errors import (
    ConfigError,
    GitHubNotAuthenticatedError,
    NoGitHistoryError,
)
from cerebrofy.governance.codeowners import generate_codeowners, write_codeowners
from cerebrofy.governance.reviewer import (
    ChangeSet,
    ReviewerSuggestion,
    changes_from_diff,
    changes_from_pr,
    suggest_reviewers,
)
from cerebrofy.governance.rules import (
    GovernanceCheckResult,
    GovernanceRulesError,
    evaluate_governance_rules,
)

_EXIT_ERROR = 1
_EXIT_USAGE = 2


@click.group("governance")
def cerebrofy_governance() -> None:
    """Own the codebase: dynamic CODEOWNERS, reviewer suggestions, governance rules."""


def _resolve_root() -> Path:
    from cerebrofy.utils.paths import InvalidRepoRootError, find_repo_root

    try:
        root = find_repo_root(Path.cwd())
    except InvalidRepoRootError as exc:
        click.echo(f"Error: [NO_INDEX] {exc}", err=True)
        sys.exit(_EXIT_ERROR)
    if root is None:
        click.echo(
            "Error: [NO_INDEX] No index found. Run 'cerebrofy build' first.",
            err=True,
        )
        sys.exit(_EXIT_ERROR)
    return root


def _load_config(root: Path) -> CerebrоfyConfig:
    from cerebrofy.config.loader import load_config

    try:
        return load_config(root / ".cerebrofy" / "config.yaml")
    except (FileNotFoundError, ConfigError) as exc:
        click.echo(f"Error: [CONFIG_ERROR] {exc}", err=True)
        sys.exit(_EXIT_USAGE)


def _open_db(root: Path) -> sqlite3.Connection:
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        click.echo("Error: [NO_INDEX] Index not found. Run 'cerebrofy build' first.", err=True)
        sys.exit(_EXIT_ERROR)
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def _changes(root: Path, pr: int | None, diff: str | None) -> ChangeSet | None:
    if pr is not None and diff is not None:
        click.echo("Error: --pr and --diff are mutually exclusive.", err=True)
        sys.exit(_EXIT_USAGE)
    try:
        if pr is not None:
            return changes_from_pr(pr)
        if diff is not None:
            return changes_from_diff(root, diff)
    except GitHubNotAuthenticatedError as exc:
        click.echo(f"Error: [GH_NOT_AUTHENTICATED] {exc}", err=True)
        sys.exit(_EXIT_ERROR)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(_EXIT_USAGE)
    return None


def _render_reviewers(
    reviewers: tuple[ReviewerSuggestion, ...], fmt: str
) -> str:
    if fmt == "json":
        return json.dumps(
            {"reviewers": [reviewer.to_dict() for reviewer in reviewers]}, indent=2
        )
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


def _render_rules(result: GovernanceCheckResult, fmt: str) -> str:
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


# ---------------------------------------------------------------------------
# generate-codeowners
# ---------------------------------------------------------------------------


@cerebrofy_governance.command("generate-codeowners")
@click.option("--dry-run", is_flag=True, default=False, help="Print the file instead of writing it.")
@click.option(
    "--output",
    "output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write to PATH instead of <repo>/CODEOWNERS.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite an existing hand-maintained CODEOWNERS file.",
)
def generate_codeowners_command(
    dry_run: bool, output: Path | None, force: bool
) -> None:
    """Generate CODEOWNERS from git blame, team.yaml, and cross-lobe calls."""
    root = _resolve_root()
    config = _load_config(root)
    conn = _open_db(root)
    try:
        try:
            result = generate_codeowners(conn, root, config)
        except NoGitHistoryError as exc:
            click.echo(f"Error: [NO_GIT_HISTORY] {exc}", err=True)
            sys.exit(_EXIT_ERROR)
    finally:
        conn.close()

    target = output or result.path
    if dry_run:
        click.echo(result.content, nl=False)
        return
    try:
        write_codeowners(target, result.content, force=force, repo_root=root)
    except FileExistsError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(_EXIT_USAGE)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(_EXIT_USAGE)
    click.echo(f"Cerebrofy: wrote {target} ({len(result.lobes)} lobes).")


# ---------------------------------------------------------------------------
# sync
# ---------------------------------------------------------------------------


@cerebrofy_governance.command("sync")
def sync_codeowners_command() -> None:
    """Regenerate CODEOWNERS in place (same protection as build auto-sync)."""
    root = _resolve_root()
    config = _load_config(root)
    conn = _open_db(root)
    try:
        try:
            result = generate_codeowners(conn, root, config)
        except NoGitHistoryError as exc:
            click.echo(f"Error: [NO_GIT_HISTORY] {exc}", err=True)
            sys.exit(_EXIT_ERROR)
    finally:
        conn.close()

    try:
        write_codeowners(result.path, result.content, repo_root=root)
    except FileExistsError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(_EXIT_USAGE)
    click.echo(f"Cerebrofy: CODEOWNERS synced ({len(result.lobes)} lobes).")


# ---------------------------------------------------------------------------
# suggest-reviewers
# ---------------------------------------------------------------------------


@cerebrofy_governance.command("suggest-reviewers")
@click.option("--pr", type=int, default=None, help="GitHub PR number (requires authenticated gh).")
@click.option("--diff", "diff_ref", default=None, help="Local git ref to diff against.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(("markdown", "json"), case_sensitive=False),
    default="markdown",
    show_default=True,
    help="Output format.",
)
def suggest_reviewers_command(pr: int | None, diff_ref: str | None, fmt: str) -> None:
    """Suggest primary, secondary, and backup reviewers for a change set."""
    root = _resolve_root()
    config = _load_config(root)
    changes = _changes(root, pr, diff_ref)
    conn = _open_db(root)
    try:
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
            click.echo(f"Error: [NO_GIT_HISTORY] {exc}", err=True)
            sys.exit(_EXIT_ERROR)
    finally:
        conn.close()
    click.echo(_render_reviewers(reviewers, fmt.lower()))


# ---------------------------------------------------------------------------
# check-rules
# ---------------------------------------------------------------------------


@cerebrofy_governance.command("check-rules")
@click.option("--lobe", default=None, help="Restrict evaluation to a specific lobe.")
@click.option("--pr", type=int, default=None, help="GitHub PR number (requires authenticated gh).")
@click.option("--diff", "diff_ref", default=None, help="Local git ref to diff against.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(("markdown", "json"), case_sensitive=False),
    default="markdown",
    show_default=True,
    help="Output format.",
)
def check_rules_command(
    lobe: str | None, pr: int | None, diff_ref: str | None, fmt: str
) -> None:
    """Evaluate governance.rules from arch-rules.yaml (reporting only)."""
    root = _resolve_root()
    config = _load_config(root)
    from cerebrofy.arch.rules import RulesError
    from cerebrofy.config.loader import load_arch_rules

    try:
        rules = load_arch_rules(root)
    except RulesError as exc:
        click.echo(f"Error: [CONFIG_ERROR] {exc}", err=True)
        sys.exit(_EXIT_USAGE)
    if rules is None or rules.governance is None or not rules.governance.rules:
        click.echo(
            "Error: [NO_GOVERNANCE_RULES] No governance.rules block found in "
            ".cerebrofy/arch-rules.yaml.",
            err=True,
        )
        sys.exit(_EXIT_USAGE)
    if lobe is not None and lobe not in config.lobes:
        click.echo(
            f"Error: unknown lobe '{lobe}'. Available: {', '.join(sorted(config.lobes))}",
            err=True,
        )
        sys.exit(_EXIT_USAGE)

    changes = _changes(root, pr, diff_ref)
    conn = _open_db(root)
    try:
        try:
            result = evaluate_governance_rules(
                rules.governance,
                conn,
                root,
                config.lobes,
                changes=changes,
                lobe=lobe,
                strategy=config.governance.strategy,
                activity_days=config.governance.activity_days,
            )
        except (NoGitHistoryError, ValueError, GovernanceRulesError) as exc:
            code = getattr(exc, "code", "CONFIG_ERROR")
            click.echo(f"Error: [{code}] {exc}", err=True)
            sys.exit(_EXIT_ERROR)
    finally:
        conn.close()
    click.echo(_render_rules(result, fmt.lower()))
