"""Unit tests for health package: metrics, snapshot, reporter."""

from __future__ import annotations

import json
import sqlite3
import time

from cerebrofy.health.metrics import (
    HealthMetrics,
    _is_test_file,
    _lobe_for_file,
    compute_metrics,
)
from cerebrofy.health.reporter import (
    format_health_snapshot,
    format_history_table,
    format_trend_sparkline,
    to_export_json,
)
from cerebrofy.health.snapshot import fetch_snapshots, fetch_latest_snapshot, record_snapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, file TEXT NOT NULL,
            type TEXT, line_start INTEGER, line_end INTEGER,
            signature TEXT, docstring TEXT, hash TEXT
        );
        CREATE TABLE edges (
            src_id TEXT, dst_id TEXT, rel_type TEXT NOT NULL,
            file TEXT, PRIMARY KEY (src_id, dst_id, rel_type)
        );
        CREATE TABLE health_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            build_ts INTEGER NOT NULL,
            commit_hash TEXT,
            coupling REAL, avg_blast REAL, dead_code_pct REAL,
            cohesion REAL, test_surface REAL, drift_velocity REAL,
            hub_concentration REAL, neuron_count INTEGER, edge_count INTEGER
        );
    """)
    return conn


def _insert_node(conn: sqlite3.Connection, nid: str, name: str, file: str) -> None:
    conn.execute(
        "INSERT INTO nodes (id, name, file) VALUES (?, ?, ?)", (nid, name, file)
    )


def _insert_edge(conn: sqlite3.Connection, src: str, dst: str, rel: str = "LOCAL_CALL") -> None:
    conn.execute(
        "INSERT INTO edges (src_id, dst_id, rel_type) VALUES (?, ?, ?)", (src, dst, rel)
    )


LOBES = {"src": "src/cerebrofy", "tests": "tests"}


# ---------------------------------------------------------------------------
# _lobe_for_file
# ---------------------------------------------------------------------------

def test_lobe_for_file_matches_prefix():
    assert _lobe_for_file("src/cerebrofy/health/metrics.py", LOBES) == "src"


def test_lobe_for_file_unknown():
    assert _lobe_for_file("docs/readme.md", LOBES) == "__unknown__"


def test_lobe_for_file_exact_match():
    lobes = {"cli": "src/cerebrofy/cli.py"}
    assert _lobe_for_file("src/cerebrofy/cli.py", lobes) == "cli"


# ---------------------------------------------------------------------------
# _is_test_file
# ---------------------------------------------------------------------------

def test_is_test_file_prefix():
    assert _is_test_file("tests/unit/test_health.py") is True


def test_is_test_file_suffix():
    assert _is_test_file("tests/health_test.py") is True


def test_is_test_file_false():
    assert _is_test_file("src/cerebrofy/health/metrics.py") is False


# ---------------------------------------------------------------------------
# compute_metrics — empty DB
# ---------------------------------------------------------------------------

def test_compute_metrics_empty_db():
    conn = _make_db()
    m = compute_metrics(conn, LOBES)
    assert m.neuron_count == 0
    assert m.edge_count == 0
    assert m.coupling == 0.0
    assert m.hotspots == ()


# ---------------------------------------------------------------------------
# compute_metrics — single neuron, no edges
# ---------------------------------------------------------------------------

def test_compute_metrics_single_neuron_no_edges():
    conn = _make_db()
    _insert_node(conn, "n1", "foo", "src/cerebrofy/health/metrics.py")
    m = compute_metrics(conn, LOBES)
    assert m.neuron_count == 1
    assert m.edge_count == 0
    assert m.dead_code_pct == 100.0   # isolated = dead
    assert m.coupling == 0.0
    assert m.avg_blast == 0.0


# ---------------------------------------------------------------------------
# coupling — cross-lobe vs intra-lobe
# ---------------------------------------------------------------------------

def test_coupling_intra_lobe_only():
    conn = _make_db()
    _insert_node(conn, "a", "a", "src/cerebrofy/foo.py")
    _insert_node(conn, "b", "b", "src/cerebrofy/bar.py")
    _insert_edge(conn, "a", "b")
    m = compute_metrics(conn, LOBES)
    assert m.coupling == 0.0  # both in "src"


def test_coupling_cross_lobe():
    conn = _make_db()
    _insert_node(conn, "a", "a", "src/cerebrofy/foo.py")
    _insert_node(conn, "t", "t", "tests/test_foo.py")
    _insert_edge(conn, "t", "a")
    m = compute_metrics(conn, LOBES)
    assert m.coupling == 1.0  # all edges cross lobes


def test_coupling_mixed():
    conn = _make_db()
    _insert_node(conn, "a", "a", "src/cerebrofy/foo.py")
    _insert_node(conn, "b", "b", "src/cerebrofy/bar.py")
    _insert_node(conn, "t", "t", "tests/test_foo.py")
    _insert_edge(conn, "a", "b")   # intra
    _insert_edge(conn, "t", "a")   # cross
    m = compute_metrics(conn, LOBES)
    assert m.coupling == 0.5


# ---------------------------------------------------------------------------
# dead code
# ---------------------------------------------------------------------------

def test_dead_code_entry_point_not_dead():
    conn = _make_db()
    _insert_node(conn, "entry", "main", "src/cerebrofy/cli.py")
    _insert_node(conn, "impl", "impl", "src/cerebrofy/foo.py")
    _insert_edge(conn, "entry", "impl")
    m = compute_metrics(conn, LOBES)
    # entry has in=0 out=1 → entry point, not dead
    # impl has in=1 out=0 → not dead
    assert m.dead_code_pct == 0.0


def test_dead_code_isolated_neuron():
    conn = _make_db()
    _insert_node(conn, "live", "live", "src/cerebrofy/foo.py")
    _insert_node(conn, "dead", "dead", "src/cerebrofy/bar.py")
    _insert_edge(conn, "live", "live")  # self-loop so live has in+out
    m = compute_metrics(conn, LOBES)
    assert m.dead_code_pct == 50.0


# ---------------------------------------------------------------------------
# cohesion
# ---------------------------------------------------------------------------

def test_cohesion_fully_cohesive():
    conn = _make_db()
    _insert_node(conn, "a", "a", "src/cerebrofy/foo.py")
    _insert_node(conn, "b", "b", "src/cerebrofy/bar.py")
    _insert_edge(conn, "a", "b")
    m = compute_metrics(conn, LOBES)
    assert m.cohesion == 1.0


def test_cohesion_fully_cross():
    conn = _make_db()
    _insert_node(conn, "a", "a", "src/cerebrofy/foo.py")
    _insert_node(conn, "t", "t", "tests/test_foo.py")
    _insert_edge(conn, "a", "t")
    m = compute_metrics(conn, LOBES)
    assert m.cohesion == 0.0


# ---------------------------------------------------------------------------
# test surface
# ---------------------------------------------------------------------------

def test_test_surface_reachable():
    conn = _make_db()
    _insert_node(conn, "test_fn", "test_fn", "tests/test_foo.py")
    _insert_node(conn, "impl", "impl", "src/cerebrofy/foo.py")
    _insert_edge(conn, "test_fn", "impl")
    m = compute_metrics(conn, LOBES)
    assert m.test_surface == 100.0  # 1/1 non-test neuron reachable


def test_test_surface_unreachable():
    conn = _make_db()
    _insert_node(conn, "test_fn", "test_fn", "tests/test_foo.py")
    _insert_node(conn, "impl", "impl", "src/cerebrofy/foo.py")
    # no edge from test to impl
    m = compute_metrics(conn, LOBES)
    assert m.test_surface == 0.0


# ---------------------------------------------------------------------------
# avg blast radius
# ---------------------------------------------------------------------------

def test_avg_blast_simple_chain():
    conn = _make_db()
    _insert_node(conn, "a", "a", "src/cerebrofy/foo.py")
    _insert_node(conn, "b", "b", "src/cerebrofy/bar.py")
    _insert_node(conn, "c", "c", "src/cerebrofy/baz.py")
    _insert_edge(conn, "a", "b")
    _insert_edge(conn, "b", "c")
    m = compute_metrics(conn, LOBES)
    # c has callers: b (depth1) + a (depth2) = 2
    # b has callers: a (depth1) = 1
    # a has callers: none = 0
    # avg = (2 + 1 + 0) / 3
    assert round(m.avg_blast, 4) == round(3 / 3, 4)


# ---------------------------------------------------------------------------
# RUNTIME_BOUNDARY edges excluded
# ---------------------------------------------------------------------------

def test_runtime_boundary_excluded():
    conn = _make_db()
    _insert_node(conn, "a", "a", "src/cerebrofy/foo.py")
    _insert_node(conn, "b", "b", "src/cerebrofy/bar.py")
    _insert_edge(conn, "a", "b", "RUNTIME_BOUNDARY")
    m = compute_metrics(conn, LOBES)
    assert m.edge_count == 0  # RUNTIME_BOUNDARY not counted


# ---------------------------------------------------------------------------
# hotspots
# ---------------------------------------------------------------------------

def test_hotspots_top_node():
    conn = _make_db()
    for i in range(5):
        _insert_node(conn, f"caller_{i}", f"caller_{i}", "src/cerebrofy/foo.py")
    _insert_node(conn, "hub", "hub", "src/cerebrofy/bar.py")
    for i in range(5):
        _insert_edge(conn, f"caller_{i}", "hub")
    m = compute_metrics(conn, LOBES)
    assert len(m.hotspots) > 0
    assert m.hotspots[0]["name"] == "hub"
    assert m.hotspots[0]["caller_count"] == 5


# ---------------------------------------------------------------------------
# snapshot: record + fetch
# ---------------------------------------------------------------------------

def _sample_metrics() -> HealthMetrics:
    return HealthMetrics(
        coupling=0.25, avg_blast=5.0, dead_code_pct=10.0, cohesion=0.75,
        test_surface=60.0, drift_velocity=1.5, hub_concentration=20.0,
        neuron_count=100, edge_count=300, hotspots=(),
    )


def test_record_and_fetch_snapshot():
    conn = _make_db()
    m = _sample_metrics()
    record_snapshot(conn, m, repo_root="/tmp")
    conn.commit()
    snaps = fetch_snapshots(conn)
    assert len(snaps) == 1
    assert snaps[0]["neuron_count"] == 100
    assert snaps[0]["coupling"] == 0.25


def test_fetch_latest_snapshot_none():
    conn = _make_db()
    assert fetch_latest_snapshot(conn) is None


def test_fetch_latest_snapshot_returns_newest():
    conn = _make_db()
    m = _sample_metrics()
    record_snapshot(conn, m, repo_root="/tmp")
    conn.commit()
    conn.execute(
        "INSERT INTO health_snapshots (build_ts, neuron_count, edge_count) VALUES (?, ?, ?)",
        (int(time.time()) + 10, 200, 600),
    )
    conn.commit()
    latest = fetch_latest_snapshot(conn)
    assert latest is not None
    assert latest["neuron_count"] == 200


def test_fetch_snapshots_respects_limit():
    conn = _make_db()
    m = _sample_metrics()
    for _ in range(5):
        record_snapshot(conn, m, repo_root="/tmp")
        conn.commit()
    snaps = fetch_snapshots(conn, limit=3)
    assert len(snaps) == 3


# ---------------------------------------------------------------------------
# reporter
# ---------------------------------------------------------------------------

def test_format_health_snapshot_contains_metrics():
    m = _sample_metrics()
    text = format_health_snapshot(m, prev=None, ts=int(time.time()), commit="abc1234")
    assert "Coupling" in text
    assert "abc1234" in text
    assert "0.25" in text


def test_format_health_snapshot_with_delta():
    m = _sample_metrics()
    prev = {"coupling": 0.30, "avg_blast": 4.0, "dead_code_pct": 12.0,
            "cohesion": 0.70, "test_surface": 55.0, "drift_velocity": 1.0,
            "hub_concentration": 18.0}
    text = format_health_snapshot(m, prev=prev)
    assert "↓" in text  # coupling went down (good)
    assert "↑" in text  # avg_blast went up


def test_format_history_table_empty():
    text = format_history_table([])
    assert "No health snapshots" in text


def test_format_history_table_populated():
    snaps = [
        {"build_ts": int(time.time()), "commit_hash": "abc", "coupling": 0.2,
         "avg_blast": 5.0, "dead_code_pct": 10.0, "cohesion": 0.8,
         "test_surface": 70.0, "hub_concentration": 15.0,
         "neuron_count": 100, "edge_count": 300},
    ]
    text = format_history_table(snaps)
    assert "abc" in text
    assert "0.200" in text


def test_format_trend_sparkline_empty():
    text = format_trend_sparkline([], "coupling")
    assert "No data" in text


def test_format_trend_sparkline_populated():
    snaps = [
        {"build_ts": i, "coupling": i * 0.1} for i in range(1, 6)
    ]
    text = format_trend_sparkline(snaps, "coupling")
    assert "coupling" in text
    assert "min=" in text


def test_to_export_json_structure():
    m = _sample_metrics()
    prev = {"coupling": 0.30, "avg_blast": 6.0, "dead_code_pct": 12.0,
            "cohesion": 0.65, "test_surface": 55.0, "drift_velocity": 2.0,
            "hub_concentration": 22.0}
    raw = to_export_json(m, prev=prev, ts=1000000, commit="deadbeef")
    data = json.loads(raw)
    assert "current" in data
    assert "delta" in data
    assert "trend" in data
    assert data["current"]["neuron_count"] == 100
    assert data["delta"]["coupling"] < 0  # improved
    assert data["trend"]["coupling"] == "down"


# ---------------------------------------------------------------------------
# _watch_loop
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock, call, patch
from cerebrofy.commands.health import _watch_loop


def _make_stat(mtime: float) -> MagicMock:
    s = MagicMock()
    s.st_mtime = mtime
    return s


def _mock_db(mtimes: list[float]) -> MagicMock:
    db = MagicMock()
    db.stat.side_effect = [_make_stat(m) for m in mtimes]
    return db


def test_watch_loop_renders_on_first_mtime():
    db = _mock_db([1000.0, 1000.0])
    config = MagicMock()

    with patch("cerebrofy.commands.health._render_snapshot") as mock_render, \
         patch("click.clear"), \
         patch("click.echo"), \
         patch("time.sleep", side_effect=[None, KeyboardInterrupt()]):
        _watch_loop(db, config)

    mock_render.assert_called_once_with(db, config)


def test_watch_loop_skips_render_when_mtime_unchanged():
    db = _mock_db([1000.0, 1000.0, 1000.0])
    config = MagicMock()

    with patch("cerebrofy.commands.health._render_snapshot") as mock_render, \
         patch("click.clear"), \
         patch("click.echo"), \
         patch("time.sleep", side_effect=[None, None, KeyboardInterrupt()]):
        _watch_loop(db, config)

    assert mock_render.call_count == 1


def test_watch_loop_rerenders_on_mtime_change():
    db = _mock_db([1000.0, 1000.0, 2000.0])
    config = MagicMock()

    with patch("cerebrofy.commands.health._render_snapshot") as mock_render, \
         patch("click.clear"), \
         patch("click.echo"), \
         patch("time.sleep", side_effect=[None, None, KeyboardInterrupt()]):
        _watch_loop(db, config)

    assert mock_render.call_count == 2


def test_watch_loop_exits_cleanly_on_interrupt():
    db = _mock_db([1000.0])
    config = MagicMock()

    with patch("cerebrofy.commands.health._render_snapshot"), \
         patch("click.clear"), \
         patch("click.echo"), \
         patch("time.sleep", side_effect=KeyboardInterrupt()):
        _watch_loop(db, config)  # must not raise
