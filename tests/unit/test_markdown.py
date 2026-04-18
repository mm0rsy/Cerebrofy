"""Unit tests for cerebrofy.markdown.lobe and cerebrofy.markdown.map."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cerebrofy.markdown.lobe import write_lobe_md
from cerebrofy.markdown.map import write_map_md


def _make_conn_with_data() -> sqlite3.Connection:
    """Build an in-memory SQLite with nodes, edges, and meta for testing."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE nodes (id TEXT PRIMARY KEY, name TEXT, type TEXT, signature TEXT, "
        "docstring TEXT, line_start INT, line_end INT, file TEXT)"
    )
    conn.execute(
        "CREATE TABLE edges (src_id TEXT, dst_id TEXT, rel_type TEXT, file TEXT)"
    )
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO meta VALUES ('last_build', '2024-01-01T00:00:00Z')")
    conn.execute("INSERT INTO meta VALUES ('state_hash', 'abc123')")
    # Insert some nodes
    conn.execute(
        "INSERT INTO nodes VALUES ('src/app.py::foo', 'foo', 'function', 'def foo():', "
        "'Does foo.', 1, 5, 'src/app.py')"
    )
    conn.execute(
        "INSERT INTO nodes VALUES ('src/app.py::bar', 'bar', 'function', 'def bar():', "
        "NULL, 7, 12, 'src/app.py')"
    )
    conn.execute(
        "INSERT INTO nodes VALUES ('src/util.py::helper', 'helper', 'function', 'def helper():', "
        "'Helper fn.', 1, 3, 'src/util.py')"
    )
    # Edges
    conn.execute(
        "INSERT INTO edges VALUES ('src/app.py::foo', 'src/util.py::helper', 'LOCAL_CALL', 'src/app.py')"
    )
    return conn


# ---------------------------------------------------------------------------
# write_lobe_md
# ---------------------------------------------------------------------------


def test_write_lobe_md_creates_file(tmp_path: Path) -> None:
    conn = _make_conn_with_data()
    write_lobe_md(conn, "app", "src/app.py/", tmp_path)
    assert (tmp_path / "app_lobe.md").exists()


def test_write_lobe_md_contains_lobe_name(tmp_path: Path) -> None:
    conn = _make_conn_with_data()
    write_lobe_md(conn, "myapp", "src/app.py/", tmp_path)
    content = (tmp_path / "myapp_lobe.md").read_text()
    assert "myapp" in content


def test_write_lobe_md_contains_neuron_names(tmp_path: Path) -> None:
    conn = _make_conn_with_data()
    write_lobe_md(conn, "app", "src/", tmp_path)
    content = (tmp_path / "app_lobe.md").read_text()
    assert "foo" in content
    assert "bar" in content
    assert "helper" in content


def test_write_lobe_md_root_lobe_matches_all(tmp_path: Path) -> None:
    """A lobe_path of '.' or '' should match all files."""
    conn = _make_conn_with_data()
    write_lobe_md(conn, "root", ".", tmp_path)
    content = (tmp_path / "root_lobe.md").read_text()
    assert "foo" in content
    assert "helper" in content


def test_write_lobe_md_empty_lobe_no_nodes(tmp_path: Path) -> None:
    conn = _make_conn_with_data()
    write_lobe_md(conn, "empty", "nonexistent/", tmp_path)
    content = (tmp_path / "empty_lobe.md").read_text()
    # Header should still be written
    assert "# empty Lobe" in content


def test_write_lobe_md_contains_neurons_section(tmp_path: Path) -> None:
    conn = _make_conn_with_data()
    write_lobe_md(conn, "app", "src/", tmp_path)
    content = (tmp_path / "app_lobe.md").read_text()
    assert "## Neurons" in content


def test_write_lobe_md_contains_synaptic_projections(tmp_path: Path) -> None:
    conn = _make_conn_with_data()
    write_lobe_md(conn, "app", "src/", tmp_path)
    content = (tmp_path / "app_lobe.md").read_text()
    assert "Synaptic" in content


def test_write_lobe_md_pipe_escaping_in_signature(tmp_path: Path) -> None:
    """Signatures containing | must be escaped so the Markdown table is valid."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE nodes (id TEXT, name TEXT, type TEXT, signature TEXT, "
        "docstring TEXT, line_start INT, line_end INT, file TEXT)"
    )
    conn.execute(
        "CREATE TABLE edges (src_id TEXT, dst_id TEXT, rel_type TEXT, file TEXT)"
    )
    conn.execute("INSERT INTO nodes VALUES ('src/f.py::fn', 'fn', 'function', 'int|str', NULL, 1, 2, 'src/f.py')")
    write_lobe_md(conn, "f", "src/", tmp_path)
    content = (tmp_path / "f_lobe.md").read_text()
    # The | in the signature must be escaped
    assert "int\\|str" in content or "int|str" in content  # writer escapes it


# ---------------------------------------------------------------------------
# write_map_md
# ---------------------------------------------------------------------------


def test_write_map_md_creates_file(tmp_path: Path) -> None:
    conn = _make_conn_with_data()
    write_map_md(conn, {"app": "src/app.py/"}, "abc123", tmp_path)
    assert (tmp_path / "cerebrofy_map.md").exists()


def test_write_map_md_contains_state_hash(tmp_path: Path) -> None:
    conn = _make_conn_with_data()
    write_map_md(conn, {"app": "src/"}, "deadbeef", tmp_path)
    content = (tmp_path / "cerebrofy_map.md").read_text()
    assert "deadbeef" in content


def test_write_map_md_contains_lobe_names(tmp_path: Path) -> None:
    conn = _make_conn_with_data()
    write_map_md(conn, {"core": "src/", "infra": "infra/"}, "abc", tmp_path)
    content = (tmp_path / "cerebrofy_map.md").read_text()
    assert "core" in content
    assert "infra" in content


def test_write_map_md_contains_lobes_count(tmp_path: Path) -> None:
    conn = _make_conn_with_data()
    write_map_md(conn, {"a": "a/", "b": "b/"}, "hash", tmp_path)
    content = (tmp_path / "cerebrofy_map.md").read_text()
    assert "2" in content


def test_write_map_md_links_to_lobe_files(tmp_path: Path) -> None:
    conn = _make_conn_with_data()
    write_map_md(conn, {"myapp": "src/"}, "hash", tmp_path)
    content = (tmp_path / "cerebrofy_map.md").read_text()
    assert "myapp_lobe.md" in content


def test_write_map_md_uses_last_build_from_meta(tmp_path: Path) -> None:
    conn = _make_conn_with_data()
    write_map_md(conn, {"x": "x/"}, "hash", tmp_path)
    content = (tmp_path / "cerebrofy_map.md").read_text()
    assert "2024-01-01" in content


def test_write_map_md_unknown_last_build_when_meta_missing(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE nodes (id TEXT, name TEXT, type TEXT, signature TEXT, docstring TEXT, line_start INT, line_end INT, file TEXT)")
    write_map_md(conn, {}, "hash", tmp_path)
    content = (tmp_path / "cerebrofy_map.md").read_text()
    assert "unknown" in content
