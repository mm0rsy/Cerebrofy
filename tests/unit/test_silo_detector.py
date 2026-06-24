"""Unit tests for the knowledge silo detector."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from cerebrofy.analysis.silo_detector import (
    SiloReport,
    _authors_for_range,
    _blame_file,
    _silo_risk_label,
    compute_silo_report,
)


# ---------------------------------------------------------------------------
# _silo_risk_label
# ---------------------------------------------------------------------------

def test_silo_risk_label_low() -> None:
    assert _silo_risk_label(0.0) == "LOW"
    assert _silo_risk_label(2.9) == "LOW"


def test_silo_risk_label_medium() -> None:
    assert _silo_risk_label(3.0) == "MEDIUM"
    assert _silo_risk_label(7.9) == "MEDIUM"


def test_silo_risk_label_high() -> None:
    assert _silo_risk_label(8.0) == "HIGH"
    assert _silo_risk_label(19.9) == "HIGH"


def test_silo_risk_label_critical() -> None:
    assert _silo_risk_label(20.0) == "CRITICAL"
    assert _silo_risk_label(100.0) == "CRITICAL"


# ---------------------------------------------------------------------------
# _authors_for_range
# ---------------------------------------------------------------------------

def test_authors_for_range_single_author() -> None:
    blame = {1: "alice@x.com", 2: "alice@x.com", 3: "alice@x.com"}
    authors, primary, pct = _authors_for_range(blame, 1, 3)
    assert authors == {"alice@x.com"}
    assert primary == "alice@x.com"
    assert pct == 1.0


def test_authors_for_range_two_authors() -> None:
    blame = {1: "alice@x.com", 2: "bob@x.com", 3: "alice@x.com", 4: "alice@x.com"}
    authors, primary, pct = _authors_for_range(blame, 1, 4)
    assert authors == {"alice@x.com", "bob@x.com"}
    assert primary == "alice@x.com"
    assert pct == pytest.approx(0.75)


def test_authors_for_range_missing_lines_fallback() -> None:
    # No blame data for the range — fallback to unknown
    authors, primary, pct = _authors_for_range({}, 5, 10)
    assert authors == {"unknown"}
    assert primary == "unknown"
    assert pct == 1.0


def test_authors_for_range_partial_coverage() -> None:
    blame = {2: "carol@x.com", 4: "carol@x.com"}
    authors, primary, pct = _authors_for_range(blame, 1, 5)
    assert primary == "carol@x.com"
    assert len(authors) == 1


# ---------------------------------------------------------------------------
# _blame_file (git subprocess)
# ---------------------------------------------------------------------------

_PORCELAIN_OUTPUT = """\
aabbccdd11223344556677889900aabbccdd1122 1 1 2
author Alice
author-mail <alice@x.com>
author-time 1700000000
author-tz +0000
committer Alice
committer-mail <alice@x.com>
committer-time 1700000000
committer-tz +0000
summary init
filename hello.py
\tdef hello():
aabbccdd11223344556677889900aabbccdd1122 2 2
\t    pass
eeff00112233445566778899aabbccddeeff0011 3 3 1
author Bob
author-mail <bob@x.com>
author-time 1700000001
author-tz +0000
committer Bob
committer-mail <bob@x.com>
committer-time 1700000001
committer-tz +0000
summary fix
filename hello.py
\t    return 1
"""


def test_blame_file_parses_porcelain(tmp_path: Path) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = _PORCELAIN_OUTPUT

        result = _blame_file("hello.py", tmp_path)

    assert result[1] == "alice@x.com"
    assert result[2] == "alice@x.com"
    assert result[3] == "bob@x.com"


def test_blame_file_returns_empty_on_git_error(tmp_path: Path) -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 128
        mock_run.return_value.stdout = ""
        result = _blame_file("missing.py", tmp_path)
    assert result == {}


# ---------------------------------------------------------------------------
# compute_silo_report (integration with in-memory DB)
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


def test_compute_silo_report_empty_db(tmp_path: Path) -> None:
    conn = _make_db()
    with patch("cerebrofy.analysis.silo_detector._blame_file", return_value={}), \
         patch("cerebrofy.analysis.silo_detector._get_current_commit", return_value="abc1234"):
        report = compute_silo_report(conn, tmp_path, depth=2, min_callers=0, top=50)
    assert isinstance(report, SiloReport)
    assert report.total_neurons_scanned == 0
    assert report.neurons == []


def test_compute_silo_report_single_author_silo(tmp_path: Path) -> None:
    conn = _make_db()
    # One neuron with 3 callers, all lines by one author
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("n1", "validate_token", "auth.py", "function", 10, 25, "def validate_token()", "", "h1"),
    )
    # 3 callers pointing to n1
    for i in range(3):
        cid = f"c{i}"
        conn.execute(
            "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
            (cid, f"caller{i}", "app.py", "function", i * 10 + 1, i * 10 + 5, "", "", ""),
        )
        conn.execute("INSERT INTO edges VALUES (?,?,?,?)", (cid, "n1", "CALLS", "app.py"))

    blame = {ln: "alice@x.com" for ln in range(1, 100)}

    with patch("cerebrofy.analysis.silo_detector._blame_file", return_value=blame), \
         patch("cerebrofy.analysis.silo_detector._get_current_commit", return_value="abc1234"):
        report = compute_silo_report(conn, tmp_path, depth=1, min_callers=1, top=50)

    silo_neurons = [n for n in report.neurons if n.name == "validate_token"]
    assert len(silo_neurons) == 1
    sn = silo_neurons[0]
    assert sn.unique_authors == 1
    assert sn.caller_count == 3
    assert sn.silo_score == 3.0
    assert sn.risk_label == "MEDIUM"
    assert report.silos_detected >= 1


def test_compute_silo_report_multi_author_reduces_risk(tmp_path: Path) -> None:
    conn = _make_db()
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("n1", "process_payment", "billing.py", "function", 1, 10, "def process_payment()", "", "h1"),
    )
    for i in range(5):
        cid = f"c{i}"
        conn.execute(
            "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
            (cid, f"caller{i}", "app.py", "function", i * 10 + 1, i * 10 + 5, "", "", ""),
        )
        conn.execute("INSERT INTO edges VALUES (?,?,?,?)", (cid, "n1", "CALLS", "app.py"))

    # 5 different authors across the 10 lines
    blame = {ln: f"dev{ln % 5}@x.com" for ln in range(1, 11)}

    with patch("cerebrofy.analysis.silo_detector._blame_file", return_value=blame), \
         patch("cerebrofy.analysis.silo_detector._get_current_commit", return_value="abc1234"):
        report = compute_silo_report(conn, tmp_path, depth=1, min_callers=1, top=50)

    sn = next(n for n in report.neurons if n.name == "process_payment")
    assert sn.unique_authors == 5
    assert sn.caller_count == 5
    assert sn.silo_score == 1.0  # 5 callers / 5 authors
    assert sn.risk_label == "LOW"


def test_compute_silo_report_min_callers_filter(tmp_path: Path) -> None:
    conn = _make_db()
    # Neuron with 0 callers — should be filtered with min_callers=1
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("n1", "isolated_fn", "util.py", "function", 1, 5, "", "", ""),
    )
    blame = {1: "alice@x.com"}
    with patch("cerebrofy.analysis.silo_detector._blame_file", return_value=blame), \
         patch("cerebrofy.analysis.silo_detector._get_current_commit", return_value=None):
        report = compute_silo_report(conn, tmp_path, depth=1, min_callers=1, top=50)
    assert all(n.name != "isolated_fn" for n in report.neurons)


def test_compute_silo_report_sorted_by_score_desc(tmp_path: Path) -> None:
    conn = _make_db()
    # Two neurons: high-score (many callers, 1 author) and low-score (few callers, many authors)
    for nid, name, line_start, line_end in [("n1", "hot_fn", 1, 5), ("n2", "cold_fn", 10, 15)]:
        conn.execute(
            "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
            (nid, name, "code.py", "function", line_start, line_end, "", "", ""),
        )

    # n1: 10 callers
    for i in range(10):
        cid = f"ca{i}"
        conn.execute(
            "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
            (cid, f"c{i}", "a.py", "function", i + 100, i + 105, "", "", ""),
        )
        conn.execute("INSERT INTO edges VALUES (?,?,?,?)", (cid, "n1", "CALLS", "a.py"))

    # n2: 1 caller
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("cb0", "lone_caller", "b.py", "function", 200, 205, "", "", ""),
    )
    conn.execute("INSERT INTO edges VALUES (?,?,?,?)", ("cb0", "n2", "CALLS", "b.py"))

    # n1: 1 author (silo); n2: 5 authors
    blame = {ln: ("alice@x.com" if ln <= 5 else f"dev{ln % 5}@x.com") for ln in range(1, 20)}

    with patch("cerebrofy.analysis.silo_detector._blame_file", return_value=blame), \
         patch("cerebrofy.analysis.silo_detector._get_current_commit", return_value=None):
        report = compute_silo_report(conn, tmp_path, depth=1, min_callers=1, top=50)

    names = [n.name for n in report.neurons]
    hot_idx = names.index("hot_fn")
    cold_idx = names.index("cold_fn")
    assert hot_idx < cold_idx  # hot_fn must rank higher
