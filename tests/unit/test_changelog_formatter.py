"""Unit tests for cerebrofy.changelog.formatter (Markdown / GitHub / Slack)."""
from __future__ import annotations

import pytest

from cerebrofy.changelog.formatter import (
    ENTRY_TYPE_META,
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


# ---------------------------------------------------------------------------
# n4: ENTRY_TYPE_META replacement preserves rendered output exactly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("audience", ["developer", "pm", "user"])
@pytest.mark.parametrize("entry_type", list(ENTRY_TYPE_META))
def test_formatter_type_audience_visibility(entry_type: str, audience: str) -> None:
    """Each entry type renders its heading iff the audience is not in skip_audiences.

    This verifies the ENTRY_TYPE_META mapping (which replaced the parallel
    _SECTION_ORDER / _AUDIENCE_SKIP structures) preserves the exact
    rendered output for every type/audience combination.
    """
    meta = ENTRY_TYPE_META[entry_type]
    entry = _entry(entry_type, f"title-{entry_type}", f"**n**: text for {entry_type}.")
    report = _report(audience=audience, entries=(entry,))
    out = format_markdown(report)

    if audience in meta.skip_audiences:
        assert meta.heading not in out, (
            f"{entry_type} heading should be absent for {audience} audience"
        )
        assert f"**n**: text for {entry_type}." not in out, (
            f"{entry_type} entry text should be absent for {audience} audience"
        )
    else:
        assert meta.heading in out, (
            f"{entry_type} heading should be present for {audience} audience"
        )
        assert f"**n**: text for {entry_type}." in out, (
            f"{entry_type} entry text should be present for {audience} audience"
        )


@pytest.mark.parametrize("audience", ["developer", "pm", "user"])
def test_formatter_output_order_unchanged(audience: str) -> None:
    """The heading order across all visible types matches ENTRY_TYPE_META insertion order."""
    entries = tuple(
        _entry(t, f"title-{t}", f"**n**: text for {t}.") for t in ENTRY_TYPE_META
    )
    report = _report(audience=audience, entries=entries)
    out = format_markdown(report)

    visible = [
        (t, m.heading) for t, m in ENTRY_TYPE_META.items()
        if audience not in m.skip_audiences
    ]
    headings = [h for _, h in visible]
    # The headings should appear in document order
    positions = [out.index(h) for h in headings if h in out]
    assert positions == sorted(positions), (
        f"Headings for {audience} should appear in ENTRY_TYPE_META order"
    )


def test_formatter_audience_skip_mapping_matches_old_behavior() -> None:
    """ENTRY_TYPE_META skip_audiences reproduces the former _AUDIENCE_SKIP table.

    Former mapping:
        developer: skip nothing
        pm:        skip internal, intent_update
        user:      skip internal, refactor, perf, intent_update
    """
    expected_skip = {
        "developer": frozenset(),
        "pm": frozenset({"internal", "intent_update"}),
        "user": frozenset({"internal", "refactor", "perf", "intent_update"}),
    }
    for audience, expected in expected_skip.items():
        for entry_type, meta in ENTRY_TYPE_META.items():
            should_skip = entry_type in expected
            is_skipped = audience in meta.skip_audiences
            assert should_skip == is_skipped, (
                f"{entry_type}: expected skip={should_skip} for {audience}, "
                f"got skip={is_skipped}"
            )


# ---------------------------------------------------------------------------
# Public dispatcher × audience/format matrix (T2)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fmt", ["markdown", "github", "slack"])
@pytest.mark.parametrize("audience", ["developer", "pm", "user"])
def test_format_changelog_all_audience_format_combinations(audience: str, fmt: str) -> None:
    """The public dispatcher handles all 3 audiences × 3 formats."""
    report = _report(audience=audience, fmt=fmt, entries=(_entry(FEAT),))
    out = format_changelog(report)
    expected_fn = {
        "markdown": format_markdown,
        "github": format_github,
        "slack": format_slack,
    }[fmt]
    assert out == expected_fn(report)
    assert "did a thing." in out  # the entry text survives every combination
