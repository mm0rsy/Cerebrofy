"""CerebrоfyConfig dataclass and config.yaml I/O helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from cerebrofy.errors import ConfigError

if TYPE_CHECKING:  # pragma: no cover
    from cerebrofy.arch.rules import RulesConfig


@dataclass(frozen=True)
class MemoryConfig:
    """Decay parameters for the agent memory layer."""

    decay_half_life_days: float = 70.0
    possibly_stale_threshold: float = 0.3
    stale_threshold: float = 0.1


# Words that describe the shape of an extraction rather than its new name.
# Single source of truth for PlanningConfig.generic_module_words; planner.py
# re-exports this name so its derive_module_name() logic is unaffected.
_GENERIC_MODULE_WORDS: frozenset[str] = frozenset({
    "service", "services", "module", "modules", "package", "packages",
    "library", "libraries", "directory", "folder", "layer", "code", "logic",
    "it", "everything", "separate", "own", "new",
})


@dataclass(frozen=True)
class SessionConfig:
    """Session tracking/neuron limits (FR-018)."""

    max_tracked_neurons: int = 50
    max_refs_per_event: int = 3


@dataclass(frozen=True)
class SynthesisConfig:
    """Cross-Session Synthesizer (Idea #24) trigger knobs."""

    every_n_sessions: int = 10


@dataclass(frozen=True)
class PlanningConfig:
    """Natural-language refactor planner (Idea #12) parameters."""

    generic_module_words: frozenset[str] = field(
        default_factory=lambda: _GENERIC_MODULE_WORDS,
    )
    min_cluster_size: int = 2
    max_cluster_size: int = 200


@dataclass(frozen=True)
class ChangelogConfig:
    """Changelog emission knobs."""

    breaking_cross_lobe_threshold: int = 3


@dataclass(frozen=True)
class GovernanceConfig:
    """Lobe ownership and CODEOWNERS generation knobs (Idea #18)."""

    strategy: str = "git-blame"
    auto_sync_codeowners: bool = False
    fallback_owner: str = "@tech-leads"
    activity_days: int = 90


@dataclass(frozen=True)
class DatabaseConfig:
    """SQLite index runtime knobs.

    ``integrity_check`` mirrors PRAGMA integrity_check semantics:
      * off  — skip the check entirely
      * warn — run it, log a warning if it returns anything besides ok
      * fail — run it, raise IntegrityError on any non-ok result
    Validation of the allowed values happens at parse time (see
    ``_parse_database``); this class is a plain value object.
    """

    integrity_check: str = "warn"


@dataclass(frozen=True)
class CerebrоfyConfig:
    """Full contents of `.cerebrofy/config.yaml`."""

    lobes: dict[str, str]
    tracked_extensions: list[str]
    embedding_model: str = "local"
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    synthesis: SynthesisConfig = field(default_factory=SynthesisConfig)
    planning: PlanningConfig = field(default_factory=PlanningConfig)
    changelog: ChangelogConfig = field(default_factory=ChangelogConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    governance: GovernanceConfig = field(default_factory=GovernanceConfig)
    record_sessions: bool = False


DEFAULT_TRACKED_EXTENSIONS: list[str] = [
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java", ".rb",
    ".cpp", ".c", ".h",
]


def validate_config(config: CerebrоfyConfig, queries_dir: Path) -> list[str]:
    """Validate config fields and return a list of warning strings (never raises)."""
    warnings: list[str] = []

    if not config.lobes:
        warnings.append("config.yaml: 'lobes' is empty — no directories will be indexed.")

    if not config.tracked_extensions:
        warnings.append("config.yaml: 'tracked_extensions' is empty — no files will be parsed.")

    for ext in config.tracked_extensions:
        # EXTENSION_TO_LANGUAGE maps .h → c_header, so check the scm name accordingly
        from cerebrofy.parser.engine import EXTENSION_TO_LANGUAGE
        lang_name = EXTENSION_TO_LANGUAGE.get(ext)
        if lang_name:
            scm = queries_dir / f"{lang_name}.scm"
        else:
            scm = queries_dir / f"{ext.lstrip('.')}.scm"
        if not scm.exists():
            warnings.append(
                f"config.yaml: no .scm file for extension '{ext}' in {queries_dir} — "
                f"files with this extension will be skipped."
            )

    return warnings


def build_default_config(lobes: dict[str, str]) -> dict:  # type: ignore[type-arg]
    """Return a plain dict matching the config.yaml schema with defaults."""
    return {
        "lobes": lobes,
        "tracked_extensions": DEFAULT_TRACKED_EXTENSIONS,
        "embedding_model": "local",
        "governance": {
            "strategy": "git-blame",
            "auto_sync_codeowners": False,
            "fallback_owner": "@tech-leads",
            "activity_days": 90,
        },
        "synthesis": {
            "every_n_sessions": 10,
        },
        "record_sessions": False,
    }


def write_config(config: dict, path: Path) -> None:  # type: ignore[type-arg]
    """Write config dict as YAML to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


# ---------------------------------------------------------------------------
# Optional section parsing + strict validation
# ---------------------------------------------------------------------------

_ALLOWED_INTEGRITY: frozenset[str] = frozenset({"off", "warn", "fail"})


def _int_field(value: object, section: str, key: str) -> int:
    """Validate *value* is a positive int (bool rejected) and return it."""
    # bool is a subclass of int — reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            f"config.yaml: {section}.{key} must be an int, "
            f"got {value!r} ({type(value).__name__})"
        )
    if value <= 0:
        raise ConfigError(f"config.yaml: {section}.{key} must be > 0")
    return value


def _require_mapping(raw: object, section: str) -> dict:  # type: ignore[type-arg]
    """Return *raw* as a dict, or raise ConfigError naming *section*."""
    if not isinstance(raw, dict):
        raise ConfigError(
            f"config.yaml: '{section}' must be a mapping, got {type(raw).__name__}"
        )
    return raw


def _validate_word_set(raw_words: object) -> frozenset[str]:
    """Validate a generic_module_words list/tuple and return a frozenset."""
    if not isinstance(raw_words, (list, tuple)):
        raise ConfigError(
            "config.yaml: planning.generic_module_words must be a list/tuple "
            "of non-empty strings"
        )
    words: set[str] = set()
    for word in raw_words:
        if not isinstance(word, str) or not word.strip():
            raise ConfigError(
                "config.yaml: planning.generic_module_words: each entry must be "
                "a non-empty string"
            )
        words.add(word)
    return frozenset(words)


def _parse_session(raw: object) -> SessionConfig:
    """Parse and validate the optional ``session:`` mapping."""
    if raw is None:
        return SessionConfig()
    raw = _require_mapping(raw, "session")
    default = SessionConfig()
    return SessionConfig(
        max_tracked_neurons=_int_field(
            raw.get("max_tracked_neurons", default.max_tracked_neurons),
            "session", "max_tracked_neurons",
        ),
        max_refs_per_event=_int_field(
            raw.get("max_refs_per_event", default.max_refs_per_event),
            "session", "max_refs_per_event",
        ),
    )


def _parse_synthesis(raw: object) -> SynthesisConfig:
    """Parse and validate the optional ``synthesis:`` mapping."""
    if raw is None:
        return SynthesisConfig()
    raw = _require_mapping(raw, "synthesis")
    default = SynthesisConfig()
    return SynthesisConfig(
        every_n_sessions=_int_field(
            raw.get("every_n_sessions", default.every_n_sessions),
            "synthesis",
            "every_n_sessions",
        ),
    )


def _parse_planning(raw: object) -> PlanningConfig:
    """Parse and validate the optional ``planning:`` mapping."""
    if raw is None:
        return PlanningConfig()
    raw = _require_mapping(raw, "planning")
    default = PlanningConfig()
    min_c = _int_field(
        raw.get("min_cluster_size", default.min_cluster_size),
        "planning", "min_cluster_size",
    )
    max_c = _int_field(
        raw.get("max_cluster_size", default.max_cluster_size),
        "planning", "max_cluster_size",
    )
    if min_c > max_c:
        raise ConfigError(
            f"config.yaml: planning.min_cluster_size ({min_c}) must be <= "
            f"max_cluster_size ({max_c})"
        )
    if "generic_module_words" in raw:
        generic_words = _validate_word_set(raw["generic_module_words"])
    else:
        generic_words = default.generic_module_words
    return PlanningConfig(
        generic_module_words=generic_words,
        min_cluster_size=min_c,
        max_cluster_size=max_c,
    )


def _parse_changelog(raw: object) -> ChangelogConfig:
    """Parse and validate the optional ``changelog:`` mapping."""
    if raw is None:
        return ChangelogConfig()
    raw = _require_mapping(raw, "changelog")
    default = ChangelogConfig()
    return ChangelogConfig(
        breaking_cross_lobe_threshold=_int_field(
            raw.get("breaking_cross_lobe_threshold", default.breaking_cross_lobe_threshold),
            "changelog", "breaking_cross_lobe_threshold",
        )
    )


def _parse_database(raw: object) -> DatabaseConfig:
    """Parse and validate the optional ``database:`` mapping."""
    if raw is None:
        return DatabaseConfig()
    raw = _require_mapping(raw, "database")
    default = DatabaseConfig()
    integrity = raw.get("integrity_check", default.integrity_check)
    if not isinstance(integrity, str) or integrity not in _ALLOWED_INTEGRITY:
        raise ConfigError(
            "config.yaml: database.integrity_check must be one of "
            f"off/warn/fail, got {integrity!r}"
        )
    return DatabaseConfig(integrity_check=integrity)


_ALLOWED_OWNERSHIP_STRATEGIES: frozenset[str] = frozenset(
    {"git-blame", "explicit", "hybrid"}
)


def _parse_governance(raw: object) -> GovernanceConfig:
    """Parse and validate the optional ``governance:`` mapping."""
    if raw is None:
        return GovernanceConfig()
    raw = _require_mapping(raw, "governance")
    default = GovernanceConfig()

    strategy = raw.get("strategy", default.strategy)
    if not isinstance(strategy, str) or strategy not in _ALLOWED_OWNERSHIP_STRATEGIES:
        raise ConfigError(
            "config.yaml: governance.strategy must be one of "
            f"git-blame/explicit/hybrid, got {strategy!r}"
        )

    auto_sync = raw.get("auto_sync_codeowners", default.auto_sync_codeowners)
    if not isinstance(auto_sync, bool):
        raise ConfigError(
            "config.yaml: governance.auto_sync_codeowners must be a boolean, "
            f"got {auto_sync!r}"
        )

    fallback_owner = raw.get("fallback_owner", default.fallback_owner)
    if not isinstance(fallback_owner, str) or not fallback_owner.strip():
        raise ConfigError(
            "config.yaml: governance.fallback_owner must be a non-empty string"
        )

    return GovernanceConfig(
        strategy=strategy,
        auto_sync_codeowners=auto_sync,
        fallback_owner=fallback_owner.strip(),
        activity_days=_int_field(
            raw.get("activity_days", default.activity_days),
            "governance",
            "activity_days",
        ),
    )


def load_config(path: Path, queries_dir: Path | None = None) -> CerebrоfyConfig:
    """Load and parse config.yaml into a CerebrоfyConfig. Raises FileNotFoundError if missing.

    If queries_dir is provided, validate_config() is called and warnings are printed to stderr.
    """
    import sys

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top-level YAML mapping expected")

    raw_memory = data.get("memory") or {}
    _default = MemoryConfig()
    memory_cfg = MemoryConfig(
        decay_half_life_days=float(raw_memory.get("decay_half_life_days", _default.decay_half_life_days)),
        possibly_stale_threshold=float(raw_memory.get("possibly_stale_threshold", _default.possibly_stale_threshold)),
        stale_threshold=float(raw_memory.get("stale_threshold", _default.stale_threshold)),
    )
    embedding_model = data.get("embedding_model", "local")
    # Fail fast: reject unsupported embedding_model values at config load time
    # so an unknown identifier never reaches the embedder-selection code path
    # unchecked. Validates against the single source of truth in the embedder
    # package (SUPPORTED_EMBEDDING_MODELS).
    from cerebrofy.embedder import validate_embedding_model
    validate_embedding_model(embedding_model)

    session_cfg = _parse_session(data.get("session"))
    synthesis_cfg = _parse_synthesis(data.get("synthesis"))
    planning_cfg = _parse_planning(data.get("planning"))
    changelog_cfg = _parse_changelog(data.get("changelog"))
    database_cfg = _parse_database(data.get("database"))
    governance_cfg = _parse_governance(data.get("governance"))

    config = CerebrоfyConfig(
        lobes=data["lobes"],
        tracked_extensions=data["tracked_extensions"],
        embedding_model=embedding_model,
        memory=memory_cfg,
        session=session_cfg,
        synthesis=synthesis_cfg,
        planning=planning_cfg,
        changelog=changelog_cfg,
        database=database_cfg,
        governance=governance_cfg,
        record_sessions=bool(data.get("record_sessions", False)),
    )
    if queries_dir is not None:
        for warning in validate_config(config, queries_dir):
            print(f"Warning: {warning}", file=sys.stderr)
    return config


# ---------------------------------------------------------------------------
# arch-rules.yaml (Idea #16) — the architecture drift rules are part of the
# project configuration surface, so they load through this module per spec.
# ---------------------------------------------------------------------------

_MAX_ARCH_RULES_BYTES = 50 * 1024  # 50KB


def load_arch_rules(root: Path) -> RulesConfig | None:
    """Load .cerebrofy/arch-rules.yaml under *root*.

    Returns None when the file does not exist; raises RulesError when it exists
    but is malformed.
    """
    from cerebrofy.arch.rules import RulesError, parse_rules_config, rules_path

    path = rules_path(root)
    if not path.exists():
        return None

    size = path.stat().st_size
    if size > _MAX_ARCH_RULES_BYTES:
        import sys
        print(
            f"Warning: arch-rules.yaml exceeds 50KB ({size} bytes) — loading anyway.",
            file=sys.stderr,
        )

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise RulesError(f"{path}: top-level YAML mapping expected")
    return parse_rules_config(data, path)
