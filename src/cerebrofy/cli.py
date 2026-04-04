"""Cerebrofy CLI entry point."""

import click

from cerebrofy import __version__


@click.group()
@click.version_option(version=__version__, prog_name="cerebrofy")
def main() -> None:
    """Cerebrofy — AI-powered codebase intelligence."""
