"""Unit tests for cerebrofy.session.middleware (Idea #11)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from cerebrofy.db.schema import create_schema
from cerebrofy.session.middleware import (
    SessionMiddleware,
    find_repo_root,
    summarize_result,
)
from cerebrofy.session.recorder import (
    count_events,
    get_session,
    list_events,
    open_sessions_db,
    start_session,
)

CONFIG_TEMPLATE = (
    "lobes:\n  src: src/\ntracked_extensions:\n  - .py\nembedding_model: none\n"
)


def _make_repo(tmp_path: Path, *, record_sessions: bool | None = None) -> Path:
    root = tmp_path / "repo"
    (root / ".cerebrofy" / "db").mkdir(parents=True, exist_ok=True)
    config = CONFIG_TEMPLATE
    if record_sessions is not None:
        config += f"record_sessions: {'true' if record_sessions else 'false'}\n"
    (root / ".cerebrofy" / "config.yaml").write_text(config)
    return root


def _make_index(root: Path) -> None:
    conn = sqlite3.connect(root / ".cerebrofy" / "db" / "cerebrofy.db")
    create_schema(conn, embed_dim=0)
    conn.execute(
        "INSERT INTO nodes VALUES ('a.py::hub','hub','a.py','function',1,5,NULL,NULL,NULL)"
    )
    conn.execute(
        "INSERT INTO nodes VALUES ('a.py::caller','caller','a.py','function',7,9,NULL,NULL,NULL)"
    )
    conn.execute("INSERT INTO edges VALUES ('a.py::caller','a.py::hub','LOCAL_CALL','a.py')")
    conn.commit()
    conn.close()


def _start(root: Path, task: str = "T") -> str:
    conn = open_sessions_db(root / ".cerebrofy")
    try:
        return start_session(conn, task=task).id
    finally:
        conn.close()


def _events(root: Path, session_id: str) -> list[Any]:
    conn = open_sessions_db(root / ".cerebrofy")
    try:
        return list_events(conn, session_id)
    finally:
        conn.close()


def _count_events(root: Path, session_id: str) -> int:
    conn = open_sessions_db(root / ".cerebrofy")
    try:
        return count_events(conn, session_id)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# find_repo_root
# ---------------------------------------------------------------------------

def test_find_repo_root_walks_up_and_handles_files(tmp_path: Path) -> None:
    root = _make_repo(tmp_path)
    nested = root / "src" / "pkg"
    nested.mkdir(parents=True)
    assert find_repo_root(nested) == root
    assert find_repo_root(root) == root
    assert find_repo_root(nested / "mod.py") == root
    plain = tmp_path / "plain"
    plain.mkdir()
    assert find_repo_root(plain) is None


# ---------------------------------------------------------------------------
# summarize_result
# ---------------------------------------------------------------------------

def test_summarize_result_extracts_first_text_and_truncates() -> None:
    result = [SimpleNamespace(text="3 hits"), SimpleNamespace(text="ignored")]
    assert summarize_result(result) == "3 hits"
    long_text = "x" * 2000
    assert summarize_result([SimpleNamespace(text=long_text)]) == "x" * 1000


def test_summarize_result_returns_none_for_non_text_payloads() -> None:
    assert summarize_result([]) is None
    assert summarize_result(None) is None
    assert summarize_result("plain string") is None
    assert summarize_result([SimpleNamespace(text=None)]) is None
    assert summarize_result([SimpleNamespace(text="")]) is None


# ---------------------------------------------------------------------------
# is_recording (opt-in resolution)
# ---------------------------------------------------------------------------

def test_is_recording_override_wins(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, record_sessions=True)
    assert SessionMiddleware(root, enabled=False).is_recording() is False
    assert SessionMiddleware(root, enabled=True).is_recording() is True


def test_is_recording_follows_config_and_missing_file(tmp_path: Path) -> None:
    assert SessionMiddleware(_make_repo(tmp_path, record_sessions=True)).is_recording() is True
    assert SessionMiddleware(_make_repo(tmp_path, record_sessions=False)).is_recording() is False
    bare = tmp_path / "bare"
    bare.mkdir()
    assert SessionMiddleware(bare).is_recording() is False


def test_is_recording_caches_config_by_mtime(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, record_sessions=False)
    mw = SessionMiddleware(root)
    fake_cfg = SimpleNamespace(record_sessions=True)
    with patch("cerebrofy.config.loader.load_config", return_value=fake_cfg) as loader:
        assert mw.is_recording() is True
        assert mw.is_recording() is True  # served from cache
        assert loader.call_count == 1

        # Touch the file → mtime changes → config reloaded.
        config_path = root / ".cerebrofy" / "config.yaml"
        stat = config_path.stat()
        os.utime(config_path, (stat.st_atime + 10, stat.st_mtime + 10))
        assert mw.is_recording() is True
        assert loader.call_count == 2


def test_is_recording_false_when_loader_raises(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, record_sessions=True)
    mw = SessionMiddleware(root)
    with patch("cerebrofy.config.loader.load_config", side_effect=RuntimeError("boom")):
        assert mw.is_recording() is False


# ---------------------------------------------------------------------------
# SessionMiddleware.record
# ---------------------------------------------------------------------------

def test_current_session_none_when_not_recording(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, record_sessions=False)
    session_id = _start(root)
    mw = SessionMiddleware(root)
    assert mw.current_session() is None
    mw.record("search_code", {"query": "x"})
    mw.close()
    assert _count_events(root, session_id) == 0


def test_current_session_none_without_open_session(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, record_sessions=True)
    mw = SessionMiddleware(root)
    assert mw.current_session() is None
    mw.record("search_code", {"query": "x"})  # no active session → no-op
    assert mw.current_session() is None


def test_record_writes_event_with_summary(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, record_sessions=True)
    session_id = _start(root)
    mw = SessionMiddleware(root)
    mw.record("search_code", {"query": "hub"}, [SimpleNamespace(text="3 hits")])
    mw.close()

    events = _events(root, session_id)
    assert len(events) == 1
    assert events[0].tool == "search_code"
    assert events[0].args == {"query": "hub"}
    assert events[0].result_summary == "3 hits"


def test_record_with_index_tracks_neurons(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, record_sessions=True)
    _make_index(root)
    session_id = _start(root)
    mw = SessionMiddleware(root)
    mw.record("cerebrofy_impact", {"target": "hub"})
    mw.close()

    conn = open_sessions_db(root / ".cerebrofy")
    try:
        session = get_session(conn, session_id)
    finally:
        conn.close()
    assert session is not None
    assert session.neurons_touched == ("a.py::hub",)
    assert session.blast_radius_before == 1


def test_record_skips_session_management_tools(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, record_sessions=True)
    session_id = _start(root)
    mw = SessionMiddleware(root)
    for tool in ("cerebrofy_session_start", "cerebrofy_session_end", "cerebrofy_session_show"):
        mw.record(tool, {"task": "x"})
    mw.close()
    assert _events(root, session_id) == []


def test_record_never_raises_when_storage_unavailable(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, record_sessions=True)
    mw = SessionMiddleware(root)
    with patch(
        "cerebrofy.session.middleware.open_sessions_db",
        side_effect=RuntimeError("disk gone"),
    ):
        assert mw.current_session() is None
        mw.record("search_code", {"query": "x"})  # must not raise


def test_record_never_raises_on_unexpected_error(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, record_sessions=True)
    mw = SessionMiddleware(root)
    with patch.object(mw, "current_session", side_effect=RuntimeError("boom")):
        mw.record("search_code", {"query": "x"})  # must not raise


# ---------------------------------------------------------------------------
# Index connection cache
# ---------------------------------------------------------------------------

def test_index_returns_none_without_index_file(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, record_sessions=True)
    mw = SessionMiddleware(root)
    assert mw._index() is None
    mw.close()


def test_index_reopens_after_rewrite(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, record_sessions=True)
    _make_index(root)
    mw = SessionMiddleware(root)
    first = mw._index()
    assert first is not None
    assert mw._index() is first  # unchanged file → cached connection

    import os

    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    db_path.write_bytes(db_path.read_bytes() + b"\n-- rewritten\n")
    stat = db_path.stat()
    os.utime(db_path, (stat.st_atime + 10, stat.st_mtime + 10))

    second = mw._index()
    assert second is not None
    assert second is not first  # fingerprint changed → reopened
    mw.close()


# ---------------------------------------------------------------------------
# Per-request middleware (no global singleton)
# ---------------------------------------------------------------------------

def test_middleware_records_session_event_end_to_end(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, record_sessions=True)
    session_id = _start(root)
    mw = SessionMiddleware(root)
    try:
        mw.record("search_code", {"query": "hub"})
        mw.record("search_code", {"query": "hub2"}, [SimpleNamespace(text="ok")])
    finally:
        mw.close()
    assert _count_events(root, session_id) == 2


def test_middleware_record_noop_outside_repo(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    mw = SessionMiddleware(plain)
    try:
        mw.record("search_code", {"query": "x"})
        assert mw.current_session() is None
    finally:
        mw.close()


def test_middleware_finds_root_from_subdir(tmp_path: Path) -> None:
    root = _make_repo(tmp_path, record_sessions=True)
    subdir = root / "src" / "pkg"
    subdir.mkdir(parents=True)
    session_id = _start(root)
    mw = SessionMiddleware(find_repo_root(subdir))
    try:
        mw.record("get_neuron", {"name": "hub"})
    finally:
        mw.close()
    assert _count_events(root, session_id) == 1
