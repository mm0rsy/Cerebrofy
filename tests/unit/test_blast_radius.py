"""Unit tests for analysis/blast_radius.py, analysis/risk_scorer.py, ci/github_commenter.py."""

from __future__ import annotations

import sqlite3


from cerebrofy.analysis.blast_radius import (
    BlastNeuron,
    BlastRadiusReport,
    NeuronBlastRadius,
    _lobe_from_file,
    bfs_callers,
    compute_neuron_blast_radius,
    find_covering_tests,
    format_pr_comment,
    neuron_for_target,
    neurons_for_changed_files,
)
from cerebrofy.analysis.risk_scorer import compute_risk_score, risk_label, risk_icon
from cerebrofy.ci.github_commenter import parse_changed_files_from_diff
from cerebrofy.graph.edges import RUNTIME_BOUNDARY, LOCAL_CALL


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_db() -> sqlite3.Connection:
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


def _node(conn, node_id, name, file, line_start=1, line_end=10, ntype="function"):
    conn.execute(
        "INSERT INTO nodes (id, name, type, file, line_start, line_end) VALUES (?,?,?,?,?,?)",
        (node_id, name, ntype, file, line_start, line_end),
    )


def _edge(conn, src, dst, rel=LOCAL_CALL):
    conn.execute(
        "INSERT INTO edges (src_id, dst_id, rel_type, file) VALUES (?,?,?,?)",
        (src, dst, rel, "test.py"),
    )


# ---------------------------------------------------------------------------
# risk_scorer
# ---------------------------------------------------------------------------

def test_risk_score_zero_callers():
    score = compute_risk_score(0, 0, 5, 1, 1.0)
    assert score == 0.0


def test_risk_score_formula():
    # (1*1.0 + 2*0.4) * (2/5) / max(0.5, 0.05) = 1.8 * 0.4 / 0.5 = 1.44
    score = compute_risk_score(1, 2, 5, 2, 0.5)
    assert abs(score - 1.44) < 0.01


def test_risk_score_clamps_coverage():
    # test_coverage_ratio=0 → uses 0.05 floor
    score_floored = compute_risk_score(1, 0, 1, 1, 0.0)
    score_explicit = compute_risk_score(1, 0, 1, 1, 0.05)
    assert abs(score_floored - score_explicit) < 0.001


def test_risk_label_low():
    assert risk_label(0.0) == "LOW"
    assert risk_label(2.9) == "LOW"


def test_risk_label_medium():
    assert risk_label(3.0) == "MEDIUM"
    assert risk_label(9.9) == "MEDIUM"


def test_risk_label_high():
    assert risk_label(10.0) == "HIGH"
    assert risk_label(999.0) == "HIGH"


def test_risk_icon():
    assert risk_icon("HIGH") == "🔴"
    assert risk_icon("MEDIUM") == "🟡"
    assert risk_icon("LOW") == "🟢"


# ---------------------------------------------------------------------------
# _lobe_from_file
# ---------------------------------------------------------------------------

def test_lobe_nested():
    assert _lobe_from_file("auth/tokens.py") == "auth"


def test_lobe_root():
    assert _lobe_from_file("main.py") == "main.py"


# ---------------------------------------------------------------------------
# neuron_for_target
# ---------------------------------------------------------------------------

def test_neuron_for_target_by_name():
    conn = _make_db()
    _node(conn, "auth/tokens.py::validate_token", "validate_token", "auth/tokens.py")
    result = neuron_for_target("validate_token", conn)
    assert result is not None
    assert result.name == "validate_token"


def test_neuron_for_target_file_name():
    conn = _make_db()
    _node(conn, "auth/tokens.py::validate_token", "validate_token", "auth/tokens.py")
    result = neuron_for_target("auth/tokens.py::validate_token", conn)
    assert result is not None


def test_neuron_for_target_file_line():
    conn = _make_db()
    _node(conn, "auth/tokens.py::validate_token", "validate_token", "auth/tokens.py", line_start=5, line_end=20)
    result = neuron_for_target("auth/tokens.py:10", conn)
    assert result is not None
    assert result.name == "validate_token"


def test_neuron_for_target_not_found():
    conn = _make_db()
    result = neuron_for_target("nonexistent", conn)
    assert result is None


# ---------------------------------------------------------------------------
# neurons_for_changed_files
# ---------------------------------------------------------------------------

def test_neurons_for_changed_files_returns_non_module():
    conn = _make_db()
    _node(conn, "auth/tokens.py::validate_token", "validate_token", "auth/tokens.py")
    _node(conn, "auth/tokens.py::tokens", "tokens", "auth/tokens.py", ntype="module")
    result = neurons_for_changed_files(["auth/tokens.py"], conn)
    assert len(result) == 1
    assert result[0].name == "validate_token"


def test_neurons_for_changed_files_empty():
    conn = _make_db()
    result = neurons_for_changed_files([], conn)
    assert result == []


def test_neurons_for_changed_files_multiple_files():
    conn = _make_db()
    _node(conn, "a.py::fn_a", "fn_a", "a.py")
    _node(conn, "b.py::fn_b", "fn_b", "b.py")
    result = neurons_for_changed_files(["a.py", "b.py"], conn)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# bfs_callers
# ---------------------------------------------------------------------------

def test_bfs_callers_depth1():
    conn = _make_db()
    _node(conn, "a.py::target", "target", "a.py")
    _node(conn, "b.py::caller", "caller", "b.py")
    _edge(conn, "b.py::caller", "a.py::target")
    d1, d2, rb = bfs_callers("a.py::target", conn, max_depth=2)
    assert any(n.name == "caller" for n in d1)
    assert d2 == []


def test_bfs_callers_depth2():
    conn = _make_db()
    _node(conn, "a.py::target", "target", "a.py")
    _node(conn, "b.py::caller1", "caller1", "b.py")
    _node(conn, "c.py::caller2", "caller2", "c.py")
    _edge(conn, "b.py::caller1", "a.py::target")
    _edge(conn, "c.py::caller2", "b.py::caller1")
    d1, d2, rb = bfs_callers("a.py::target", conn, max_depth=2)
    assert len(d1) == 1
    assert len(d2) == 1
    assert d2[0].name == "caller2"


def test_bfs_callers_runtime_boundary_excluded():
    conn = _make_db()
    _node(conn, "a.py::target", "target", "a.py")
    _node(conn, "b.py::caller", "caller", "b.py")
    _edge(conn, "b.py::caller", "a.py::target", rel=RUNTIME_BOUNDARY)
    d1, d2, rb = bfs_callers("a.py::target", conn, max_depth=2)
    assert d1 == []
    assert "b.py::caller" in rb


def test_bfs_callers_no_callers():
    conn = _make_db()
    _node(conn, "a.py::target", "target", "a.py")
    d1, d2, rb = bfs_callers("a.py::target", conn, max_depth=2)
    assert d1 == [] and d2 == [] and rb == []


# ---------------------------------------------------------------------------
# find_covering_tests
# ---------------------------------------------------------------------------

def test_find_covering_tests_found():
    conn = _make_db()
    _node(conn, "auth/tokens.py::target", "target", "auth/tokens.py")
    _node(conn, "tests/test_tokens.py::test_fn", "test_fn", "tests/test_tokens.py")
    _edge(conn, "tests/test_tokens.py::test_fn", "auth/tokens.py::target")
    tests, uncovered = find_covering_tests("auth/tokens.py::target", set(), conn)
    assert any(t.name == "test_fn" for t in tests)


def test_find_covering_tests_uncovered():
    conn = _make_db()
    _node(conn, "a.py::target", "target", "a.py")
    _node(conn, "b.py::caller", "caller", "b.py")
    tests, uncovered = find_covering_tests("a.py::target", {"b.py::caller"}, conn)
    assert "b.py::caller" in uncovered


# ---------------------------------------------------------------------------
# compute_neuron_blast_radius
# ---------------------------------------------------------------------------

def test_compute_neuron_blast_radius_risk_high():
    conn = _make_db()
    target = BlastNeuron("a.py::target", "target", "a.py", 1, "a")
    _node(conn, "a.py::target", "target", "a.py")
    for i in range(12):
        lobe = ["auth", "api", "middleware", "core"][i % 4]
        _node(conn, f"{lobe}/c{i}.py::fn{i}", f"fn{i}", f"{lobe}/c{i}.py")
        _edge(conn, f"{lobe}/c{i}.py::fn{i}", "a.py::target")
    nbr = compute_neuron_blast_radius(target, conn, depth=1)
    assert nbr.risk_label == "HIGH"


def test_compute_neuron_blast_radius_no_callers():
    conn = _make_db()
    target = BlastNeuron("a.py::target", "target", "a.py", 1, "a")
    _node(conn, "a.py::target", "target", "a.py")
    nbr = compute_neuron_blast_radius(target, conn, depth=2)
    assert nbr.risk_label == "LOW"
    assert nbr.callers_depth1 == []


# ---------------------------------------------------------------------------
# BlastRadiusReport properties
# ---------------------------------------------------------------------------

def test_report_total_affected():
    n1 = BlastNeuron("b::fn1", "fn1", "b.py", 1, "b")
    n2 = BlastNeuron("c::fn2", "fn2", "c.py", 1, "c")
    nbr = NeuronBlastRadius(
        neuron=BlastNeuron("a::target", "target", "a.py", 1, "a"),
        callers_depth1=[n1],
        callers_depth2=[n2],
    )
    report = BlastRadiusReport(changed_neurons=[nbr])
    assert report.total_affected == 2


def test_report_highest_risk_aggregates():
    low = NeuronBlastRadius(neuron=BlastNeuron("a::fn", "fn", "a.py", 1, "a"), risk_label="LOW")
    high = NeuronBlastRadius(neuron=BlastNeuron("b::fn", "fn", "b.py", 1, "b"), risk_label="HIGH")
    report = BlastRadiusReport(changed_neurons=[low, high])
    assert report.highest_risk_label == "HIGH"


# ---------------------------------------------------------------------------
# format_pr_comment
# ---------------------------------------------------------------------------

def test_format_pr_comment_contains_table():
    nbr = NeuronBlastRadius(
        neuron=BlastNeuron("auth/tokens.py::validate_token", "validate_token", "auth/tokens.py", 42, "auth"),
        risk_label="HIGH",
        risk_icon="🔴",
    )
    report = BlastRadiusReport(changed_neurons=[nbr])
    comment = format_pr_comment(report)
    assert "🧠 Cerebrofy" in comment
    assert "validate_token" in comment
    assert "🔴 HIGH" in comment


def test_format_pr_comment_includes_details_when_callers():
    caller = BlastNeuron("b.py::caller", "caller", "b.py", 1, "b")
    nbr = NeuronBlastRadius(
        neuron=BlastNeuron("a.py::target", "target", "a.py", 1, "a"),
        callers_depth1=[caller],
        risk_label="LOW",
        risk_icon="🟢",
    )
    report = BlastRadiusReport(changed_neurons=[nbr])
    comment = format_pr_comment(report)
    assert "<details>" in comment
    assert "caller" in comment


# ---------------------------------------------------------------------------
# parse_changed_files_from_diff
# ---------------------------------------------------------------------------

def test_parse_changed_files_from_diff():
    diff = """\
diff --git a/auth/tokens.py b/auth/tokens.py
--- a/auth/tokens.py
+++ b/auth/tokens.py
diff --git a/api/views.py b/api/views.py
--- a/api/views.py
+++ b/api/views.py
"""
    files = parse_changed_files_from_diff(diff)
    assert "auth/tokens.py" in files
    assert "api/views.py" in files


def test_parse_changed_files_deduplicates():
    diff = "+++ b/auth/tokens.py\n+++ b/auth/tokens.py\n"
    files = parse_changed_files_from_diff(diff)
    assert files.count("auth/tokens.py") == 1
