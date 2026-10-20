"""Changelog output data structures: the spec output schema + generation context.

Extracted from ``generator.py`` (M3) so that ``formatter.py`` and ``renderer.py``
can share these types without importing the generator module, eliminating the
generator ↔ formatter circular dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChangelogEntry:
    """One changelog entry (spec output schema + generation context)."""

    type: str
    title: str
    description: str
    neurons: tuple[str, ...]
    blast_radius: int
    audience_text: str
    # Generation-only context (not serialised to the spec output schema).
    lobes: tuple[str, ...] = ()
    memory_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the exact spec entry schema (6 keys)."""
        return {
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "neurons": list(self.neurons),
            "blast_radius": self.blast_radius,
            "audience_text": self.audience_text,
        }


@dataclass(frozen=True)
class ChangelogReport:
    """Full changelog report for a range at a given audience and format."""

    since: str
    until: str
    entries: tuple[ChangelogEntry, ...]
    breaking_changes: tuple[dict[str, Any], ...]
    health_delta: dict[str, float]
    full_text: str
    audience: str = "developer"
    format: str = "markdown"
    until_short: str = ""
    until_date: str = ""
    note: str | None = None  # non-fatal range-resolution note (e.g. last-build fallback)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the exact spec output schema."""
        return {
            "since": self.since,
            "until": self.until,
            "entries": [e.to_dict() for e in self.entries],
            "breaking_changes": [dict(b) for b in self.breaking_changes],
            "health_delta": dict(self.health_delta),
            "full_text": self.full_text,
            "note": self.note,
        }
