"""Unit tests for analysis/sequence.py — deterministic topological ordering.

Regression tests for finding m8: the reverse topological sort must produce
identical output when equal-in-degree nodes are encountered in different
iteration orders. Previously ``planning/sequence.py::_reverse_topo_order``
re-keyed the graph to work around upstream instability; ``analysis.sequence``
now inserts nodes/edges in stable sorted-id order and seeds its Kahn queue
deterministically, so no re-keying helper is needed.
"""

from __future__ import annotations

import sqlite3

from cerebrofy.analysis.impact import ImpactNeuron
from cerebrofy.analysis.sequence import (
    _build_caller_graph,
    _topological_sort,
    build_sequence,
)
from cerebrofy.graph.edges import LOCAL_CALL

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY, name TEXT, type TEXT,
            file TEXT, line_start INTEGER, line_end INTEGER,
            signature TEXT, docstring TEXT
        );
        CREATE TABLE edges (
            src_id TEXT NOT NULL, dst_id TEXT NOT NULL,
            rel_type TEXT NOT NULL, file TEXT NOT NULL
        );
    """)
    return conn


def _insert_node(conn: sqlite3.Connection, nid: str, name: str, file: str, line_start: int = 1) -> None:
    conn.execute(
        "INSERT INTO nodes (id, name, type, file, line_start, line_end) VALUES (?,?,?,?,?,?)",
        (nid, name, "function", file, line_start, line_start + 9),
    )


def _insert_edge(conn: sqlite3.Connection, src: str, dst: str, rel: str = LOCAL_CALL) -> None:
    conn.execute(
        "INSERT INTO edges (src_id, dst_id, rel_type, file) VALUES (?,?,?,?)",
        (src, dst, rel, "test.py"),
    )


# ---------------------------------------------------------------------------
# _topological_sort — determinism with equal-in-degree nodes
# ---------------------------------------------------------------------------

def test_topological_sort_identical_regardless_of_insertion_order() -> None:
    """Equal in-degree callers inserted first vs last must yield identical order.

    This is the core m8 regression: two graphs with identical edges but different
    dict insertion order must produce the same topological order. The
    determinism comes from a min-heap ready queue (always pops smallest id)
    and sorted edge traversal — no re-keying helper needed.
    """
    # caller_a and caller_b both have in-degree 0; callee depends on both.
    graph_a_first = {"caller_a": {"callee"}, "caller_b": {"callee"}, "callee": set()}
    graph_b_first = {"callee": set(), "caller_b": {"callee"}, "caller_a": {"callee"}}

    order_a = _topological_sort(graph_a_first)
    order_b = _topological_sort(graph_b_first)

    assert order_a == order_b
    # Zero in-degree nodes emitted in sorted order, then their dependents.
    assert order_a == ["caller_a", "caller_b", "callee"]


def test_topological_sort_two_deps_same_node_different_orders() -> None:
    """A node with two dependencies must produce identical output regardless
    of graph dict insertion order.

    Catches insertion-order dependence: without a sorted ready queue, set/dict
    iteration order leaks non-determinism into the topological output.
    """
    # D depends on C and E; A and B are independent zero in-degree roots.
    graph_v1 = {
        "A": {"C"},
        "B": {"C"},
        "C": set(),
        "D": {"C", "E"},
        "E": set(),
    }
    graph_v2 = {
        "E": set(),
        "D": {"E", "C"},
        "C": set(),
        "B": {"C"},
        "A": {"C"},
    }

    result_v1 = _topological_sort(graph_v1)
    result_v2 = _topological_sort(graph_v2)

    assert result_v1 == result_v2
    # Roots in sorted order, then D (whose deps C/E were just unlocked),
    # then C and E.
    assert result_v1 == ["A", "B", "D", "C", "E"]


def test_topological_sort_deterministic_with_interleaved_dependencies() -> None:
    """Nodes with equal in-degrees that become zero at different times."""
    # a → c, b → d, a → d
    # in_degree: a=0, b=0, c=1(a), d=2(a,b)
    graph_order1 = {
        "a": {"c", "d"},
        "b": {"d"},
        "c": set(),
        "d": set(),
    }
    graph_order2 = {
        "d": set(),
        "b": {"d"},
        "c": set(),
        "a": {"c", "d"},
    }

    assert _topological_sort(graph_order1) == _topological_sort(graph_order2)


def test_topological_sort_cycle_fallback_is_sorted() -> None:
    """Cycle members that can't be ordered fall back in sorted-id order."""
    graph = {"node_b": {"node_a"}, "node_a": {"node_b"}}
    order = _topological_sort(graph)
    # No zero in-degree → entire graph is "remaining" → sorted.
    assert order == ["node_a", "node_b"]


# ---------------------------------------------------------------------------
# _build_caller_graph — sorted construction
# ---------------------------------------------------------------------------

def test_build_caller_graph_sorted_independently_of_set_iteration() -> None:
    """Graph dict must be in sorted-id order regardless of input set order."""
    conn = _make_db()
    _insert_node(conn, "target", "target", "t.py")
    _insert_node(conn, "a_caller", "a", "a.py")
    _insert_node(conn, "b_caller", "b", "b.py")
    _insert_edge(conn, "b_caller", "target")
    _insert_edge(conn, "a_caller", "target")

    # Set iteration order is unpredictable; the graph must still be sorted.
    ids = {"b_caller", "a_caller", "target"}
    graph = _build_caller_graph(ids, conn)

    assert list(graph) == ["a_caller", "b_caller", "target"]


# ---------------------------------------------------------------------------
# build_sequence — end-to-end determinism
# ---------------------------------------------------------------------------

def test_build_sequence_deterministic_across_input_orders() -> None:
    """build_sequence must produce identical steps for reordered caller lists.

    Two equal-in-degree callers (one per file) inserted in opposite orders in
    callers_by_depth must yield identical SequenceStep lists.
    """
    conn = _make_db()
    _insert_node(conn, "a.py::target", "target", "a.py")
    _insert_node(conn, "b.py::caller_a", "caller_a", "b.py")
    _insert_node(conn, "c.py::caller_b", "caller_b", "c.py")
    _insert_edge(conn, "b.py::caller_a", "a.py::target")
    _insert_edge(conn, "c.py::caller_b", "a.py::target")

    target = ImpactNeuron("a.py::target", "target", "a.py", 1, 10, "a")
    caller_a = ImpactNeuron("b.py::caller_a", "caller_a", "b.py", 1, 5, "b")
    caller_b = ImpactNeuron("c.py::caller_b", "caller_b", "c.py", 1, 5, "c")

    steps_ab = build_sequence(target, {1: [caller_a, caller_b]}, [], conn)
    steps_ba = build_sequence(target, {1: [caller_b, caller_a]}, [], conn)

    assert steps_ab == steps_ba


def test_build_sequence_reverse_topo_orders_callees_before_callers() -> None:
    """Target must always be the last (non-boundary) step."""
    conn = _make_db()
    _insert_node(conn, "a.py::target", "target", "a.py")
    _insert_node(conn, "b.py::caller", "caller", "b.py")
    _insert_edge(conn, "b.py::caller", "a.py::target")

    target = ImpactNeuron("a.py::target", "target", "a.py", 1, 10, "a")
    caller = ImpactNeuron("b.py::caller", "caller", "b.py", 1, 5, "b")

    steps = build_sequence(target, {1: [caller]}, [], conn)
    non_boundary = [s for s in steps if not s.is_runtime_boundary]
    assert target.id in non_boundary[-1].neuron_ids
