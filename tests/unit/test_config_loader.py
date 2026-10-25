"""Unit tests for cerebrofy.config.loader."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cerebrofy.config.loader import (
    DEFAULT_TRACKED_EXTENSIONS,
    CerebrоfyConfig,
    ChangelogConfig,
    ConfigError,
    DatabaseConfig,
    GovernanceConfig,
    PlanningConfig,
    SessionConfig,
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
    assert result["record_sessions"] is False
    assert "top_k" not in result
    assert "system_prompt_template" not in result


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
        "embedding_model": "none",
    }
    cfg_path = tmp_path / "config.yaml"
    with open(cfg_path, "w") as f:
        yaml.dump(cfg_dict, f)

    loaded = load_config(cfg_path)
    assert loaded.lobes == {"api": "src/api/"}
    assert loaded.tracked_extensions == [".py", ".ts"]
    assert loaded.embedding_model == "none"


def test_load_config_each_allowed_value_loads(tmp_path: Path) -> None:
    """Every value in SUPPORTED_EMBEDDING_MODELS loads without error."""
    from cerebrofy.embedder import SUPPORTED_EMBEDDING_MODELS

    for model in SUPPORTED_EMBEDDING_MODELS:
        cfg_path = tmp_path / f"config_{model}.yaml"
        cfg_path.write_text(
            yaml.dump({
                "lobes": {"src": "src/"},
                "tracked_extensions": [".py"],
                "embedding_model": model,
            }),
            encoding="utf-8",
        )
        loaded = load_config(cfg_path)
        assert loaded.embedding_model == model


def test_load_config_rejects_unknown_embedding_model(tmp_path: Path) -> None:
    """An unsupported embedding_model raises ValueError at load with a clear message."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.dump({
            "lobes": {"src": "src/"},
            "tracked_extensions": [".py"],
            "embedding_model": "openai",
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as exc_info:
        load_config(cfg_path)
    msg = str(exc_info.value)
    assert "Unsupported embedding_model 'openai'" in msg
    assert "'local'" in msg
    assert "'none'" in msg
    assert "Allowed values" in msg


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
    # embed_dim is not a CerebrофyConfig field; validate_config warns about unknown extensions
    queries_dir = tmp_path / "queries"
    queries_dir.mkdir()
    cfg = CerebrоfyConfig(
        lobes={"src": "src/"},
        tracked_extensions=[".unknown_ext"],
    )
    warnings = validate_config(cfg, queries_dir)
    assert any(".unknown_ext" in w for w in warnings)


def test_validate_config_no_warnings_for_valid_config(tmp_path: Path) -> None:
    queries_dir = tmp_path / "queries"
    queries_dir.mkdir()
    (queries_dir / "python.scm").write_text("", encoding="utf-8")
    cfg = CerebrоfyConfig(
        lobes={"src": "src/"},
        tracked_extensions=[".py"],
        embedding_model="local",
    )
    warnings = validate_config(cfg, queries_dir)
    assert not any("lobes" in w for w in warnings)
    assert not any("tracked_extensions" in w for w in warnings)


# ---------------------------------------------------------------------------
# MemoryConfig
# ---------------------------------------------------------------------------


def test_memory_config_defaults() -> None:
    from cerebrofy.config.loader import MemoryConfig
    cfg = MemoryConfig()
    assert cfg.decay_half_life_days == 70.0
    assert cfg.stale_threshold == 0.1
    assert cfg.possibly_stale_threshold == 0.3


def test_memory_config_on_cerebrofy_config() -> None:
    from cerebrofy.config.loader import MemoryConfig
    cfg = CerebrоfyConfig(lobes={}, tracked_extensions=[], embedding_model="local")
    assert isinstance(cfg.memory, MemoryConfig)
    assert cfg.memory.decay_half_life_days == 70.0


def test_load_config_parses_memory_section(tmp_path: Path) -> None:
    """load_config correctly reads a memory: section from YAML."""
    import yaml as _yaml

    from cerebrofy.config.loader import load_config
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(_yaml.dump({
        "lobes": {"src": "src/"},
        "tracked_extensions": [".py"],
        "memory": {
            "decay_half_life_days": 30.0,
            "possibly_stale_threshold": 0.4,
            "stale_threshold": 0.15,
        },
    }))
    config = load_config(cfg_file)
    assert config.memory.decay_half_life_days == 30.0
    assert config.memory.possibly_stale_threshold == 0.4
    assert config.memory.stale_threshold == 0.15


def test_load_config_memory_null_key_uses_defaults(tmp_path: Path) -> None:
    """load_config handles `memory:` set to null without crashing."""
    from cerebrofy.config.loader import MemoryConfig, load_config
    cfg_file = tmp_path / "config.yaml"
    # `memory:` with no value → YAML parses as null
    cfg_file.write_text("lobes:\n  src: src/\ntracked_extensions:\n  - .py\nmemory:\n")
    config = load_config(cfg_file)
    assert config.memory == MemoryConfig()  # all defaults


# ---------------------------------------------------------------------------
# load_arch_rules (Idea #16 — rules load through the config layer)
# ---------------------------------------------------------------------------


def _write_arch_rules_file(root: Path, text: str) -> None:
    rules_dir = root / ".cerebrofy"
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / "arch-rules.yaml").write_text(text, encoding="utf-8")


def test_load_arch_rules_none_when_missing(tmp_path: Path) -> None:
    from cerebrofy.config.loader import load_arch_rules

    assert load_arch_rules(tmp_path) is None


def test_load_arch_rules_parses_file(tmp_path: Path) -> None:
    from cerebrofy.config.loader import load_arch_rules

    _write_arch_rules_file(
        tmp_path, "rules:\n  - name: r\n    check:\n      no_cycles: lobes\n"
    )
    cfg = load_arch_rules(tmp_path)
    assert cfg is not None
    assert cfg.rule_names == ("r",)


def test_load_arch_rules_raises_on_invalid_rule(tmp_path: Path) -> None:
    from cerebrofy.arch.rules import RulesError
    from cerebrofy.config.loader import load_arch_rules

    _write_arch_rules_file(tmp_path, "rules: not-a-list\n")
    with pytest.raises(RulesError, match="'rules' must be a list"):
        load_arch_rules(tmp_path)


def test_load_arch_rules_raises_on_non_mapping_top_level(tmp_path: Path) -> None:
    from cerebrofy.arch.rules import RulesError
    from cerebrofy.config.loader import load_arch_rules

    _write_arch_rules_file(tmp_path, "- just\n- a list\n")
    with pytest.raises(RulesError, match="top-level YAML mapping"):
        load_arch_rules(tmp_path)


def test_load_arch_rules_warns_when_oversized(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from cerebrofy.config.loader import load_arch_rules

    padding = "# " + "x" * 100 + "\n"
    _write_arch_rules_file(
        tmp_path, padding * 600 + "rules:\n  - name: r\n    check:\n      no_cycles: lobes\n"
    )
    cfg = load_arch_rules(tmp_path)
    assert cfg is not None
    assert "exceeds 50KB" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Optional config sections (session / planning / changelog / database)
# ---------------------------------------------------------------------------


def _write_config(tmp_path: Path, data: dict) -> Path:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.dump(data), encoding="utf-8")
    return cfg_path


def test_config_sections_default_when_absent(tmp_path: Path) -> None:
    """Sections omitted from YAML get their dataclass defaults."""
    cfg_path = _write_config(tmp_path, {
        "lobes": {"src": "src/"},
        "tracked_extensions": [".py"],
        "embedding_model": "local",
    })
    loaded = load_config(cfg_path)
    assert loaded.session == SessionConfig()
    assert loaded.planning == PlanningConfig()
    assert loaded.changelog == ChangelogConfig()
    assert loaded.database == DatabaseConfig()


def test_config_sections_custom_values(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, {
        "lobes": {"src": "src/"},
        "tracked_extensions": [".py"],
        "embedding_model": "local",
        "session": {"max_tracked_neurons": 10, "max_refs_per_event": 7},
        "planning": {
            "min_cluster_size": 3,
            "max_cluster_size": 150,
            "generic_module_words": ["foo", "bar"],
        },
        "changelog": {"breaking_cross_lobe_threshold": 5},
        "database": {"integrity_check": "fail"},
    })
    loaded = load_config(cfg_path)
    assert loaded.session == SessionConfig(max_tracked_neurons=10, max_refs_per_event=7)
    assert loaded.planning == PlanningConfig(
        min_cluster_size=3,
        max_cluster_size=150,
        generic_module_words=frozenset({"foo", "bar"}),
    )
    assert loaded.changelog == ChangelogConfig(breaking_cross_lobe_threshold=5)
    assert loaded.database == DatabaseConfig(integrity_check="fail")


def test_config_null_section_uses_defaults(tmp_path: Path) -> None:
    """A `section:` key with a null value must fall back to defaults."""
    cfg_path = _write_config(tmp_path, {
        "lobes": {"src": "src/"},
        "tracked_extensions": [".py"],
        "embedding_model": "local",
        "session": None,
        "planning": None,
        "changelog": None,
        "database": None,
    })
    loaded = load_config(cfg_path)
    assert loaded.session == SessionConfig()
    assert loaded.planning == PlanningConfig()
    assert loaded.changelog == ChangelogConfig()
    assert loaded.database == DatabaseConfig()


# --- strict int validation -------------------------------------------------


def test_config_rejects_string_for_int(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, {
        "lobes": {"src": "src/"},
        "tracked_extensions": [".py"],
        "embedding_model": "local",
        "session": {"max_tracked_neurons": "50"},
    })
    with pytest.raises(ConfigError, match="must be an int"):
        load_config(cfg_path)


def test_config_rejects_bool_for_int(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, {
        "lobes": {"src": "src/"},
        "tracked_extensions": [".py"],
        "embedding_model": "local",
        "changelog": {"breaking_cross_lobe_threshold": True},
    })
    with pytest.raises(ConfigError, match="must be an int"):
        load_config(cfg_path)


def test_config_rejects_non_positive_int(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, {
        "lobes": {"src": "src/"},
        "tracked_extensions": [".py"],
        "embedding_model": "local",
        "planning": {"min_cluster_size": 0},
    })
    with pytest.raises(ConfigError, match="must be > 0"):
        load_config(cfg_path)


def test_config_rejects_min_greater_than_max(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, {
        "lobes": {"src": "src/"},
        "tracked_extensions": [".py"],
        "embedding_model": "local",
        "planning": {"min_cluster_size": 10, "max_cluster_size": 2},
    })
    with pytest.raises(ConfigError, match="must be <="):
        load_config(cfg_path)


def test_config_rejects_empty_generic_word(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, {
        "lobes": {"src": "src/"},
        "tracked_extensions": [".py"],
        "embedding_model": "local",
        "planning": {"generic_module_words": ["valid", ""]},
    })
    with pytest.raises(ConfigError, match="non-empty string"):
        load_config(cfg_path)


def test_config_rejects_invalid_integrity_check(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, {
        "lobes": {"src": "src/"},
        "tracked_extensions": [".py"],
        "embedding_model": "local",
        "database": {"integrity_check": "loud"},
    })
    with pytest.raises(ConfigError, match="off/warn/fail"):
        load_config(cfg_path)


def test_config_rejects_non_mapping_section(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, {
        "lobes": {"src": "src/"},
        "tracked_extensions": [".py"],
        "embedding_model": "local",
        "session": "not-a-mapping",
    })
    with pytest.raises(ConfigError, match="'session' must be a mapping"):
        load_config(cfg_path)


# --- YAML / top-level shape ------------------------------------------------


def test_config_rejects_malformed_yaml(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    # Unclosed flow sequence is not valid YAML.
    cfg_path.write_text(
        "lobes: {src: src/}\n  tracked_extensions: [1, 2\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(cfg_path)


def test_config_rejects_top_level_list(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="top-level YAML mapping"):
        load_config(cfg_path)


def test_config_rejects_top_level_none(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match="top-level YAML mapping"):
        load_config(cfg_path)


# --- Governance (Idea #18) -------------------------------------------------


def test_governance_defaults_when_absent(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, {
        "lobes": {"src": "src/"},
        "tracked_extensions": [".py"],
        "embedding_model": "local",
    })
    cfg = load_config(cfg_path)
    assert cfg.governance == GovernanceConfig()


def test_governance_custom_values(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, {
        "lobes": {"src": "src/"},
        "tracked_extensions": [".py"],
        "embedding_model": "local",
        "governance": {
            "strategy": "hybrid",
            "auto_sync_codeowners": True,
            "fallback_owner": "@platform",
            "activity_days": 30,
        },
    })
    cfg = load_config(cfg_path)
    assert cfg.governance.strategy == "hybrid"
    assert cfg.governance.auto_sync_codeowners is True
    assert cfg.governance.fallback_owner == "@platform"
    assert cfg.governance.activity_days == 30


def test_governance_rejects_unknown_strategy(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, {
        "lobes": {"src": "src/"},
        "tracked_extensions": [".py"],
        "embedding_model": "local",
        "governance": {"strategy": "vibes"},
    })
    with pytest.raises(ConfigError, match="git-blame/explicit/hybrid"):
        load_config(cfg_path)


def test_governance_rejects_non_bool_auto_sync(tmp_path: Path) -> None:
    cfg_path = _write_config(tmp_path, {
        "lobes": {"src": "src/"},
        "tracked_extensions": [".py"],
        "embedding_model": "local",
        "governance": {"auto_sync_codeowners": "yes"},
    })
    with pytest.raises(ConfigError, match="must be a boolean"):
        load_config(cfg_path)
