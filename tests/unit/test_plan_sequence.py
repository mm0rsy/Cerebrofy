"""Unit tests for planning/sequence.py — dependency-safe migration steps (Idea #12)."""

from __future__ import annotations

import sqlite3

from cerebrofy.graph.edges import LOCAL_CALL
from cerebrofy.planning.extractor import ClusterNeuron
from cerebrofy.planning.sequence import MigrationStep, build_migration_steps

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY, name TEXT, file TEXT, type TEXT,
            line_start INTEGER, line_end INTEGER
        );
        CREATE TABLE edges (
            src_id TEXT, dst_id TEXT, rel_type TEXT, file TEXT
        );
    """)
    return conn


def _neuron(nid: str, file: str, name: str | None = None, line: int = 1) -> ClusterNeuron:
    return ClusterNeuron(
        id=nid,
        name=name or nid.split("::")[-1],
        file=file,
        line_start=line,
        line_end=line + 5,
        relevance_score=0.9,
    )


def _edge(conn: sqlite3.Connection, src: str, dst: str) -> None:
    conn.execute(
        "INSERT INTO edges(src_id, dst_id, rel_type, file) VALUES (?,?,?,?)",
        (src, dst, LOCAL_CALL, "x.py"),
    )


def _steps(
    conn: sqlite3.Connection,
    cluster: list[ClusterNeuron],
    *,
    callers: list[ClusterNeuron] | None = None,
    runtime_boundary_callers: list[str] | None = None,
    new_module: str = "extracted",
) -> list[MigrationStep]:
    file_map = {n.file: f"{new_module}/{n.file.split('/')[-1]}" for n in cluster}
    return build_migration_steps(
        cluster=cluster,
        callers=callers or [],
        runtime_boundary_callers=runtime_boundary_callers or [],
        conn=conn,
        new_module=new_module,
        file_map=file_map,
    )


# ---------------------------------------------------------------------------
# Step shape
# ---------------------------------------------------------------------------

def test_first_step_creates_skeleton_with_no_neurons() -> None:
    conn = _make_db()
    cluster = [_neuron("a.py::f", "a.py")]
    steps = _steps(conn, cluster, new_module="payments")

    first = steps[0]
    assert first.step_number == 1
    assert first.description.startswith("Create skeleton for 'payments/'")
    assert "a.py" in first.description
    assert first.neurons_affected == []
    assert first.callers_break is False


def test_last_step_removes_stubs_and_lists_all_moved_neurons() -> None:
    conn = _make_db()
    cluster = [_neuron("a.py::f", "a.py"), _neuron("b.py::g", "b.py")]
    steps = _steps(conn, cluster)

    last = steps[-1]
    assert "Remove backward-compat re-exports" in last.description
    assert "run the test suite" in last.description
    assert sorted(last.neurons_affected) == ["a.py::f", "b.py::g"]
    assert last.callers_break is False


def test_step_numbers_are_sequential() -> None:
    conn = _make_db()
    cluster = [_neuron("a.py::f", "a.py")]
    caller = _neuron("api.py::handler", "api.py")
    steps = _steps(conn, cluster, callers=[caller], runtime_boundary_callers=["hook"])
    assert [s.step_number for s in steps] == list(range(1, len(steps) + 1))


# ---------------------------------------------------------------------------
# Ordering: callees before callers
# ---------------------------------------------------------------------------

def test_callee_moves_before_caller_within_same_file() -> None:
    conn = _make_db()
    _edge(conn, "a.py::caller", "a.py::callee")
    cluster = [_neuron("a.py::caller", "a.py", line=20), _neuron("a.py::callee", "a.py", line=5)]

    steps = _steps(conn, cluster)
    move_step = steps[1]
    assert move_step.neurons_affected == ["a.py::callee", "a.py::caller"]


def test_callee_file_group_moves_before_caller_file_group() -> None:
    conn = _make_db()
    # 'y.py' is the callee file but sorts after 'x.py' alphabetically — callee-first
    # ordering must win over file-name ordering.
    _edge(conn, "x.py::caller", "y.py::callee")
    cluster = [_neuron("x.py::caller", "x.py"), _neuron("y.py::callee", "y.py")]

    steps = _steps(conn, cluster)
    assert "y.py → " in steps[1].description
    assert "x.py → " in steps[2].description


def test_cycle_degrades_to_deterministic_linear_order() -> None:
    conn = _make_db()
    _edge(conn, "a.py::one", "a.py::two")
    _edge(conn, "a.py::two", "a.py::one")
    cluster = [_neuron("a.py::one", "a.py"), _neuron("a.py::two", "a.py")]

    first = _steps(conn, cluster)[1].neurons_affected
    second = _steps(conn, cluster)[1].neurons_affected

    assert sorted(first) == ["a.py::one", "a.py::two"]
    assert first == second  # deterministic across runs


def test_every_cluster_neuron_appears_exactly_once_in_move_steps() -> None:
    conn = _make_db()
    _edge(conn, "a.py::caller", "b.py::callee")
    _edge(conn, "c.py::other", "a.py::caller")
    cluster = [
        _neuron("a.py::caller", "a.py"),
        _neuron("b.py::callee", "b.py"),
        _neuron("c.py::other", "c.py"),
    ]

    steps = _steps(conn, cluster)
    # Steps 2..N-1 are the move steps (no callers / no runtime boundary here).
    moved = [nid for step in steps[1:-1] for nid in step.neurons_affected]
    assert sorted(moved) == ["a.py::caller", "b.py::callee", "c.py::other"]
    assert len(moved) == len(set(moved))


# ---------------------------------------------------------------------------
# Caller + runtime boundary steps
# ---------------------------------------------------------------------------

def test_caller_update_step_lists_callers_and_files() -> None:
    conn = _make_db()
    cluster = [_neuron("pay.py::charge", "pay.py")]
    callers = [
        _neuron("api.py::route", "api.py", line=10),
        _neuron("api.py::web", "api.py", line=30),
        _neuron("jobs.py::run", "jobs.py", line=1),
    ]

    steps = _steps(conn, cluster, callers=callers)
    caller_step = steps[-2]
    assert caller_step.description.startswith("Update 3 caller(s) across 2 file(s)")
    assert caller_step.description.endswith("to import from 'extracted/'")
    assert caller_step.neurons_affected == ["api.py::route", "api.py::web", "jobs.py::run"]
    assert caller_step.callers_break is False


def test_no_caller_step_when_no_external_callers() -> None:
    conn = _make_db()
    cluster = [_neuron("pay.py::charge", "pay.py")]
    steps = _steps(conn, cluster)
    assert all("caller(s)" not in s.description for s in steps)


def test_runtime_boundary_step_marks_callers_break_and_precedes_stub_removal() -> None:
    conn = _make_db()
    cluster = [_neuron("pay.py::charge", "pay.py")]
    steps = _steps(conn, cluster, runtime_boundary_callers=["hook", "framework::router"])

    boundary_step = steps[-2]
    assert "RUNTIME_BOUNDARY" in boundary_step.description
    assert boundary_step.neurons_affected == ["hook", "framework::router"]
    assert boundary_step.callers_break is True
    # Final step is still the stub removal.
    assert "Remove backward-compat re-exports" in steps[-1].description


def test_full_step_order_skeleton_moves_callers_boundary_stubs() -> None:
    conn = _make_db()
    _edge(conn, "api.py::handler", "pay.py::charge")
    cluster = [_neuron("pay.py::charge", "pay.py")]
    callers = [_neuron("api.py::handler", "api.py")]

    steps = _steps(conn, cluster, callers=callers, runtime_boundary_callers=["hook"])

    assert steps[0].description.startswith("Create skeleton")
    assert steps[1].description.startswith("Move 1 neuron(s)")
    assert steps[2].description.startswith("Update 1 caller(s)")
    assert "RUNTIME_BOUNDARY" in steps[3].description
    assert "Remove backward-compat re-exports" in steps[4].description


# ---------------------------------------------------------------------------
# File mapping / descriptions
# ---------------------------------------------------------------------------

def test_move_step_description_uses_target_file_from_file_map() -> None:
    conn = _make_db()
    cluster = [_neuron("src/big.py::charge", "src/big.py", line=3)]
    steps = build_migration_steps(
        cluster=cluster,
        callers=[],
        runtime_boundary_callers=[],
        conn=conn,
        new_module="payments",
        file_map={"src/big.py": "payments/big.py"},
    )
    assert "src/big.py → payments/big.py" in steps[1].description
    assert "charge" in steps[1].description
