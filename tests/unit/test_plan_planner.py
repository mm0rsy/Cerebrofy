"""Unit tests for planning/planner.py — orchestration, naming, error codes (Idea #12)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import sqlite_vec  # type: ignore[import-untyped]

from cerebrofy.db.schema import create_schema
from cerebrofy.graph.edges import LOCAL_CALL
from cerebrofy.planning.extractor import ClusterNeuron
from cerebrofy.planning.planner import (
    CLUSTER_TOO_LARGE,
    CLUSTER_TOO_SMALL,
    NO_INDEX,
    PlanError,
    build_refactor_plan,
    derive_module_name,
    map_cluster_files,
)

_QUERY = [1.0, 0.0, 0.0, 0.0]
_EXACT = [1.0, 0.0, 0.0, 0.0]
_NEAR = [0.9, 0.1, 0.0, 0.0]


# ---------------------------------------------------------------------------
# DB fixtures (real file required — build_refactor_plan opens read-only)
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    db_path = tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    create_schema(conn, embed_dim=4)
    conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '1')")
    return db_path, conn


def _node(conn: sqlite3.Connection, nid: str, name: str | None = None,
          file: str | None = None, line: int = 1) -> None:
    conn.execute(
        "INSERT INTO nodes(id, name, file, type, line_start, line_end) VALUES (?,?,?,?,?,?)",
        (nid, name or nid.split("::")[-1], file or f"src/{nid.split('::')[0]}.py",
         "function", line, line + 9),
    )


def _vec(conn: sqlite3.Connection, nid: str, embedding: list[float]) -> None:
    conn.execute(
        "INSERT INTO vec_neurons(id, embedding) VALUES (?, vec_f32(?))",
        (nid, json.dumps(embedding)),
    )


def _edge(conn: sqlite3.Connection, src: str, dst: str) -> None:
    conn.execute(
        "INSERT INTO edges(src_id, dst_id, rel_type, file) VALUES (?,?,?,?)",
        (src, dst, LOCAL_CALL, "src/main.py"),
    )


def _build_fixture(tmp_path: Path, *, caller_count: int = 5) -> Path:
    """Payment-cluster fixture: 2 seeds, 1 expansion neuron, N external callers."""
    db_path, conn = _make_db(tmp_path)
    _node(conn, "pay_a", "charge", "src/pay/charge.py", line=10)
    _node(conn, "pay_b", "refund", "src/pay/refund.py", line=20)
    _node(conn, "helper", "validate", "src/pay/helpers.py", line=30)
    _vec(conn, "pay_a", _EXACT)
    _vec(conn, "pay_b", _NEAR)
    _edge(conn, "helper", "pay_a")
    _edge(conn, "helper", "pay_b")
    for i in range(caller_count):
        caller = f"caller{i}"
        file = "src/api/routes.py" if i < 3 else "src/jobs/run.py"
        _node(conn, caller, f"route_{i}", file, line=100 + i)
        _edge(conn, caller, "pay_a")
        # Dilution so callers stay outside the cluster (ratio 1/3 ≤ 0.5).
        _edge(conn, caller, f"sinks/{caller}-0")
        _edge(conn, caller, f"sinks/{caller}-1")
    conn.commit()
    conn.close()
    return db_path


def _generate(tmp_path: Path, db_path: Path, **kwargs: Any) -> Any:
    defaults: dict[str, Any] = dict(
        description="extract the payment logic into a payments service",
        db_path=db_path,
        embedding=_QUERY,
        repo_root=tmp_path,
    )
    defaults.update(kwargs)
    return build_refactor_plan(**defaults)


# ---------------------------------------------------------------------------
# derive_module_name
# ---------------------------------------------------------------------------

def test_derive_module_name_from_named_target() -> None:
    assert derive_module_name("extract the payment logic into a payments service", []) == "payments"


def test_derive_module_name_from_token_with_slash() -> None:
    assert derive_module_name("move database code into a db/ module", []) == "db"


def test_derive_module_name_strips_generic_words_and_falls_back_to_graph() -> None:
    cluster = [ClusterNeuron("x", "f", "src/billing/core.py", 1, 5, 0.9)]
    assert derive_module_name("extract it into its own module", cluster) == "billing"


def test_derive_module_name_fallback_to_dominant_parent_dir() -> None:
    cluster = [
        ClusterNeuron("a", "a", "src/payments/charge.py", 1, 2, 0.9),
        ClusterNeuron("b", "b", "src/payments/refund.py", 1, 2, 0.9),
        ClusterNeuron("c", "c", "src/api/routes.py", 1, 2, 0.9),
    ]
    assert derive_module_name("extract these helpers please", cluster) == "payments"


def test_derive_module_name_fallback_to_file_stem_for_root_files() -> None:
    cluster = [ClusterNeuron("a", "a", "auth.py", 1, 2, 0.9)]
    assert derive_module_name("extract these helpers", cluster) == "auth"


def test_derive_module_name_ultimate_fallback() -> None:
    assert derive_module_name("extract these helpers", []) == "extracted"


def test_derive_module_name_handles_backticked_target() -> None:
    assert derive_module_name("move the logic into `billing_v2` package", []) == "billing_v2"


# ---------------------------------------------------------------------------
# map_cluster_files
# ---------------------------------------------------------------------------

def test_map_cluster_files_deduplicates_stem_collisions() -> None:
    cluster = [
        ClusterNeuron("a", "a", "a/conn.py", 1, 2, 0.9),
        ClusterNeuron("b", "b", "b/conn.py", 1, 2, 0.9),
    ]
    file_map = map_cluster_files(cluster, "db")
    assert file_map["a/conn.py"] == "db/conn.py"
    assert file_map["b/conn.py"] == "db/conn_2.py"


def test_map_cluster_files_skips_blank_files() -> None:
    cluster = [ClusterNeuron("a", "a", "", 1, 2, 0.9)]
    assert map_cluster_files(cluster, "db") == {}


# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------

def test_no_index_when_db_missing(tmp_path: Path) -> None:
    with pytest.raises(PlanError) as exc_info:
        _generate(tmp_path, tmp_path / "missing.db")
    assert exc_info.value.code == NO_INDEX


def test_cluster_too_small_when_fewer_than_two_seeds(tmp_path: Path) -> None:
    db_path, conn = _make_db(tmp_path)
    _node(conn, "only", "only_fn", "src/only.py")
    _vec(conn, "only", _EXACT)
    conn.commit()
    conn.close()

    with pytest.raises(PlanError) as exc_info:
        _generate(tmp_path, db_path)
    assert exc_info.value.code == CLUSTER_TOO_SMALL
    assert "Only 1" in exc_info.value.message


def test_cluster_too_large_above_200_seeds(tmp_path: Path) -> None:
    db_path, conn = _make_db(tmp_path)
    for i in range(201):
        _node(conn, f"n{i}", f"fn{i}", f"src/n{i}.py")
        _vec(conn, f"n{i}", _EXACT)
    conn.commit()
    conn.close()

    with pytest.raises(PlanError) as exc_info:
        _generate(tmp_path, db_path, top_k=201)
    assert exc_info.value.code == CLUSTER_TOO_LARGE
    assert "201 neurons" in exc_info.value.message


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_happy_path_plan_structure(tmp_path: Path) -> None:
    db_path = _build_fixture(tmp_path)
    plan = _generate(tmp_path, db_path)

    assert plan.new_module == "payments"
    assert [n.id for n in plan.cluster] == ["pay_a", "pay_b", "helper"]
    assert [c.id for c in plan.callers_to_update] == [f"caller{i}" for i in range(5)]
    assert plan.proposed_files == [
        "payments/charge.py", "payments/helpers.py", "payments/refund.py",
    ]
    # Steps: skeleton + 3 file moves + caller update + stub removal.
    assert plan.steps[0].description.startswith("Create skeleton")
    assert plan.steps[-1].description.startswith("Remove backward-compat re-exports")
    assert any("Update 5 caller(s)" in s.description for s in plan.steps)
    assert plan.handoff_summary is None
    assert plan.memory_context == []
    assert plan.avoid_pattern_warnings == []
    assert plan.runtime_boundary_callers == []
    assert plan.blast_radius_label in {"LOW", "MEDIUM", "HIGH"}


def test_happy_path_impact_annotation_and_formulas(tmp_path: Path) -> None:
    db_path = _build_fixture(tmp_path)
    plan = _generate(tmp_path, db_path)

    # #07 integration: the charge.py move step is annotated with its impact rating.
    assert any("— impact:" in s.description for s in plan.steps)

    # Deterministic effort/file formulas (spec).
    expected_hours = round(
        0.5 + 0.1 * len(plan.cluster)
        + 0.05 * len(plan.callers_to_update)
        + 0.25 * len(plan.file_map),
        1,
    )
    assert plan.estimated_hours == expected_hours

    expected_files = len(
        {n.file for n in plan.cluster if n.file}
        | set(plan.file_map.values())
        | {c.file for c in plan.callers_to_update if c.file}
    )
    assert plan.files_affected == expected_files == 8


def test_file_map_and_proposed_files_are_consistent(tmp_path: Path) -> None:
    db_path = _build_fixture(tmp_path)
    plan = _generate(tmp_path, db_path)
    assert sorted(plan.file_map.values()) == plan.proposed_files
    for source, target in plan.file_map.items():
        assert target.startswith(f"{plan.new_module}/")
        assert target.endswith(Path(source).suffix)


# ---------------------------------------------------------------------------
# Execution handoff (dry_run=False) — degrade-gracefully behavior
# ---------------------------------------------------------------------------

def test_dry_run_true_never_prepares_handoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _build_fixture(tmp_path)

    def _boom(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover - must not run
        raise AssertionError("optimize_context must not be called for dry runs")

    monkeypatch.setattr("cerebrofy.context.optimizer.optimize_context", _boom)
    plan = _generate(tmp_path, db_path, dry_run=True)
    assert plan.handoff_summary is None


def test_dry_run_false_prepares_handoff_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = _build_fixture(tmp_path)
    fake_plan = SimpleNamespace(neurons=[1, 2, 3], tokens_used=1200, token_budget=2000)
    monkeypatch.setattr(
        "cerebrofy.context.optimizer.optimize_context", lambda **kwargs: fake_plan
    )

    plan = _generate(tmp_path, db_path, dry_run=False)

    assert plan.handoff_summary == (
        "3 neuron(s) packed into 1200/2000 tokens — "
        "execution handoff ready for the calling agent"
    )


def test_handoff_degrades_to_none_when_optimizer_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = _build_fixture(tmp_path)

    def _fail(**kwargs: Any) -> Any:
        raise RuntimeError("no context db")

    monkeypatch.setattr("cerebrofy.context.optimizer.optimize_context", _fail)
    plan = _generate(tmp_path, db_path, dry_run=False)
    assert plan.handoff_summary is None
