"""cerebrofy parse — read-only diagnostic parser, outputs NDJSON Neurons."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from cerebrofy.config.loader import load_config
from cerebrofy.ignore.ruleset import IgnoreRuleSet
from cerebrofy.parser.engine import parse_file
from cerebrofy.parser.neuron import Neuron


def _find_repo_root(start: Path) -> Path | None:
    """Walk up from start until .cerebrofy/config.yaml is found."""
    current = start if start.is_dir() else start.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".cerebrofy" / "config.yaml").exists():
            return candidate
    return None


def _derive_lobe(neuron_file: str) -> str:
    """Derive the lobe name from the Neuron's file path.

    Uses the first path component as the lobe name (same logic as hybrid search).
    Returns "root" for files in the top-level directory.
    """
    parts = neuron_file.split("/")
    return parts[0] if len(parts) > 1 else "root"


def _serialize_neuron(neuron: Neuron) -> dict:  # type: ignore[type-arg]
    """Serialize a Neuron to the spec-defined NDJSON dict.

    Renames 'type' → 'kind' and adds a 'lobe' field, per cli-parse.md contract.
    Excludes 'id' and 'docstring' (not part of the public parse output schema).
    """
    return {
        "file": neuron.file,
        "name": neuron.name,
        "kind": neuron.type,
        "line_start": neuron.line_start,
        "line_end": neuron.line_end,
        "signature": neuron.signature,
        "lobe": _derive_lobe(neuron.file),
    }


@click.command("parse")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
def cerebrofy_parse(path: Path) -> None:
    """Parse source files and emit Neurons as NDJSON (one JSON object per line).

    PATH may be a single file or a directory. No writes are made to disk.
    """
    path = path.resolve()

    repo_root = _find_repo_root(path)
    if repo_root is None:
        click.echo(
            "Error: No Cerebrofy config found. Run 'cerebrofy init' first.", err=True
        )
        sys.exit(1)

    config = load_config(repo_root / ".cerebrofy" / "config.yaml")
    ignore_rules = IgnoreRuleSet.from_directory(repo_root)
    queries_dir = repo_root / ".cerebrofy" / "queries"

    if path.is_file():
        rel = str(path.relative_to(repo_root)).replace("\\", "/")
        if ignore_rules.matches(rel):
            click.echo(f"{rel}: excluded by ignore rules")
            sys.exit(0)
        result = parse_file(path, queries_dir, repo_root)
        for w in result.warnings:
            click.echo(f"Warning: {w}", err=True)
        for neuron in result.neurons:
            click.echo(json.dumps(_serialize_neuron(neuron)))
    else:
        for file_path in sorted(path.rglob("*")):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in config.tracked_extensions:
                continue
            rel = str(file_path.relative_to(repo_root)).replace("\\", "/")
            if ignore_rules.matches(rel):
                click.echo(f"{rel}: excluded by ignore rules")
                continue
            result = parse_file(file_path, queries_dir, repo_root)
            for w in result.warnings:
                click.echo(f"Warning: {w}", err=True)
            for neuron in result.neurons:
                click.echo(json.dumps(_serialize_neuron(neuron)))
