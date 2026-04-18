"""Unit tests for cerebrofy.config.loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cerebrofy.config.loader import (
    DEFAULT_TRACKED_EXTENSIONS,
    CerebrоfyConfig,
    build_default_config,
    load_config,
    validate_config,
    write_config,
)


# ---------------------------------------------------------------------------
# build_default_config
# ---------------------------------------------------------------------------


def test_build_default_config_returns_dict() -> None:
    result = build_default_config({"src": "src/"})
    assert isinstance(result, dict)
    assert result["lobes"] == {"src": "src/"}
    assert result["tracked_extensions"] == DEFAULT_TRACKED_EXTENSIONS
    assert result["embedding_model"] == "local"
    assert result["embed_dim"] == 768
    assert result["top_k"] == 10


def test_build_default_config_empty_lobes() -> None:
    result = build_default_config({})
    assert result["lobes"] == {}


# ---------------------------------------------------------------------------
# write_config + load_config round-trip
# ---------------------------------------------------------------------------


def test_write_and_load_config_roundtrip(tmp_path: Path) -> None:
    cfg_dict = build_default_config({"app": "src/app/"})
    cfg_path = tmp_path / ".cerebrofy" / "config.yaml"
    write_config(cfg_dict, cfg_path)

    assert cfg_path.exists()
    loaded = load_config(cfg_path)
    assert loaded.lobes == {"app": "src/app/"}
    assert loaded.embedding_model == "local"
    assert loaded.embed_dim == 768
    assert loaded.top_k == 10


def test_write_config_creates_parent_dirs(tmp_path: Path) -> None:
    cfg_path = tmp_path / "deep" / "nested" / "config.yaml"
    write_config(build_default_config({"x": "x/"}), cfg_path)
    assert cfg_path.exists()


def test_load_config_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nonexistent.yaml")


def test_load_config_custom_values(tmp_path: Path) -> None:
    cfg_dict = {
        "lobes": {"api": "src/api/"},
        "tracked_extensions": [".py", ".ts"],
        "embedding_model": "openai",
        "embed_dim": 1536,
        "llm_endpoint": "https://api.openai.com/v1",
        "llm_model": "gpt-4",
        "top_k": 5,
    }
    cfg_path = tmp_path / "config.yaml"
    with open(cfg_path, "w") as f:
        yaml.dump(cfg_dict, f)

    loaded = load_config(cfg_path)
    assert loaded.lobes == {"api": "src/api/"}
    assert loaded.tracked_extensions == [".py", ".ts"]
    assert loaded.embedding_model == "openai"
    assert loaded.embed_dim == 1536
    assert loaded.llm_model == "gpt-4"
    assert loaded.top_k == 5


def test_load_config_default_optional_fields(tmp_path: Path) -> None:
    """Fields not in YAML get the dataclass defaults."""
    cfg_dict = {
        "lobes": {"core": "src/"},
        "tracked_extensions": [".py"],
    }
    cfg_path = tmp_path / "config.yaml"
    with open(cfg_path, "w") as f:
        yaml.dump(cfg_dict, f)

    loaded = load_config(cfg_path)
    assert loaded.embedding_model == "local"
    assert loaded.llm_endpoint == ""
    assert loaded.top_k == 10


# ---------------------------------------------------------------------------
# validate_config
# ---------------------------------------------------------------------------


def test_validate_config_empty_lobes_warning(tmp_path: Path) -> None:
    cfg = CerebrоfyConfig(lobes={}, tracked_extensions=[".py"])
    queries_dir = tmp_path / "queries"
    queries_dir.mkdir()
    (queries_dir / "python.scm").write_text("", encoding="utf-8")
    warnings = validate_config(cfg, queries_dir)
    assert any("lobes" in w for w in warnings)


def test_validate_config_empty_extensions_warning(tmp_path: Path) -> None:
    cfg = CerebrоfyConfig(lobes={"src": "src/"}, tracked_extensions=[])
    warnings = validate_config(cfg, tmp_path)
    assert any("tracked_extensions" in w for w in warnings)


def test_validate_config_missing_scm_warning(tmp_path: Path) -> None:
    queries_dir = tmp_path / "queries"
    queries_dir.mkdir()
    # No .scm file for .rs
    cfg = CerebrоfyConfig(lobes={"src": "src/"}, tracked_extensions=[".rs"])
    warnings = validate_config(cfg, queries_dir)
    assert any(".rs" in w for w in warnings)


def test_validate_config_embed_dim_mismatch_warning(tmp_path: Path) -> None:
    queries_dir = tmp_path / "queries"
    queries_dir.mkdir()
    cfg = CerebrоfyConfig(
        lobes={"src": "src/"},
        tracked_extensions=[],
        embedding_model="openai",
        embed_dim=999,  # Wrong for openai (expected 1536)
    )
    warnings = validate_config(cfg, queries_dir)
    assert any("embed_dim" in w for w in warnings)


def test_validate_config_no_warnings_for_valid_config(tmp_path: Path) -> None:
    queries_dir = tmp_path / "queries"
    queries_dir.mkdir()
    (queries_dir / "python.scm").write_text("", encoding="utf-8")
    cfg = CerebrоfyConfig(
        lobes={"src": "src/"},
        tracked_extensions=[".py"],
        embedding_model="local",
        embed_dim=768,
    )
    warnings = validate_config(cfg, queries_dir)
    # No embed_dim mismatch, no lobes/extensions warning
    assert not any("embed_dim" in w for w in warnings)
    assert not any("lobes" in w for w in warnings)
    assert not any("tracked_extensions" in w for w in warnings)
