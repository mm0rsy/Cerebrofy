"""Unit tests for the Onboarding Navigator planner and queries."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from cerebrofy.onboard.planner import OnboardPlan, build_plan
from cerebrofy.onboard.queries import (
    build_adjacency,
    compute_node_lobes,
    fetch_entry_points,
    fetch_hotspots,
    fetch_lobe_reading_order,
    fetch_lobe_sections,
    fetch_safe_zones,
    fetch_things_to_know,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE meta (schema_version INTEGER NOT NULL);
        INSERT INTO meta VALUES (1);
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            file TEXT NOT NULL,
            line_start INTEGER NOT NULL,
            signature TEXT,
            docstring TEXT,
            hash TEXT
        );
        CREATE TABLE edges (
            src_id TEXT NOT NULL,
            dst_id TEXT NOT NULL,
            rel_type TEXT NOT NULL,
            file TEXT,
            PRIMARY KEY (src_id, dst_id, rel_type)
        );
    """)
    return conn


def _add_node(conn: sqlite3.Connection, nid: str, name: str, file: str, line: int = 1) -> None:
    conn.execute(
        "INSERT INTO nodes(id, name, type, file, line_start) VALUES (?,?,?,?,?)",
        (nid, name, "function", file, line),
    )


def _add_edge(conn: sqlite3.Connection, src: str, dst: str, rel: str = "LOCAL_CALL") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO edges(src_id, dst_id, rel_type) VALUES (?,?,?)",
        (src, dst, rel),
    )


# ---------------------------------------------------------------------------
# build_adjacency
# ---------------------------------------------------------------------------

def test_build_adjacency_basic(tmp_path: Path) -> None:
    conn = _make_db(tmp_path / "db.sqlite")
    _add_node(conn, "a::f", "f", "a/module.py")
    _add_node(conn, "b::g", "g", "b/module.py")
    _add_edge(conn, "a::f", "b::g")
    conn.commit()

    node_map, in_adj, out_adj, valid_edges = build_adjacency(conn)
    conn.close()

    assert "a::f" in node_map
    assert "b::g" in node_map
    assert "b::g" in out_adj["a::f"]
    assert "a::f" in in_adj["b::g"]
    assert len(valid_edges) == 1


def test_build_adjacency_ignores_runtime_boundary(tmp_path: Path) -> None:
    conn = _make_db(tmp_path / "db.sqlite")
    _add_node(conn, "a::f", "f", "a/mod.py")
    _add_node(conn, "b::g", "g", "b/mod.py")
    _add_edge(conn, "a::f", "b::g", "RUNTIME_BOUNDARY")
    conn.commit()

    _, in_adj, out_adj, valid_edges = build_adjacency(conn)
    conn.close()

    assert len(valid_edges) == 0
    assert not out_adj.get("a::f")


# ---------------------------------------------------------------------------
# fetch_lobe_reading_order (Kahn's sort)
# ---------------------------------------------------------------------------

def test_reading_order_simple_chain(tmp_path: Path) -> None:
    """config → db → graph: graph depends on db depends on config."""
    conn = _make_db(tmp_path / "db.sqlite")
    _add_node(conn, "graph::f", "f", "src/graph/mod.py")
    _add_node(conn, "db::g", "g", "src/db/mod.py")
    _add_node(conn, "config::h", "h", "src/config/mod.py")
    # graph → db → config (graph calls db; db calls config)
    _add_edge(conn, "graph::f", "db::g", "EXTERNAL_CALL")
    _add_edge(conn, "db::g", "config::h", "EXTERNAL_CALL")
    conn.commit()

    node_map, in_adj, out_adj, _ = build_adjacency(conn)
    conn.close()

    lobes = {"graph": "src/graph", "db": "src/db", "config": "src/config"}
    node_lobe = compute_node_lobes(node_map, lobes)
    order = fetch_lobe_reading_order(node_lobe, lobes, in_adj, out_adj)

    assert order.index("config") < order.index("db")
    assert order.index("db") < order.index("graph")


def test_reading_order_all_lobes_returned(tmp_path: Path) -> None:
    conn = _make_db(tmp_path / "db.sqlite")
    _add_node(conn, "a::f", "f", "src/a/mod.py")
    _add_node(conn, "b::g", "g", "src/b/mod.py")
    conn.commit()

    node_map, in_adj, out_adj, _ = build_adjacency(conn)
    conn.close()

    lobes = {"a": "src/a", "b": "src/b"}
    node_lobe = compute_node_lobes(node_map, lobes)
    order = fetch_lobe_reading_order(node_lobe, lobes, in_adj, out_adj)

    assert set(order) == {"a", "b"}


def test_reading_order_cycle_does_not_hang(tmp_path: Path) -> None:
    """Cyclic lobe dependency should still return all lobes without hanging."""
    conn = _make_db(tmp_path / "db.sqlite")
    _add_node(conn, "a::f", "f", "src/a/mod.py")
    _add_node(conn, "b::g", "g", "src/b/mod.py")
    _add_edge(conn, "a::f", "b::g", "EXTERNAL_CALL")
    _add_edge(conn, "b::g", "a::f", "EXTERNAL_CALL")
    conn.commit()

    node_map, in_adj, out_adj, _ = build_adjacency(conn)
    conn.close()

    lobes = {"a": "src/a", "b": "src/b"}
    node_lobe = compute_node_lobes(node_map, lobes)
    order = fetch_lobe_reading_order(node_lobe, lobes, in_adj, out_adj)

    assert set(order) == {"a", "b"}
    assert len(order) == 2


# ---------------------------------------------------------------------------
# fetch_entry_points
# ---------------------------------------------------------------------------

def test_entry_points_only_no_incoming(tmp_path: Path) -> None:
    conn = _make_db(tmp_path / "db.sqlite")
    _add_node(conn, "cli::main", "main", "src/cli/cli.py")    # entry: in=0, out>0
    _add_node(conn, "db::open", "open", "src/db/conn.py")     # has callers
    _add_edge(conn, "cli::main", "db::open")
    conn.commit()

    node_map, in_adj, out_adj, _ = build_adjacency(conn)
    conn.close()

    lobes = {"cli": "src/cli", "db": "src/db"}
    node_lobe = compute_node_lobes(node_map, lobes)
    eps = fetch_entry_points(node_map, in_adj, out_adj, node_lobe)

    assert len(eps) == 1
    assert eps[0].name == "main"


def test_entry_points_exclude_tests(tmp_path: Path) -> None:
    conn = _make_db(tmp_path / "db.sqlite")
    _add_node(conn, "test::test_f", "test_f", "tests/test_cli.py")
    _add_node(conn, "cli::main", "main", "src/cli/cli.py")
    _add_edge(conn, "cli::main", "test::test_f")
    _add_edge(conn, "test::test_f", "cli::main")
    conn.commit()

    node_map, in_adj, out_adj, _ = build_adjacency(conn)
    conn.close()

    lobes = {"cli": "src/cli"}
    node_lobe = compute_node_lobes(node_map, lobes)
    eps = fetch_entry_points(node_map, in_adj, out_adj, node_lobe)

    names = [ep.name for ep in eps]
    assert "test_f" not in names


# ---------------------------------------------------------------------------
# fetch_hotspots
# ---------------------------------------------------------------------------

def test_hotspots_ranked_by_score(tmp_path: Path) -> None:
    conn = _make_db(tmp_path / "db.sqlite")
    # hub: called by 3 nodes from 2 lobes → score = 3*2 = 6
    _add_node(conn, "db::hub", "hub", "src/db/mod.py")
    _add_node(conn, "a::f1", "f1", "src/a/mod.py")
    _add_node(conn, "a::f2", "f2", "src/a/mod.py")
    _add_node(conn, "b::f3", "f3", "src/b/mod.py")
    _add_edge(conn, "a::f1", "db::hub")
    _add_edge(conn, "a::f2", "db::hub")
    _add_edge(conn, "b::f3", "db::hub")
    conn.commit()

    node_map, in_adj, out_adj, _ = build_adjacency(conn)
    conn.close()

    lobes = {"db": "src/db", "a": "src/a", "b": "src/b"}
    node_lobe = compute_node_lobes(node_map, lobes)
    hotspots = fetch_hotspots(node_map, in_adj, node_lobe)

    assert hotspots[0].name == "hub"
    assert hotspots[0].caller_count == 3
    assert hotspots[0].lobe_spread == 2


# ---------------------------------------------------------------------------
# fetch_safe_zones
# ---------------------------------------------------------------------------

def test_safe_zones_isolated_lobe_is_dead(tmp_path: Path) -> None:
    """A lobe with no edges should have 100% dead code."""
    conn = _make_db(tmp_path / "db.sqlite")
    _add_node(conn, "iso::f", "f", "src/iso/mod.py")
    conn.commit()

    node_map, in_adj, out_adj, _ = build_adjacency(conn)
    conn.close()

    lobes = {"iso": "src/iso"}
    node_lobe = compute_node_lobes(node_map, lobes)
    zones = fetch_safe_zones(lobes, node_map, node_lobe, in_adj, out_adj)

    assert len(zones) == 1
    assert zones[0].dead_code_pct == 100.0


# ---------------------------------------------------------------------------
# fetch_things_to_know
# ---------------------------------------------------------------------------

def test_things_to_know_absent_db(tmp_path: Path) -> None:
    titles, available = fetch_things_to_know(tmp_path / ".cerebrofy")
    assert titles == []
    assert available is False


# ---------------------------------------------------------------------------
# build_plan (integration of planner)
# ---------------------------------------------------------------------------

def test_build_plan_returns_onboard_plan(tmp_path: Path) -> None:
    db_path = tmp_path / "cerebrofy.db"
    conn = _make_db(db_path)
    _add_node(conn, "cli::main", "main", "src/cli/cli.py")
    _add_node(conn, "db::open", "open_db", "src/db/conn.py")
    _add_edge(conn, "cli::main", "db::open", "EXTERNAL_CALL")
    conn.commit()

    cerebrofy_dir = tmp_path / ".cerebrofy"
    cerebrofy_dir.mkdir()
    (cerebrofy_dir / "db").mkdir()

    lobes = {"cli": "src/cli", "db": "src/db"}
    plan = build_plan(
        conn=conn,
        lobes=lobes,
        cerebrofy_dir=cerebrofy_dir,
        repo_name="myrepo",
        depth="senior",
    )
    conn.close()

    assert isinstance(plan, OnboardPlan)
    assert plan.repo_name == "myrepo"
    assert plan.depth == "senior"
    assert plan.neuron_count == 2
    assert plan.edge_count == 1
    assert len(plan.lobe_reading_order) == 2
    # db should come before cli (cli depends on db)
    order_names = [s.name for s in plan.lobe_reading_order]
    assert order_names.index("db") < order_names.index("cli")
    # cli::main is the entry point
    assert any(ep.name == "main" for ep in plan.entry_points)
    assert plan.memories_available is False


def test_build_plan_to_dict_is_json_serialisable(tmp_path: Path) -> None:
    import json
    db_path = tmp_path / "cerebrofy.db"
    conn = _make_db(db_path)
    _add_node(conn, "a::f", "f", "src/a/mod.py")
    conn.commit()

    cerebrofy_dir = tmp_path / ".cerebrofy"
    cerebrofy_dir.mkdir()
    (cerebrofy_dir / "db").mkdir()

    plan = build_plan(conn=conn, lobes={"a": "src/a"}, cerebrofy_dir=cerebrofy_dir, repo_name="r")
    conn.close()

    serialised = json.dumps(plan.to_dict())
    assert '"repo_name"' in serialised


def test_build_plan_focus_lobe_filters(tmp_path: Path) -> None:
    db_path = tmp_path / "cerebrofy.db"
    conn = _make_db(db_path)
    _add_node(conn, "a::f", "f", "src/a/mod.py")
    _add_node(conn, "b::g", "g", "src/b/mod.py")
    _add_node(conn, "c::h", "h", "src/c/mod.py")
    _add_edge(conn, "a::f", "b::g", "EXTERNAL_CALL")
    conn.commit()

    cerebrofy_dir = tmp_path / ".cerebrofy"
    cerebrofy_dir.mkdir()
    (cerebrofy_dir / "db").mkdir()

    lobes = {"a": "src/a", "b": "src/b", "c": "src/c"}
    plan = build_plan(conn=conn, lobes=lobes, cerebrofy_dir=cerebrofy_dir,
                      repo_name="r", focus_lobe="a")
    conn.close()

    lobe_names = {s.name for s in plan.lobe_reading_order}
    assert "a" in lobe_names
    assert "b" in lobe_names   # neighbour of a
    assert "c" not in lobe_names  # isolated from a
