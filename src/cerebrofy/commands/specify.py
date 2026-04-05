"""cerebrofy specify — hybrid search + LLM streaming spec writer."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

import click

from cerebrofy.search.hybrid import HybridSearchResult


def _resolve_output_path(specs_dir: Path, now: datetime) -> Path:
    """Resolve a unique output path under specs_dir based on the current timestamp."""
    timestamp = now.strftime("%Y-%m-%dT%H-%M-%S")
    base = specs_dir / f"{timestamp}_spec.md"
    if not base.exists():
        return base
    for suffix in range(2, 1000):
        candidate = specs_dir / f"{timestamp}_{suffix}_spec.md"
        if not candidate.exists():
            return candidate
    return base


def _print_search_summary(result: HybridSearchResult, model: str) -> None:
    """Print a search summary to stderr."""
    n = len(result.matched_neurons)
    m = len(result.affected_lobes)
    click.echo(
        f"Cerebrofy: Hybrid search — {n} neurons matched, {m} lobes affected",
        err=True,
    )
    for neuron in result.matched_neurons:
        click.echo(
            f"  · {neuron.name} ({neuron.file}) — score {neuron.similarity:.2f}",
            err=True,
        )
    lobe_list = ", ".join(sorted(result.affected_lobes))
    click.echo(f"Cerebrofy: Affected lobes: {lobe_list}", err=True)
    click.echo(f"Cerebrofy: Calling LLM ({model})...", err=True)


def _validate_specify_prerequisites(config: object, db_meta: dict[str, str]) -> None:
    """Validate LLM config, API key, template path, and embed model before any search."""
    llm_endpoint: str = getattr(config, "llm_endpoint", "")
    llm_model: str = getattr(config, "llm_model", "")
    system_prompt_template: str = getattr(config, "system_prompt_template", "")
    embedding_model: str = getattr(config, "embedding_model", "local")

    if not llm_endpoint:
        raise click.UsageError("Missing config key: llm_endpoint")
    if not llm_model:
        raise click.UsageError("Missing config key: llm_model")

    # Derive API key env var from endpoint URL.
    # Users on non-OpenAI providers must set LLM_API_KEY.
    if "openai" in llm_endpoint.lower():
        api_key_var = "OPENAI_API_KEY"
    else:
        api_key_var = "LLM_API_KEY"

    if not os.environ.get(api_key_var):
        raise click.UsageError(f"Missing environment variable: {api_key_var}")

    if system_prompt_template:
        repo_root = Path.cwd()
        resolved = repo_root / system_prompt_template
        if not resolved.exists():
            raise click.UsageError(
                f"Error: system_prompt_template file not found: {resolved}"
            )

    index_embed_model = db_meta.get("embed_model", "")
    if index_embed_model != embedding_model:
        raise click.UsageError(
            f"Embedding model mismatch: index was built with {index_embed_model}, "
            f"config says {embedding_model}. Run 'cerebrofy build' to rebuild."
        )


@click.command("specify")
@click.argument("description")
@click.option("--top-k", default=None, type=int, help="Override KNN top-k for this run.")
def cerebrofy_specify(description: str, top_k: int | None) -> None:
    """Generate a feature spec using hybrid search + LLM grounding."""
    if not description:
        click.echo("Description must not be empty.", err=True)
        sys.exit(1)

    root = Path.cwd()
    config_path = root / ".cerebrofy" / "config.yaml"
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"

    from cerebrofy.config.loader import load_config
    config = load_config(config_path)

    if not db_path.exists():
        click.echo("No index found. Run 'cerebrofy build' first.", err=True)
        sys.exit(1)

    import sqlite3
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        from cerebrofy.db.connection import check_schema_version
        try:
            check_schema_version(conn)
        except ValueError:
            click.echo(
                "Schema version mismatch. Run 'cerebrofy migrate' to upgrade.",
                err=True,
            )
            sys.exit(1)

        meta_rows = conn.execute("SELECT key, value FROM meta").fetchall()
        db_meta = {row[0]: row[1] for row in meta_rows}
    finally:
        conn.close()

    _validate_specify_prerequisites(config, db_meta)

    current_state_hash = db_meta.get("state_hash", "")
    if current_state_hash:
        import hashlib
        from cerebrofy.ignore.ruleset import IgnoreRuleSet
        ignore_rules = IgnoreRuleSet.from_directory(root)
        try:
            file_hashes: list[str] = []
            for fp in sorted(root.rglob("*")):
                if not fp.is_file():
                    continue
                rel = str(fp.relative_to(root)).replace("\\", "/")
                if not ignore_rules.matches(rel) and fp.suffix.lower() in config.tracked_extensions:
                    h = hashlib.sha256(fp.read_bytes()).hexdigest()
                    file_hashes.append(f"{rel}:{h}\n")
            computed = hashlib.sha256("".join(file_hashes).encode()).hexdigest()
            if computed != current_state_hash:
                click.echo(
                    "Warning: Index may be out of sync. Run 'cerebrofy update' for current results.",
                    err=True,
                )
        except Exception:
            pass

    effective_top_k = top_k or config.top_k or 10

    from cerebrofy.search.hybrid import _embed_query, hybrid_search
    embedding = _embed_query(description, config)

    lobe_dir = str(root / "docs" / "cerebrofy")
    result = hybrid_search(
        query=description,
        db_path=str(db_path),
        embedding=embedding,
        top_k=effective_top_k,
        config_embed_model=config.embedding_model,
        lobe_dir=lobe_dir,
    )

    if not result.matched_neurons:
        click.echo("Cerebrofy: No relevant code units found for this description.")
        sys.exit(0)

    from cerebrofy.llm.prompt_builder import build_llm_context
    payload = build_llm_context(result, config.system_prompt_template or None, str(root))
    _print_search_summary(result, config.llm_model)

    import os as _os
    if "openai" in config.llm_endpoint.lower():
        api_key = _os.environ.get("OPENAI_API_KEY", "")
    else:
        api_key = _os.environ.get("LLM_API_KEY", "")

    from cerebrofy.llm.client import LLMClient
    client = LLMClient(
        base_url=config.llm_endpoint,
        api_key=api_key,
        model=config.llm_model,
        timeout=config.llm_timeout,
    )

    import openai as _openai
    try:
        full_response = client.call(payload)
    except TimeoutError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    except _openai.RateLimitError:
        click.echo(
            "Error: LLM rate limit exceeded (HTTP 429). Wait and retry.", err=True
        )
        sys.exit(1)
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    specs_dir = root / "docs" / "cerebrofy" / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    output_path = _resolve_output_path(specs_dir, datetime.now())
    output_path.write_text(full_response, encoding="utf-8")
    click.echo(str(output_path))
    sys.exit(0)
