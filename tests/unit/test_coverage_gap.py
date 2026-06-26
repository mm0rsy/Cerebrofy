"""Unit tests for the Test Coverage Gap Predictor."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cerebrofy.analysis.coverage_gap import (
    GapNeuron,
    GapReport,
    _detect_covered_neurons,
    _file_velocity,
    _gap_risk_label,
    _gap_risk_icon,
    _get_current_commit,
    _parse_coverage_xml,
    _topology_covered_neurons,
    _write_gap_memories,
    compute_coverage_gap_report,
)


# ---------------------------------------------------------------------------
# _gap_risk_label
# ---------------------------------------------------------------------------

def test_gap_risk_label_low() -> None:
    assert _gap_risk_label(0.0) == "LOW"
    assert _gap_risk_label(4.9) == "LOW"


def test_gap_risk_label_medium() -> None:
    assert _gap_risk_label(5.0) == "MEDIUM"
    assert _gap_risk_label(24.9) == "MEDIUM"


def test_gap_risk_label_high() -> None:
    assert _gap_risk_label(25.0) == "HIGH"
    assert _gap_risk_label(99.9) == "HIGH"


def test_gap_risk_label_critical() -> None:
    assert _gap_risk_label(100.0) == "CRITICAL"
    assert _gap_risk_label(500.0) == "CRITICAL"


# ---------------------------------------------------------------------------
# _gap_risk_icon
# ---------------------------------------------------------------------------

def test_gap_risk_icon_all_labels() -> None:
    assert _gap_risk_icon("CRITICAL") == "🔴"
    assert _gap_risk_icon("HIGH") == "🟠"
    assert _gap_risk_icon("MEDIUM") == "🟡"
    assert _gap_risk_icon("LOW") == "🟢"
    assert _gap_risk_icon("UNKNOWN") == "⚪"


# ---------------------------------------------------------------------------
# _get_current_commit
# ---------------------------------------------------------------------------

def test_get_current_commit_returns_hash(tmp_path: Path) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "abc1234\n"
        result = _get_current_commit(tmp_path)
    assert result == "abc1234"


def test_get_current_commit_returns_none_on_error(tmp_path: Path) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 128
        mock_run.return_value.stdout = ""
        result = _get_current_commit(tmp_path)
    assert result is None


# ---------------------------------------------------------------------------
# _file_velocity
# ---------------------------------------------------------------------------

def test_file_velocity_counts_commits(tmp_path: Path) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "abc\ndef\nghi\n"
        result = _file_velocity("src/mod.py", tmp_path, days=30)
    assert result == 3


def test_file_velocity_returns_zero_on_git_error(tmp_path: Path) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 128
        mock_run.return_value.stdout = ""
        result = _file_velocity("missing.py", tmp_path, days=30)
    assert result == 0


def test_file_velocity_ignores_blank_lines(tmp_path: Path) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "abc\n\ndef\n\n"
        result = _file_velocity("src/mod.py", tmp_path, days=30)
    assert result == 2


def test_file_velocity_passes_correct_args(tmp_path: Path) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        _file_velocity("src/auth.py", tmp_path, days=14)
    args = mock_run.call_args[0][0]
    assert args[0] == "git"
    assert "--since=14 days ago" in args
    assert "src/auth.py" in args
    assert mock_run.call_args[1].get("shell") is not True


# ---------------------------------------------------------------------------
# _parse_coverage_xml
# ---------------------------------------------------------------------------

_COVERAGE_XML = """\
<?xml version="1.0" ?>
<coverage version="7.0" timestamp="1700000000" lines-valid="100" lines-covered="70">
  <packages>
    <package name="cerebrofy">
      <classes>
        <class name="blast_radius.py" filename="src/cerebrofy/analysis/blast_radius.py">
          <lines>
            <line number="10" hits="1"/>
            <line number="11" hits="1"/>
            <line number="12" hits="0"/>
            <line number="20" hits="1"/>
          </lines>
        </class>
        <class name="uncovered.py" filename="src/cerebrofy/uncovered.py">
          <lines>
            <line number="5" hits="0"/>
            <line number="6" hits="0"/>
          </lines>
        </class>
      </classes>
    </package>
  </packages>
</coverage>
"""


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


def test_parse_coverage_xml_identifies_covered_neuron(tmp_path: Path) -> None:
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(_COVERAGE_XML)

    conn = _make_db()
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("n1", "bfs_callers", "src/cerebrofy/analysis/blast_radius.py",
         "function", 10, 15, "", "", ""),
    )

    result = _parse_coverage_xml(xml_path, conn)
    assert "n1" in result


def test_parse_coverage_xml_excludes_uncovered_neuron(tmp_path: Path) -> None:
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(_COVERAGE_XML)

    conn = _make_db()
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("n2", "uncovered_fn", "src/cerebrofy/uncovered.py", "function", 5, 6, "", "", ""),
    )

    result = _parse_coverage_xml(xml_path, conn)
    assert "n2" not in result


def test_parse_coverage_xml_returns_empty_on_malformed(tmp_path: Path) -> None:
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text("not xml at all <<<")
    conn = _make_db()
    result = _parse_coverage_xml(xml_path, conn)
    assert result == set()


def test_parse_coverage_xml_returns_empty_when_no_hits(tmp_path: Path) -> None:
    xml = """<coverage><packages><package><classes>
        <class filename="src/mod.py">
          <lines><line number="1" hits="0"/></lines>
        </class>
    </classes></package></packages></coverage>"""
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(xml)
    conn = _make_db()
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("n1", "fn", "src/mod.py", "function", 1, 1, "", "", ""),
    )
    result = _parse_coverage_xml(xml_path, conn)
    assert "n1" not in result


# ---------------------------------------------------------------------------
# _topology_covered_neurons
# ---------------------------------------------------------------------------

def test_topology_covered_neurons_finds_test_edge() -> None:
    conn = _make_db()
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("prod_fn", "validate", "src/auth.py", "function", 1, 10, "", "", ""),
    )
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("test_fn", "test_validate", "tests/test_auth.py", "function", 1, 5, "", "", ""),
    )
    conn.execute("INSERT INTO edges VALUES (?,?,?,?)", ("test_fn", "prod_fn", "CALLS", "tests/test_auth.py"))

    result = _topology_covered_neurons(conn)
    assert "prod_fn" in result


def test_topology_covered_neurons_excludes_no_test_edge() -> None:
    conn = _make_db()
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("prod_fn", "validate", "src/auth.py", "function", 1, 10, "", "", ""),
    )
    result = _topology_covered_neurons(conn)
    assert "prod_fn" not in result


# ---------------------------------------------------------------------------
# _detect_covered_neurons
# ---------------------------------------------------------------------------

def test_detect_covered_neurons_prefers_coverage_xml(tmp_path: Path) -> None:
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(_COVERAGE_XML)
    conn = _make_db()
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("n1", "bfs_callers", "src/cerebrofy/analysis/blast_radius.py",
         "function", 10, 15, "", "", ""),
    )

    covered, source = _detect_covered_neurons(tmp_path, conn)
    assert source == "coverage_xml"
    assert "n1" in covered


def test_detect_covered_neurons_falls_back_to_topology(tmp_path: Path) -> None:
    conn = _make_db()
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("prod_fn", "fn", "src/mod.py", "function", 1, 5, "", "", ""),
    )
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("test_fn", "test_fn", "tests/test_mod.py", "function", 1, 3, "", "", ""),
    )
    conn.execute("INSERT INTO edges VALUES (?,?,?,?)", ("test_fn", "prod_fn", "CALLS", "tests/test_mod.py"))

    covered, source = _detect_covered_neurons(tmp_path, conn)
    assert source == "graph_topology"
    assert "prod_fn" in covered


def test_detect_covered_neurons_falls_back_when_xml_has_no_hits(tmp_path: Path) -> None:
    empty_xml = """<coverage><packages><package><classes>
        <class filename="src/mod.py"><lines><line number="1" hits="0"/></lines></class>
    </classes></package></packages></coverage>"""
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(empty_xml)

    conn = _make_db()
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("test_fn", "test_fn", "tests/test_mod.py", "function", 1, 3, "", "", ""),
    )
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("prod_fn", "fn", "src/mod.py", "function", 1, 1, "", "", ""),
    )
    conn.execute("INSERT INTO edges VALUES (?,?,?,?)", ("test_fn", "prod_fn", "CALLS", "tests/test_mod.py"))

    covered, source = _detect_covered_neurons(tmp_path, conn)
    assert source == "graph_topology"


# ---------------------------------------------------------------------------
# compute_coverage_gap_report (integration with in-memory DB)
# ---------------------------------------------------------------------------

def _insert_node(conn: sqlite3.Connection, nid: str, name: str, file: str,
                 line_start: int = 1, line_end: int = 10, ntype: str = "function") -> None:
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        (nid, name, file, ntype, line_start, line_end, "", "", ""),
    )


def _insert_edge(conn: sqlite3.Connection, src: str, dst: str) -> None:
    conn.execute("INSERT INTO edges VALUES (?,?,?,?)", (src, dst, "CALLS", ""))


def test_compute_report_empty_db(tmp_path: Path) -> None:
    conn = _make_db()
    with patch("cerebrofy.analysis.coverage_gap._file_velocity", return_value=0), \
         patch("cerebrofy.analysis.coverage_gap._get_current_commit", return_value=None):
        report = compute_coverage_gap_report(conn, tmp_path)
    assert isinstance(report, GapReport)
    assert report.total_neurons_scanned == 0
    assert report.neurons == []


def test_compute_report_uncovered_neuron_ranked(tmp_path: Path) -> None:
    conn = _make_db()
    _insert_node(conn, "target", "process_payment", "src/billing.py")
    for i in range(5):
        cid = f"caller{i}"
        _insert_node(conn, cid, f"caller{i}", "src/app.py", i * 10 + 1, i * 10 + 5)
        _insert_edge(conn, cid, "target")

    with patch("cerebrofy.analysis.coverage_gap._file_velocity", return_value=10), \
         patch("cerebrofy.analysis.coverage_gap._get_current_commit", return_value="abc1234"):
        report = compute_coverage_gap_report(conn, tmp_path, depth=1)

    assert report.total_neurons_scanned >= 1
    assert report.uncovered_count >= 1
    gap_neurons = [n for n in report.neurons if n.name == "process_payment"]
    assert len(gap_neurons) == 1
    gn = gap_neurons[0]
    assert gn.velocity == 10
    assert gn.gap_score > 0
    assert gn.caller_count == 5


def test_compute_report_covered_neuron_excluded(tmp_path: Path) -> None:
    conn = _make_db()
    _insert_node(conn, "prod_fn", "validate_token", "src/auth.py")
    _insert_node(conn, "test_fn", "test_validate_token", "tests/test_auth.py")
    _insert_edge(conn, "test_fn", "prod_fn")

    with patch("cerebrofy.analysis.coverage_gap._file_velocity", return_value=5), \
         patch("cerebrofy.analysis.coverage_gap._get_current_commit", return_value=None):
        report = compute_coverage_gap_report(conn, tmp_path)

    assert all(n.name != "validate_token" for n in report.neurons)


def test_compute_report_zero_velocity_included(tmp_path: Path) -> None:
    """Dormant uncovered neurons are included but rank at the bottom (gap_score=0)."""
    conn = _make_db()
    _insert_node(conn, "n1", "stale_fn", "src/old.py")
    _insert_node(conn, "c1", "caller", "src/app.py")
    _insert_edge(conn, "c1", "n1")

    with patch("cerebrofy.analysis.coverage_gap._file_velocity", return_value=0), \
         patch("cerebrofy.analysis.coverage_gap._get_current_commit", return_value=None):
        report = compute_coverage_gap_report(conn, tmp_path)

    gap_neurons = [n for n in report.neurons if n.name == "stale_fn"]
    assert len(gap_neurons) == 1
    assert gap_neurons[0].gap_score == 0.0
    assert gap_neurons[0].velocity == 0


def test_compute_report_sorted_by_gap_score_desc(tmp_path: Path) -> None:
    conn = _make_db()
    # hot_fn: 10 callers, velocity=10 → high score
    _insert_node(conn, "hot", "hot_fn", "src/hot.py")
    for i in range(10):
        cid = f"hc{i}"
        _insert_node(conn, cid, f"hc{i}", "src/app.py", i * 10 + 1, i * 10 + 5)
        _insert_edge(conn, cid, "hot")

    # cold_fn: 1 caller, velocity=1 → low score
    _insert_node(conn, "cold", "cold_fn", "src/cold.py")
    _insert_node(conn, "cc0", "cc0", "src/other.py")
    _insert_edge(conn, "cc0", "cold")

    def mock_velocity(file_path: str, repo_root: Path, days: int) -> int:
        return 10 if "hot" in file_path else 1

    with patch("cerebrofy.analysis.coverage_gap._file_velocity", side_effect=mock_velocity), \
         patch("cerebrofy.analysis.coverage_gap._get_current_commit", return_value=None):
        report = compute_coverage_gap_report(conn, tmp_path, depth=1)

    names = [n.name for n in report.neurons]
    assert names.index("hot_fn") < names.index("cold_fn")


def test_compute_report_lobe_filter(tmp_path: Path) -> None:
    conn = _make_db()
    _insert_node(conn, "n1", "auth_fn", "auth/login.py")
    _insert_node(conn, "n2", "billing_fn", "billing/charge.py")
    _insert_node(conn, "c1", "caller", "src/app.py")
    _insert_edge(conn, "c1", "n1")
    _insert_edge(conn, "c1", "n2")

    with patch("cerebrofy.analysis.coverage_gap._file_velocity", return_value=5), \
         patch("cerebrofy.analysis.coverage_gap._get_current_commit", return_value=None):
        report = compute_coverage_gap_report(conn, tmp_path, lobe_filter="auth")

    assert all(n.lobe == "auth" for n in report.neurons)


def test_compute_report_risk_filter(tmp_path: Path) -> None:
    conn = _make_db()
    _insert_node(conn, "n1", "fn", "src/mod.py")

    with patch("cerebrofy.analysis.coverage_gap._file_velocity", return_value=0), \
         patch("cerebrofy.analysis.coverage_gap._get_current_commit", return_value=None):
        report = compute_coverage_gap_report(conn, tmp_path, risk_filter="CRITICAL")

    # With velocity=0, gap_score=0 → LOW, not CRITICAL
    assert all(n.risk_label == "CRITICAL" for n in report.neurons)


def test_compute_report_min_blast_filter(tmp_path: Path) -> None:
    conn = _make_db()
    # isolated fn: no callers → blast_weighted=0
    _insert_node(conn, "n1", "isolated_fn", "src/mod.py")

    with patch("cerebrofy.analysis.coverage_gap._file_velocity", return_value=10), \
         patch("cerebrofy.analysis.coverage_gap._get_current_commit", return_value=None):
        report = compute_coverage_gap_report(conn, tmp_path, min_blast=1.0)

    assert all(n.name != "isolated_fn" for n in report.neurons)


def test_compute_report_modules_excluded(tmp_path: Path) -> None:
    conn = _make_db()
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("mod", "__init__", "src/__init__.py", "module", 1, 1, "", "", ""),
    )

    with patch("cerebrofy.analysis.coverage_gap._file_velocity", return_value=10), \
         patch("cerebrofy.analysis.coverage_gap._get_current_commit", return_value=None):
        report = compute_coverage_gap_report(conn, tmp_path)

    assert report.total_neurons_scanned == 0


def test_compute_report_top_limit(tmp_path: Path) -> None:
    conn = _make_db()
    for i in range(30):
        _insert_node(conn, f"n{i}", f"fn{i}", "src/mod.py", i * 10 + 1, i * 10 + 5)
        caller = f"c{i}"
        _insert_node(conn, caller, f"c{i}", "src/app.py", i * 100 + 1, i * 100 + 5)
        _insert_edge(conn, caller, f"n{i}")

    with patch("cerebrofy.analysis.coverage_gap._file_velocity", return_value=3), \
         patch("cerebrofy.analysis.coverage_gap._get_current_commit", return_value=None):
        report = compute_coverage_gap_report(conn, tmp_path, top=10)

    assert len(report.neurons) <= 10


def test_compute_report_coverage_xml_used_when_present(tmp_path: Path) -> None:
    xml_path = tmp_path / "coverage.xml"
    xml_path.write_text(_COVERAGE_XML)
    conn = _make_db()
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("n1", "bfs_callers", "src/cerebrofy/analysis/blast_radius.py",
         "function", 10, 15, "", "", ""),
    )

    with patch("cerebrofy.analysis.coverage_gap._file_velocity", return_value=5), \
         patch("cerebrofy.analysis.coverage_gap._get_current_commit", return_value=None):
        report = compute_coverage_gap_report(conn, tmp_path)

    assert report.coverage_source == "coverage_xml"
    # n1 is covered by coverage.xml → should not appear in gaps
    assert all(n.name != "bfs_callers" for n in report.neurons)


def test_compute_report_as_of_commit(tmp_path: Path) -> None:
    conn = _make_db()
    with patch("cerebrofy.analysis.coverage_gap._file_velocity", return_value=0), \
         patch("cerebrofy.analysis.coverage_gap._get_current_commit", return_value="def5678"):
        report = compute_coverage_gap_report(conn, tmp_path)
    assert report.as_of_commit == "def5678"


def test_compute_report_velocity_cache_per_file(tmp_path: Path) -> None:
    """Velocity is fetched once per unique file, not once per neuron."""
    conn = _make_db()
    for i in range(3):
        _insert_node(conn, f"n{i}", f"fn{i}", "src/mod.py", i * 10 + 1, i * 10 + 5)

    call_count = 0

    def counting_velocity(file_path: str, repo_root: Path, days: int) -> int:
        nonlocal call_count
        call_count += 1
        return 5

    with patch("cerebrofy.analysis.coverage_gap._file_velocity", side_effect=counting_velocity), \
         patch("cerebrofy.analysis.coverage_gap._get_current_commit", return_value=None):
        compute_coverage_gap_report(conn, tmp_path)

    # All 3 neurons share the same file — velocity should be fetched only once
    assert call_count == 1


# ---------------------------------------------------------------------------
# _write_gap_memories
# ---------------------------------------------------------------------------

def _make_gap_neuron(risk_label: str = "HIGH") -> GapNeuron:
    return GapNeuron(
        id="n1", name="process_payment", file="billing/charge.py",
        line_start=1, line_end=20, lobe="billing",
        caller_count=10, velocity=8, gap_score=80.0,
        risk_label=risk_label, risk_icon="🟠",
        coverage_source="graph_topology",
    )


def test_write_gap_memories_writes_high_and_critical(tmp_path: Path) -> None:
    neurons = [_make_gap_neuron("HIGH"), _make_gap_neuron("CRITICAL")]
    mock_conn = MagicMock()

    with patch("cerebrofy.memory.store.open_memories_db", return_value=mock_conn), \
         patch("cerebrofy.memory.embedder.embed_memory", return_value=[0.0] * 384), \
         patch("cerebrofy.memory.store.write_memory") as mock_write:
        _write_gap_memories(neurons, tmp_path)

    assert mock_write.call_count == 2


def test_write_gap_memories_skips_low_and_medium(tmp_path: Path) -> None:
    neurons = [_make_gap_neuron("LOW"), _make_gap_neuron("MEDIUM")]
    mock_conn = MagicMock()

    with patch("cerebrofy.memory.store.open_memories_db", return_value=mock_conn), \
         patch("cerebrofy.memory.embedder.embed_memory", return_value=[0.0] * 384), \
         patch("cerebrofy.memory.store.write_memory") as mock_write:
        _write_gap_memories(neurons, tmp_path)

    assert mock_write.call_count == 0


def test_write_gap_memories_swallows_exception(tmp_path: Path) -> None:
    neurons = [_make_gap_neuron("CRITICAL")]
    with patch("cerebrofy.memory.store.open_memories_db", side_effect=RuntimeError("db error")):
        _write_gap_memories(neurons, tmp_path)  # must not raise
