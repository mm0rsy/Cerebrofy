"""cerebrofy parse — read-only diagnostic parser, outputs NDJSON Neurons."""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import click

from cerebrofy.config.loader import load_config
from cerebrofy.ignore.ruleset import IgnoreRuleSet
from cerebrofy.parser.engine import parse_directory, parse_file


def _find_repo_root(start: Path) -> Path | None:
    """Walk up from start until .cerebrofy/config.yaml is found."""
    current = start if start.is_dir() else start.parent
    for candidate in [current, *current.parents]:
        if (candidate / ".cerebrofy" / "config.yaml").exists():
            return candidate
    return None


@click.command("parse")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
def cerebrofy_parse(path: Path) -> None:
    """Parse source files and emit Neurons as NDJSON (one JSON object per line).

    PATH may be a single file or a directory. No writes are made to disk.
    """
    path = path.resolve()

    if path.is_file():
        repo_root = _find_repo_root(path)
        if repo_root is None:
            click.echo(
                "Error: No Cerebrofy config found. Run 'cerebrofy init' first.", err=True
            )
            sys.exit(1)
        queries_dir = repo_root / ".cerebrofy" / "queries"
        result = parse_file(path, queries_dir, repo_root)
        for w in result.warnings:
            click.echo(f"Warning: {w}", err=True)
        for neuron in result.neurons:
            click.echo(json.dumps(dataclasses.asdict(neuron)))
    else:
        repo_root = _find_repo_root(path)
        if repo_root is None:
            click.echo(
                "Error: No Cerebrofy config found. Run 'cerebrofy init' first.", err=True
            )
            sys.exit(1)
        config = load_config(repo_root / ".cerebrofy" / "config.yaml")
        ignore_rules = IgnoreRuleSet.from_directory(repo_root)
        queries_dir = repo_root / ".cerebrofy" / "queries"
        results = parse_directory(path, config, ignore_rules, queries_dir)
        for result in results:
            for w in result.warnings:
                click.echo(f"Warning: {w}", err=True)
            for neuron in result.neurons:
                click.echo(json.dumps(dataclasses.asdict(neuron)))
