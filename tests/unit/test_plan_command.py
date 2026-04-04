"""Unit tests for cerebrofy.commands.plan — formatters."""

from __future__ import annotations

import json

from cerebrofy.search.hybrid import (
    BlastRadiusNeuron,
    HybridSearchResult,
    MatchedNeuron,
    RuntimeBoundaryWarning,
)
from cerebrofy.commands.plan import _format_plan_json, _format_plan_markdown


def _make_result(
    matched: list[MatchedNeuron] | None = None,
    blast: list[BlastRadiusNeuron] | None = None,
    warnings: list[RuntimeBoundaryWarning] | None = None,
    query: str = "test",
) -> HybridSearchResult:
    matched = matched or []
    blast = blast or []
    warnings = warnings or []
    return HybridSearchResult(
        query=query,
        top_k=10,
        matched_neurons=tuple(matched),
        blast_radius=tuple(blast),
        affected_lobes=frozenset(["auth"]) if matched else frozenset(),
        affected_lobe_files={"auth": "/docs/auth_lobe.md"} if matched else {},
        runtime_boundary_warnings=tuple(warnings),
        reindex_scope=len(matched) + len(blast),
        search_duration_ms=1.0,
    )


# ---------------------------------------------------------------------------
# T044: _format_plan_json
# ---------------------------------------------------------------------------


def test_format_plan_json_schema_version() -> None:
    """Output must include schema_version: 1."""
    n = MatchedNeuron(id="a::foo", name="foo", file="a.py", line_start=1, similarity=0.9)
    result = _make_result(matched=[n])
    parsed = json.loads(_format_plan_json(result))
    assert parsed["schema_version"] == 1


def test_format_plan_json_all_fields_present() -> None:
    """All four array fields always present even when empty."""
    n = MatchedNeuron(id="a::foo", name="foo", file="a.py", line_start=1, similarity=0.912)
    b = BlastRadiusNeuron(id="b::bar", name="bar", file="b.py", line_start=5)
    result = _make_result(matched=[n], blast=[b])
    parsed = json.loads(_format_plan_json(result))

    assert "matched_neurons" in parsed
    assert "blast_radius" in parsed
    assert "affected_lobes" in parsed
    assert "reindex_scope" in parsed
    assert parsed["matched_neurons"][0]["similarity"] == 0.91


def test_format_plan_json_empty_blast_radius() -> None:
    """Empty blast_radius → key is [] not absent."""
    n = MatchedNeuron(id="a::foo", name="foo", file="a.py", line_start=1, similarity=0.8)
    result = _make_result(matched=[n])
    parsed = json.loads(_format_plan_json(result))
    assert parsed["blast_radius"] == []


def test_format_plan_markdown_sections() -> None:
    """Markdown output contains all required section headers."""
    n = MatchedNeuron(id="a::foo", name="foo", file="a.py", line_start=1, similarity=0.9)
    b = BlastRadiusNeuron(id="b::bar", name="bar", file="b.py", line_start=5)
    result = _make_result(matched=[n], blast=[b], query="add login")
    md = _format_plan_markdown(result)

    assert "# Cerebrofy Plan: add login" in md
    assert "## Matched Neurons" in md
    assert "## Blast Radius" in md
    assert "## Affected Lobes" in md
    assert "## Re-index Scope" in md


def test_format_plan_markdown_no_runtime_section_when_empty() -> None:
    """RUNTIME_BOUNDARY section omitted when no warnings."""
    n = MatchedNeuron(id="a::foo", name="foo", file="a.py", line_start=1, similarity=0.9)
    result = _make_result(matched=[n])
    md = _format_plan_markdown(result)
    assert "RUNTIME_BOUNDARY" not in md
