"""Unit tests for MCP resource helpers (mcp/resources.py)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cerebrofy.mcp.resources import (
    blast_radius_summary,
    current_health,
    entry_points,
    file_neurons,
    filter_resource_entries,
    get_neuron,
    index_fingerprint,
    list_lobe_names,
    list_resource_entries,
    memories_for_neuron,
    neuron_callers,
    neuron_source,
    read_lobe,
    read_map,
    search_resource_results,
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


def test_read_lobe_rejects_path_traversal(tmp_path: Path) -> None:
    _make_docs(tmp_path, lobes=["auth"])
    (tmp_path / "secret_lobe.md").write_text("SECRET", encoding="utf-8")

    try:
        read_lobe("../../secret", tmp_path)
        assert False, "Expected FileNotFoundError"
    except FileNotFoundError as exc:
        assert "not found" in str(exc)


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


# ---------------------------------------------------------------------------
# file_neurons
# ---------------------------------------------------------------------------

def _insert_neuron(
    conn: sqlite3.Connection,
    node_id: str,
    name: str,
    file: str,
    line_start: int = 1,
    line_end: int = 10,
) -> None:
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        (node_id, name, file, "function", line_start, line_end, "", "", ""),
    )


def test_file_neurons_exact_match_ordered_by_line(tmp_path: Path) -> None:
    conn = _make_db()
    _insert_neuron(conn, "a1", "second", "src/auth/tokens.py", line_start=20)
    _insert_neuron(conn, "a2", "first", "src/auth/tokens.py", line_start=5)
    _insert_neuron(conn, "other", "elsewhere", "src/other.py")

    result = file_neurons("src/auth/tokens.py", conn)
    assert [r["name"] for r in result] == ["first", "second"]


def test_file_neurons_suffix_match_when_no_exact(tmp_path: Path) -> None:
    conn = _make_db()
    _insert_neuron(conn, "a1", "validate", "src/auth/tokens.py")

    result = file_neurons("auth/tokens.py", conn)
    assert [r["name"] for r in result] == ["validate"]


def test_file_neurons_normalises_backslashes(tmp_path: Path) -> None:
    conn = _make_db()
    _insert_neuron(conn, "a1", "fn", "src/auth/tokens.py")

    result = file_neurons("src\\auth\\tokens.py", conn)
    assert [r["name"] for r in result] == ["fn"]


def test_file_neurons_underscore_is_literal(tmp_path: Path) -> None:
    conn = _make_db()
    _insert_neuron(conn, "a1", "fn", "src/my_module.py")
    _insert_neuron(conn, "a2", "other", "src/myXmodule.py")

    result = file_neurons("my_module.py", conn)
    assert [r["name"] for r in result] == ["fn"]


def test_file_neurons_returns_empty_for_unknown_file(tmp_path: Path) -> None:
    conn = _make_db()
    assert file_neurons("nope.py", conn) == []


def test_file_neurons_returns_empty_for_empty_path(tmp_path: Path) -> None:
    conn = _make_db()
    assert file_neurons("   ", conn) == []


# ---------------------------------------------------------------------------
# blast_radius_summary
# ---------------------------------------------------------------------------

def test_blast_radius_summary_returns_payload(tmp_path: Path) -> None:
    conn = _make_db()
    _insert_neuron(conn, "t", "validate_token", "auth/tokens.py")
    _insert_neuron(conn, "c1", "login_handler", "src/app.py")
    conn.execute("INSERT INTO edges VALUES (?,?,?,?)", ("c1", "t", "CALLS", ""))

    result = blast_radius_summary("auth/tokens.py::validate_token", conn)
    assert result is not None
    assert result["target_neuron"]["name"] == "validate_token"
    assert any(c["name"] == "login_handler" and c["depth"] == 1 for c in result["callers"])
    assert "risk_score" in result
    assert "risk_label" in result
    assert "summary" in result


def test_blast_radius_summary_returns_none_when_missing(tmp_path: Path) -> None:
    conn = _make_db()
    assert blast_radius_summary("nonexistent", conn) is None


# ---------------------------------------------------------------------------
# neuron_source / neuron_callers
# ---------------------------------------------------------------------------

def test_neuron_source_returns_line_range(tmp_path: Path) -> None:
    src = tmp_path / "pkg"
    src.mkdir()
    (src / "mod.py").write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")

    source = neuron_source(
        {"file": "pkg/mod.py", "line_start": 2, "line_end": 3}, tmp_path
    )
    assert source == "two\nthree"


def test_neuron_source_returns_none_when_file_missing(tmp_path: Path) -> None:
    neuron = {"file": "gone.py", "line_start": 1, "line_end": 2}
    assert neuron_source(neuron, tmp_path) is None


def test_neuron_source_returns_none_without_line_range(tmp_path: Path) -> None:
    assert neuron_source({"file": "gone.py"}, tmp_path) is None


def test_neuron_callers_returns_direct_callers(tmp_path: Path) -> None:
    conn = _make_db()
    _insert_neuron(conn, "t", "validate_token", "auth/tokens.py")
    _insert_neuron(conn, "c1", "login_handler", "src/app.py")
    conn.execute("INSERT INTO edges VALUES (?,?,?,?)", ("c1", "t", "CALLS", ""))

    callers = neuron_callers("auth/tokens.py::validate_token", conn)
    assert callers == [{"name": "login_handler", "file": "src/app.py", "line": 1}]


def test_neuron_callers_returns_empty_for_unknown_neuron(tmp_path: Path) -> None:
    conn = _make_db()
    assert neuron_callers("nope.py::ghost", conn) == []


# ---------------------------------------------------------------------------
# list_resource_entries / filter_resource_entries
# ---------------------------------------------------------------------------

def test_list_resource_entries_contains_static_templates_and_lobes(tmp_path: Path) -> None:
    _make_docs(tmp_path, lobes=["auth", "api"])
    entries = list_resource_entries(tmp_path)
    uris = [e["uri"] for e in entries]

    assert "cerebrofy://graph/map" in uris
    assert "cerebrofy://graph/entry-points" in uris
    assert "cerebrofy://health/current" in uris
    assert "cerebrofy://lobes/auth" in uris
    assert "cerebrofy://lobes/api" in uris
    assert "cerebrofy://neurons/{neuron_id}" in uris
    assert "cerebrofy://neurons/file/{file_path}" in uris
    assert "cerebrofy://neurons/search{?q}" in uris
    assert "cerebrofy://memories/{neuron_id}" in uris
    assert "cerebrofy://blast-radius/{neuron_id}" in uris

    assert sum(1 for e in entries if e["template"]) == 5


def test_list_resource_entries_without_docs_has_no_lobes(tmp_path: Path) -> None:
    entries = list_resource_entries(tmp_path)
    assert all(e["category"] != "lobes" for e in entries)


def test_filter_resource_entries_all_returns_everything(tmp_path: Path) -> None:
    _make_docs(tmp_path, lobes=["auth"])
    entries = list_resource_entries(tmp_path)
    assert filter_resource_entries(entries, "all") == entries
    assert filter_resource_entries(entries, "") == entries


def test_filter_resource_entries_by_category(tmp_path: Path) -> None:
    _make_docs(tmp_path, lobes=["auth"])
    entries = list_resource_entries(tmp_path)

    lobes = filter_resource_entries(entries, "lobes")
    assert [e["uri"] for e in lobes] == ["cerebrofy://lobes/auth"]

    neurons = filter_resource_entries(entries, "neurons")
    assert len(neurons) == 3
    assert all(e["template"] for e in neurons)

    graph = filter_resource_entries(entries, "graph")
    assert [e["uri"] for e in graph] == [
        "cerebrofy://graph/map",
        "cerebrofy://graph/entry-points",
    ]


def test_filter_resource_entries_unknown_filter_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown filter"):
        filter_resource_entries([], "bogus")


# ---------------------------------------------------------------------------
# index_fingerprint
# ---------------------------------------------------------------------------

def test_index_fingerprint_all_none_when_missing(tmp_path: Path) -> None:
    assert index_fingerprint(tmp_path) == (None, None, None)


def test_index_fingerprint_changes_when_db_changes(tmp_path: Path) -> None:
    db_dir = tmp_path / ".cerebrofy" / "db"
    db_dir.mkdir(parents=True)
    db = db_dir / "cerebrofy.db"
    db.write_text("v1", encoding="utf-8")

    before = index_fingerprint(tmp_path)
    assert before[0] is not None
    db.write_text("version-2-longer-content", encoding="utf-8")
    after = index_fingerprint(tmp_path)
    assert before != after
    assert after[0] != before[0]


def test_index_fingerprint_changes_when_docs_change(tmp_path: Path) -> None:
    _make_docs(tmp_path, lobes=["auth"])
    before = index_fingerprint(tmp_path)
    assert before[2] is not None

    (tmp_path / "docs" / "cerebrofy" / "api_lobe.md").write_text("# api\n", encoding="utf-8")
    after = index_fingerprint(tmp_path)
    assert before != after
    assert before[2] != after[2]


def test_index_fingerprint_detects_memories_db(tmp_path: Path) -> None:
    db_dir = tmp_path / ".cerebrofy" / "db"
    db_dir.mkdir(parents=True)
    before = index_fingerprint(tmp_path)
    (db_dir / "memories.db").write_text("memories", encoding="utf-8")
    after = index_fingerprint(tmp_path)
    assert before != after
    assert after[1] is not None


# ---------------------------------------------------------------------------
# search_resource_results
# ---------------------------------------------------------------------------

def _write_config(tmp_path: Path) -> None:
    config_dir = tmp_path / ".cerebrofy"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(
        "embedding_model: local\n"
        "lobes:\n  app: src/\n"
        "tracked_extensions: [.py]\n",
        encoding="utf-8",
    )


def test_search_resource_results_shapes_hits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path)
    from cerebrofy.search import hybrid as hybrid_mod
    from cerebrofy.search.hybrid import MatchedNeuron

    neuron = MatchedNeuron(
        id="src/app.py::main",
        name="main",
        type="function",
        file="src/app.py",
        line_start=1,
        line_end=10,
        signature="def main()",
        docstring="Entry point.",
        similarity=0.9,
    )
    seen: dict[str, Any] = {}

    def fake_search(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return SimpleNamespace(matched_neurons=[neuron])

    monkeypatch.setattr(hybrid_mod, "embed_query", lambda query, model: [0.1, 0.2])
    monkeypatch.setattr(hybrid_mod, "hybrid_search", fake_search)

    results = search_resource_results("entry point", tmp_path, top_k=5)

    assert results == [{
        "id": "src/app.py::main",
        "name": "main",
        "type": "function",
        "file": "src/app.py",
        "line": 1,
        "similarity": 0.9,
        "summary": "Entry point.",
    }]
    assert seen["query"] == "entry point"
    assert seen["top_k"] == 5
    assert seen["repo_root"] == tmp_path
    assert seen["db_path"] == tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"


def test_search_resource_results_falls_back_to_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path)
    from cerebrofy.search import hybrid as hybrid_mod
    from cerebrofy.search.hybrid import MatchedNeuron

    neuron = MatchedNeuron(
        id="src/app.py::helper",
        name="helper",
        type="function",
        file="src/app.py",
        line_start=None,
        line_end=None,
        signature="def helper(x: int) -> str",
        docstring=None,
        similarity=0.0,
    )

    monkeypatch.setattr(hybrid_mod, "embed_query", lambda query, model: [0.1])
    monkeypatch.setattr(
        hybrid_mod, "hybrid_search", lambda **kwargs: SimpleNamespace(matched_neurons=[neuron])
    )

    results = search_resource_results("helper", tmp_path)
    assert results[0]["summary"] == "def helper(x: int) -> str"
    assert results[0]["line"] is None


# ---------------------------------------------------------------------------
# Server wiring (requires the optional `mcp` extra)
# ---------------------------------------------------------------------------

def test_cerebrofy_server_advertises_subscribe_when_wired() -> None:
    pytest.importorskip("mcp")
    from mcp.server import NotificationOptions

    from cerebrofy.mcp.server import CerebrofyMCPServer

    app = CerebrofyMCPServer("test")
    caps = app.get_capabilities(NotificationOptions(resources_changed=True), {})
    assert caps.resources is None  # no resource handlers registered yet

    @app.list_resources()  # type: ignore[no-untyped-call,untyped-decorator]
    async def _list() -> list[object]:
        return []

    @app.subscribe_resource()  # type: ignore[no-untyped-call,untyped-decorator]
    async def _subscribe(uri: object) -> None:
        pass

    caps = app.get_capabilities(NotificationOptions(resources_changed=True), {})
    assert caps.resources is not None
    assert caps.resources.subscribe is True
    assert caps.resources.listChanged is True


class _FakeSession:
    def __init__(self) -> None:
        self.updated: list[str] = []
        self.list_changed = 0

    async def send_resource_updated(self, uri: object) -> None:
        self.updated.append(str(uri))

    async def send_resource_list_changed(self) -> None:
        self.list_changed += 1


def test_notify_resource_changes_sends_updated_for_subscriptions() -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp.server import _notify_resource_changes

    session = _FakeSession()
    subs = {"cerebrofy://graph/map", "cerebrofy://health/current"}
    asyncio.run(
        _notify_resource_changes(session, subs, db_changed=True, docs_changed=False)
    )
    assert session.updated == [
        "cerebrofy://graph/map",
        "cerebrofy://health/current",
    ]
    assert session.list_changed == 0


def test_notify_resource_changes_sends_list_changed_on_docs_change() -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp.server import _notify_resource_changes

    session = _FakeSession()
    asyncio.run(
        _notify_resource_changes(session, set(), db_changed=False, docs_changed=True)
    )
    assert session.updated == []
    assert session.list_changed == 1


def test_notify_resource_changes_noop_when_nothing_subscribed() -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp.server import _notify_resource_changes

    session = _FakeSession()
    asyncio.run(
        _notify_resource_changes(session, set(), db_changed=True, docs_changed=False)
    )
    assert session.updated == []
    assert session.list_changed == 0


def test_start_index_watcher_is_noop_without_request_context() -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp.server import _start_index_watcher

    class _NoContextApp:
        @property
        def request_context(self) -> object:
            raise LookupError("no request context")

    state: dict[str, object] = {}
    _start_index_watcher(_NoContextApp(), set(), state)
    assert state.get("started") is not True


def test_start_index_watcher_starts_task_and_resets_on_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp import server as server_mod

    monkeypatch.chdir(tmp_path)
    db_dir = tmp_path / ".cerebrofy" / "db"
    db_dir.mkdir(parents=True)
    (tmp_path / ".cerebrofy" / "config.yaml").write_text("lobes: {}\n", encoding="utf-8")
    (db_dir / "cerebrofy.db").write_text("v1", encoding="utf-8")

    class _App:
        class request_context:
            session = _FakeSession()

    state: dict[str, Any] = {}

    async def scenario() -> None:
        server_mod._start_index_watcher(_App(), set(), state)
        assert state["started"] is True
        task = state["task"]
        assert task is not None
        # Second call is a no-op while the watcher is alive.
        server_mod._start_index_watcher(_App(), set(), state)
        assert state["task"] is task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0)  # let the done-callback run

    asyncio.run(scenario())
    assert state["started"] is False


def test_watch_index_changes_emits_updated_on_db_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp import server as server_mod

    monkeypatch.setattr(server_mod, "_INDEX_WATCH_INTERVAL_SECONDS", 0.01)

    db_dir = tmp_path / ".cerebrofy" / "db"
    db_dir.mkdir(parents=True)
    db = db_dir / "cerebrofy.db"
    db.write_text("v1", encoding="utf-8")

    session = _FakeSession()
    subscriptions = {"cerebrofy://graph/map"}

    async def scenario() -> None:
        task = asyncio.create_task(
            server_mod._watch_index_changes(session, subscriptions, tmp_path)
        )
        try:
            await asyncio.sleep(0.05)
            db.write_text("v2-longer-content", encoding="utf-8")
            for _ in range(300):
                if session.updated:
                    break
                await asyncio.sleep(0.01)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    asyncio.run(scenario())
    assert session.updated == ["cerebrofy://graph/map"]
    assert session.list_changed == 0


def test_watch_index_changes_emits_list_changed_on_docs_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp import server as server_mod

    monkeypatch.setattr(server_mod, "_INDEX_WATCH_INTERVAL_SECONDS", 0.01)

    docs = tmp_path / "docs" / "cerebrofy"
    docs.mkdir(parents=True)
    (docs / "auth_lobe.md").write_text("# auth\n", encoding="utf-8")

    session = _FakeSession()
    subscriptions = {"cerebrofy://lobes/auth"}

    async def scenario() -> None:
        task = asyncio.create_task(
            server_mod._watch_index_changes(session, subscriptions, tmp_path)
        )
        try:
            await asyncio.sleep(0.05)
            (docs / "api_lobe.md").write_text("# api\n", encoding="utf-8")
            for _ in range(300):
                if session.list_changed:
                    break
                await asyncio.sleep(0.01)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    asyncio.run(scenario())
    assert session.list_changed == 1
    assert session.updated == ["cerebrofy://lobes/auth"]


def test_watch_index_changes_stops_quietly_when_notify_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp import server as server_mod

    monkeypatch.setattr(server_mod, "_INDEX_WATCH_INTERVAL_SECONDS", 0.01)

    class _BrokenSession:
        async def send_resource_updated(self, uri: object) -> None:
            raise RuntimeError("client connection is gone")

        async def send_resource_list_changed(self) -> None:
            raise AssertionError("should not be called")

    db_dir = tmp_path / ".cerebrofy" / "db"
    db_dir.mkdir(parents=True)
    db = db_dir / "cerebrofy.db"
    db.write_text("v1", encoding="utf-8")

    async def scenario() -> None:
        task = asyncio.create_task(
            server_mod._watch_index_changes(_BrokenSession(), {"cerebrofy://graph/map"}, tmp_path)
        )
        await asyncio.sleep(0.05)
        db.write_text("v2-longer-content", encoding="utf-8")
        # The watcher returns (no exception) once sending fails.
        await asyncio.wait_for(task, timeout=5.0)

    asyncio.run(scenario())


def test_handle_list_resources_returns_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp.server import _handle_list_resources

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".cerebrofy").mkdir()
    (tmp_path / ".cerebrofy" / "config.yaml").write_text("lobes: {}\n", encoding="utf-8")
    _make_docs(tmp_path, lobes=["auth"])

    result = _handle_list_resources({})
    payload = json.loads(result[0].text)
    assert payload["count"] > 0
    assert any(r["uri"] == "cerebrofy://lobes/auth" for r in payload["resources"])


def test_handle_list_resources_honours_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp.server import _handle_list_resources

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".cerebrofy").mkdir()
    (tmp_path / ".cerebrofy" / "config.yaml").write_text("lobes: {}\n", encoding="utf-8")
    _make_docs(tmp_path, lobes=["auth", "api"])

    result = _handle_list_resources({"filter": "lobes"})
    payload = json.loads(result[0].text)
    assert payload["count"] == 2
    assert all(r["category"] == "lobes" for r in payload["resources"])


def test_handle_list_resources_rejects_unknown_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp.server import _handle_list_resources

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".cerebrofy").mkdir()
    (tmp_path / ".cerebrofy" / "config.yaml").write_text("lobes: {}\n", encoding="utf-8")

    result = _handle_list_resources({"filter": "bogus"})
    assert "[error]" in result[0].text
    assert "Unknown filter" in result[0].text


def test_handle_list_resources_no_index_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp.server import _handle_list_resources

    monkeypatch.chdir(tmp_path)
    result = _handle_list_resources({})
    assert "[NO_INDEX]" in result[0].text
