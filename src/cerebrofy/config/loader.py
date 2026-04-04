"""CerebrоfyConfig dataclass and config.yaml I/O helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class CerebrоfyConfig:
    """Full contents of `.cerebrofy/config.yaml`."""

    lobes: dict[str, str]
    tracked_extensions: list[str]
    embedding_model: str = "local"
    embed_dim: int = 768
    llm_endpoint: str = ""
    llm_model: str = ""
    llm_timeout: int = 60
    system_prompt_template: str = ""
    top_k: int = 10


DEFAULT_TRACKED_EXTENSIONS: list[str] = [
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java", ".rb",
    ".cpp", ".c", ".h",
]


_EMBED_DIM_EXPECTED: dict[str, int] = {
    "local": 768,
    "openai": 1536,
    "cohere": 1024,
}


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

    expected_dim = _EMBED_DIM_EXPECTED.get(config.embedding_model)
    if expected_dim is not None and config.embed_dim != expected_dim:
        warnings.append(
            f"config.yaml: embed_dim={config.embed_dim} does not match "
            f"embedding_model='{config.embedding_model}' (expected {expected_dim})."
        )

    return warnings


def build_default_config(lobes: dict[str, str]) -> dict:  # type: ignore[type-arg]
    """Return a plain dict matching the config.yaml schema with defaults."""
    return {
        "lobes": lobes,
        "tracked_extensions": DEFAULT_TRACKED_EXTENSIONS,
        "embedding_model": "local",
        "embed_dim": 768,
        "llm_endpoint": "",
        "llm_model": "",
        "top_k": 10,
    }


def write_config(config: dict, path: Path) -> None:  # type: ignore[type-arg]
    """Write config dict as YAML to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def load_config(path: Path, queries_dir: Path | None = None) -> CerebrоfyConfig:
    """Load and parse config.yaml into a CerebrоfyConfig. Raises FileNotFoundError if missing.

    If queries_dir is provided, validate_config() is called and warnings are printed to stderr.
    """
    import sys

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    config = CerebrоfyConfig(
        lobes=data["lobes"],
        tracked_extensions=data["tracked_extensions"],
        embedding_model=data.get("embedding_model", "local"),
        embed_dim=data.get("embed_dim", 768),
        llm_endpoint=data.get("llm_endpoint", ""),
        llm_model=data.get("llm_model", ""),
        llm_timeout=data.get("llm_timeout", 60),
        system_prompt_template=data.get("system_prompt_template", ""),
        top_k=data.get("top_k", 10),
    )
    if queries_dir is not None:
        for warning in validate_config(config, queries_dir):
            print(f"Warning: {warning}", file=sys.stderr)
    return config
