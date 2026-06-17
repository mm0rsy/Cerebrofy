import json
import sqlite3
import pytest
from cerebrofy.viz.graph_export import (
    export_graph, VizGraph, ANATOMICAL_REGIONS
)


@pytest.fixture
def db_path(tmp_path):
    db = tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE nodes (
            id TEXT, name TEXT, type TEXT, lobe TEXT,
            file TEXT, line_start INTEGER, line_end INTEGER
        );
        CREATE TABLE edges (src_id TEXT, dst_id TEXT, rel_type TEXT);
        INSERT INTO nodes VALUES ('pkg::foo','foo','function','pkg','pkg.py',1,5);
        INSERT INTO nodes VALUES ('pkg::bar','bar','function','pkg','pkg.py',7,12);
        INSERT INTO nodes VALUES ('cmd::run','run','function','cmd','cmd.py',1,10);
        INSERT INTO edges VALUES ('pkg::foo','pkg::bar','CALLS');
        INSERT INTO edges VALUES ('pkg::foo','cmd::run','RUNTIME_BOUNDARY');
    """)
    con.commit()
    con.close()
    return db


def test_export_returns_viz_graph(db_path):
    assert isinstance(export_graph(db_path), VizGraph)


def test_nodes_include_all_db_nodes(db_path):
    assert len(export_graph(db_path).nodes) == 3


def test_region_is_one_of_five_anatomical(db_path):
    for node in export_graph(db_path).nodes:
        assert node.region in ANATOMICAL_REGIONS


def test_runtime_boundary_excluded_from_edges(db_path):
    assert all(e.rel != "RUNTIME_BOUNDARY" for e in export_graph(db_path).edges)


def test_calls_edge_included(db_path):
    assert any(e.rel == "CALLS" for e in export_graph(db_path).edges)


def test_same_lobe_gets_same_region(db_path):
    pkg_regions = {n.region for n in export_graph(db_path).nodes if n.lobe == "pkg"}
    assert len(pkg_regions) == 1


def test_meta_counts(db_path):
    graph = export_graph(db_path)
    assert graph.meta.node_count == 3
    assert graph.meta.edge_count == 1
    assert graph.meta.lobe_count == 2


def test_to_json_produces_valid_structure(db_path):
    data = json.loads(export_graph(db_path).to_json())
    assert set(data.keys()) == {"nodes", "edges", "meta"}
    assert data["nodes"][0].keys() >= {"id", "name", "type", "lobe", "region", "file", "line"}
