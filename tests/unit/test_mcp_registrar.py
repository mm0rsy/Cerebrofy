"""Unit tests for cerebrofy.mcp.registrar."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cerebrofy.mcp.registrar import (
    MCP_ENTRY,
    MCP_FALLBACK_SNIPPET,
    find_writable_mcp_config,
    has_cerebrofy_mcp_entry,
    warn_if_multiple_installations,
    write_mcp_entry,
)


# ---------------------------------------------------------------------------
# has_cerebrofy_mcp_entry
# ---------------------------------------------------------------------------


def test_has_entry_returns_false_for_missing_file(tmp_path: Path) -> None:
    assert not has_cerebrofy_mcp_entry(tmp_path / "nonexistent.json")


def test_has_entry_returns_true_when_key_present(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    cfg.write_text(
        json.dumps({"mcpServers": {"cerebrofy": MCP_ENTRY}}),
        encoding="utf-8",
    )
    assert has_cerebrofy_mcp_entry(cfg)


def test_has_entry_returns_false_when_key_absent(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"other": {}}}), encoding="utf-8")
    assert not has_cerebrofy_mcp_entry(cfg)


def test_has_entry_returns_false_for_invalid_json(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    cfg.write_text("NOT JSON", encoding="utf-8")
    assert not has_cerebrofy_mcp_entry(cfg)


def test_has_entry_returns_false_for_empty_file(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    cfg.write_text("", encoding="utf-8")
    assert not has_cerebrofy_mcp_entry(cfg)


# ---------------------------------------------------------------------------
# write_mcp_entry
# ---------------------------------------------------------------------------


def test_write_mcp_entry_creates_file_when_missing(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    write_mcp_entry(cfg)
    assert cfg.exists()
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert "cerebrofy" in data["mcpServers"]


def test_write_mcp_entry_merges_into_existing(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    existing = {"mcpServers": {"other-tool": {"command": "other"}}}
    cfg.write_text(json.dumps(existing), encoding="utf-8")
    write_mcp_entry(cfg)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert "other-tool" in data["mcpServers"]
    assert "cerebrofy" in data["mcpServers"]


def test_write_mcp_entry_is_idempotent(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    write_mcp_entry(cfg)
    write_mcp_entry(cfg)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert list(data["mcpServers"].keys()).count("cerebrofy") == 1


def test_write_mcp_entry_handles_corrupt_json(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    cfg.write_text("{INVALID}", encoding="utf-8")
    # Should not raise — falls back to empty dict
    write_mcp_entry(cfg)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert "cerebrofy" in data["mcpServers"]


def test_write_mcp_entry_stores_correct_command(tmp_path: Path) -> None:
    cfg = tmp_path / "mcp.json"
    write_mcp_entry(cfg)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    entry = data["mcpServers"]["cerebrofy"]
    assert entry["command"] == "cerebrofy"
    assert "mcp" in entry["args"]


# ---------------------------------------------------------------------------
# MCP_FALLBACK_SNIPPET
# ---------------------------------------------------------------------------


def test_fallback_snippet_is_valid_json() -> None:
    data = json.loads(MCP_FALLBACK_SNIPPET)
    assert "mcpServers" in data
    assert "cerebrofy" in data["mcpServers"]


# ---------------------------------------------------------------------------
# find_writable_mcp_config
# ---------------------------------------------------------------------------


def test_find_writable_mcp_config_returns_existing_file(tmp_path: Path) -> None:
    """If a file from the priority list exists and is writable, it should be returned."""
    from unittest.mock import patch

    fake_path = tmp_path / "mcp.json"
    fake_path.write_text("{}", encoding="utf-8")

    # find_writable_mcp_config() takes no args; patch the priority list
    with patch("cerebrofy.mcp.registrar.MCP_CONFIG_PRIORITY_LIST", [fake_path]):
        result = find_writable_mcp_config()

    assert result == fake_path


def test_find_writable_mcp_config_returns_fallback_when_no_file_exists(tmp_path: Path) -> None:
    from unittest.mock import patch

    nonexistent = tmp_path / "subdir" / "does_not_exist.json"
    # When no existing+writable path is found AND the parent doesn't exist,
    # the function creates the fallback dir and returns the fallback path.
    with patch("cerebrofy.mcp.registrar.MCP_CONFIG_PRIORITY_LIST", [nonexistent]):
        result = find_writable_mcp_config()

    # It should return *some* Path (the fallback)
    assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# warn_if_multiple_installations
# ---------------------------------------------------------------------------


def test_warn_if_multiple_installations_no_output_when_single(
    capsys: pytest.CaptureFixture[str]
) -> None:
    from unittest.mock import patch

    # Simulate only one installation detected
    with patch("cerebrofy.mcp.registrar.detect_multiple_installations", return_value=["/usr/bin/cerebrofy"]):
        warn_if_multiple_installations()

    captured = capsys.readouterr()
    assert "Warning" not in captured.out and "Warning" not in captured.err
