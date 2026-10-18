"""Unit tests for cerebrofy.changelog.formatter (Markdown / GitHub / Slack)."""
from __future__ import annotations

from cerebrofy.changelog.formatter import (
    format_changelog,
    format_github,
    format_markdown,
    format_slack,
    _visible_types,
)
from cerebrofy.changelog.generator import ChangelogEntry, ChangelogReport
from cerebrofy.changelog.classifier import BREAKING, FEAT, INTERNAL


def _entry(t: str, title: str = "T", text: str = "**n**: did a thing.") -> ChangelogEntry:
    return ChangelogEntry(
        type=t, title=title, description="desc", neurons=("f::n",),
        blast_radius=2, audience_text=text, lobes=("src",), memory_notes=(),
    )


def _report(audience: str = "developer", fmt: str = "markdown",
            entries=(), breaking=(), health=None) -> ChangelogReport:
    return ChangelogReport(
        since="v1.0.0", until="abc1234", entries=entries,
        breaking_changes=breaking,
        health_delta=health or {"coupling": 0.0, "avg_blast": 0.0},
        full_text="", audience=audience, format=fmt, until_short="abc1234",
        until_date="2026-06-19",
    )


def test_visible_types_filters_by_audience() -> None:
    dev_kinds = {k for k, _ in _visible_types("developer")}
    assert {"breaking", "internal", "intent_update"} <= dev_kinds
    pm_kinds = {k for k, _ in _visible_types("pm")}
    assert "internal" not in pm_kinds
    assert "intent_update" not in pm_kinds
    user_kinds = {k for k, _ in _visible_types("user")}
    assert "internal" not in user_kinds
    assert "refactor" not in user_kinds
    assert "perf" not in user_kinds


def test_format_markdown_has_range_header_and_sections() -> None:
    report = _report(
        entries=(_entry(BREAKING, "BREAKING: n changed"), _entry(INTERNAL)),
    )
    out = format_markdown(report)
    assert out.startswith("## Changelog v1.0.0 → abc1234")
    assert "_2026-06-19_" in out
    assert "### ⚠️ Breaking Changes" in out
    assert "### 🧹 Internal" in out
    assert "**n**: did a thing." in out  # audience_text rendered as bullets


def test_format_markdown_omits_internal_for_pm() -> None:
    report = _report(audience="pm", entries=(_entry(INTERNAL, "internal", text=""),))
    out = format_markdown(report)
    assert "🧹 Internal" not in out


def test_format_markdown_includes_health_delta_when_nonzero() -> None:
    report = _report(
        entries=(_entry(FEAT),),
        health={"coupling": 0.3, "avg_blast": 2.0},
    )
    out = format_markdown(report)
    assert "Health delta: coupling +0.3000 · avg blast +2.00" in out


def test_format_markdown_omits_health_when_zero() -> None:
    report = _report(entries=(_entry(FEAT),), health={"coupling": 0.0, "avg_blast": 0.0})
    out = format_markdown(report)
    assert "Health delta" not in out


def test_format_markdown_breaking_upgrade_section_for_developer() -> None:
    report = _report(
        audience="developer",
        entries=(_entry(BREAKING),),
        breaking=[{"title": "BREAKING: n changed", "description": "desc", "neurons": ["f::n"]}],
    )
    out = format_markdown(report)
    assert "### Upgrading" in out


def test_format_github_uses_release_header() -> None:
    report = _report(
        fmt="github",
        entries=(_entry(BREAKING, "BREAKING: n changed"), _entry(FEAT)),
        breaking=[{"title": "BREAKING: n changed", "description": "desc", "neurons": ["f::n"]}],
    )
    out = format_github(report)
    assert out.startswith("## What's Changed")
    assert "### ⚠️ Upgrading notes" in out


def test_format_slack_bolds_headers_and_bullets() -> None:
    report = _report(fmt="slack", entries=(_entry(FEAT),))
    out = format_slack(report)
    assert out.startswith("*📦 Release v1.0.0 → abc1234*")
    assert "*🚀 Features*" in out
    assert "• " in out


def test_format_changelog_dispatches_by_format() -> None:
    entries = (_entry(FEAT),)
    md = format_changelog(_report(fmt="markdown", entries=entries))
    gh = format_changelog(_report(fmt="github", entries=entries))
    sl = format_changelog(_report(fmt="slack", entries=entries))
    assert md.startswith("## Changelog")
    assert gh.startswith("## What's Changed")
    assert sl.startswith("*📦 Release")


def test_format_empty_report_renders_header_only() -> None:
    out = format_markdown(_report(entries=()))
    assert "## Changelog" in out
    assert "## What's Changed" in format_github(_report(fmt="github", entries=()))
