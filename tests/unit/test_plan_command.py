"""Unit tests for commands/plan.py and mcp/tools/plan.py — entry points (Idea #12)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import sqlite_vec  # type: ignore[import-untyped]
from click.testing import CliRunner

from cerebrofy.commands.plan import cerebrofy_plan
from cerebrofy.db.schema import create_schema
from cerebrofy.graph.edges import LOCAL_CALL
from cerebrofy.planning.planner import CLUSTER_TOO_LARGE, PlanError

_EXACT = [1.0, 0.0, 0.0, 0.0]
_NEAR = [0.9, 0.1, 0.0, 0.0]

_EXPECTED_KEYS = {
    "cluster", "proposed_structure", "callers_to_update",
    "steps", "estimated_hours", "files_affected",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_config(tmp_path: Path, *, embedding_model: str = "local") -> None:
    cfg_dir = tmp_path / ".cerebrofy"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.yaml").write_text(
        "lobes:\n  root: .\n"
        "tracked_extensions: [.py]\n"
        f"embedding_model: {embedding_model}\n"
        "embed_dim: 4\n",
        encoding="utf-8",
    )


def _write_index(tmp_path: Path, *, seed_count: int = 2) -> None:
    db_path = tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    create_schema(conn, embed_dim=4)
    conn.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '1')")

    def node(nid: str, name: str, file: str, line: int = 1) -> None:
        conn.execute(
            "INSERT INTO nodes(id, name, file, type, line_start, line_end)"
            " VALUES (?,?,?,?,?,?)",
            (nid, name, file, "function", line, line + 9),
        )

    def vec(nid: str, embedding: list[float]) -> None:
        conn.execute(
            "INSERT INTO vec_neurons(id, embedding) VALUES (?, vec_f32(?))",
            (nid, json.dumps(embedding)),
        )

    def edge(src: str, dst: str) -> None:
        conn.execute(
            "INSERT INTO edges(src_id, dst_id, rel_type, file) VALUES (?,?,?,?)",
            (src, dst, LOCAL_CALL, "src/main.py"),
        )

    node("pay_a", "charge", "src/pay/charge.py", line=10)
    vec("pay_a", _EXACT)
    if seed_count >= 2:
        node("pay_b", "refund", "src/pay/refund.py", line=20)
        vec("pay_b", _NEAR)
        node("caller", "route", "src/api/routes.py", line=5)
        edge("caller", "pay_a")
        edge("caller", "sinks/caller-0")
        edge("caller", "sinks/caller-1")
    conn.commit()
    conn.close()


def _fake_embedding(*args: Any, **kwargs: Any) -> list[float]:
    return list(_EXACT)


@pytest.fixture()
def cli_runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# CLI — NO_INDEX paths
# ---------------------------------------------------------------------------

def test_cli_no_cerebrofy_dir_reports_no_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli_runner: CliRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    result = cli_runner.invoke(cerebrofy_plan, ["extract the auth helpers"])
    assert result.exit_code == 1
    assert "[NO_INDEX]" in result.output


def test_cli_missing_db_reports_no_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli_runner: CliRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)  # config exists, index does not
    result = cli_runner.invoke(cerebrofy_plan, ["extract the auth helpers"])
    assert result.exit_code == 1
    assert "[NO_INDEX]" in result.output
    assert "cerebrofy build" in result.output


def test_cli_embedding_model_none_reports_value_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli_runner: CliRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path, embedding_model="none")
    _write_index(tmp_path)
    result = cli_runner.invoke(cerebrofy_plan, ["extract the auth helpers"])
    assert result.exit_code == 1
    assert "embedding_model is 'none'" in result.output


# ---------------------------------------------------------------------------
# CLI — happy paths
# ---------------------------------------------------------------------------

def test_cli_json_output_matches_spec_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli_runner: CliRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _write_index(tmp_path)
    monkeypatch.setattr("cerebrofy.commands.plan.embed_query", _fake_embedding)

    result = cli_runner.invoke(
        cerebrofy_plan,
        ["extract the payment logic into a payments service", "--output", "json"],
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert set(data) == _EXPECTED_KEYS
    assert data["proposed_structure"]["new_module"] == "payments"
    assert data["cluster"]
    assert data["steps"]
    assert isinstance(data["estimated_hours"], float)
    assert isinstance(data["files_affected"], int)


def test_cli_markdown_output_is_human_reviewable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli_runner: CliRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _write_index(tmp_path)
    monkeypatch.setattr("cerebrofy.commands.plan.embed_query", _fake_embedding)

    result = cli_runner.invoke(cerebrofy_plan, ["extract the payment logic into a service"])

    assert result.exit_code == 0, result.output
    assert "# Refactoring Plan:" in result.output
    assert "## Step-by-Step Migration Plan" in result.output
    assert "## Execution Handoff" not in result.output  # dry run by default


def test_cli_cluster_too_small(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli_runner: CliRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _write_index(tmp_path, seed_count=1)
    monkeypatch.setattr("cerebrofy.commands.plan.embed_query", _fake_embedding)

    result = cli_runner.invoke(cerebrofy_plan, ["extract the auth helpers"])

    assert result.exit_code == 1
    assert "[CLUSTER_TOO_SMALL]" in result.output


def test_cli_execute_flag_attaches_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli_runner: CliRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _write_index(tmp_path)
    monkeypatch.setattr("cerebrofy.commands.plan.embed_query", _fake_embedding)
    monkeypatch.setattr(
        "cerebrofy.planning.planner._execution_handoff",
        lambda *args, **kwargs: "context window packed — ready",
    )

    result = cli_runner.invoke(cerebrofy_plan, ["extract the payment logic", "--execute"])

    assert result.exit_code == 0, result.output
    assert "## Execution Handoff" in result.output
    assert "context window packed — ready" in result.output


def test_cli_plan_error_is_rendered_with_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cli_runner: CliRunner
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _write_index(tmp_path)

    def _raise(**kwargs: Any) -> Any:
        raise PlanError(CLUSTER_TOO_LARGE, "999 neurons matched — scope narrower")

    monkeypatch.setattr("cerebrofy.commands.plan.embed_query", _fake_embedding)
    monkeypatch.setattr("cerebrofy.commands.plan.build_refactor_plan", _raise)

    result = cli_runner.invoke(cerebrofy_plan, ["extract everything"])

    assert result.exit_code == 1
    assert "[CLUSTER_TOO_LARGE] 999 neurons matched — scope narrower" in result.output


# ---------------------------------------------------------------------------
# MCP handler (skipped when mcp extra not installed)
# ---------------------------------------------------------------------------

def _get_handle_plan():
    """Lazy import — skipped if mcp extra not installed."""
    pytest.importorskip("mcp")
    from cerebrofy.mcp.tools.plan import handle_plan as _hp
    return _hp


def test_mcp_plan_requires_description() -> None:
    handle_plan = _get_handle_plan()
    result = handle_plan({})
    assert "description" in result[0].text
    assert "required" in result[0].text


def test_mcp_plan_rejects_whitespace_description() -> None:
    handle_plan = _get_handle_plan()
    result = handle_plan({"description": "   "})
    assert "'description' is required" in result[0].text


def test_mcp_plan_rejects_unknown_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle_plan = _get_handle_plan()
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    result = handle_plan({"description": "extract auth", "format": "xml"})
    assert "'format' must be 'markdown' or 'json'" in result[0].text


def test_mcp_plan_no_index_reports_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle_plan = _get_handle_plan()
    monkeypatch.chdir(tmp_path)
    result = handle_plan({"description": "extract auth"})
    assert "NO_INDEX" in result[0].text


def test_mcp_plan_missing_db_reports_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle_plan = _get_handle_plan()
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    result = handle_plan({"description": "extract auth"})
    assert "[NO_INDEX]" in result[0].text
    assert "cerebrofy build" in result[0].text


def test_mcp_plan_json_payload_matches_spec_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle_plan = _get_handle_plan()
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _write_index(tmp_path)
    monkeypatch.setattr("cerebrofy.search.hybrid.embed_query", _fake_embedding)

    result = handle_plan({
        "description": "extract the payment logic into a payments service",
        "format": "json",
    })

    data = json.loads(result[0].text)
    assert set(data) == _EXPECTED_KEYS
    assert data["proposed_structure"]["new_module"] == "payments"


def test_mcp_plan_markdown_default_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle_plan = _get_handle_plan()
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _write_index(tmp_path)
    monkeypatch.setattr("cerebrofy.search.hybrid.embed_query", _fake_embedding)

    result = handle_plan({"description": "extract the payment logic"})

    assert "## Step-by-Step Migration Plan" in result[0].text
    assert "## Execution Handoff" not in result[0].text


def test_mcp_plan_dry_run_false_adds_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle_plan = _get_handle_plan()
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _write_index(tmp_path)
    monkeypatch.setattr("cerebrofy.search.hybrid.embed_query", _fake_embedding)
    monkeypatch.setattr(
        "cerebrofy.planning.planner._execution_handoff",
        lambda *args, **kwargs: "handoff window ready",
    )

    result = handle_plan({
        "description": "extract the payment logic",
        "dry_run": False,
    })

    assert "## Execution Handoff" in result[0].text
    assert "handoff window ready" in result[0].text


def test_mcp_plan_handler_never_writes_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handle_plan = _get_handle_plan()
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _write_index(tmp_path)
    monkeypatch.setattr("cerebrofy.search.hybrid.embed_query", _fake_embedding)

    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    handle_plan({"description": "extract the payment logic"})
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))

    assert before == after


def test_mcp_plan_surfaces_value_error_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unexpected ValueError from the planner is reported, not raised."""
    handle_plan = _get_handle_plan()
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _write_index(tmp_path)
    monkeypatch.setattr("cerebrofy.search.hybrid.embed_query", _fake_embedding)

    def _raise(**kwargs: Any) -> Any:
        raise ValueError("boom")

    monkeypatch.setattr("cerebrofy.planning.planner.build_refactor_plan", _raise)
    # handle_plan imports build_refactor_plan at call time from the planner module.
    result = handle_plan({"description": "extract the payment logic"})
    assert "[error] boom" in result[0].text


def test_mcp_plan_is_importable_with_simple_namespace_result_shape() -> None:
    """The handler always returns TextContent-compatible items."""
    handle_plan = _get_handle_plan()
    result = handle_plan({"description": ""})
    assert isinstance(result, list)
    assert hasattr(result[0], "type") and result[0].type == "text"
