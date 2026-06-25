"""Unit tests for commands/silo.py — CLI, rendering, and DB helpers."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from cerebrofy.analysis.silo_detector import SiloNeuron, SiloReport
from cerebrofy.commands.silo import (
    _find_repo_root,
    _open_db_ro,
    _render_json,
    _render_text,
    cerebrofy_silo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_neuron(name: str = "my_fn", risk_label: str = "MEDIUM") -> SiloNeuron:
    return SiloNeuron(
        id="n1", name=name, file="src/mod.py", line_start=10, line_end=20,
        lobe="src", unique_authors=1, primary_author="alice@x.com",
        primary_author_pct=1.0, caller_count=5, silo_score=5.0,
        risk_label=risk_label, risk_icon="🟡",
    )


def _make_report(risk_label: str = "MEDIUM") -> SiloReport:
    return SiloReport(
        neurons=[_make_neuron("target_fn", risk_label)],
        total_neurons_scanned=10,
        silos_detected=1,
        as_of_commit="abc1234",
    )


def _invoke(args: list[str], report: SiloReport | None = None) -> object:
    if report is None:
        report = _make_report()
    runner = CliRunner()
    mock_conn = MagicMock(spec=sqlite3.Connection)
    with patch("cerebrofy.commands.silo._find_repo_root", return_value=Path("/repo")), \
         patch("cerebrofy.commands.silo._open_db_ro", return_value=mock_conn), \
         patch("cerebrofy.commands.silo.check_schema_version"), \
         patch("cerebrofy.analysis.silo_detector.compute_silo_report", return_value=report):
        return runner.invoke(cerebrofy_silo, args, catch_exceptions=False)


# ---------------------------------------------------------------------------
# _open_db_ro
# ---------------------------------------------------------------------------

def test_open_db_ro_exits_when_no_db(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _open_db_ro(tmp_path)
    assert exc_info.value.code == 1


def test_open_db_ro_returns_connection(tmp_path: Path) -> None:
    db_path = tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"
    db_path.parent.mkdir(parents=True)
    sqlite3.connect(str(db_path)).close()
    conn = _open_db_ro(tmp_path)
    assert conn is not None
    conn.close()


# ---------------------------------------------------------------------------
# _find_repo_root
# ---------------------------------------------------------------------------

def test_find_repo_root_exits_when_no_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc_info:
        _find_repo_root()
    assert exc_info.value.code == 1


def test_find_repo_root_returns_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"
    db_path.parent.mkdir(parents=True)
    sqlite3.connect(str(db_path)).close()
    monkeypatch.chdir(tmp_path)
    assert _find_repo_root() == tmp_path


# ---------------------------------------------------------------------------
# _render_text
# ---------------------------------------------------------------------------

def test_render_text_no_silos() -> None:
    report = SiloReport(neurons=[], total_neurons_scanned=0, silos_detected=0)
    _render_text(report, top=10)  # must not raise; prints "No silos detected"


def test_render_text_with_neurons() -> None:
    report = SiloReport(
        neurons=[_make_neuron("hot_fn", "HIGH")],
        total_neurons_scanned=10,
        silos_detected=1,
        as_of_commit="abc1234",
    )
    _render_text(report, top=10)  # must not raise


def test_render_text_with_critical_silos_prints_warning() -> None:
    neurons = [_make_neuron(f"fn{i}", "CRITICAL") for i in range(7)]
    report = SiloReport(
        neurons=neurons,
        total_neurons_scanned=20,
        silos_detected=7,
        as_of_commit=None,
    )
    _render_text(report, top=20)  # covers the critical-silo warning block


# ---------------------------------------------------------------------------
# _render_json
# ---------------------------------------------------------------------------

def test_render_json_outputs_valid_json() -> None:
    report = SiloReport(
        neurons=[_make_neuron()],
        total_neurons_scanned=5,
        silos_detected=1,
        as_of_commit="abc1234",
    )
    runner = CliRunner()

    @click.command()
    def _cmd() -> None:
        _render_json(report)

    result = runner.invoke(_cmd, [])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["silos_detected"] == 1
    assert data["as_of_commit"] == "abc1234"
    assert len(data["neurons"]) == 1


def test_render_json_no_commit() -> None:
    report = SiloReport(neurons=[], total_neurons_scanned=0, silos_detected=0, as_of_commit=None)
    runner = CliRunner()

    @click.command()
    def _cmd() -> None:
        _render_json(report)

    result = runner.invoke(_cmd, [])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["as_of_commit"] is None


# ---------------------------------------------------------------------------
# cerebrofy_silo CLI command
# ---------------------------------------------------------------------------

def test_silo_command_text_output_exits_zero() -> None:
    result = _invoke([])
    assert result.exit_code == 0


def test_silo_command_json_output_is_parseable() -> None:
    result = _invoke(["--output", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "neurons" in data
    assert data["silos_detected"] == 1


def test_silo_command_passes_filter_args() -> None:
    result = _invoke(["--lobe", "auth", "--risk", "HIGH", "--top", "5"])
    assert result.exit_code == 0


def test_silo_command_write_memories_flag() -> None:
    result = _invoke(["--write-memories"])
    assert result.exit_code == 0


def test_silo_command_schema_error_exits_one() -> None:
    runner = CliRunner()
    mock_conn = MagicMock(spec=sqlite3.Connection)
    with patch("cerebrofy.commands.silo._find_repo_root", return_value=Path("/repo")), \
         patch("cerebrofy.commands.silo._open_db_ro", return_value=mock_conn), \
         patch("cerebrofy.commands.silo.check_schema_version",
               side_effect=ValueError("v1 != v2")):
        result = runner.invoke(cerebrofy_silo, [])
    assert result.exit_code == 1
    assert "migrate" in result.output
