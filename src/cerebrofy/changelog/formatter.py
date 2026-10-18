"""Changelog output formatters: Markdown, GitHub release body, Slack post."""

from __future__ import annotations

from cerebrofy.changelog.generator import ChangelogEntry, ChangelogReport

#: Section heading per entry type, in display order.
_SECTION_ORDER: tuple[tuple[str, str], ...] = (
    ("breaking", "⚠️ Breaking Changes"),
    ("security", "🔒 Security"),
    ("feat", "🚀 Features"),
    ("fix", "🐛 Fixes"),
    ("perf", "⚡ Performance"),
    ("refactor", "🔧 Refactors"),
    ("internal", "🧹 Internal"),
    ("intent_update", "🎯 Product Intent"),
)

#: Entry types an audience does not want to see.
_AUDIENCE_SKIP: dict[str, frozenset[str]] = {
    "developer": frozenset(),
    "pm": frozenset({"internal", "intent_update"}),
    "user": frozenset({"internal", "refactor", "perf", "intent_update"}),
}


def _visible_types(audience: str) -> tuple[tuple[str, str], ...]:
    skip = _AUDIENCE_SKIP.get(audience, frozenset())
    return tuple((kind, title) for kind, title in _SECTION_ORDER if kind not in skip)


def _entries_of(report: ChangelogReport, kind: str) -> list[ChangelogEntry]:
    return [e for e in report.entries if e.type == kind and e.audience_text]


def _range_label(report: ChangelogReport) -> str:
    return f"{report.since} → {report.until_short}"


def _health_line(report: ChangelogReport) -> str | None:
    coupling = report.health_delta.get("coupling", 0.0)
    avg_blast = report.health_delta.get("avg_blast", 0.0)
    if coupling == 0.0 and avg_blast == 0.0:
        return None
    return (
        f"Health delta: coupling {coupling:+.4f} · avg blast {avg_blast:+.2f}"
    )


def format_markdown(report: ChangelogReport) -> str:
    """Markdown changelog — headings per entry type, one bullet per entry."""
    lines = [f"## Changelog {_range_label(report)}"]
    if report.until_date:
        lines.append("")
        lines.append(f"_{report.until_date}_")
    lines.append("")

    for kind, heading in _visible_types(report.audience):
        entries = _entries_of(report, kind)
        if not entries:
            continue
        lines.append(f"### {heading}")
        lines.append("")
        for entry in entries:
            lines.append(f"- {entry.audience_text}")
        lines.append("")

    if report.breaking_changes and report.audience == "developer":
        lines.append("### Upgrading")
        lines.append("")
        for breaking in report.breaking_changes:
            lines.append(f"- {breaking['description']}")
        lines.append("")

    health = _health_line(report)
    if health:
        lines.append("---")
        lines.append("")
        lines.append(f"_{health}_")
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def format_github(report: ChangelogReport) -> str:
    """GitHub release body — 'What's Changed' + type sections."""
    lines = ["## What's Changed", "", f"_{_range_label(report)}_", ""]

    for kind, heading in _visible_types(report.audience):
        entries = _entries_of(report, kind)
        if not entries:
            continue
        lines.append(f"### {heading}")
        lines.append("")
        for entry in entries:
            lines.append(f"- {entry.audience_text}")
        lines.append("")

    if report.breaking_changes and report.audience == "developer":
        lines.append("### ⚠️ Upgrading notes")
        lines.append("")
        for breaking in report.breaking_changes:
            lines.append(f"- {breaking['description']}")
        lines.append("")

    health = _health_line(report)
    if health:
        lines.append(f"_{health}_")
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def format_slack(report: ChangelogReport) -> str:
    """Slack announcement — bold headers, compact bullets."""
    lines = [f"*📦 Release {_range_label(report)}*"]
    if report.until_date:
        lines.append(f"_{report.until_date}_")
    lines.append("")

    for kind, heading in _visible_types(report.audience):
        entries = _entries_of(report, kind)
        if not entries:
            continue
        lines.append(f"*{heading}*")
        for entry in entries:
            lines.append(f"• {entry.audience_text}")
        lines.append("")

    health = _health_line(report)
    if health:
        lines.append(f"_{health}_")

    return "\n".join(lines).rstrip("\n") + "\n"


def format_changelog(report: ChangelogReport) -> str:
    """Dispatch on ``report.format`` — markdown (default) | github | slack."""
    if report.format == "github":
        return format_github(report)
    if report.format == "slack":
        return format_slack(report)
    return format_markdown(report)
