"""Cerebrofy CLI entry point."""

import sys

import rich_click as click

from cerebrofy import __version__
from cerebrofy.commands.arch import cerebrofy_arch
from cerebrofy.commands.blast_radius import cerebrofy_blast_radius
from cerebrofy.commands.build import cerebrofy_build
from cerebrofy.commands.changelog import cerebrofy_changelog
from cerebrofy.commands.context import cerebrofy_context
from cerebrofy.commands.epistemic import cerebrofy_epistemic
from cerebrofy.commands.health import cerebrofy_health
from cerebrofy.commands.governance import cerebrofy_governance
from cerebrofy.commands.impact import cerebrofy_impact
from cerebrofy.commands.init import cerebrofy_init
from cerebrofy.commands.intent import cerebrofy_intent
from cerebrofy.commands.memory import mem_group
from cerebrofy.commands.onboard import cerebrofy_onboard
from cerebrofy.commands.plan import cerebrofy_plan
from cerebrofy.commands.review import cerebrofy_review
from cerebrofy.commands.mcp import cerebrofy_mcp
from cerebrofy.commands.migrate import cerebrofy_migrate
from cerebrofy.commands.session import session_group
from cerebrofy.commands.update import cerebrofy_update
from cerebrofy.commands.upgrade import cerebrofy_upgrade
from cerebrofy.commands.coverage_gap import cerebrofy_coverage_gap
from cerebrofy.commands.coordination import (
    claim_command,
    conflicts_command,
    coordination_group,
    release_command,
    resolve_command,
    who_command,
)
from cerebrofy.commands.silo import cerebrofy_silo
from cerebrofy.commands.validate import cerebrofy_validate
from cerebrofy.commands.viz import cerebrofy_viz
from cerebrofy.commands.vuln import cerebrofy_vuln

click.rich_click.USE_RICH_MARKUP = True
click.rich_click.USE_MARKDOWN = False
click.rich_click.SHOW_ARGUMENTS = True
click.rich_click.GROUP_ARGUMENTS_OPTIONS = False
click.rich_click.STYLE_COMMANDS_TABLE_COLUMN_WIDTH_RATIO = (1, 3)
click.rich_click.HEADER_TEXT = (
    "[bold cyan]"
    " \u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2557   \u2588\u2588\u2557\n"
    "\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2550\u2550\u255d\u255a\u2588\u2588\u2557 \u2588\u2588\u2554\u255d\n"
    "\u2588\u2588\u2551     \u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2588\u2588\u2588\u2557  \u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2557   \u255a\u2588\u2588\u2588\u2588\u2554\u255d \n"
    "\u2588\u2588\u2551     \u2588\u2588\u2554\u2550\u2550\u255d  \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u255d  \u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u255d    \u255a\u2588\u2588\u2554\u255d  \n"
    "\u255a\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2557\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2551  \u2588\u2588\u2551\u255a\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2551        \u2588\u2588\u2551   \n"
    " \u255a\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u255d\u255a\u2550\u2550\u2550\u2550\u2550\u255d \u255a\u2550\u255d  \u255a\u2550\u255d \u255a\u2550\u2550\u2550\u2550\u2550\u255d \u255a\u2550\u255d        \u255a\u2550\u255d[/bold cyan]\n\n"
    "[dim]AI-powered codebase intelligence \u2014 zero code upload, ~97% token reduction[/dim]"
)


def _force_utf8_output() -> None:
    """Make stdout/stderr able to render the glyphs the CLI prints.

    Legacy Windows consoles use a codepage (cp1252) that cannot encode the
    banner, box-drawing characters or emoji in reports, and the command dies
    with UnicodeEncodeError. Reconfigure to UTF-8 and degrade unencodable
    characters instead of raising.
    """
    for stream in (sys.stdout, sys.stderr):
        if not hasattr(stream, "reconfigure"):
            continue
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding == "utf8":
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # pragma: no cover - non-file streams
            pass


@click.group()
@click.version_option(version=__version__, prog_name="cerebrofy")
def main() -> None:
    _force_utf8_output()


# Public commands (shown in --help)
main.add_command(cerebrofy_blast_radius)
main.add_command(cerebrofy_coverage_gap)
main.add_command(cerebrofy_build)
main.add_command(cerebrofy_changelog)
main.add_command(cerebrofy_context)
main.add_command(cerebrofy_epistemic)
main.add_command(cerebrofy_health)
main.add_command(cerebrofy_governance)
main.add_command(cerebrofy_impact)
main.add_command(cerebrofy_init)
main.add_command(cerebrofy_intent)
main.add_command(cerebrofy_arch)
main.add_command(mem_group)
main.add_command(cerebrofy_onboard)
main.add_command(cerebrofy_plan)
main.add_command(cerebrofy_review)
main.add_command(cerebrofy_silo)
main.add_command(session_group)
main.add_command(cerebrofy_update)
main.add_command(cerebrofy_upgrade)
main.add_command(cerebrofy_validate)
main.add_command(cerebrofy_vuln)

# Multi-agent coordination (Idea #25) — top-level commands plus an alias group.
main.add_command(who_command)
main.add_command(claim_command)
main.add_command(release_command)
main.add_command(conflicts_command)
main.add_command(resolve_command)
main.add_command(coordination_group)

# Hidden/internal commands (not shown in --help)
cerebrofy_mcp.hidden = True
cerebrofy_migrate.hidden = True
main.add_command(cerebrofy_mcp)
main.add_command(cerebrofy_migrate)
main.add_command(cerebrofy_viz)
