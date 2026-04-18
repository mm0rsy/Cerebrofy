"""Unit tests for cerebrofy.graph.resolver and cerebrofy.graph.edges."""

from __future__ import annotations

from cerebrofy.graph.edges import (
    EXTERNAL_CALL,
    IMPORT_REL,
    LOCAL_CALL,
    RUNTIME_BOUNDARY,
    Edge,
)
from cerebrofy.graph.resolver import (
    build_name_registry,
    find_containing_neuron,
    resolve_cross_module_edges,
    resolve_import_edges,
    resolve_local_edges,
)
from cerebrofy.parser.neuron import Neuron, ParseResult, RawCapture


def _neuron(name: str, file: str, line_start: int = 1, line_end: int = 10, ntype: str = "function") -> Neuron:
    return Neuron(
        id=f"{file}::{name}",
        name=name,
        type=ntype,
        file=file,
        line_start=line_start,
        line_end=line_end,
        signature=f"def {name}():",
    )


def _call_capture(text: str, file: str, line: int) -> RawCapture:
    return RawCapture(capture_name="call", text=text, file=file, line=line)


def _import_capture(text: str, file: str, line: int) -> RawCapture:
    return RawCapture(capture_name="import", text=text, file=file, line=line)


# ---------------------------------------------------------------------------
# Edge dataclass
# ---------------------------------------------------------------------------


def test_edge_is_frozen() -> None:
    import pytest
    e = Edge(src_id="a", dst_id="b", rel_type=LOCAL_CALL, file="f.py")
    with pytest.raises(Exception):
        e.src_id = "x"  # type: ignore[misc]


def test_edge_equality() -> None:
    e1 = Edge("a", "b", LOCAL_CALL, "f.py")
    e2 = Edge("a", "b", LOCAL_CALL, "f.py")
    assert e1 == e2


def test_edge_rel_type_constants() -> None:
    assert LOCAL_CALL == "LOCAL_CALL"
    assert EXTERNAL_CALL == "EXTERNAL_CALL"
    assert IMPORT_REL == "IMPORT"
    assert RUNTIME_BOUNDARY == "RUNTIME_BOUNDARY"


# ---------------------------------------------------------------------------
# build_name_registry
# ---------------------------------------------------------------------------


def test_build_name_registry_single_file() -> None:
    n = _neuron("foo", "f.py")
    pr = ParseResult(file="f.py", neurons=[n])
    registry = build_name_registry([pr])
    assert "foo" in registry
    assert registry["foo"] == [n]


def test_build_name_registry_multiple_files() -> None:
    n1 = _neuron("foo", "a.py")
    n2 = _neuron("foo", "b.py")
    pr_a = ParseResult(file="a.py", neurons=[n1])
    pr_b = ParseResult(file="b.py", neurons=[n2])
    registry = build_name_registry([pr_a, pr_b])
    assert len(registry["foo"]) == 2


def test_build_name_registry_empty() -> None:
    assert build_name_registry([]) == {}


# ---------------------------------------------------------------------------
# find_containing_neuron
# ---------------------------------------------------------------------------


def test_find_containing_neuron_found() -> None:
    n = _neuron("foo", "f.py", line_start=5, line_end=15)
    result = find_containing_neuron([n], 10)
    assert result == n.id


def test_find_containing_neuron_at_boundary() -> None:
    n = _neuron("foo", "f.py", line_start=5, line_end=15)
    assert find_containing_neuron([n], 5) == n.id
    assert find_containing_neuron([n], 15) == n.id


def test_find_containing_neuron_not_found() -> None:
    n = _neuron("foo", "f.py", line_start=5, line_end=10)
    assert find_containing_neuron([n], 100) is None


def test_find_containing_neuron_empty_list() -> None:
    assert find_containing_neuron([], 1) is None


# ---------------------------------------------------------------------------
# resolve_local_edges
# ---------------------------------------------------------------------------


def test_resolve_local_edges_single_call() -> None:
    caller = _neuron("main", "app.py", line_start=1, line_end=20)
    callee = _neuron("helper", "app.py", line_start=25, line_end=30)
    capture = _call_capture("helper()", "app.py", line=10)
    pr = ParseResult(file="app.py", neurons=[caller, callee], raw_captures=(capture,))
    registry = build_name_registry([pr])
    edges = resolve_local_edges(pr, registry)
    assert len(edges) >= 1
    assert any(e.rel_type == LOCAL_CALL and e.dst_id == callee.id for e in edges)


def test_resolve_local_edges_no_matching_callee() -> None:
    caller = _neuron("main", "app.py", line_start=1, line_end=20)
    capture = _call_capture("unknown()", "app.py", line=5)
    pr = ParseResult(file="app.py", neurons=[caller], raw_captures=(capture,))
    registry = build_name_registry([pr])
    edges = resolve_local_edges(pr, registry)
    # No local match → no LOCAL_CALL edge
    assert all(e.rel_type != LOCAL_CALL or e.dst_id != "app.py::unknown" for e in edges)


def test_resolve_local_edges_caller_not_found() -> None:
    """Call not inside any neuron → no edge produced."""
    capture = _call_capture("foo()", "app.py", line=999)
    pr = ParseResult(file="app.py", neurons=[], raw_captures=(capture,))
    edges = resolve_local_edges(pr, {})
    assert edges == []


# ---------------------------------------------------------------------------
# resolve_cross_module_edges
# ---------------------------------------------------------------------------


def test_resolve_cross_module_edges_external_call() -> None:
    caller = _neuron("main", "app.py", line_start=1, line_end=20)
    callee = _neuron("helper", "lib.py", line_start=1, line_end=10)
    capture = _call_capture("helper()", "app.py", line=10)
    pr_app = ParseResult(file="app.py", neurons=[caller], raw_captures=(capture,))
    pr_lib = ParseResult(file="lib.py", neurons=[callee])
    registry = build_name_registry([pr_app, pr_lib])
    edges = resolve_cross_module_edges(pr_app, registry)
    assert any(e.rel_type == EXTERNAL_CALL and e.dst_id == callee.id for e in edges)


def test_resolve_cross_module_edges_runtime_boundary_for_unknown() -> None:
    caller = _neuron("main", "app.py", line_start=1, line_end=20)
    capture = _call_capture("completely_unknown()", "app.py", line=10)
    pr = ParseResult(file="app.py", neurons=[caller], raw_captures=(capture,))
    edges = resolve_cross_module_edges(pr, {})
    assert any(e.rel_type == RUNTIME_BOUNDARY for e in edges)


def test_resolve_cross_module_edges_skips_same_file() -> None:
    """Calls resolved to the same file should not appear as EXTERNAL_CALL."""
    caller = _neuron("main", "app.py", line_start=1, line_end=20)
    callee = _neuron("helper", "app.py", line_start=25, line_end=30)
    capture = _call_capture("helper()", "app.py", line=10)
    pr = ParseResult(file="app.py", neurons=[caller, callee], raw_captures=(capture,))
    registry = build_name_registry([pr])
    edges = resolve_cross_module_edges(pr, registry)
    # helper is in same file → no EXTERNAL_CALL for it
    assert not any(e.rel_type == EXTERNAL_CALL and e.dst_id == callee.id for e in edges)


# ---------------------------------------------------------------------------
# resolve_import_edges
# ---------------------------------------------------------------------------


def test_resolve_import_edges_no_module_neuron() -> None:
    """Without a 'module' type neuron, no import edges should be emitted."""
    n = _neuron("foo", "a.py")
    capture = _import_capture("os", "a.py", 1)
    pr = ParseResult(file="a.py", neurons=[n], raw_captures=(capture,))
    edges = resolve_import_edges(pr, {})
    assert edges == []


def test_resolve_import_edges_with_module_neuron() -> None:
    module_n = Neuron(id="a.py::module", name="a", type="module", file="a.py", line_start=1, line_end=100)
    imported_n = _neuron("os", "stdlib/os.py", line_start=1, line_end=100)
    capture = _import_capture("import os", "a.py", line=1)
    pr = ParseResult(file="a.py", neurons=[module_n], raw_captures=(capture,))
    registry = {"os": [imported_n]}
    edges = resolve_import_edges(pr, registry)
    assert any(e.rel_type == IMPORT_REL for e in edges)
