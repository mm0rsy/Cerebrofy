"""cerebrofy arch — architecture drift alerts over the live call graph."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path

import rich_click as click

from cerebrofy.arch.checker import (
    CheckResult,
    changed_files_since,
    fix_hint,
    run_arch_check,
)
from cerebrofy.arch.ci import CI_WORKFLOW_PATH, write_ci_workflow
from cerebrofy.arch.history import (
    current_commit,
    entry_from_result,
    first_violation_map,
    read_history,
    record_history,
)
from cerebrofy.arch.reporter import (
    render_annotations,
    render_json,
    render_markdown,
    render_text,
)
from cerebrofy.arch.rules import (
    AllowedCallersCheck,
    ArchRule,
    Check,
    MaxBlastRadiusCheck,
    NoCyclesCheck,
    NoEdgeCheck,
    RulesConfig,
    RulesError,
    SLACK_WEBHOOK_ENV,
    dump_arch_rules,
    load_arch_rules,
    rules_path,
    scaffold_arch_rules,
)
from cerebrofy.arch.watcher import WatchSample, send_slack, watch_forever
from cerebrofy.config.loader import load_config
from cerebrofy.db.connection import open_db_readonly

_EXIT_VIOLATIONS = 1
_EXIT_CONFIG = 2

_CheckPromptFn = Callable[[list[str]], tuple[Check, dict[str, str]]]


@click.group("arch")
def cerebrofy_arch() -> None:
    """Define and enforce architecture drift rules over the live call graph."""


# ---------------------------------------------------------------------------
# Shared internals
# ---------------------------------------------------------------------------

def _require_init(root: Path) -> None:
    """Exit 2 (config error) when .cerebrofy/config.yaml is missing."""
    if not (root / ".cerebrofy" / "config.yaml").exists():
        click.echo(
            "Error: .cerebrofy/config.yaml not found. Run 'cerebrofy init' first.", err=True
        )
        sys.exit(_EXIT_CONFIG)


def _load_rules(root: Path) -> RulesConfig | None:
    """Load arch rules; malformed file exits 2, missing file returns None."""
    try:
        return load_arch_rules(root)
    except RulesError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(_EXIT_CONFIG)


def _load_lobes(root: Path) -> dict[str, str]:
    """Load config.yaml and return its lobe mapping; any failure exits 2."""
    try:
        config = load_config(root / ".cerebrofy" / "config.yaml")
    except Exception as exc:
        click.echo(f"Error: .cerebrofy/config.yaml could not be loaded — {exc}", err=True)
        sys.exit(_EXIT_CONFIG)
    return config.lobes


def _apply_since(root: Path, since_ref: str | None) -> frozenset[str] | None:
    if since_ref is None:
        return None
    try:
        return frozenset(changed_files_since(root, since_ref))
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(_EXIT_CONFIG)


def _apply_since_quiet(root: Path, since_ref: str | None) -> frozenset[str] | None:
    """Like _apply_since but degrades to 'no filter' when git fails mid-watch."""
    if since_ref is None:
        return None
    try:
        return frozenset(changed_files_since(root, since_ref))
    except ValueError as exc:
        click.echo(f"Warning: {exc}", err=True)
        return None


def _run_check(
    root: Path,
    rules: RulesConfig,
    lobes: dict[str, str],
    rule_name: str | None,
    changed_files: frozenset[str] | None,
) -> CheckResult:
    """Open the index read-only and evaluate the rules."""
    conn: sqlite3.Connection = open_db_readonly(root / ".cerebrofy" / "db" / "cerebrofy.db")
    try:
        return run_arch_check(
            rules,
            conn,
            lobes,
            repo_root=root,
            rule_name=rule_name,
            changed_files=changed_files,
        )
    finally:
        conn.close()


def _render(result: CheckResult, fmt: str, hook_mode: bool) -> str:
    if fmt == "json":
        return render_json(result)
    if fmt == "markdown":
        return render_markdown(result)
    if fmt == "github-annotations":
        return render_annotations(result)
    return render_text(result, hook_mode=hook_mode)


def _exit_with_code(result: CheckResult) -> None:
    """0 = pass/warn-only, 1 = error-severity violations, 2 = rule config errors."""
    if result.error_violations:
        sys.exit(_EXIT_VIOLATIONS)
    if result.config_errors:
        sys.exit(_EXIT_CONFIG)


def _slack_message(result: CheckResult) -> str:
    """Names-and-counts summary — rule names only, never source code."""
    lines = [
        f"Cerebrofy architecture check — {result.result}",
        (
            f"{len(result.rule_results)} rules checked · "
            f"{len(result.error_violations)} error(s), "
            f"{len(result.warning_violations)} warning(s)"
        ),
    ]
    for rr in result.rule_results:
        if rr.error is None and rr.violations:
            icon = "🔴" if rr.rule.severity == "error" else "⚠️"
            lines.append(f"{icon} {rr.rule.name}: {len(rr.violations)} violation(s)")
    for _, err in result.config_errors:
        lines.append(f"⛔ {err}")
    return "\n".join(lines)


def _slack_webhook(rules: RulesConfig) -> str | None:
    return os.environ.get(SLACK_WEBHOOK_ENV) or rules.slack_webhook


def _maybe_slack(result: CheckResult, rules: RulesConfig, requested: bool) -> None:
    if not requested:
        return
    if not (result.error_violations or result.warning_violations or result.config_errors):
        return
    webhook = _slack_webhook(rules)
    if webhook is None:
        click.echo(
            "Warning: --slack requested but no webhook configured "
            f"(set {SLACK_WEBHOOK_ENV} or 'slack_webhook:' in arch-rules.yaml).",
            err=True,
        )
        return
    error = send_slack(webhook, _slack_message(result))
    if error is not None:
        click.echo(f"Warning: Slack notification failed: {error}", err=True)


def _describe_check(rule: ArchRule) -> str:
    check = rule.check
    if isinstance(check, NoEdgeCheck):
        src = check.from_lobe or "|".join(check.from_patterns)
        dst = check.to_lobe or "|".join(check.to_patterns)
        return f"no_edge: '{src}' must not call '{dst}'"
    if isinstance(check, NoCyclesCheck):
        return f"no_cycles: scope={check.scope}"
    if isinstance(check, AllowedCallersCheck):
        return (
            f"allowed_callers: '{check.neuron}' must only be called from "
            f"[{', '.join(check.from_lobes)}]"
        )
    assert isinstance(check, MaxBlastRadiusCheck)
    return f"max_blast_radius: reverse callers (depth 1+2) must be <= {check.limit}"


def _rule_by_name(rules: RulesConfig, name: str) -> ArchRule:
    return next(rule for rule in rules.rules if rule.name == name)


# ---------------------------------------------------------------------------
# cerebrofy arch check
# ---------------------------------------------------------------------------

@cerebrofy_arch.command("check")
@click.option("--rule", "rule_name", default=None, help="Check a single rule by name.")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(("text", "json", "markdown", "github-annotations"), case_sensitive=False),
    default="text",
    show_default=True,
    help="Report format.",
)
@click.option(
    "--since",
    "since_ref",
    default=None,
    help="Only report drift touching files changed since this git ref (e.g. HEAD~1).",
)
@click.option(
    "--slack",
    is_flag=True,
    default=False,
    help="Post a Slack summary when violations exist (CEREBROFY_SLACK_WEBHOOK or slack_webhook: key).",
)
@click.option(
    "--record/--no-record",
    "record",
    default=True,
    help="Append the run outcome to .cerebrofy/arch-history.jsonl.",
)
@click.option(
    "--hook",
    "hook_name",
    default=None,
    hidden=True,
    help="Invoked by a git hook — suppresses history and stays quiet when clean.",
)
def arch_check(
    rule_name: str | None,
    fmt: str,
    since_ref: str | None,
    slack: bool,
    record: bool,
    hook_name: str | None,
) -> None:
    """Check all architecture rules and report violations.

    Exit codes: 0 = pass or warnings only, 1 = error-severity violations
    (blocks commits/pushes/CI), 2 = configuration or usage error.
    """
    fmt = fmt.lower()
    root = Path.cwd()
    _require_init(root)

    rules = _load_rules(root)
    if rules is None:
        click.echo(
            "No architecture rules defined — run 'cerebrofy arch init' to create "
            ".cerebrofy/arch-rules.yaml."
        )
        return
    if rule_name is not None and rule_name not in rules.rule_names:
        click.echo(
            f"Error: rule '{rule_name}' not found. "
            f"Available rules: {', '.join(rules.rule_names) or '(none)'}",
            err=True,
        )
        sys.exit(_EXIT_CONFIG)

    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        if hook_name is None:
            click.echo("Warning: no index yet — run 'cerebrofy build' first. Check skipped.", err=True)
        return

    lobes = _load_lobes(root)
    changed_files = _apply_since(root, since_ref)

    result = _run_check(root, rules, lobes, rule_name, changed_files)
    text = _render(result, fmt, hook_mode=hook_name is not None)
    if text:
        click.echo(text)

    _maybe_slack(result, rules, slack)
    if record and hook_name is None:
        try:
            record_history(root, entry_from_result(result, current_commit(root), since_ref))
        except OSError as exc:
            click.echo(f"Warning: could not record history — {exc}", err=True)
    _exit_with_code(result)


# ---------------------------------------------------------------------------
# cerebrofy arch explain
# ---------------------------------------------------------------------------

@cerebrofy_arch.command("explain")
@click.argument("rule_name")
def arch_explain(rule_name: str) -> None:
    """Show RULE_NAME's check definition and every current violation."""
    root = Path.cwd()
    _require_init(root)

    rules = _load_rules(root)
    if rules is None or rule_name not in rules.rule_names:
        available = ", ".join(rules.rule_names) if rules else "(none)"
        click.echo(
            f"Error: rule '{rule_name}' not found in .cerebrofy/arch-rules.yaml. "
            f"Available rules: {available}",
            err=True,
        )
        sys.exit(_EXIT_CONFIG)
    rule = _rule_by_name(rules, rule_name)

    click.echo(f"\n🧠 Rule: {rule.name}")
    blocking = "blocks commits/CI" if rule.severity == "error" else "informational only"
    click.echo(f"   Severity: {rule.severity} ({blocking})")
    click.echo(f"   Check: {_describe_check(rule)}")
    click.echo(f"   Fix hint: {fix_hint(rule.check.__class__.__name__, rule.description)}")
    click.echo()

    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        click.echo("No index found — run 'cerebrofy build' first to see current violations.")
        return

    result = _run_check(root, rules, _load_lobes(root), rule_name, None)
    click.echo(render_text(result))
    _exit_with_code(result)


# ---------------------------------------------------------------------------
# cerebrofy arch history
# ---------------------------------------------------------------------------

@cerebrofy_arch.command("history")
@click.option(
    "--limit", default=30, show_default=True, help="Max archived runs to consider."
)
@click.option("--json", "as_json", is_flag=True, default=False, help="Machine-readable output.")
def arch_history(limit: int, as_json: bool) -> None:
    """Show when each architecture rule was first violated, plus run history."""
    root = Path.cwd()
    entries = read_history(root)
    if not entries:
        click.echo("No arch check history yet — run 'cerebrofy arch check' first.")
        return

    if as_json:
        click.echo(json.dumps([entry.to_dict() for entry in entries], indent=2))
        return

    recent = entries[-limit:]
    click.echo(f"\n🧠 Cerebrofy — Architecture History ({len(entries)} runs recorded)")
    latest = recent[-1]
    commit_note = f" (commit {latest.commit})" if latest.commit else ""
    click.echo(f"  newest run: {latest.result} at {_fmt_ts(latest.ts)}{commit_note}")
    click.echo()

    firsts = first_violation_map(entries)
    titles = sorted(
        {rule for entry in recent for rule in entry.passing}
        | {failure.rule for entry in recent for failure in entry.failing}
    )
    width = max((len(name) for name in titles), default=4)
    for name in titles:
        first = firsts.get(name)
        if first is None:
            origin = "never violated"
        else:
            origin = _fmt_ts(first.ts) + (f" (commit {first.commit})" if first.commit else "")
        failing_runs = sum(
            1
            for entry in recent
            for failure in entry.failing
            if failure.rule == name and failure.count > 0
        )
        click.echo(
            f"  {name:<{width}}  first violated: {origin:<32} "
            f"failing runs: {failing_runs}/{len(recent)}"
        )
    click.echo()


def _fmt_ts(ts: int) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# cerebrofy arch init
# ---------------------------------------------------------------------------

@cerebrofy_arch.command("init")
@click.option(
    "--ci",
    is_flag=True,
    default=False,
    help="Also write the GitHub Actions workflow (.github/workflows/cerebrofy-arch.yml).",
)
@click.option("--force", is_flag=True, default=False, help="Overwrite the CI workflow if present.")
def arch_init(ci: bool, force: bool) -> None:
    """Create .cerebrofy/arch-rules.yaml and start the interactive rule builder."""
    root = Path.cwd()
    _require_init(root)

    path = rules_path(root)
    if not path.exists():
        scaffold_arch_rules(path)
        click.echo(f"Created {path} — uncomment examples, or use the builder below.")

    if ci:
        _write_ci_workflow(root, force)
        return

    _run_rule_wizard(root)
    click.echo("Run 'cerebrofy arch check' to see current violations.")


def _write_ci_workflow(root: Path, force: bool) -> None:
    path = root / CI_WORKFLOW_PATH
    if write_ci_workflow(root, force=force):
        click.echo(f"Created {path}")
    else:
        click.echo(f"CI workflow already exists at {path} (use --force to overwrite).")


# ---------------------------------------------------------------------------
# Rule builder wizard
# ---------------------------------------------------------------------------


def _run_rule_wizard(root: Path) -> None:
    """Prompt for one rule and rewrite arch-rules.yaml (comments are not preserved)."""
    lobes = sorted(_load_lobes(root))
    kind = str(
        click.prompt(
            "What should be restricted?",
            type=click.Choice(tuple(_CHECK_PROMPTS), case_sensitive=False),
            default="edge-between-lobes",
        )
    ).lower()
    prompt_fn, name_template = _CHECK_PROMPTS[kind]
    check, name_defaults = prompt_fn(lobes)
    default_name = name_template.format(**name_defaults)

    severity = str(
        click.prompt(
            "Severity?",
            type=click.Choice(("error", "warning"), case_sensitive=False),
            default="warning",
        )
    ).lower()
    description = str(click.prompt("Description (used as the Fix: hint)", default=""))
    name = str(click.prompt("Rule name?", default=default_name)).strip() or default_name
    rule = ArchRule(name=name, severity=severity, check=check, description=description)

    existing = _load_rules(root)
    known = existing.rules if existing else ()
    kept = [r for r in known if r.name != name]
    if len(kept) != len(known):
        click.echo(f"Replacing existing rule '{name}'.")
    dump_arch_rules(
        RulesConfig(
            rules=tuple([*kept, rule]),
            slack_webhook=existing.slack_webhook if existing else None,
        ),
        rules_path(root),
    )
    click.echo(f"✅ Rule added to {rules_path(root)}")


def _prompt_edge_check(lobes: list[str]) -> tuple[Check, dict[str, str]]:
    from_lobe = click.prompt("From which lobe?", type=click.Choice(lobes), default=lobes[0])
    to_lobe = click.prompt(
        "To which lobe?",
        type=click.Choice(lobes),
        default=lobes[-1] if len(lobes) > 1 else lobes[0],
    )
    return NoEdgeCheck(from_lobe=from_lobe, to_lobe=to_lobe), {
        "src_lobe": str(from_lobe),
        "to_lobe": str(to_lobe),
    }


def _prompt_allowed_callers(lobes: list[str]) -> tuple[Check, dict[str, str]]:
    pattern = click.prompt(
        "Neuron pattern (glob over file::name, name, or file path)", default=f"*{lobes[0]}/*"
    )
    allowed = click.prompt("Allowed caller lobes (comma separated)", default=lobes[0])
    from_lobes = tuple(
        part.strip() for part in str(allowed).split(",") if part.strip()
    )
    return (
        AllowedCallersCheck(neuron=str(pattern), from_lobes=from_lobes),
        {"first_lobe": lobes[0]},
    )


def _prompt_blast_radius(lobes: list[str]) -> tuple[Check, dict[str, str]]:
    _ = lobes
    limit = click.prompt(
        "Max blast radius (reverse callers at depth 1 + 2)",
        type=click.IntRange(min=1),
        default=50,
    )
    return MaxBlastRadiusCheck(limit=int(limit)), {}


def _prompt_cycles(lobes: list[str]) -> tuple[Check, dict[str, str]]:
    _ = lobes
    click.echo("No further configuration — cycles are detected across all lobes.")
    return NoCyclesCheck(scope="lobes"), {}


_CHECK_PROMPTS: dict[str, tuple[_CheckPromptFn, str]] = {
    "edge-between-lobes": (_prompt_edge_check, "no-{src_lobe}-in-{to_lobe}"),
    "allowed-callers": (_prompt_allowed_callers, "{first_lobe}-is-isolated"),
    "max-blast-radius": (_prompt_blast_radius, "max-blast-radius"),
    "no-cycles": (_prompt_cycles, "no-circular-lobe-deps"),
}


# ---------------------------------------------------------------------------
# cerebrofy arch watch
# ---------------------------------------------------------------------------

@cerebrofy_arch.command("watch")
@click.option(
    "--interval", type=float, default=2.0, show_default=True, help="Seconds between re-checks."
)
@click.option("--rule", "rule_name", default=None, help="Watch a single rule by name.")
@click.option("--since", "since_ref", default=None, help="Scope to files changed since this git ref.")
@click.option(
    "--slack",
    is_flag=True,
    default=False,
    help="Post a Slack summary whenever the drift set changes.",
)
@click.option("--clear/--no-clear", "clear", default=True, help="Redraw the terminal each update.")
def arch_watch(
    interval: float,
    rule_name: str | None,
    since_ref: str | None,
    slack: bool,
    clear: bool,
) -> None:
    """Live monitor: re-run the architecture check on an interval."""
    root = Path.cwd()
    _require_init(root)
    rules = _load_rules(root)
    if rules is None:
        click.echo("No architecture rules defined — run 'cerebrofy arch init' first.")
        return
    if rule_name is not None and rule_name not in rules.rule_names:
        click.echo(f"Error: rule '{rule_name}' not found.", err=True)
        sys.exit(_EXIT_CONFIG)

    webhook = _slack_webhook(rules) if slack else None
    if slack and webhook is None:
        click.echo(
            f"Warning: --slack requested but no webhook configured (set {SLACK_WEBHOOK_ENV}).",
            err=True,
        )

    def sample() -> WatchSample:
        try:
            result = _run_check(
                root, rules, _load_lobes(root), rule_name, _apply_since_quiet(root, since_ref)
            )
            drift = sorted(
                (v.rule_name, v.location, v.detail)
                for rr in result.rule_results
                for v in rr.violations
            ) + [(name, err, "config") for name, err in result.config_errors]
            state = result.result + "|" + ",".join(f"{r}:{c}" for r, c, _ in drift)
            alert_text = _slack_message(result) if drift else None
            return WatchSample(state=state, text=render_text(result), alert_text=alert_text)
        except Exception as exc:  # keep the loop alive on transient read errors
            return WatchSample(state=f"error:{exc}", text=f"Error: {exc}", alert_text=None)

    def notify(message: str) -> None:
        if webhook is None:
            return
        error = send_slack(webhook, message)
        if error is not None:
            click.echo(f"Warning: Slack notification failed: {error}", err=True)

    try:
        watch_forever(sample, interval=interval, clear=clear, on_state_change=notify)
    except KeyboardInterrupt:
        click.echo("\nCerebrofy: watch stopped.")
