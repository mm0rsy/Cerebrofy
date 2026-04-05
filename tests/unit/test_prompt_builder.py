"""Unit tests for cerebrofy.llm.prompt_builder."""

from __future__ import annotations

import string
from pathlib import Path

import pytest

from cerebrofy.llm.prompt_builder import (
    DEFAULT_SYSTEM_PROMPT,
    _build_lobe_context,
    _load_template,
)


# ---------------------------------------------------------------------------
# T040: _load_template
# ---------------------------------------------------------------------------


def test_load_template_none_returns_default() -> None:
    """None template_path → returns Template wrapping DEFAULT_SYSTEM_PROMPT."""
    tmpl = _load_template(None, "/some/root")
    assert isinstance(tmpl, string.Template)
    assert tmpl.template == DEFAULT_SYSTEM_PROMPT


def test_load_template_empty_string_returns_default() -> None:
    """Empty string → returns built-in default."""
    tmpl = _load_template("", "/some/root")
    assert tmpl.template == DEFAULT_SYSTEM_PROMPT


def test_load_template_reads_file(tmp_path: Path) -> None:
    """Valid file path → content is loaded into Template."""
    tpl_file = tmp_path / "my_prompt.txt"
    tpl_file.write_text("Hello $lobe_context world", encoding="utf-8")
    tmpl = _load_template("my_prompt.txt", str(tmp_path))
    assert tmpl.template == "Hello $lobe_context world"


def test_load_template_missing_file_raises(tmp_path: Path) -> None:
    """Non-existent file → FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="system_prompt_template file not found"):
        _load_template("nonexistent.txt", str(tmp_path))


# ---------------------------------------------------------------------------
# T041: _build_lobe_context
# ---------------------------------------------------------------------------


def test_build_lobe_context_empty() -> None:
    """Empty lobe_files → returns empty string."""
    assert _build_lobe_context({}) == ""


def test_build_lobe_context_two_lobes_alphabetical(tmp_path: Path) -> None:
    """Two lobes → content concatenated alphabetically by lobe name."""
    (tmp_path / "beta_lobe.md").write_text("Beta content", encoding="utf-8")
    (tmp_path / "alpha_lobe.md").write_text("Alpha content", encoding="utf-8")

    lobe_files = {
        "beta": str(tmp_path / "beta_lobe.md"),
        "alpha": str(tmp_path / "alpha_lobe.md"),
    }
    result = _build_lobe_context(lobe_files)

    alpha_pos = result.index("Alpha content")
    beta_pos = result.index("Beta content")
    assert alpha_pos < beta_pos, "alpha lobe must appear before beta lobe"
    assert "## alpha" in result
    assert "## beta" in result


def test_build_lobe_context_missing_file_silently_skipped(tmp_path: Path) -> None:
    """Missing lobe file → silently skipped, no error."""
    existing = tmp_path / "auth_lobe.md"
    existing.write_text("Auth content", encoding="utf-8")

    lobe_files = {
        "auth": str(existing),
        "ghost": str(tmp_path / "ghost_lobe.md"),  # does not exist
    }
    result = _build_lobe_context(lobe_files)
    assert "Auth content" in result
    assert "ghost" not in result
