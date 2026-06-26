"""Unit tests for MCP resource helpers (mcp/resources.py)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

from cerebrofy.mcp.resources import (
    current_health,
    entry_points,
    get_neuron,
    list_lobe_names,
    memories_for_neuron,
    read_lobe,
    read_map,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY, name TEXT, file TEXT,
            type TEXT, line_start INTEGER, line_end INTEGER,
            signature TEXT, docstring TEXT, hash TEXT
        );
        CREATE TABLE edges (
            src_id TEXT, dst_id TEXT, rel_type TEXT, file TEXT,
            PRIMARY KEY (src_id, dst_id, rel_type)
        );
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO meta VALUES ('schema_version', '1');
    """)
    return conn


def _make_docs(root: Path, lobes: list[str] | None = None) -> None:
    docs = root / "docs" / "cerebrofy"
    docs.mkdir(parents=True)
    (docs / "cerebrofy_map.md").write_text("# Map\n\nAll neurons here.", encoding="utf-8")
    for lobe in (lobes or []):
        (docs / f"{lobe}_lobe.md").write_text(f"# {lobe} lobe\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# read_map
# ---------------------------------------------------------------------------

def test_read_map_returns_content(tmp_path: Path) -> None:
    _make_docs(tmp_path, lobes=["auth"])
    content = read_map(tmp_path)
    assert "# Map" in content


def test_read_map_raises_when_missing(tmp_path: Path) -> None:
    (tmp_path / "docs" / "cerebrofy").mkdir(parents=True)
    try:
        read_map(tmp_path)
        assert False, "Expected FileNotFoundError"
    except FileNotFoundError as exc:
        assert "cerebrofy build" in str(exc)


# ---------------------------------------------------------------------------
# read_lobe
# ---------------------------------------------------------------------------

def test_read_lobe_returns_content(tmp_path: Path) -> None:
    _make_docs(tmp_path, lobes=["auth"])
    content = read_lobe("auth", tmp_path)
    assert "auth lobe" in content


def test_read_lobe_raises_when_missing(tmp_path: Path) -> None:
    _make_docs(tmp_path)
    try:
        read_lobe("nonexistent", tmp_path)
        assert False, "Expected FileNotFoundError"
    except FileNotFoundError as exc:
        assert "nonexistent" in str(exc)


# ---------------------------------------------------------------------------
# list_lobe_names
# ---------------------------------------------------------------------------

def test_list_lobe_names_returns_sorted(tmp_path: Path) -> None:
    _make_docs(tmp_path, lobes=["billing", "auth", "core"])
    names = list_lobe_names(tmp_path)
    assert names == ["auth", "billing", "core"]


def test_list_lobe_names_returns_empty_when_docs_missing(tmp_path: Path) -> None:
    assert list_lobe_names(tmp_path) == []


def test_list_lobe_names_excludes_non_lobe_files(tmp_path: Path) -> None:
    docs = tmp_path / "docs" / "cerebrofy"
    docs.mkdir(parents=True)
    (docs / "auth_lobe.md").write_text("auth")
    (docs / "cerebrofy_map.md").write_text("map")   # must not be returned
    (docs / "readme.md").write_text("readme")        # must not be returned
    names = list_lobe_names(tmp_path)
    assert names == ["auth"]


# ---------------------------------------------------------------------------
# entry_points
# ---------------------------------------------------------------------------

def test_entry_points_returns_nodes_with_no_incoming_edges(tmp_path: Path) -> None:
    conn = _make_db()
    # entry: has outgoing edge, no incoming
    conn.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
                 ("ep", "main", "src/main.py", "function", 1, 10, "", "", ""))
    # downstream: called by entry
    conn.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
                 ("ds", "helper", "src/helper.py", "function", 1, 5, "", "", ""))
    conn.execute("INSERT INTO edges VALUES (?,?,?,?)", ("ep", "ds", "CALLS", ""))

    result = entry_points(conn)
    assert len(result) == 1
    assert result[0]["name"] == "main"


def test_entry_points_excludes_isolated_nodes(tmp_path: Path) -> None:
    conn = _make_db()
    conn.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
                 ("iso", "orphan", "src/x.py", "function", 1, 5, "", "", ""))
    # no edges at all — not an entry point (no outgoing edges either)
    result = entry_points(conn)
    assert result == []


def test_entry_points_excludes_modules(tmp_path: Path) -> None:
    conn = _make_db()
    conn.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
                 ("mod", "__init__", "src/__init__.py", "module", 1, 1, "", "", ""))
    conn.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
                 ("fn", "fn", "src/x.py", "function", 1, 5, "", "", ""))
    conn.execute("INSERT INTO edges VALUES (?,?,?,?)", ("mod", "fn", "CALLS", ""))
    result = entry_points(conn)
    assert all(r["type"] != "module" for r in result)


def test_entry_points_excludes_runtime_boundary_as_incoming(tmp_path: Path) -> None:
    conn = _make_db()
    # "caller" reaches "target" only via RUNTIME_BOUNDARY — target should still be entry point
    conn.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
                 ("target", "handle_request", "src/app.py", "function", 1, 10, "", "", ""))
    conn.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
                 ("caller", "wsgi_app", "src/wsgi.py", "function", 1, 5, "", "", ""))
    conn.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
                 ("leaf", "leaf_fn", "src/leaf.py", "function", 1, 3, "", "", ""))
    conn.execute("INSERT INTO edges VALUES (?,?,?,?)", ("caller", "target", "RUNTIME_BOUNDARY", ""))
    conn.execute("INSERT INTO edges VALUES (?,?,?,?)", ("target", "leaf", "CALLS", ""))

    result = entry_points(conn)
    names = [r["name"] for r in result]
    assert "handle_request" in names  # RUNTIME_BOUNDARY incoming doesn't disqualify


# ---------------------------------------------------------------------------
# get_neuron
# ---------------------------------------------------------------------------

def test_get_neuron_returns_dict(tmp_path: Path) -> None:
    conn = _make_db()
    conn.execute("INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
                 ("auth::validate", "validate", "auth/tokens.py", "function",
                  10, 25, "def validate(t)", "Validate token.", "abc123"))
    result = get_neuron("auth::validate", conn)
    assert result is not None
    assert result["name"] == "validate"
    assert result["file"] == "auth/tokens.py"
    assert result["signature"] == "def validate(t)"


def test_get_neuron_returns_none_when_missing(tmp_path: Path) -> None:
    conn = _make_db()
    assert get_neuron("nonexistent::fn", conn) is None


# ---------------------------------------------------------------------------
# memories_for_neuron
# ---------------------------------------------------------------------------

def test_memories_for_neuron_returns_empty_when_no_db(tmp_path: Path) -> None:
    result = memories_for_neuron("auth::validate", tmp_path)
    assert result == []


def test_memories_for_neuron_returns_list(tmp_path: Path) -> None:
    mock_mem = MagicMock()
    mock_mem.id = "m1"
    mock_mem.neuron_id = "auth::validate"
    mock_mem.lobe = "auth"
    mock_mem.type = "warning"
    mock_mem.title = "Test warning"
    mock_mem.body = "Be careful"
    mock_mem.author = "agent:test"
    mock_mem.created_ts = 1700000000
    mock_mem.tags = ("warning",)
    mock_mem.decay_score = 1.0
    mock_mem.status = "active"

    # Create the memories.db path so the existence check passes
    db_dir = tmp_path / ".cerebrofy" / "db"
    db_dir.mkdir(parents=True)
    (db_dir / "memories.db").touch()

    with patch("cerebrofy.memory.store.open_memories_db") as mock_open, \
         patch("cerebrofy.memory.store.list_memories", return_value=[mock_mem]):
        mock_open.return_value = MagicMock()
        # dataclasses.asdict won't work on a MagicMock — patch it too
        with patch("dataclasses.asdict", return_value={"id": "m1", "title": "Test warning"}):
            result = memories_for_neuron("auth::validate", tmp_path)
    assert isinstance(result, list)


def test_memories_for_neuron_swallows_exception(tmp_path: Path) -> None:
    db_dir = tmp_path / ".cerebrofy" / "db"
    db_dir.mkdir(parents=True)
    (db_dir / "memories.db").touch()

    with patch("cerebrofy.memory.store.open_memories_db", side_effect=RuntimeError("db error")):
        result = memories_for_neuron("auth::validate", tmp_path)
    assert result == []


# ---------------------------------------------------------------------------
# current_health
# ---------------------------------------------------------------------------

def test_current_health_returns_none_when_no_snapshots(tmp_path: Path) -> None:
    conn = _make_db()
    with patch("cerebrofy.health.snapshot.fetch_latest_snapshot", return_value=None):
        result = current_health(conn)
    assert result is None


def test_current_health_returns_snapshot(tmp_path: Path) -> None:
    conn = _make_db()
    snapshot = {"id": 1, "build_ts": 1700000000, "neuron_count": 42}
    with patch("cerebrofy.health.snapshot.fetch_latest_snapshot", return_value=snapshot):
        result = current_health(conn)
    assert result == snapshot
