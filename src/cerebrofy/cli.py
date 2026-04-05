"""Cerebrofy CLI entry point."""

import click

from cerebrofy import __version__
from cerebrofy.commands.build import cerebrofy_build
from cerebrofy.commands.init import cerebrofy_init
from cerebrofy.commands.mcp import cerebrofy_mcp
from cerebrofy.commands.migrate import cerebrofy_migrate
from cerebrofy.commands.parse import cerebrofy_parse
from cerebrofy.commands.plan import cerebrofy_plan
from cerebrofy.commands.specify import cerebrofy_specify
from cerebrofy.commands.tasks import cerebrofy_tasks
from cerebrofy.commands.update import cerebrofy_update
from cerebrofy.commands.validate import cerebrofy_validate


@click.group()
@click.version_option(version=__version__, prog_name="cerebrofy")
def main() -> None:
    """Cerebrofy — AI-powered codebase intelligence."""


main.add_command(cerebrofy_build)
main.add_command(cerebrofy_init)
main.add_command(cerebrofy_mcp)
main.add_command(cerebrofy_migrate)
main.add_command(cerebrofy_parse)
main.add_command(cerebrofy_plan)
main.add_command(cerebrofy_specify)
main.add_command(cerebrofy_tasks)
main.add_command(cerebrofy_update)
main.add_command(cerebrofy_validate)
