"""Integration tests for cerebrofy mcp (T078)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from cerebrofy.cli import main


# ---------------------------------------------------------------------------
# T078a: import guard — exits 1 with clear error when mcp package absent
# ---------------------------------------------------------------------------


def test_mcp_import_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """cerebrofy mcp without `mcp` package installed → exit 1 with helpful error."""
    import builtins
    real_import = builtins.__import__

    def import_blocker(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    runner = CliRunner()
    with patch("builtins.__import__", side_effect=import_blocker):
        result = runner.invoke(main, ["mcp"])

    assert result.exit_code == 1
    assert "mcp" in result.output.lower() or "mcp" in (result.exception or "")
    assert "pip install" in result.output or "cerebrofy[mcp]" in result.output


# ---------------------------------------------------------------------------
# T078b: build tool returns [success] prefix
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path) -> None:
    config_dir = tmp_path / ".cerebrofy"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(
        "lobes:\n  root: .\n"
        "tracked_extensions: [.py]\n"
        "embedding_model: local\n"
        "embed_dim: 2\n",
        encoding="utf-8",
    )


def test_mcp_build_tool_returns_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP cerebrofy_build tool returns [success] or [error] prefix."""
    monkeypatch.chdir(tmp_path)
    _make_config(tmp_path)

    # Simulate a fast successful subprocess run
    fake_result = type("R", (), {"returncode": 0, "stdout": "Build complete.", "stderr": ""})()

    with patch("subprocess.run", return_value=fake_result):
        from cerebrofy.mcp.server import _handle_build
        result = _handle_build({})

    assert len(result) == 1
    assert result[0].text.startswith("[success]")


def test_mcp_build_tool_returns_error_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP cerebrofy_build tool returns [error] prefix when cerebrofy exits non-zero."""
    monkeypatch.chdir(tmp_path)
    _make_config(tmp_path)

    fake_result = type("R", (), {"returncode": 1, "stdout": "", "stderr": "Build failed."})()

    with patch("subprocess.run", return_value=fake_result):
        from cerebrofy.mcp.server import _handle_build
        result = _handle_build({})

    assert len(result) == 1
    assert result[0].text.startswith("[error]")


# ---------------------------------------------------------------------------
# T078c: update tool with and without path argument
# ---------------------------------------------------------------------------


def test_mcp_update_tool_no_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP cerebrofy_update tool auto-detects when no path argument given."""
    monkeypatch.chdir(tmp_path)
    _make_config(tmp_path)

    fake_result = type("R", (), {"returncode": 0, "stdout": "Nothing to update.", "stderr": ""})()

    calls: list[list[str]] = []

    def capture_run(cmd: list[str], **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        return fake_result

    with patch("subprocess.run", side_effect=capture_run):
        from cerebrofy.mcp.server import _handle_update
        result = _handle_update({})

    assert result[0].text.startswith("[success]")
    # No explicit path — command should be ["...", "update"]
    assert calls[0][-1] == "update"


def test_mcp_update_tool_with_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP cerebrofy_update tool passes path arg to CLI when provided."""
    monkeypatch.chdir(tmp_path)
    _make_config(tmp_path)

    fake_result = type("R", (), {"returncode": 0, "stdout": "Updated.", "stderr": ""})()

    calls: list[list[str]] = []

    def capture_run(cmd: list[str], **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        return fake_result

    with patch("subprocess.run", side_effect=capture_run):
        from cerebrofy.mcp.server import _handle_update
        result = _handle_update({"path": "src/foo.py"})

    assert result[0].text.startswith("[success]")
    assert "src/foo.py" in calls[0]


# ---------------------------------------------------------------------------
# T078d: validate tool returns drift label
# ---------------------------------------------------------------------------


def test_mcp_validate_tool_returns_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP cerebrofy_validate tool returns [clean] when exit code is 0."""
    monkeypatch.chdir(tmp_path)
    _make_config(tmp_path)

    fake_result = type("R", (), {"returncode": 0, "stdout": "No drift.", "stderr": ""})()

    with patch("subprocess.run", return_value=fake_result):
        from cerebrofy.mcp.server import _handle_validate
        result = _handle_validate({})

    assert result[0].text.startswith("[clean]")


def test_mcp_validate_tool_returns_structural_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MCP cerebrofy_validate tool returns [structural_drift] when exit code is 2."""
    monkeypatch.chdir(tmp_path)
    _make_config(tmp_path)

    fake_result = type("R", (), {"returncode": 2, "stdout": "Structural drift.", "stderr": ""})()

    with patch("subprocess.run", return_value=fake_result):
        from cerebrofy.mcp.server import _handle_validate
        result = _handle_validate({})

    assert result[0].text.startswith("[structural_drift]")


# ---------------------------------------------------------------------------
# T078e: error when no cerebrofy config found
# ---------------------------------------------------------------------------


def test_mcp_handle_build_no_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_handle_build returns error message when no .cerebrofy/config.yaml is found."""
    # Start in a directory with no cerebrofy config
    monkeypatch.chdir(tmp_path)

    from cerebrofy.mcp.server import _handle_build
    result = _handle_build({})

    assert len(result) == 1
    assert "[error]" in result[0].text
    assert "cerebrofy init" in result[0].text.lower()



# ---------------------------------------------------------------------------
