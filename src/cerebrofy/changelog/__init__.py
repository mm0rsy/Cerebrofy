"""Semantic changelog generation (Idea #14).

Classifies changed neurons into semantic entry types (feat, fix, refactor,
security, breaking, perf, internal) using the drift records (#16), blast
radius (#01), agent memories (#05), vulnerability tags (#08), and product
intent (#23) — never commit messages.
"""

from cerebrofy.changelog.classifier import (
    BREAKING_CROSS_LOBE_CALLERS,
    ENTRY_TYPES,
    ChangelogError,
    ClassifiedChange,
    CollectedChanges,
    NeuronChange,
    ResolvedRange,
    collect_changes,
    lobe_for_file,
    resolve_range,
)
from cerebrofy.changelog.generator import (
    ChangelogEntry,
    ChangelogReport,
    generate_changelog,
    write_narrative_events,
)

__all__ = [
    "BREAKING_CROSS_LOBE_CALLERS",
    "ENTRY_TYPES",
    "ChangelogEntry",
    "ChangelogError",
    "ChangelogReport",
    "ClassifiedChange",
    "CollectedChanges",
    "NeuronChange",
    "ResolvedRange",
    "collect_changes",
    "generate_changelog",
    "lobe_for_file",
    "resolve_range",
    "write_narrative_events",
]
