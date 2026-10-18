"""Render a CheckResult as text, markdown, JSON, or GitHub Actions annotations."""

from __future__ import annotations

import json
from typing import Any

from cerebrofy.arch.checker import CheckResult, Violation, fix_hint

_DIVIDER = "─" * 64
_MAX_ANNOTATION = 400  # GitHub annotation message cap


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def render_text(result: CheckResult, *, hook_mode: bool = False) -> str:
    """Spec-style console report.

    hook_mode (under a git hook) suppresses the summary header and the PASS/WARN
    verdict so a green check prints nothing at all; a failing check still prints
    its violations and the FAILED verdict line.
    """
    errors = result.error_violations
    warnings = result.warning_violations
    lines: list[str] = []

    if not hook_mode:
        lines.extend(
            [
                "🧠 Cerebrofy Architecture Check",
                "",
                f"  Rules Checked: {len(result.rule_results)}",
                f"  ✅ Passing: {len(result.passing_rules)}",
            ]
        )
        if errors:
            lines.append(f"  🔴 Failing: {len(errors)}  (severity: error — blocking)")
        if warnings:
            lines.append(f"  ⚠️  Warnings: {len(warnings)}")
        for name, error in result.config_errors:
            lines.append(f"  ⛔ Config: rule '{name}' — {error}")
        lines.append("")

    for rr in result.rule_results:
        title = "🔴 RULE VIOLATION" if rr.rule.severity == "error" else "⚠️  WARNING"
        for v in rr.violations:
            lines.append(f"  {title}: {v.rule_name}")
            lines.append(f"  {_DIVIDER}")
            lines.append(f"  {v.location}")
            if v.detail:
                lines.append(f"  {v.detail}")
            if v.introduced_in:
                lines.append(f"  Introduced in: {v.introduced_in}")
            lines.append(f"  {_DIVIDER}")
            lines.append(f"  Fix: {fix_hint(v.kind, rr.rule.description)}")
            lines.append("")

    if hook_mode:
        if errors:
            lines.append(f"  RESULT: ❌ FAILED ({len(errors)} error{_plural(len(errors))})")
    else:
        lines.append(_verdict_line(result))
    return "\n".join(lines).rstrip()


def _verdict_line(result: CheckResult) -> str:
    errors = result.error_violations
    warnings = result.warning_violations
    if errors:
        verdict = f"RESULT: ❌ FAILED ({len(errors)} error{_plural(len(errors))})"
        if result.config_errors:
            verdict += f" — {len(result.config_errors)} rule configuration error(s)"
        return f"{verdict} — commit blocked"
    if warnings:
        return f"RESULT: ⚠️  WARN ({len(warnings)} warning{_plural(len(warnings))})"
    return "RESULT: ✅ PASSED (all rules clear)"


def _plural(count: int) -> str:
    return "" if count == 1 else "s"


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def render_markdown(result: CheckResult) -> str:
    """Markdown report for PR comments and MCP consumers."""
    icon = {"FAIL": "❌", "WARN": "⚠️", "PASS": "✅"}[result.result]
    glyph = {"FAIL": "🔴", "WARN": "⚠️", "PASS": "✅"}[result.result]
    counts: list[str] = []
    if result.error_violations:
        counts.append(f"{len(result.error_violations)} error(s)")
    if result.warning_violations:
        counts.append(f"{len(result.warning_violations)} warning(s)")
    summary = " · ".join(counts) if counts else "no violations"

    lines = [
        "## 🧠 Cerebrofy Architecture Check",
        "",
        f"**Result: {icon} {result.result}** — {len(result.rule_results)} rules checked · {summary}",
        "",
    ]
    for rr in result.rule_results:
        if rr.error is not None:
            lines.append(f"> ⛔ **{rr.rule.name}** skipped — {rr.error}")
            lines.append("")
        if not rr.violations:
            continue
        severity = "error" if rr.rule.severity == "error" else "warning"
        lines.append(f"### {glyph} {rr.rule.name} ({severity})")
        lines.append("")
        for v in rr.violations:
            detail = f" — {v.detail}" if v.detail else ""
            introduced = f" *(introduced in {v.introduced_in})*" if v.introduced_in else ""
            lines.append(f"- `{v.location}`{detail}{introduced}")
        lines.append("")
        for v in rr.violations:
            hint = fix_hint(v.kind, rr.rule.description)
            lines.append(f"- **Fix:** {hint}")
            break
        lines.append("")
    if not result.error_violations and not result.warning_violations and not result.config_errors:
        lines.append("✅ No architecture violations detected.")
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# JSON (spec output schema)
# ---------------------------------------------------------------------------

def render_json(result: CheckResult) -> str:
    """Spec-conformant JSON: rules_checked / passing / failing / warnings / result."""
    return json.dumps(_json_dict(result), indent=2)


def _json_dict(result: CheckResult) -> dict[str, Any]:
    passing: list[str] = []
    failing: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    for rr in result.rule_results:
        if rr.error is not None:
            warnings.append({"rule": rr.rule.name, "message": rr.error})
        elif not rr.violations:
            passing.append(rr.rule.name)
        elif rr.rule.severity == "error":
            failing.append({"rule": rr.rule.name, "severity": "error", "violations": [
                {
                    "from_neuron": v.src_name,
                    "to_neuron": v.dst_name,
                    "file": v.file,
                    "line": v.line,
                }
                for v in rr.violations
            ]})
        else:
            for v in rr.violations:
                message = v.location + (f" — {v.detail}" if v.detail else "")
                warnings.append({"rule": rr.rule.name, "message": message})
    return {
        "rules_checked": len(result.rule_results),
        "passing": passing,
        "failing": failing,
        "warnings": warnings,
        "result": result.result,
    }


# ---------------------------------------------------------------------------
# GitHub Actions workflow commands
# ---------------------------------------------------------------------------

def render_annotations(result: CheckResult) -> str:
    """GitHub Actions annotations — one workflow-command line per violation."""
    lines: list[str] = []
    for v in result.error_violations:
        lines.append(_annotation("error", v))
    for v in result.warning_violations:
        lines.append(_annotation("warning", v))
    return "\n".join(lines)


def _annotation(level: str, v: Violation) -> str:
    prefix = f"::{level} file={v.file}"
    if v.line > 0:
        prefix += f",line={v.line}"
    prefix += "::"
    message = f"[{v.rule_name}] {v.location}"
    if v.detail:
        message += f" — {v.detail}"
    return prefix + message[:_MAX_ANNOTATION]
