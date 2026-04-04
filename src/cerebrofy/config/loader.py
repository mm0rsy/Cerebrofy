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
    llm_endpoint: str = "openai"
    llm_model: str = "gpt-4o"
    top_k: int = 10


DEFAULT_TRACKED_EXTENSIONS: list[str] = [
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java", ".rb",
    ".cpp", ".c", ".h",
]

def validate_config(config: CerebrоfyConfig, queries_dir: Path) -> list[str]:

def build_default_config(lobes: dict[str, str]) -> dict:  # type: ignore[type-arg]
    """Return a plain dict matching the config.yaml schema with defaults."""
    return {
        "lobes": lobes,
        "tracked_extensions": DEFAULT_TRACKED_EXTENSIONS,
        "embedding_model": "local",
        "embed_dim": 768,
        "llm_endpoint": "openai",
        "llm_model": "gpt-4o",
        "top_k": 10,
    }


def write_config(config: dict, path: Path) -> None:  # type: ignore[type-arg]
    """Write config dict as YAML to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


def load_config(path: Path, queries_dir: Path | None = None) -> CerebrоfyConfig:
    """Load and parse config.yaml into a CerebrоfyConfig. Raises FileNotFoundError if missing.
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    config = CerebrоfyConfig(
        lobes=data["lobes"],
        tracked_extensions=data["tracked_extensions"],
        embedding_model=data.get("embedding_model", "local"),
        embed_dim=data.get("embed_dim", 768),
        llm_endpoint=data.get("llm_endpoint", "openai"),
        llm_model=data.get("llm_model", "gpt-4o"),
        top_k=data.get("top_k", 10),
    )
