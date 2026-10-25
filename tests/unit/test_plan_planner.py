"""Unit tests for planning/planner.py — orchestration, naming, error codes (Idea #12)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import sqlite_vec  # type: ignore[import-untyped]

from cerebrofy.config.loader import PlanningConfig
from cerebrofy.db.connection import open_db_readonly
from cerebrofy.db.schema import create_schema
from cerebrofy.graph.edges import LOCAL_CALL
from cerebrofy.planning.extractor import (
    DEFAULT_TOP_K,
    ClusterNeuron,
    NeuronCluster,
)
from cerebrofy.planning.planner import (  # pipeline steps under test
    CLUSTER_TOO_LARGE,
    CLUSTER_TOO_SMALL,
    NO_INDEX,
    PlanContext,
    PlanError,
    _annotate_impact_step,
    _blast_label_step,
    _collect_context_step,
    _estimate_step,
    _extract_cluster_step,
    _handoff_step,
    _map_files_step,
    _name_module_step,
    _sequence_step,
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


def a_payment_cluster_with_5_callers(tmp_path: Path, *, caller_count: int = 5) -> Path:
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
    from cerebrofy.db.connection import open_db_readonly
    
    try:
        conn = open_db_readonly(db_path)
    except FileNotFoundError as exc:
        raise PlanError(NO_INDEX, "Index not found. Run 'cerebrofy build' first.") from exc
    
    try:
        defaults: dict[str, Any] = {
            "description": "extract the payment logic into a payments service",
            "conn": conn,
            "embedding": _QUERY,
            "repo_root": tmp_path,
        }
        defaults.update(kwargs)
        return build_refactor_plan(**defaults)
    finally:
        conn.close()


def _make_ctx(
    tmp_path: Path, db_path: Path, **overrides: Any
) -> PlanContext:
    """Build a PlanContext on a fresh read-only connection (test must close)."""
    conn = open_db_readonly(db_path)
    return PlanContext(
        repo_root=Path(tmp_path),
        conn=conn,
        description=overrides.pop("description", "extract the payment logic into a payments service"),
        embedding=overrides.pop("embedding", _QUERY),
        config=overrides.pop("config", PlanningConfig()),
        top_k=overrides.pop("top_k", DEFAULT_TOP_K),
        config_path=overrides.pop("config_path", Path(tmp_path) / ".cerebrofy" / "config.yaml"),
        dry_run=overrides.pop("dry_run", True),
    )


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


def test_derive_module_name_honors_custom_generic_words() -> None:
    """A custom generic_words set changes which tokens are filtered out.

    With the default set, "services" is generic → filtered → graph fallback.
    With an empty custom set, "services" is accepted as the derived name.
    """
    description = "extract the logic into a services package"
    # Default filter excludes "services" (a generic word) → graph fallback.
    assert derive_module_name(description, []) == "extracted"
    # Empty custom set → "services" is no longer filtered → returned as name.
    assert derive_module_name(
        description, [], generic_words=frozenset()
    ) == "services"


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
    db_path = a_payment_cluster_with_5_callers(tmp_path)
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


def test_annotates_steps_with_impact_rating(tmp_path: Path) -> None:
    plan = _generate(tmp_path, a_payment_cluster_with_5_callers(tmp_path))
    # #07 integration: the charge.py move step is annotated with its impact rating.
    assert any("— impact:" in s.description for s in plan.steps)


def test_estimates_effort_using_published_formula(tmp_path: Path) -> None:
    plan = _generate(tmp_path, a_payment_cluster_with_5_callers(tmp_path))
    # Formula constants (spec): effort = base + per-neuron + per-caller + per-file
    effort_base = 0.5
    effort_per_neuron = 0.1
    effort_per_caller = 0.05
    effort_per_file = 0.25
    expected_hours = round(
        effort_base
        + effort_per_neuron * len(plan.cluster)
        + effort_per_caller * len(plan.callers_to_update)
        + effort_per_file * len(plan.file_map),
        1,
    )
    assert plan.estimated_hours == expected_hours


def test_counts_affected_files_across_cluster_file_map_and_callers(tmp_path: Path) -> None:
    plan = _generate(tmp_path, a_payment_cluster_with_5_callers(tmp_path))
    expected_files = len(
        {n.file for n in plan.cluster if n.file}
        | set(plan.file_map.values())
        | {c.file for c in plan.callers_to_update if c.file}
    )
    assert plan.files_affected == expected_files == 8


def test_file_map_and_proposed_files_are_consistent(tmp_path: Path) -> None:
    db_path = a_payment_cluster_with_5_callers(tmp_path)
    plan = _generate(tmp_path, db_path)
    assert sorted(plan.file_map.values()) == plan.proposed_files
    for source, target in plan.file_map.items():
        assert target.startswith(f"{plan.new_module}/")
        assert target.endswith(Path(source).suffix)


# ---------------------------------------------------------------------------
# Execution handoff (dry_run=False) — degrade-gracefully behavior
# ---------------------------------------------------------------------------

def test_dry_run_true_never_prepares_handoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = a_payment_cluster_with_5_callers(tmp_path)

    def _boom(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover - must not run
        raise AssertionError("optimize_context must not be called for dry runs")

    monkeypatch.setattr("cerebrofy.planning.planner.optimize_context", _boom)
    plan = _generate(tmp_path, db_path, dry_run=True)
    assert plan.handoff_summary is None


def test_dry_run_false_prepares_handoff_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = a_payment_cluster_with_5_callers(tmp_path)
    fake_plan = SimpleNamespace(neurons=[1, 2, 3], tokens_used=1200, token_budget=2000)
    monkeypatch.setattr(
        "cerebrofy.planning.planner.optimize_context", lambda **kwargs: fake_plan
    )

    plan = _generate(tmp_path, db_path, dry_run=False)

    assert plan.handoff_summary == (
        "3 neuron(s) packed into 1200/2000 tokens — "
        "execution handoff ready for the calling agent"
    )


def test_handoff_degrades_to_none_when_optimizer_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = a_payment_cluster_with_5_callers(tmp_path)

    def _fail(**kwargs: Any) -> Any:
        raise RuntimeError("no context db")

    monkeypatch.setattr("cerebrofy.planning.planner.optimize_context", _fail)
    plan = _generate(tmp_path, db_path, dry_run=False)
    assert plan.handoff_summary is None


# ---------------------------------------------------------------------------
# PlanningConfig injection (m11) — custom bounds + generic words
# ---------------------------------------------------------------------------

def test_custom_config_min_size_3_raises_too_small(tmp_path: Path) -> None:
    """With min_cluster_size=3, two seeds (2 < 3) surface CLUSTER_TOO_SMALL."""
    db_path, conn = _make_db(tmp_path)
    _node(conn, "a", "a", "src/a.py")
    _vec(conn, "a", _EXACT)
    _node(conn, "b", "b", "src/b.py")
    _vec(conn, "b", _NEAR)
    conn.commit()
    conn.close()

    with pytest.raises(PlanError) as exc_info:
        _generate(
            tmp_path, db_path,
            config=PlanningConfig(min_cluster_size=3, max_cluster_size=5),
        )
    assert exc_info.value.code == CLUSTER_TOO_SMALL
    assert "Only 2" in exc_info.value.message
    # The message no longer hard-codes the spec's "2" floor.
    assert "2 neurons" not in exc_info.value.message


def test_custom_config_max_size_5_raises_too_large(tmp_path: Path) -> None:
    """With max_cluster_size=5, six seeds (6 > 5) surface CLUSTER_TOO_LARGE."""
    db_path, conn = _make_db(tmp_path)
    for i in range(6):
        _node(conn, f"n{i}", f"fn{i}", f"src/n{i}.py")
        _vec(conn, f"n{i}", _EXACT)
    conn.commit()
    conn.close()

    with pytest.raises(PlanError) as exc_info:
        _generate(
            tmp_path, db_path,
            top_k=6,
            config=PlanningConfig(min_cluster_size=3, max_cluster_size=5),
        )
    assert exc_info.value.code == CLUSTER_TOO_LARGE
    assert "6 neurons" in exc_info.value.message
    # The message reports the *actual* configured ceiling, not the spec default.
    assert "more than the 5 supported" in exc_info.value.message


def test_custom_config_generic_words_changes_module_name(tmp_path: Path) -> None:
    """Wiring: build_refactor_plan forwards config.generic_module_words.

    With "payments" promoted to a generic word, the description no longer yields
    "payments" and the name falls back to the cluster's graph-derived "pay".
    """
    db_path = a_payment_cluster_with_5_callers(tmp_path)
    custom = PlanningConfig(
        generic_module_words=PlanningConfig().generic_module_words | frozenset({"payments"})
    )
    plan = _generate(tmp_path, db_path, config=custom)
    assert plan.new_module == "pay"


def test_custom_config_default_matches_spec_defaults(tmp_path: Path) -> None:
    """A default PlanningConfig reproduces the unchanged plan output."""
    db_path = a_payment_cluster_with_5_callers(tmp_path)
    plan = _generate(tmp_path, db_path, config=PlanningConfig())
    assert plan.new_module == "payments"
    assert [n.id for n in plan.cluster] == ["pay_a", "pay_b", "helper"]
    assert plan.files_affected == 8


# ---------------------------------------------------------------------------
# Pipeline steps (independent unit tests)
# ---------------------------------------------------------------------------

def test_extract_cluster_step_returns_neuron_cluster(tmp_path: Path) -> None:
    db_path = a_payment_cluster_with_5_callers(tmp_path)
    ctx = _make_ctx(tmp_path, db_path)
    try:
        cluster = _extract_cluster_step(ctx)
        assert [n.id for n in cluster.neurons] == ["pay_a", "pay_b", "helper"]
        assert [c.id for c in cluster.external_callers] == [f"caller{i}" for i in range(5)]
        assert cluster.runtime_boundary_callers == []
    finally:
        ctx.conn.close()


def test_name_module_step_uses_config_generic_words(tmp_path: Path) -> None:
    db_path = a_payment_cluster_with_5_callers(tmp_path)
    custom = PlanningConfig(
        generic_module_words=PlanningConfig().generic_module_words | frozenset({"payments"})
    )
    custom_ctx = _make_ctx(tmp_path, db_path, config=custom)
    default_ctx = _make_ctx(tmp_path, db_path)
    try:
        cluster = _extract_cluster_step(custom_ctx)
        # "payments" filtered → graph fallback "pay".
        assert _name_module_step(custom_ctx, cluster) == "pay"
        # Default config keeps "payments" from the description.
        assert _name_module_step(default_ctx, cluster) == "payments"
    finally:
        custom_ctx.conn.close()
        default_ctx.conn.close()


def test_map_files_step_targets_new_module(tmp_path: Path) -> None:
    db_path = a_payment_cluster_with_5_callers(tmp_path)
    ctx = _make_ctx(tmp_path, db_path)
    try:
        cluster = _extract_cluster_step(ctx)
        file_map = _map_files_step(ctx, cluster, "payments")
        assert set(file_map) == {"src/pay/charge.py", "src/pay/refund.py", "src/pay/helpers.py"}
        assert all(t.startswith("payments/") for t in file_map.values())
        assert file_map["src/pay/charge.py"] == "payments/charge.py"
    finally:
        ctx.conn.close()


def test_sequence_step_emits_skeleton_moves_callers_stubs(tmp_path: Path) -> None:
    db_path = a_payment_cluster_with_5_callers(tmp_path)
    ctx = _make_ctx(tmp_path, db_path)
    try:
        cluster = _extract_cluster_step(ctx)
        file_map = _map_files_step(ctx, cluster, "payments")
        steps = _sequence_step(ctx, cluster, "payments", file_map)
        assert steps[0].description.startswith("Create skeleton")
        assert steps[-1].description.startswith("Remove backward-compat re-exports")
        assert any("Update 5 caller(s)" in s.description for s in steps)
        # Step numbers are sequential (skeleton=1 ... stubs=last).
        assert [s.step_number for s in steps] == list(range(1, len(steps) + 1))
    finally:
        ctx.conn.close()


def test_annotate_impact_step_attaches_ratings_and_returns_warnings(tmp_path: Path) -> None:
    db_path = a_payment_cluster_with_5_callers(tmp_path)
    ctx = _make_ctx(tmp_path, db_path)
    try:
        cluster = _extract_cluster_step(ctx)
        steps = _sequence_step(ctx, cluster, "payments", _map_files_step(ctx, cluster, "payments"))
        annotated, warnings = _annotate_impact_step(ctx, steps)
        assert any("— impact:" in s.description for s in annotated)
        assert isinstance(warnings, list)
    finally:
        ctx.conn.close()


def test_blast_label_step_returns_valid_risk_label(tmp_path: Path) -> None:
    db_path = a_payment_cluster_with_5_callers(tmp_path)
    ctx = _make_ctx(tmp_path, db_path)
    try:
        cluster = _extract_cluster_step(ctx)
        steps = _sequence_step(ctx, cluster, "payments", _map_files_step(ctx, cluster, "payments"))
        steps, _warnings = _annotate_impact_step(ctx, steps)
        label = _blast_label_step(ctx, cluster, steps)
        assert label in {"LOW", "MEDIUM", "HIGH"}
    finally:
        ctx.conn.close()


def test_collect_context_step_merges_impact_warnings(tmp_path: Path) -> None:
    db_path = a_payment_cluster_with_5_callers(tmp_path)
    ctx = _make_ctx(tmp_path, db_path)
    try:
        cluster = _extract_cluster_step(ctx)
        # No memories.db under tmp_path → memory_context is just the warnings.
        result = _collect_context_step(ctx, cluster, "payments", ["high churn", "god object"])
        assert set(result.memory_context) == {"warning: high churn", "warning: god object"}
        assert result.avoid_pattern_warnings == []
    finally:
        ctx.conn.close()


def test_estimate_step_uses_published_formula() -> None:
    """Pure estimate: effort = 0.5 + 0.1*neurons + 0.05*callers + 0.25*files."""
    cluster = NeuronCluster(
        seeds=[],
        neurons=[
            ClusterNeuron("a", "af", "src/a.py", 1, 2, 0.9),
            ClusterNeuron("b", "bf", "src/b.py", 1, 2, 0.9),
        ],
        external_callers=[
            ClusterNeuron("c", "cf", "src/c.py", 1, 2, 0.0),
            ClusterNeuron("d", "df", "src/d.py", 1, 2, 0.0),
        ],
        runtime_boundary_callers=[],
    )
    file_map = {"src/a.py": "new/a.py", "src/b.py": "new/b.py"}
    hours, files = _estimate_step(cluster, file_map)
    expected_files = len(
        {"src/a.py", "src/b.py"} | {"new/a.py", "new/b.py"} | {"src/c.py", "src/d.py"}
    )
    expected_hours = round(0.5 + 0.1 * 2 + 0.05 * 2 + 0.25 * 2, 1)
    assert files == expected_files == 6
    assert hours == expected_hours == 1.3


def test_handoff_step_is_none_for_dry_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = a_payment_cluster_with_5_callers(tmp_path)
    ctx = _make_ctx(tmp_path, db_path, dry_run=True)

    def _boom(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover - must not run
        raise AssertionError("optimize_context must not be called for dry runs")

    monkeypatch.setattr("cerebrofy.planning.planner.optimize_context", _boom)
    try:
        assert _handoff_step(ctx) is None
    finally:
        ctx.conn.close()


def test_handoff_step_delegates_to_execution_handoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = a_payment_cluster_with_5_callers(tmp_path)
    ctx = _make_ctx(tmp_path, db_path, dry_run=False)
    captured: dict[str, Any] = {}

    def _fake(description, db_path, config_path, repo_root) -> str:
        captured.update(
            description=description,
            db_path=db_path,
            config_path=config_path,
            repo_root=repo_root,
        )
        return "handoff-ready"

    monkeypatch.setattr("cerebrofy.planning.planner._execution_handoff", _fake)
    try:
        assert _handoff_step(ctx) == "handoff-ready"
        assert captured["description"] == ctx.description
        assert captured["db_path"] == tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"
        assert captured["config_path"] == tmp_path / ".cerebrofy" / "config.yaml"
        assert captured["repo_root"] == tmp_path
    finally:
        ctx.conn.close()


def test_pipeline_steps_compose_to_expected_plan(tmp_path: Path) -> None:
    """Run every step in order; the composed result matches the happy-path plan."""
    db_path = a_payment_cluster_with_5_callers(tmp_path)
    ctx = _make_ctx(tmp_path, db_path)
    try:
        cluster = _extract_cluster_step(ctx)
        module = _name_module_step(ctx, cluster)
        file_map = _map_files_step(ctx, cluster, module)
        steps = _sequence_step(ctx, cluster, module, file_map)
        steps, impact_warnings = _annotate_impact_step(ctx, steps)
        blast_label = _blast_label_step(ctx, cluster, steps)
        context = _collect_context_step(ctx, cluster, module, impact_warnings)
        hours, files_affected = _estimate_step(cluster, file_map)

        assert module == "payments"
        assert [n.id for n in cluster.neurons] == ["pay_a", "pay_b", "helper"]
        assert [c.id for c in cluster.external_callers] == [f"caller{i}" for i in range(5)]
        assert sorted(set(file_map.values())) == [
            "payments/charge.py", "payments/helpers.py", "payments/refund.py",
        ]
        assert steps[0].description.startswith("Create skeleton")
        assert steps[-1].description.startswith("Remove backward-compat")
        assert any("Update 5 caller(s)" in s.description for s in steps)
        assert blast_label in {"LOW", "MEDIUM", "HIGH"}
        assert files_affected == 8
        assert hours == round(0.5 + 0.1 * 3 + 0.05 * 5 + 0.25 * 3, 1)
        assert context.memory_context == []
        assert context.avoid_pattern_warnings == []
        assert _handoff_step(ctx) is None  # dry_run=True
    finally:
        ctx.conn.close()
