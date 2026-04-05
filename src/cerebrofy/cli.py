"""Cerebrofy CLI entry point."""

import click

from cerebrofy import __version__
from cerebrofy.commands.init import cerebrofy_init
from cerebrofy.commands.parse import cerebrofy_parse


@click.group()
@click.version_option(version=__version__, prog_name="cerebrofy")
def main() -> None:
    """Cerebrofy — AI-powered codebase intelligence."""


main.add_command(cerebrofy_init)
main.add_command(cerebrofy_parse)
