"""Changelog entry rendering: text templates, entry building, full-text formatting.

Split from ``generator.py`` (M3).  ``with_full_text`` imports ``formatter`` at
module scope — the types now live in ``types.py``, so there is no circular
import (m9).
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from cerebrofy.changelog.classifier import (
    BREAKING,
    ENTRY_TYPES,
    FEAT,
    FIX,
    INTENT_UPDATE,
    INTERNAL,
    PERF,
    REFACTOR,
    SECURITY,
    ClassifiedChange,
    NeuronChange,
)
from cerebrofy.changelog.formatter import format_changelog
from cerebrofy.changelog.types import ChangelogEntry, ChangelogReport

#: Display order for entry types (severity first).
_ENTRY_ORDER: tuple[str, ...] = (
    BREAKING,
    SECURITY,
    FEAT,
    FIX,
    PERF,
    REFACTOR,
    INTERNAL,
    INTENT_UPDATE,
)

#: Audience -> entries eligible for that audience's prose.
_AUDIENCE_TYPES: dict[str, frozenset[str]] = {
    "developer": frozenset(ENTRY_TYPES),
    "pm": frozenset({BREAKING, SECURITY, FEAT, FIX, PERF, REFACTOR}),
    "user": frozenset({BREAKING, SECURITY, FEAT, FIX}),
}

#: Lowercase tokens whose trailing period must not be treated as a sentence end.
_ABBREVIATIONS = frozenset({"e.g", "i.e", "etc", "vs"})

#: Regex matching known abbreviations (with their trailing period) preceded by a
#: non-letter boundary, so the period is preserved during sentence splitting.
_ABBR_RE = re.compile(r'(?<![A-Za-z])(?:e\.g\.|i\.e\.|etc\.|vs\.)', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Text templates
# ---------------------------------------------------------------------------


def _first_sentence(text: str, limit: int = 140) -> str:
    """Extract the first sentence of *text* for use as a summary.

    Handles common abbreviations (``e.g.``, ``i.e.``, ``etc.``, ``vs.``) so their
    trailing periods do not prematurely terminate an entry.  Only the first line is
    considered (docstring summaries are single-line).  If no terminal punctuation
    is found the full first line is returned.
    """
    text = text.strip()
    if not text:
        return ""
    first_line = text.split("\n", 1)[0].strip()
    if not first_line:
        return ""

    # Record period positions that belong to known abbreviations so they are
    # skipped during sentence-end detection.
    skip_periods: set[int] = set()
    for match in _ABBR_RE.finditer(first_line):
        for i in range(match.start(), match.end()):
            if first_line[i] == ".":
                skip_periods.add(i)

    for i, ch in enumerate(first_line):
        if ch in ".!?" and i not in skip_periods:
            if i + 1 >= len(first_line) or first_line[i + 1].isspace():
                sentence = first_line[: i + 1].strip()
                return sentence[:limit]

    return first_line[:limit]


def _names(neurons: Sequence[NeuronChange]) -> str:
    names = [n.name for n in neurons]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:3]) + (f" +{len(names) - 3} more" if len(names) > 3 else "")


def _entry_title(entry_type: str, neurons: Sequence[NeuronChange]) -> str:
    names = _names(neurons)
    templates = {
        FEAT: f"Added {names}",
        FIX: f"Fixed {names}",
        SECURITY: f"Patched security issue in {names}",
        BREAKING: f"BREAKING: {names} changed",
        PERF: f"Improved performance of {names}",
        REFACTOR: f"Refactored {names}",
        INTERNAL: f"Changed {names}",
    }
    return templates.get(entry_type, f"Changed {names}")


def _entry_description(change: ClassifiedChange) -> str:
    parts = [
        f"{n.file}::{n.name} ({n.kind})" for n in change.neurons
    ]
    suffix = f". Callers: {change.direct_callers} direct"
    if change.cross_lobe_callers:
        suffix += f" ({change.cross_lobe_callers} cross-lobe)"
    suffix += f". Blast radius: {change.blast_radius}."
    if change.memories:
        why = change.memories[0]
        suffix += f" Why: {why.title} — {_first_sentence(why.body, 160)}"
    return "; ".join(parts) + suffix


def _why_text(change: ClassifiedChange, docstrings: Mapping[str, str]) -> str | None:
    if change.memories:
        return change.memories[0].title
    for neuron in change.neurons:
        docstring = docstrings.get(neuron.id)
        if docstring:
            return _first_sentence(docstring)
    return None


def _developer_text(
    change: ClassifiedChange, docstrings: Mapping[str, str]
) -> str:
    names = _names(change.neurons)
    files = sorted({n.file for n in change.neurons})
    location = files[0] if len(files) == 1 else ", ".join(files[:2])
    text = f"**{names}** ({location})"
    why = _why_text(change, docstrings)
    detail = _entry_title(change.entry_type, change.neurons)
    text += f": {detail}."
    if change.direct_callers:
        text += f" Callers: {change.direct_callers} direct"
        if change.cross_lobe_callers:
            text += f" ({change.cross_lobe_callers} cross-lobe)"
        text += "."
    if why and why not in detail:
        text += f" Why: {why}"
    return text


def _pm_text(
    change: ClassifiedChange, docstrings: Mapping[str, str]
) -> str:
    lobe = change.neurons[0].lobe
    why = _why_text(change, docstrings)
    names = _names(change.neurons)
    if change.entry_type == FEAT:
        base = f"New capability in the {lobe} area ({names})"
        return f"{base}: {why}." if why else f"{base}."
    if change.entry_type == BREAKING:
        return f"Important change in the {lobe} area — integrations calling {names} must be updated."
    if change.entry_type == SECURITY:
        return f"Security hardening in the {lobe} area: {why or names}."
    if change.entry_type == FIX:
        return f"Reliability fix in the {lobe} area: {why or names}."
    if change.entry_type == PERF:
        return f"Performance improvement in the {lobe} area: {why or names}."
    return "Internal restructuring — no change in functionality."


def _user_text(change: ClassifiedChange, docstrings: Mapping[str, str]) -> str:
    why = _why_text(change, docstrings)
    names = _names(change.neurons)
    if change.entry_type == FEAT:
        return f"New: {why or names}."
    if change.entry_type == FIX:
        return f"Fixed: {why or names}."
    if change.entry_type == SECURITY:
        return f"Security improvement: {why or 'hardened validation and access controls'}."
    if change.entry_type == BREAKING:
        return f"Important: {names} changed — update to the latest version for the best experience."
    return ""


def _audience_text(
    change: ClassifiedChange, audience: str, docstrings: Mapping[str, str]
) -> str:
    if audience == "pm":
        return _pm_text(change, docstrings)
    if audience == "user":
        return _user_text(change, docstrings)
    return _developer_text(change, docstrings)


# ---------------------------------------------------------------------------
# Entry assembly
# ---------------------------------------------------------------------------


def build_entries(
    changes: Sequence[ClassifiedChange],
    audience: str,
    docstrings: Mapping[str, str],
) -> tuple[ChangelogEntry, ...]:
    ordered = sorted(
        changes,
        key=lambda c: (_ENTRY_ORDER.index(c.entry_type), c.neurons[0].name),
    )
    entries: list[ChangelogEntry] = []
    eligible = _AUDIENCE_TYPES.get(audience, _AUDIENCE_TYPES["developer"])
    for change in ordered:
        entries.append(
            ChangelogEntry(
                type=change.entry_type,
                title=_entry_title(change.entry_type, change.neurons),
                description=_entry_description(change),
                neurons=tuple(n.id for n in change.neurons),
                blast_radius=change.blast_radius,
                audience_text=_audience_text(change, audience, docstrings)
                if change.entry_type in eligible
                else "",
                lobes=tuple(sorted({n.lobe for n in change.neurons})),
                memory_notes=tuple(m.title for m in change.memories),
            )
        )
    return tuple(entries)


def _breaking_changes(
    entries: Sequence[ChangelogEntry],
) -> tuple[dict[str, Any], ...]:
    out: list[dict[str, Any]] = []
    for entry in entries:
        if entry.type != BREAKING:
            continue
        out.append(
            {
                "title": entry.title,
                "description": entry.description,
                "neurons": list(entry.neurons),
            }
        )
    return tuple(out)


def with_full_text(report: ChangelogReport) -> ChangelogReport:
    """Attach the rendered ``full_text`` to *report* and return the updated report.

    ``format_changelog`` is imported at module scope — the types now live in
    ``types.py``, so there is no circular import with ``formatter`` (m9).
    """
    return ChangelogReport(
        since=report.since,
        until=report.until,
        entries=report.entries,
        breaking_changes=report.breaking_changes,
        health_delta=report.health_delta,
        full_text=format_changelog(report),
        audience=report.audience,
        format=report.format,
        until_short=report.until_short,
        until_date=report.until_date,
        note=report.note,
    )
