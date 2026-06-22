"""Unit tests for epistemic/state.py — confidence factors, caveats, injection."""

from __future__ import annotations

import json
import sqlite3

from cerebrofy.epistemic.state import (
    EpistemicState,
    _build_caveats,
    _dynamic_dispatch_count,
    _graph_age_hours,
    _missing_test_paths,
    _recommendation,
    _total_neurons,
    compute_epistemic_state,
    inject_epistemic,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(last_build_offset_hours: float = 0.0) -> sqlite3.Connection:
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
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE file_hashes (file TEXT PRIMARY KEY, hash TEXT NOT NULL);
    """)
    import datetime
    if last_build_offset_hours == 0.0:
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
    else:
        dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=last_build_offset_hours)
        ts = dt.isoformat()
    conn.execute("INSERT INTO meta VALUES ('schema_version', '1')")
    conn.execute("INSERT INTO meta VALUES ('last_build', ?)", (ts,))
    conn.commit()
    return conn


def _insert_node(conn: sqlite3.Connection, nid: str, name: str, file: str, sig: str = "") -> None:
    conn.execute(
        "INSERT INTO nodes (id, name, file, signature) VALUES (?, ?, ?, ?)",
        (nid, name, file, sig),
    )


def _insert_edge(conn: sqlite3.Connection, src: str, dst: str, rel: str = "LOCAL_CALL") -> None:
    conn.execute("INSERT INTO edges (src_id, dst_id, rel_type) VALUES (?, ?, ?)", (src, dst, rel))


EXTENSIONS = [".py"]


# ---------------------------------------------------------------------------
# _graph_age_hours
# ---------------------------------------------------------------------------

def test_graph_age_fresh():
    conn = _make_db(last_build_offset_hours=0.0)
    age = _graph_age_hours(conn)
    assert 0.0 <= age < 0.05  # under 3 minutes


def test_graph_age_24h():
    conn = _make_db(last_build_offset_hours=24.0)
    age = _graph_age_hours(conn)
    assert 23.9 < age < 24.1


def test_graph_age_no_meta():
    conn = sqlite3.connect(":memory:")
    conn.executescript("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);")
    age = _graph_age_hours(conn)
    assert age == 0.0


# ---------------------------------------------------------------------------
# _total_neurons
# ---------------------------------------------------------------------------

def test_total_neurons_empty():
    conn = _make_db()
    assert _total_neurons(conn) == 0


def test_total_neurons_count():
    conn = _make_db()
    _insert_node(conn, "a", "a", "src/foo.py")
    _insert_node(conn, "b", "b", "src/bar.py")
    assert _total_neurons(conn) == 2


# ---------------------------------------------------------------------------
# _dynamic_dispatch_count
# ---------------------------------------------------------------------------

def test_dynamic_dispatch_none():
    conn = _make_db()
    _insert_node(conn, "a", "a", "src/foo.py", sig="def a(x): return x")
    assert _dynamic_dispatch_count(conn) == 0


def test_dynamic_dispatch_detected():
    conn = _make_db()
    _insert_node(conn, "a", "a", "src/foo.py", sig="getattr(obj, name)")
    _insert_node(conn, "b", "b", "src/bar.py", sig="def b(): pass")
    assert _dynamic_dispatch_count(conn) == 1


def test_dynamic_dispatch_vars():
    conn = _make_db()
    _insert_node(conn, "a", "a", "src/foo.py", sig="vars(self)")
    assert _dynamic_dispatch_count(conn) == 1


# ---------------------------------------------------------------------------
# _missing_test_paths
# ---------------------------------------------------------------------------

def test_missing_test_paths_all_covered():
    conn = _make_db()
    _insert_node(conn, "t", "test_foo", "tests/test_foo.py")
    _insert_node(conn, "impl", "impl", "src/foo.py")
    _insert_edge(conn, "t", "impl")
    assert _missing_test_paths(conn) == 0


def test_missing_test_paths_none_covered():
    conn = _make_db()
    _insert_node(conn, "t", "test_foo", "tests/test_foo.py")
    _insert_node(conn, "impl", "impl", "src/foo.py")
    # no edge from t to impl
    assert _missing_test_paths(conn) == 1


def test_missing_test_paths_no_tests():
    conn = _make_db()
    _insert_node(conn, "impl", "impl", "src/foo.py")
    # no test neurons at all
    assert _missing_test_paths(conn) == 1


def test_missing_test_paths_runtime_boundary_excluded():
    conn = _make_db()
    _insert_node(conn, "t", "test_foo", "tests/test_foo.py")
    _insert_node(conn, "impl", "impl", "src/foo.py")
    _insert_edge(conn, "t", "impl", "RUNTIME_BOUNDARY")
    # RUNTIME_BOUNDARY edges don't count for test coverage
    assert _missing_test_paths(conn) == 1


# ---------------------------------------------------------------------------
# _build_caveats
# ---------------------------------------------------------------------------

def test_caveats_empty_when_fresh():
    caveats = _build_caveats(0.5, 0, 100, [], 0, 0)
    assert caveats == []


def test_caveats_stale_graph():
    caveats = _build_caveats(48.0, 5, 100, [], 0, 0)
    assert any("48h" in c for c in caveats)
    assert any("5 neuron" in c for c in caveats)


def test_caveats_unindexed_language():
    caveats = _build_caveats(0.0, 0, 100, ["ts", "go"], 0, 0)
    assert any("ts" in c for c in caveats)


def test_caveats_dynamic_dispatch():
    caveats = _build_caveats(0.0, 0, 100, [], 3, 0)
    assert any("dynamic dispatch" in c for c in caveats)


def test_caveats_missing_tests():
    caveats = _build_caveats(0.0, 0, 100, [], 0, 42)
    assert any("42" in c for c in caveats)


# ---------------------------------------------------------------------------
# _recommendation
# ---------------------------------------------------------------------------

def test_recommendation_fresh():
    r = _recommendation(0.9, 1.0, 0)
    assert "reliable" in r


def test_recommendation_low_confidence():
    r = _recommendation(0.6, 30.0, 10)
    assert "update" in r.lower() or "build" in r.lower()


def test_recommendation_critical():
    r = _recommendation(0.4, 200.0, 50)
    assert "build" in r.lower()


# ---------------------------------------------------------------------------
# compute_epistemic_state — confidence formula
# ---------------------------------------------------------------------------

def test_confidence_fresh_index(tmp_path):
    conn = _make_db(last_build_offset_hours=0.0)
    _insert_node(conn, "a", "a", "src/foo.py")
    state = compute_epistemic_state(conn, EXTENSIONS, tmp_path)
    # Fresh index with no changes → high confidence
    assert state.overall_confidence >= 0.9
    assert state.graph_age_hours < 0.1


def test_confidence_stale_index(tmp_path):
    conn = _make_db(last_build_offset_hours=72.0)
    _insert_node(conn, "a", "a", "src/foo.py")
    state = compute_epistemic_state(conn, EXTENSIONS, tmp_path)
    # 72h old → age_factor = max(0.5, 1 - 72/168) = 0.571
    assert state.overall_confidence < 0.9
    assert state.graph_age_hours > 71.0


def test_confidence_minimum_floor(tmp_path):
    conn = _make_db(last_build_offset_hours=500.0)  # very stale
    _insert_node(conn, "a", "a", "src/foo.py")
    state = compute_epistemic_state(conn, EXTENSIONS, tmp_path)
    assert state.overall_confidence >= 0.5


def test_confidence_unindexed_language(tmp_path):
    # Create a .ts file in tmp_path so _unindexed_languages detects it
    (tmp_path / "app.ts").write_text("const x = 1;")
    conn = _make_db(last_build_offset_hours=0.0)
    _insert_node(conn, "a", "a", "src/foo.py")
    state = compute_epistemic_state(conn, [".py"], tmp_path)
    assert "ts" in state.unindexed_languages
    assert state.overall_confidence < 1.0


def test_confidence_dynamic_dispatch(tmp_path):
    conn = _make_db(last_build_offset_hours=0.0)
    _insert_node(conn, "a", "a", "src/foo.py", sig="getattr(obj, name)")
    state = compute_epistemic_state(conn, EXTENSIONS, tmp_path)
    assert state.dynamic_dispatch_count >= 1
    assert state.overall_confidence <= 0.9  # dispatch_factor = 0.9


def test_confidence_empty_db(tmp_path):
    conn = _make_db(last_build_offset_hours=0.0)
    state = compute_epistemic_state(conn, EXTENSIONS, tmp_path)
    assert state.neurons_changed_since_build == 0
    assert state.overall_confidence >= 0.5  # still valid


def test_epistemic_state_to_dict(tmp_path):
    conn = _make_db()
    state = compute_epistemic_state(conn, EXTENSIONS, tmp_path)
    d = state.to_dict()
    assert "overall_confidence" in d
    assert "graph_age_hours" in d
    assert "caveats" in d
    assert "recommendation" in d


def test_epistemic_state_warning_field(tmp_path):
    conn = _make_db(last_build_offset_hours=100.0)
    _insert_node(conn, "a", "a", "src/foo.py")
    state = compute_epistemic_state(conn, EXTENSIONS, tmp_path)
    d = state.to_dict()
    # Confidence will be below 0.7 for a 100h-old index
    assert "warning" in d or "error" in d


def test_epistemic_no_warning_when_fresh(tmp_path):
    conn = _make_db(last_build_offset_hours=0.0)
    _insert_node(conn, "a", "a", "src/foo.py")
    state = compute_epistemic_state(conn, EXTENSIONS, tmp_path)
    d = state.to_dict()
    assert "warning" not in d
    assert "error" not in d


# ---------------------------------------------------------------------------
# EpistemicState.neuron_count property (via state fields)
# ---------------------------------------------------------------------------

def test_epistemic_state_fields(tmp_path):
    conn = _make_db()
    _insert_node(conn, "t", "test_a", "tests/test_a.py")
    _insert_node(conn, "b", "impl", "src/foo.py")
    state = compute_epistemic_state(conn, EXTENSIONS, tmp_path)
    assert state.memory_stale_count == 0  # not yet implemented
    assert state.missing_test_paths == 1  # impl not reachable from test_a


# ---------------------------------------------------------------------------
# inject_epistemic
# ---------------------------------------------------------------------------

def _sample_state() -> EpistemicState:
    return EpistemicState(
        graph_age_hours=2.5,
        neurons_changed_since_build=0,
        unindexed_languages=(),
        dynamic_dispatch_count=0,
        memory_stale_count=0,
        missing_test_paths=5,
        overall_confidence=0.95,
        caveats=(),
        recommendation="Index is fresh — results are reliable",
    )


def test_inject_epistemic_into_json():
    payload = json.dumps({"results": [{"name": "foo"}], "count": 1})
    state = _sample_state()
    out = inject_epistemic(payload, state)
    data = json.loads(out)
    assert "epistemic" in data
    assert data["epistemic"]["overall_confidence"] == 0.95
    assert data["results"][0]["name"] == "foo"  # original content preserved


def test_inject_epistemic_into_markdown():
    text = "## Blast Radius\n\nfoo is called by bar."
    state = _sample_state()
    out = inject_epistemic(text, state)
    assert "Blast Radius" in out
    assert "confidence" in out.lower()


def test_inject_epistemic_preserves_invalid_json():
    text = "plain text response"
    state = _sample_state()
    out = inject_epistemic(text, state)
    assert "plain text response" in out
    assert "confidence" in out.lower()


def test_confidence_line_high():
    state = _sample_state()
    line = state.confidence_line()
    assert "95%" in line
    assert "✅" in line


def test_confidence_line_low():
    state = EpistemicState(
        graph_age_hours=80.0,
        neurons_changed_since_build=20,
        unindexed_languages=("ts",),
        dynamic_dispatch_count=5,
        memory_stale_count=0,
        missing_test_paths=50,
        overall_confidence=0.55,
        caveats=("Graph is 80h old",),
        recommendation="Run cerebrofy build",
    )
    line = state.confidence_line()
    assert "⚠️" in line


def test_memory_stale_count_no_db(tmp_path):
    from cerebrofy.epistemic.state import _memory_stale_count
    assert _memory_stale_count(tmp_path) == 0


def test_memory_stale_count_with_stale(tmp_path):
    from cerebrofy.epistemic.state import _memory_stale_count
    from cerebrofy.memory.store import Memory, open_memories_db, write_memory

    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True)
    conn = open_memories_db(cerebrofy_dir)
    m = Memory(
        id="s1", neuron_id=None, lobe=None, type="warning",
        title="Old", body="Stale", author=None,
        created_ts=1_000_000, tags=(), decay_score=0.05, status="stale",
    )
    write_memory(conn, m, [0.1] * 384)
    conn.commit()
    conn.close()
    assert _memory_stale_count(tmp_path) == 1
