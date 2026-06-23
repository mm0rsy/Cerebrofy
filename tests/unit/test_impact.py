"""Unit tests for analysis/impact.py and analysis/sequence.py."""

from __future__ import annotations

import sqlite3


from cerebrofy.analysis.impact import (
    ImpactNeuron,
    _complexity_rating,
    _compute_loc,
    _lobe_from_file,
    bfs_callers,
    compute_impact,
    find_covering_tests,
    find_runtime_boundary_callers,
    resolve_target,
)
from cerebrofy.analysis.sequence import build_sequence
from cerebrofy.graph.edges import LOCAL_CALL, RUNTIME_BOUNDARY


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_db() -> sqlite3.Connection:
    """In-memory DB with minimal schema for impact tests."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO meta VALUES ('schema_version', '1');

        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            file TEXT NOT NULL,
            line_start INTEGER,
            line_end INTEGER,
            signature TEXT,
            docstring TEXT
        );

        CREATE TABLE edges (
            src_id TEXT NOT NULL,
            dst_id TEXT NOT NULL,
            rel_type TEXT NOT NULL,
            file TEXT NOT NULL
        );
    """)
    return conn


def _insert_node(conn, node_id, name, file, line_start=1, line_end=10, ntype="function"):
    conn.execute(
        "INSERT INTO nodes (id, name, type, file, line_start, line_end) VALUES (?,?,?,?,?,?)",
        (node_id, name, ntype, file, line_start, line_end),
    )


def _insert_edge(conn, src, dst, rel=LOCAL_CALL):
    conn.execute(
        "INSERT INTO edges (src_id, dst_id, rel_type, file) VALUES (?,?,?,?)",
        (src, dst, rel, "test.py"),
    )


# ---------------------------------------------------------------------------
# _lobe_from_file
# ---------------------------------------------------------------------------

def test_lobe_from_nested_file():
    assert _lobe_from_file("auth/tokens.py") == "auth"


def test_lobe_from_root_file():
    assert _lobe_from_file("main.py") == "main.py"


# ---------------------------------------------------------------------------
# _complexity_rating
# ---------------------------------------------------------------------------

def test_complexity_low():
    assert _complexity_rating(1, 2) == "LOW"


def test_complexity_medium_by_lobes():
    assert _complexity_rating(2, 1) == "MEDIUM"


def test_complexity_medium_by_callers():
    assert _complexity_rating(1, 5) == "MEDIUM"


def test_complexity_high_by_lobes():
    assert _complexity_rating(3, 1) == "HIGH"


def test_complexity_high_by_callers():
    assert _complexity_rating(1, 10) == "HIGH"


# ---------------------------------------------------------------------------
# _compute_loc
# ---------------------------------------------------------------------------

def test_compute_loc():
    neurons = [
        ImpactNeuron("a", "a", "f.py", 1, 10, "auth"),
        ImpactNeuron("b", "b", "f.py", 20, 25, "auth"),
    ]
    assert _compute_loc(neurons) == 10 + 6  # (10-1+1) + (25-20+1)


def test_compute_loc_empty():
    assert _compute_loc([]) == 0


# ---------------------------------------------------------------------------
# resolve_target
# ---------------------------------------------------------------------------

def test_resolve_target_by_name(tmp_path):
    conn = _make_db()
    _insert_node(conn, "auth/tokens.py::validate_token", "validate_token", "auth/tokens.py")
    result = resolve_target("validate_token", conn)
    assert result is not None
    assert result.name == "validate_token"


def test_resolve_target_by_file_name(tmp_path):
    conn = _make_db()
    _insert_node(conn, "auth/tokens.py::validate_token", "validate_token", "auth/tokens.py")
    result = resolve_target("auth/tokens.py::validate_token", conn)
    assert result is not None
    assert result.file == "auth/tokens.py"


def test_resolve_target_by_file_line(tmp_path):
    conn = _make_db()
    _insert_node(conn, "auth/tokens.py::validate_token", "validate_token", "auth/tokens.py", line_start=5, line_end=20)
    result = resolve_target("auth/tokens.py:10", conn)
    assert result is not None
    assert result.name == "validate_token"


def test_resolve_target_not_found():
    conn = _make_db()
    result = resolve_target("nonexistent_function", conn)
    assert result is None


def test_resolve_target_skips_module_by_name():
    conn = _make_db()
    _insert_node(conn, "auth/tokens.py::tokens", "tokens", "auth/tokens.py", ntype="module")
    _insert_node(conn, "auth/tokens.py::validate_token", "validate_token", "auth/tokens.py", ntype="function")
    result = resolve_target("validate_token", conn)
    assert result is not None
    assert result.name == "validate_token"


# ---------------------------------------------------------------------------
# bfs_callers
# ---------------------------------------------------------------------------

def test_bfs_callers_depth1():
    conn = _make_db()
    _insert_node(conn, "a.py::target", "target", "a.py")
    _insert_node(conn, "b.py::caller1", "caller1", "b.py")
    _insert_edge(conn, "b.py::caller1", "a.py::target")
    result = bfs_callers("a.py::target", conn, max_depth=1)
    assert 1 in result
    assert any(n.name == "caller1" for n in result[1])


def test_bfs_callers_depth2():
    conn = _make_db()
    _insert_node(conn, "a.py::target", "target", "a.py")
    _insert_node(conn, "b.py::caller1", "caller1", "b.py")
    _insert_node(conn, "c.py::caller2", "caller2", "c.py")
    _insert_edge(conn, "b.py::caller1", "a.py::target")
    _insert_edge(conn, "c.py::caller2", "b.py::caller1")
    result = bfs_callers("a.py::target", conn, max_depth=2)
    assert len(result[1]) == 1
    assert len(result[2]) == 1
    assert result[2][0].name == "caller2"


def test_bfs_callers_skips_runtime_boundary():
    conn = _make_db()
    _insert_node(conn, "a.py::target", "target", "a.py")
    _insert_node(conn, "b.py::caller", "caller", "b.py")
    _insert_edge(conn, "b.py::caller", "a.py::target", rel=RUNTIME_BOUNDARY)
    result = bfs_callers("a.py::target", conn, max_depth=1)
    assert result == {}


def test_bfs_callers_no_callers():
    conn = _make_db()
    _insert_node(conn, "a.py::target", "target", "a.py")
    result = bfs_callers("a.py::target", conn, max_depth=2)
    assert result == {}


def test_bfs_callers_deduplicates():
    conn = _make_db()
    _insert_node(conn, "a.py::target", "target", "a.py")
    _insert_node(conn, "b.py::caller", "caller", "b.py")
    _insert_edge(conn, "b.py::caller", "a.py::target")
    _insert_edge(conn, "b.py::caller", "a.py::target")  # duplicate edge
    result = bfs_callers("a.py::target", conn, max_depth=1)
    assert len(result[1]) == 1


# ---------------------------------------------------------------------------
# find_runtime_boundary_callers
# ---------------------------------------------------------------------------

def test_find_runtime_boundary_callers():
    conn = _make_db()
    _insert_node(conn, "a.py::target", "target", "a.py")
    _insert_edge(conn, "framework::handler", "a.py::target", rel=RUNTIME_BOUNDARY)
    result = find_runtime_boundary_callers("a.py::target", conn)
    assert "framework::handler" in result


def test_find_runtime_boundary_callers_empty():
    conn = _make_db()
    _insert_node(conn, "a.py::target", "target", "a.py")
    result = find_runtime_boundary_callers("a.py::target", conn)
    assert result == []


# ---------------------------------------------------------------------------
# find_covering_tests
# ---------------------------------------------------------------------------

def test_find_covering_tests_detects_test_caller():
    conn = _make_db()
    _insert_node(conn, "auth/tokens.py::target", "target", "auth/tokens.py")
    _insert_node(conn, "tests/test_tokens.py::test_validate", "test_validate", "tests/test_tokens.py")
    _insert_edge(conn, "tests/test_tokens.py::test_validate", "auth/tokens.py::target")
    tests, uncovered = find_covering_tests(set(), "auth/tokens.py::target", conn)
    assert any(t.name == "test_validate" for t in tests)


def test_find_covering_tests_uncovered_caller():
    conn = _make_db()
    _insert_node(conn, "a.py::target", "target", "a.py")
    _insert_node(conn, "b.py::caller", "caller", "b.py")
    # No test node calls the caller
    tests, uncovered = find_covering_tests({"b.py::caller"}, "a.py::target", conn)
    assert "b.py::caller" in uncovered


# ---------------------------------------------------------------------------
# compute_impact (integration)
# ---------------------------------------------------------------------------

def test_compute_impact_complexity_high():
    conn = _make_db()
    target = ImpactNeuron("a.py::target", "target", "a.py", 1, 10, "a")
    _insert_node(conn, "a.py::target", "target", "a.py")
    # Add 10 callers across 3 lobes
    for i in range(10):
        lobe = ["auth", "api", "middleware"][i % 3]
        _insert_node(conn, f"{lobe}/c{i}.py::caller{i}", f"caller{i}", f"{lobe}/c{i}.py")
        _insert_edge(conn, f"{lobe}/c{i}.py::caller{i}", "a.py::target")
    result = compute_impact(target, conn, depth=1, show_tests=False)
    assert result.complexity_rating == "HIGH"
    assert result.lobe_spread >= 3


def test_compute_impact_no_callers():
    conn = _make_db()
    target = ImpactNeuron("a.py::target", "target", "a.py", 1, 10, "a")
    _insert_node(conn, "a.py::target", "target", "a.py")
    result = compute_impact(target, conn, depth=2, show_tests=False)
    assert result.callers_by_depth == {}
    assert result.complexity_rating == "LOW"


# ---------------------------------------------------------------------------
# build_sequence
# ---------------------------------------------------------------------------

def test_build_sequence_target_always_last():
    conn = _make_db()
    target = ImpactNeuron("a.py::target", "target", "a.py", 1, 10, "a")
    caller = ImpactNeuron("b.py::caller", "caller", "b.py", 1, 5, "b")
    _insert_node(conn, "a.py::target", "target", "a.py")
    _insert_node(conn, "b.py::caller", "caller", "b.py")
    _insert_edge(conn, "b.py::caller", "a.py::target")
    steps = build_sequence(target, {1: [caller]}, [], conn)
    # Last non-boundary step should reference the target
    non_boundary = [s for s in steps if not s.is_runtime_boundary]
    assert target.id in non_boundary[-1].neuron_ids


def test_build_sequence_runtime_boundary_step():
    conn = _make_db()
    target = ImpactNeuron("a.py::target", "target", "a.py", 1, 10, "a")
    _insert_node(conn, "a.py::target", "target", "a.py")
    steps = build_sequence(target, {}, ["framework::handler"], conn)
    boundary_steps = [s for s in steps if s.is_runtime_boundary]
    assert len(boundary_steps) == 1
    assert "framework::handler" in boundary_steps[0].neuron_ids


def test_build_sequence_no_callers():
    conn = _make_db()
    target = ImpactNeuron("a.py::target", "target", "a.py", 1, 10, "a")
    _insert_node(conn, "a.py::target", "target", "a.py")
    steps = build_sequence(target, {}, [], conn)
    # Only the target step
    assert len(steps) == 1
    assert steps[0].neuron_ids == [target.id]
