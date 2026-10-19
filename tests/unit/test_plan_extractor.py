"""Unit tests for planning/extractor.py — cohesive cluster detection (Idea #12)."""

from __future__ import annotations

import json
import sqlite3

import sqlite_vec  # type: ignore[import-untyped]

from cerebrofy.db.schema import create_schema
from cerebrofy.graph.edges import LOCAL_CALL, RUNTIME_BOUNDARY
from cerebrofy.planning.extractor import (
    ClusterSizeError,
    expand_cluster,
    find_external_callers,
    find_extraction_cluster,
    find_runtime_boundary_callers,
    knn_seeds,
)

_QUERY = [1.0, 0.0, 0.0, 0.0]
_EXACT = [1.0, 0.0, 0.0, 0.0]
_NEAR = [0.9, 0.1, 0.0, 0.0]
_ORTHOGONAL = [0.0, 1.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_conn() -> sqlite3.Connection:
    """In-memory DB with sqlite-vec loaded and the production schema."""
    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    create_schema(conn, embed_dim=4)
    conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '1')")
    return conn


def _insert_node(
    conn: sqlite3.Connection,
    nid: str,
    *,
    name: str | None = None,
    file: str | None = None,
    line_start: int = 1,
    line_end: int = 5,
) -> None:
    conn.execute(
        "INSERT INTO nodes(id, name, file, type, line_start, line_end) VALUES (?,?,?,?,?,?)",
        (nid, name or nid.split("::")[-1], file or f"src/{nid.split('::')[0]}.py",
         "function", line_start, line_end),
    )


def _insert_vec(conn: sqlite3.Connection, nid: str, embedding: list[float]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO vec_neurons(id, embedding) VALUES (?, vec_f32(?))",
        (nid, json.dumps(embedding)),
    )


def _insert_edge(
    conn: sqlite3.Connection, src: str, dst: str, rel: str = LOCAL_CALL
) -> None:
    conn.execute(
        "INSERT INTO edges(src_id, dst_id, rel_type, file) VALUES (?,?,?,?)",
        (src, dst, rel, "src/main.py"),
    )


def _insert_dilution(conn: sqlite3.Connection, nid: str, count: int = 2) -> None:
    """Give *nid* extra outbound edges so it cannot be absorbed as a cluster member."""
    for i in range(count):
        _insert_edge(conn, nid, f"sinks/{nid}-{i}")


def _seed_pair(conn: sqlite3.Connection) -> None:
    """Two standard KNN seeds in different files."""
    _insert_node(conn, "pay_a", name="charge", file="src/pay/a.py", line_start=1)
    _insert_node(conn, "pay_b", name="refund", file="src/pay/b.py", line_start=1)
    _insert_vec(conn, "pay_a", _EXACT)
    _insert_vec(conn, "pay_b", _NEAR)


# ---------------------------------------------------------------------------
# knn_seeds
# ---------------------------------------------------------------------------

def test_knn_seeds_sorted_desc_and_filters_zero_similarity() -> None:
    conn = _make_conn()
    _insert_node(conn, "near", name="near_fn", file="src/near.py", line_start=3, line_end=9)
    _insert_node(conn, "exact", name="exact_fn", file="src/exact.py", line_start=1, line_end=4)
    _insert_node(conn, "ortho", name="ortho_fn", file="src/ortho.py")
    _insert_vec(conn, "near", _NEAR)
    _insert_vec(conn, "exact", _EXACT)
    _insert_vec(conn, "ortho", _ORTHOGONAL)

    seeds = knn_seeds(conn, _QUERY, top_k=10)

    assert [s.id for s in seeds] == ["exact", "near"]
    assert seeds[0].relevance_score > seeds[1].relevance_score
    # Node metadata is carried through.
    assert seeds[0].name == "exact_fn"
    assert seeds[0].file == "src/exact.py"
    assert seeds[0].line_start == 1
    assert seeds[0].line_end == 4
    assert seeds[1].file == "src/near.py"
    assert seeds[1].line_start == 3


def test_knn_seeds_skips_vec_rows_without_node_rows() -> None:
    conn = _make_conn()
    _insert_node(conn, "real", name="real_fn", file="src/real.py")
    _insert_vec(conn, "real", _EXACT)
    _insert_vec(conn, "ghost", _EXACT)  # vec row with no matching nodes row

    seeds = knn_seeds(conn, _QUERY, top_k=10)

    assert [s.id for s in seeds] == ["real"]


def test_knn_seeds_respects_top_k() -> None:
    conn = _make_conn()
    for i in range(5):
        _insert_node(conn, f"n{i}", name=f"fn{i}", file=f"src/n{i}.py")
        _insert_vec(conn, f"n{i}", _EXACT)
    seeds = knn_seeds(conn, _QUERY, top_k=3)
    assert len(seeds) == 3


# ---------------------------------------------------------------------------
# expand_cluster
# ---------------------------------------------------------------------------

def test_expand_cluster_adds_dense_neighbor_with_ratio_score() -> None:
    conn = _make_conn()
    _seed_pair(conn)
    # helper: 2 of 3 edges internal → 0.6667 > 0.5 → joins.
    _insert_node(conn, "helper", name="validate", file="src/pay/helpers.py", line_start=7)
    _insert_edge(conn, "helper", "pay_a")
    _insert_edge(conn, "helper", "pay_b")
    _insert_dilution(conn, "helper", count=1)

    seeds = knn_seeds(conn, _QUERY, top_k=10)
    result = expand_cluster(conn, seeds)

    assert [n.id for n in result] == ["pay_a", "pay_b", "helper"]
    helper = result[-1]
    assert helper.name == "validate"
    assert helper.file == "src/pay/helpers.py"
    assert helper.relevance_score == round(2 / 3, 4)


def test_expand_cluster_rejects_sparse_neighbor() -> None:
    conn = _make_conn()
    _seed_pair(conn)
    # 1 of 3 edges internal → 0.333 ≤ 0.5 → stays out.
    _insert_node(conn, "sparse", name="sparse_fn", file="src/pay/sparse.py")
    _insert_edge(conn, "sparse", "pay_a")
    _insert_dilution(conn, "sparse")

    seeds = knn_seeds(conn, _QUERY, top_k=10)
    result = expand_cluster(conn, seeds)

    assert [n.id for n in result] == ["pay_a", "pay_b"]


def test_expand_cluster_requires_strictly_more_than_half_internal() -> None:
    conn = _make_conn()
    _seed_pair(conn)
    # Exactly 50% internal → must NOT join (strict > comparison).
    _insert_node(conn, "half", name="half_fn", file="src/pay/half.py")
    _insert_edge(conn, "half", "pay_a")
    _insert_edge(conn, "half", "sinks/outside")

    seeds = knn_seeds(conn, _QUERY, top_k=10)
    result = expand_cluster(conn, seeds)

    assert [n.id for n in result] == ["pay_a", "pay_b"]


def test_expand_cluster_never_traverses_runtime_boundary_edges() -> None:
    conn = _make_conn()
    _seed_pair(conn)
    _insert_node(conn, "hook", name="framework_hook", file="framework/hooks.py")
    _insert_edge(conn, "hook", "pay_a", rel=RUNTIME_BOUNDARY)

    seeds = knn_seeds(conn, _QUERY, top_k=10)
    result = expand_cluster(conn, seeds)

    assert [n.id for n in result] == ["pay_a", "pay_b"]


def test_expand_cluster_raises_when_exceeding_max_size() -> None:
    conn = _make_conn()
    _seed_pair(conn)
    _insert_node(conn, "dense", name="dense_fn", file="src/pay/dense.py")
    _insert_edge(conn, "dense", "pay_a")
    _insert_edge(conn, "dense", "pay_b")

    seeds = knn_seeds(conn, _QUERY, top_k=10)
    try:
        expand_cluster(conn, seeds, max_size=2)
    except ClusterSizeError as exc:
        assert exc.size == 3
    else:  # pragma: no cover - guard for clearer failure
        raise AssertionError("ClusterSizeError not raised")


def test_expand_cluster_seeds_come_first_in_knn_order() -> None:
    conn = _make_conn()
    _seed_pair(conn)
    seeds = knn_seeds(conn, _QUERY, top_k=10)
    result = expand_cluster(conn, seeds)
    assert [n.id for n in result[:2]] == [s.id for s in seeds]


# ---------------------------------------------------------------------------
# External callers / runtime boundary
# ---------------------------------------------------------------------------

def test_find_external_callers_returns_direct_outside_callers_sorted() -> None:
    conn = _make_conn()
    _insert_node(conn, "z_caller", name="zeta", file="src/z.py", line_start=1)
    _insert_node(conn, "a_caller", name="alpha", file="src/a.py", line_start=2)
    _insert_edge(conn, "z_caller", "pay_a")
    _insert_edge(conn, "a_caller", "pay_a")
    _insert_edge(conn, "pay_b", "pay_a")  # internal edge — excluded

    callers = find_external_callers(conn, {"pay_a", "pay_b"})

    assert [c.id for c in callers] == ["a_caller", "z_caller"]
    assert callers[0].name == "alpha"
    assert callers[0].line_start == 2
    assert callers[0].relevance_score == 0.0


def test_find_external_callers_excludes_runtime_boundary() -> None:
    conn = _make_conn()
    _insert_node(conn, "hook", name="hook_fn", file="framework/hooks.py")
    _insert_edge(conn, "hook", "pay_a", rel=RUNTIME_BOUNDARY)

    assert find_external_callers(conn, {"pay_a"}) == []
    assert find_runtime_boundary_callers(conn, {"pay_a"}) == ["hook"]


def test_find_runtime_boundary_callers_sorted_unique() -> None:
    conn = _make_conn()
    _insert_edge(conn, "zeta", "pay_a", rel=RUNTIME_BOUNDARY)
    _insert_edge(conn, "alpha", "pay_a", rel=RUNTIME_BOUNDARY)
    _insert_edge(conn, "alpha", "pay_b", rel=RUNTIME_BOUNDARY)

    assert find_runtime_boundary_callers(conn, {"pay_a", "pay_b"}) == ["alpha", "zeta"]


def test_find_external_callers_empty_cluster() -> None:
    conn = _make_conn()
    assert find_external_callers(conn, set()) == []
    assert find_runtime_boundary_callers(conn, set()) == []


# ---------------------------------------------------------------------------
# find_extraction_cluster (public entry point)
# ---------------------------------------------------------------------------

def test_find_extraction_cluster_empty_index_raises_too_small() -> None:
    conn = _make_conn()
    try:
        find_extraction_cluster(conn, _QUERY)
    except ClusterSizeError as exc:
        assert exc.size == 0
    else:  # pragma: no cover
        raise AssertionError("ClusterSizeError not raised")


def test_find_extraction_cluster_single_seed_raises_too_small() -> None:
    conn = _make_conn()
    _insert_node(conn, "only", name="only_fn", file="src/only.py")
    _insert_vec(conn, "only", _EXACT)

    try:
        find_extraction_cluster(conn, _QUERY)
    except ClusterSizeError as exc:
        assert exc.size == 1
    else:  # pragma: no cover
        raise AssertionError("ClusterSizeError not raised")


def test_find_extraction_cluster_over_max_size_raises_too_large() -> None:
    conn = _make_conn()
    for i in range(201):
        _insert_node(conn, f"n{i}", name=f"fn{i}", file=f"src/n{i}.py")
        _insert_vec(conn, f"n{i}", _EXACT)

    try:
        find_extraction_cluster(conn, _QUERY, top_k=201)
    except ClusterSizeError as exc:
        assert exc.size == 201
    else:  # pragma: no cover
        raise AssertionError("ClusterSizeError not raised")


def test_find_extraction_cluster_happy_path_end_to_end() -> None:
    conn = _make_conn()
    _seed_pair(conn)
    # Dense expansion neuron.
    _insert_node(conn, "helper", name="validate", file="src/pay/helpers.py", line_start=7)
    _insert_edge(conn, "helper", "pay_a")
    _insert_edge(conn, "helper", "pay_b")
    # External caller (must appear in callers; dilution keeps it from being absorbed).
    _insert_node(conn, "routes", name="handle_charge", file="src/api/routes.py", line_start=11)
    _insert_edge(conn, "routes", "pay_a")
    _insert_dilution(conn, "routes", count=2)
    # RUNTIME_BOUNDARY caller (reported separately, never traversed).
    _insert_node(conn, "hook", name="webhook", file="framework/hooks.py")
    _insert_edge(conn, "hook", "pay_b", rel=RUNTIME_BOUNDARY)

    result = find_extraction_cluster(conn, _QUERY)

    assert [n.id for n in result.seeds] == ["pay_a", "pay_b"]
    assert [n.id for n in result.neurons] == ["pay_a", "pay_b", "helper"]
    assert [c.id for c in result.external_callers] == ["routes"]
    assert result.runtime_boundary_callers == ["hook"]


def test_expansion_order_is_deterministic_across_runs() -> None:
    conn = _make_conn()
    _seed_pair(conn)
    for i in range(4):
        nid = f"helper{i}"
        _insert_node(conn, nid, name=f"h{i}", file=f"src/pay/h{i}.py")
        _insert_edge(conn, nid, "pay_a")
        _insert_edge(conn, nid, "pay_b")
    seeds = knn_seeds(conn, _QUERY, top_k=10)
    first = [n.id for n in expand_cluster(conn, seeds)]
    second = [n.id for n in expand_cluster(conn, seeds)]
    assert first == second == ["pay_a", "pay_b", "helper0", "helper1", "helper2", "helper3"]


# ---------------------------------------------------------------------------
# Config-bound size checks (min_size / max_size) + actual-bounds messaging
# ---------------------------------------------------------------------------

def test_cluster_size_error_message_uses_actual_bounds() -> None:
    """ClusterSizeError reports the bounds in effect, not the spec defaults."""
    err = ClusterSizeError(7, low=3, high=5)
    assert err.size == 7
    assert err.low == 3
    assert err.high == 5
    assert str(err) == "cluster size 7 is outside 3..5"


def test_cluster_size_error_defaults_to_spec_bounds() -> None:
    """Constructing without bounds keeps the spec's 2..200 range in the message."""
    err = ClusterSizeError(1)
    assert err.low == 2
    assert err.high == 200
    assert "2..200" in str(err)


def test_find_extraction_cluster_custom_min_size_changes_boundary() -> None:
    """min_size=3: two seeds are no longer enough (2 < 3 → too small)."""
    conn = _make_conn()
    _seed_pair(conn)
    try:
        find_extraction_cluster(conn, _QUERY, min_size=3)
    except ClusterSizeError as exc:
        assert exc.size == 2
        assert exc.low == 3
        assert exc.high == 200  # max defaults to spec bound
    else:  # pragma: no cover
        raise AssertionError("ClusterSizeError not raised")


def test_find_extraction_cluster_custom_max_size_changes_boundary() -> None:
    """max_size=5: six seeds exceed the configured ceiling (6 > 5 → too large)."""
    conn = _make_conn()
    for i in range(6):
        _insert_node(conn, f"n{i}", name=f"fn{i}", file=f"src/n{i}.py")
        _insert_vec(conn, f"n{i}", _EXACT)
    try:
        find_extraction_cluster(conn, _QUERY, top_k=6, max_size=5)
    except ClusterSizeError as exc:
        assert exc.size == 6
        assert exc.low == 2  # min defaults to spec bound
        assert exc.high == 5
        assert "2..5" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("ClusterSizeError not raised")


def test_find_extraction_cluster_custom_bounds_passed_to_expand_cluster() -> None:
    """expand_cluster's size-violation error reports the bounds in effect."""
    conn = _make_conn()
    _seed_pair(conn)
    _insert_node(conn, "dense", name="dense_fn", file="src/pay/dense.py")
    _insert_edge(conn, "dense", "pay_a")
    _insert_edge(conn, "dense", "pay_b")
    seeds = knn_seeds(conn, _QUERY, top_k=10)
    try:
        expand_cluster(conn, seeds, min_size=2, max_size=2)
    except ClusterSizeError as exc:
        assert exc.size == 3
        assert exc.low == 2
        assert exc.high == 2
        assert "2..2" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("ClusterSizeError not raised")


def test_find_extraction_cluster_custom_bounds_happy_path_within_range() -> None:
    """A cluster within custom bounds succeeds and expansion still runs."""
    conn = _make_conn()
    _seed_pair(conn)
    _insert_node(conn, "helper", name="validate", file="src/pay/helpers.py", line_start=7)
    _insert_edge(conn, "helper", "pay_a")
    _insert_edge(conn, "helper", "pay_b")
    _insert_dilution(conn, "helper", count=1)

    result = find_extraction_cluster(conn, _QUERY, min_size=2, max_size=10)

    assert [n.id for n in result.seeds] == ["pay_a", "pay_b"]
    assert [n.id for n in result.neurons] == ["pay_a", "pay_b", "helper"]
