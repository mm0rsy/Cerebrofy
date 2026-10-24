"""Codebase Narrative Engine — auto-generates NARRATIVE.md from health, memories, git."""

from cerebrofy.narrative.generator import (
    NarrativeData,
    build_narrative_data,
    generate_narrative,
    maybe_update_narrative,
)

__all__ = [
    "NarrativeData",
    "build_narrative_data",
    "generate_narrative",
    "maybe_update_narrative",
]
