"""Unit tests for security/vuln_scanner.py."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cerebrofy.analysis.impact import bfs_callers
from cerebrofy.security.vuln_scanner import (
    compute_vuln_blast_radius,
    find_package_callers,
    read_pinned_version,
    _is_trust_boundary,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path) -> sqlite3.Connection:
    """In-memory DB with nodes + edges schema for testing."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY, name TEXT, file TEXT,
            type TEXT, line_start INTEGER, line_end INTEGER,
            signature TEXT, docstring TEXT, hash TEXT
        );
        CREATE TABLE edges (
            src_id TEXT, dst_id TEXT, rel_type TEXT NOT NULL, file TEXT,
            PRIMARY KEY (src_id, dst_id, rel_type)
        );
    """)
    return conn


def _add_node(conn: sqlite3.Connection, id: str, name: str, file: str, line: int = 1) -> None:
    conn.execute(
        "INSERT INTO nodes(id, name, file, type, line_start, line_end) VALUES (?,?,?,?,?,?)",
        (id, name, file, "function", line, line + 5),
    )


def _add_edge(conn: sqlite3.Connection, src: str, dst: str, rel: str, file: str = "f.py") -> None:
    conn.execute(
        "INSERT INTO edges(src_id, dst_id, rel_type, file) VALUES (?,?,?,?)",
        (src, dst, rel, file),
    )


# ---------------------------------------------------------------------------
# _is_trust_boundary
# ---------------------------------------------------------------------------

class TestIsTrustBoundary:
    def test_no_incoming_edges_is_boundary(self, db: sqlite3.Connection) -> None:
        _add_node(db, "a", "entry", "api/views.py")
        assert _is_trust_boundary("a", db) is True

    def test_has_caller_not_boundary(self, db: sqlite3.Connection) -> None:
        _add_node(db, "a", "entry", "api/views.py")
        _add_node(db, "b", "caller", "api/router.py")
        _add_edge(db, "b", "a", "LOCAL_CALL")
        assert _is_trust_boundary("a", db) is False


# ---------------------------------------------------------------------------
# find_package_callers
# ---------------------------------------------------------------------------

class TestFindPackageCallers:
    def test_finds_direct_package_call(self, db: sqlite3.Connection) -> None:
        _add_node(db, "utils::fetch", "fetch", "utils/http.py")
        _add_edge(db, "utils::fetch", "external::requests.get", "RUNTIME_BOUNDARY", "utils/http.py")

        callers = find_package_callers("requests", None, db)
        assert len(callers) == 1
        assert callers[0].name == "fetch"
        assert callers[0].call_target == "external::requests.get"

    def test_function_pattern_exact_match(self, db: sqlite3.Connection) -> None:
        _add_node(db, "a", "do_get", "api/client.py")
        _add_node(db, "b", "do_post", "api/client.py")
        _add_edge(db, "a", "external::requests.get", "RUNTIME_BOUNDARY", "api/client.py")
        _add_edge(db, "b", "external::requests.post", "RUNTIME_BOUNDARY", "api/client.py")

        callers = find_package_callers("requests", "requests.get", db)
        assert len(callers) == 1
        assert callers[0].name == "do_get"

    def test_no_match_returns_empty(self, db: sqlite3.Connection) -> None:
        _add_node(db, "a", "fn", "main.py")
        _add_edge(db, "a", "external::httpx.get", "RUNTIME_BOUNDARY", "main.py")
        assert find_package_callers("requests", None, db) == []

    def test_deduplicates_same_src_multiple_calls(self, db: sqlite3.Connection) -> None:
        _add_node(db, "a", "fn", "api/client.py")
        _add_edge(db, "a", "external::requests.get", "RUNTIME_BOUNDARY", "api/client.py")
        _add_edge(db, "a", "external::requests.post", "RUNTIME_BOUNDARY", "api/client.py")

        callers = find_package_callers("requests", None, db)
        assert len(callers) == 1

    def test_trust_boundary_flag_set(self, db: sqlite3.Connection) -> None:
        _add_node(db, "entry::fn", "entry_fn", "api/views.py")
        _add_edge(db, "entry::fn", "external::requests.get", "RUNTIME_BOUNDARY", "api/views.py")

        callers = find_package_callers("requests", None, db)
        assert callers[0].is_trust_boundary is True

    def test_non_trust_boundary_when_has_caller(self, db: sqlite3.Connection) -> None:
        _add_node(db, "utils::fetch", "fetch", "utils/http.py")
        _add_node(db, "api::view", "view", "api/views.py")
        _add_edge(db, "utils::fetch", "external::requests.get", "RUNTIME_BOUNDARY", "utils/http.py")
        _add_edge(db, "api::view", "utils::fetch", "LOCAL_CALL", "api/views.py")

        callers = find_package_callers("requests", None, db)
        assert callers[0].is_trust_boundary is False

    def test_test_file_flagged(self, db: sqlite3.Connection) -> None:
        _add_node(db, "tests::helper", "fetch_mock", "tests/helpers.py")
        _add_edge(db, "tests::helper", "external::requests.get", "RUNTIME_BOUNDARY", "tests/helpers.py")

        callers = find_package_callers("requests", None, db)
        assert callers[0].is_test is True


# ---------------------------------------------------------------------------
# _bfs_upstream
# ---------------------------------------------------------------------------

class TestBfsCallers:
    def test_finds_upstream_caller(self, db: sqlite3.Connection) -> None:
        _add_node(db, "utils::fetch", "fetch", "utils/http.py")
        _add_node(db, "api::view", "view", "api/views.py")
        _add_edge(db, "api::view", "utils::fetch", "LOCAL_CALL", "api/views.py")

        result = bfs_callers("utils::fetch", db, max_depth=2)
        assert 1 in result
        names = [n.name for n in result[1]]
        assert "view" in names

    def test_skips_runtime_boundary_edges(self, db: sqlite3.Connection) -> None:
        _add_node(db, "a", "a_fn", "a.py")
        _add_edge(db, "a", "external::something", "RUNTIME_BOUNDARY", "a.py")

        result = bfs_callers("a", db, max_depth=2)
        assert result == {}

    def test_depth_limit_respected(self, db: sqlite3.Connection) -> None:
        _add_node(db, "a", "a", "a.py")
        _add_node(db, "b", "b", "b.py")
        _add_node(db, "c", "c", "c.py")
        _add_edge(db, "b", "a", "LOCAL_CALL", "b.py")
        _add_edge(db, "c", "b", "LOCAL_CALL", "c.py")

        result = bfs_callers("a", db, max_depth=1)
        assert 1 in result
        assert 2 not in result


# ---------------------------------------------------------------------------
# compute_vuln_blast_radius
# ---------------------------------------------------------------------------

class TestComputeVulnBlastRadius:
    def test_package_not_used_returns_empty(self, db: sqlite3.Connection) -> None:
        result = compute_vuln_blast_radius("requests", None, db)
        assert result.direct_callers == []
        assert result.critical_exposure == []

    def test_trust_boundary_caller_is_critical(self, db: sqlite3.Connection) -> None:
        _add_node(db, "api::view", "view", "api/views.py")
        _add_edge(db, "api::view", "external::requests.get", "RUNTIME_BOUNDARY", "api/views.py")

        result = compute_vuln_blast_radius("requests", None, db)
        assert len(result.direct_callers) == 1
        assert len(result.critical_exposure) == 1
        assert result.critical_exposure[0].exposure_score == 1.0

    def test_internal_caller_with_tb_ancestor_is_critical(self, db: sqlite3.Connection) -> None:
        _add_node(db, "utils::fetch", "fetch", "utils/http.py")
        _add_node(db, "api::view", "view", "api/views.py")
        _add_edge(db, "utils::fetch", "external::requests.get", "RUNTIME_BOUNDARY", "utils/http.py")
        _add_edge(db, "api::view", "utils::fetch", "LOCAL_CALL", "api/views.py")

        result = compute_vuln_blast_radius("requests", None, db)
        assert len(result.critical_exposure) == 1
        assert result.critical_exposure[0].exposure_score == 0.6

    def test_test_only_caller_is_low_exposure(self, db: sqlite3.Connection) -> None:
        _add_node(db, "tests::helper", "fetch_test", "tests/helpers.py")
        _add_edge(db, "tests::helper", "external::requests.get", "RUNTIME_BOUNDARY", "tests/helpers.py")

        result = compute_vuln_blast_radius("requests", None, db)
        assert result.critical_exposure == []
        assert len(result.low_exposure) == 1

    def test_remediation_sequence_generated(self, db: sqlite3.Connection) -> None:
        _add_node(db, "api::view", "view", "api/views.py")
        _add_edge(db, "api::view", "external::requests.get", "RUNTIME_BOUNDARY", "api/views.py")

        result = compute_vuln_blast_radius("requests", None, db)
        assert len(result.remediation_sequence) >= 2
        last_step = result.remediation_sequence[-1]
        assert "requests" in last_step["description"]
        assert last_step["neuron"] is None

    def test_pinned_version_from_pyproject(self, tmp_path: Path, db: sqlite3.Connection) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\ndependencies = ["requests>=2.28.0,<3.0"]\n'
        )
        result = compute_vuln_blast_radius("requests", None, db, root=tmp_path)
        assert result.pinned_version is not None
        assert "requests" in result.pinned_version


# ---------------------------------------------------------------------------
# read_pinned_version
# ---------------------------------------------------------------------------

class TestReadPinnedVersion:
    def test_reads_pyproject_pep517(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\ndependencies = ["requests>=2.28.0"]\n'
        )
        assert read_pinned_version("requests", tmp_path) == "requests>=2.28.0"

    def test_reads_requirements_txt(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("requests==2.28.2\nhttpx==0.23.0\n")
        assert read_pinned_version("requests", tmp_path) == "requests==2.28.2"

    def test_returns_none_when_not_found(self, tmp_path: Path) -> None:
        assert read_pinned_version("nonexistent-pkg", tmp_path) is None

    def test_no_files_returns_none(self, tmp_path: Path) -> None:
        assert read_pinned_version("requests", tmp_path) is None

    def test_does_not_match_prefix_of_longer_package(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("requests-mock==1.11.0\nrequests==2.31.0\n")
        result = read_pinned_version("requests", tmp_path)
        assert result == "requests==2.31.0"


# ---------------------------------------------------------------------------
# Trust boundary IMPORT edge exclusion
# ---------------------------------------------------------------------------

class TestIsTrustBoundaryImportExclusion:
    def test_only_import_edge_still_trust_boundary(self, db: sqlite3.Connection) -> None:
        # A neuron that is only imported (IMPORT edge), not called — should still be a trust boundary
        _add_node(db, "utils::helper", "helper", "utils/helpers.py")
        _add_node(db, "mod::module", "module_mod", "mod/__init__.py")
        _add_edge(db, "mod::module", "utils::helper", "IMPORT")

        assert _is_trust_boundary("utils::helper", db) is True

    def test_called_neuron_is_not_trust_boundary(self, db: sqlite3.Connection) -> None:
        _add_node(db, "utils::helper", "helper", "utils/helpers.py")
        _add_node(db, "api::view", "view", "api/views.py")
        _add_edge(db, "api::view", "utils::helper", "LOCAL_CALL")

        assert _is_trust_boundary("utils::helper", db) is False


# ---------------------------------------------------------------------------
# Per-caller BFS attribution (multiple callers with distinct ancestors)
# ---------------------------------------------------------------------------

class TestPerCallerAttribution:
    def test_two_callers_with_distinct_ancestors(self, db: sqlite3.Connection) -> None:
        # caller_a has trust boundary ancestor_a
        # caller_b has trust boundary ancestor_b
        # Both are internal callers (have callers themselves)
        _add_node(db, "ancestor_a", "entry_a", "api/route_a.py")
        _add_node(db, "ancestor_b", "entry_b", "api/route_b.py")
        _add_node(db, "caller_a", "fetch_a", "utils/http_a.py")
        _add_node(db, "caller_b", "fetch_b", "utils/http_b.py")

        # Both callers call requests
        _add_edge(db, "caller_a", "external::requests.get", "RUNTIME_BOUNDARY", "utils/http_a.py")
        _add_edge(db, "caller_b", "external::requests.get", "RUNTIME_BOUNDARY", "utils/http_b.py")

        # ancestor_a calls caller_a; ancestor_b calls caller_b
        _add_edge(db, "ancestor_a", "caller_a", "LOCAL_CALL", "api/route_a.py")
        _add_edge(db, "ancestor_b", "caller_b", "LOCAL_CALL", "api/route_b.py")

        result = compute_vuln_blast_radius("requests", None, db)
        assert len(result.critical_exposure) == 2

        entry_points = {p.entry_point_name for p in result.critical_exposure}
        assert "entry_a" in entry_points
        assert "entry_b" in entry_points
