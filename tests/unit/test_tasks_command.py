"""Unit tests for cerebrofy.commands.tasks."""

from __future__ import annotations

from cerebrofy.search.hybrid import (
    BlastRadiusNeuron,
    HybridSearchResult,
    MatchedNeuron,
    RuntimeBoundaryWarning,
)
from cerebrofy.commands.tasks import _build_task_items


def _make_result(
    matched: list[MatchedNeuron],
    blast: list[BlastRadiusNeuron] | None = None,
    warnings: list[RuntimeBoundaryWarning] | None = None,
) -> HybridSearchResult:
    blast = blast or []
    warnings = warnings or []
    return HybridSearchResult(
        query="test",
        top_k=10,
        matched_neurons=tuple(matched),
        blast_radius=tuple(blast),
        affected_lobes=frozenset(["auth"]),
        affected_lobe_files={"auth": "/docs/auth_lobe.md"},
        runtime_boundary_warnings=tuple(warnings),
        reindex_scope=len(matched) + len(blast),
        search_duration_ms=1.0,
    )


# ---------------------------------------------------------------------------
# T045: _build_task_items
# ---------------------------------------------------------------------------


def test_build_task_items_ordering() -> None:
    """Items ordered by descending similarity (already ordered by hybrid_search)."""
    n1 = MatchedNeuron(id="a::foo", name="foo", file="auth/a.py", line_start=1, similarity=0.9)
    n2 = MatchedNeuron(id="b::bar", name="bar", file="auth/b.py", line_start=5, similarity=0.7)
    result = _make_result(matched=[n1, n2])
    items, _ = _build_task_items(result)

    assert len(items) == 2
    assert items[0].neuron.name == "foo"
    assert items[1].neuron.name == "bar"
    assert items[0].index == 1
    assert items[1].index == 2


def test_build_task_items_blast_count_shared() -> None:
    """blast_count is total blast_radius count, same for all items."""
    n1 = MatchedNeuron(id="a::foo", name="foo", file="auth/a.py", line_start=1, similarity=0.9)
    n2 = MatchedNeuron(id="b::bar", name="bar", file="auth/b.py", line_start=5, similarity=0.7)
    blast = [
        BlastRadiusNeuron(id="c::baz", name="baz", file="auth/c.py", line_start=3),
        BlastRadiusNeuron(id="d::qux", name="qux", file="auth/d.py", line_start=7),
    ]
    result = _make_result(matched=[n1, n2], blast=blast)
    items, _ = _build_task_items(result)

    assert items[0].blast_count == 2
    assert items[1].blast_count == 2


def test_build_task_items_runtime_boundary_note() -> None:
    """One RUNTIME_BOUNDARY warning → one note string in notes list."""
    n = MatchedNeuron(id="a::foo", name="foo", file="auth/a.py", line_start=1, similarity=0.9)
    w = RuntimeBoundaryWarning(
        src_id="a::foo", src_name="foo", src_file="auth/a.py",
        dst_id="ext::handler", lobe_name="auth",
    )
    result = _make_result(matched=[n], warnings=[w])
    items, notes = _build_task_items(result)

    assert len(notes) == 1
    assert "foo" in notes[0]
    assert "RUNTIME_BOUNDARY" in notes[0]
    assert "[[auth]]" in notes[0]


def test_build_task_items_lobe_unassigned_for_root_file() -> None:
    """File with no subdirectory → lobe comes from affected_lobe_files or (unassigned)."""
    n = MatchedNeuron(id="root::main", name="main", file="main.py", line_start=1, similarity=0.8)
    result = HybridSearchResult(
        query="test",
        top_k=10,
        matched_neurons=(n,),
        blast_radius=(),
        affected_lobes=frozenset(),
        affected_lobe_files={},
        runtime_boundary_warnings=(),
        reindex_scope=1,
        search_duration_ms=1.0,
    )
    items, _ = _build_task_items(result)
    assert items[0].lobe_name == "(unassigned)"
