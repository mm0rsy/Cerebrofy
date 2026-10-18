"""cerebrofy changelog — semantic changelog generator (Idea #14)."""

from __future__ import annotations

import sys
from pathlib import Path

import rich_click as click


@click.command("changelog")
@click.option(
    "--since",
    required=True,
    help=(
        "Changelog start point: a git tag, commit hash, 'last-build' "
        "(commit of the newest health snapshot), or 'project-start'."
    ),
)
@click.option(
    "--audience",
    type=click.Choice(["developer", "pm", "user"]),
    default="developer",
    show_default=True,
    help="Target audience for the generated prose.",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "github", "slack"]),
    default="markdown",
    show_default=True,
    help="Output format for the full changelog text.",
)
@click.option(
    "--narrative",
    is_flag=True,
    default=False,
    help=(
        "Also write every entry to the narrative_events table "
        "(idempotent per range — feeds the narrative engine, Idea #26)."
    ),
)
def cerebrofy_changelog(
    since: str,
    audience: str,
    output_format: str,
    narrative: bool,
) -> None:
    """Generate a changelog from the semantic graph — not from commit messages.

    \b
    Examples:
      cerebrofy changelog --since v1.2.0
      cerebrofy changelog --since last-build --audience pm
      cerebrofy changelog --since main --format github
      cerebrofy changelog --narrative --since project-start
    """
    from cerebrofy.changelog.classifier import ChangelogError
    from cerebrofy.changelog.generator import generate_changelog, write_narrative_events
    from cerebrofy.db.connection import check_schema_version, open_db, open_db_readonly

    root = Path.cwd()
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        click.echo("Error: [NO_INDEX] No index found. Run 'cerebrofy build' first.", err=True)
        sys.exit(1)

    report = None
    try:
        if narrative:
            conn = open_db(db_path)
            try:
                check_schema_version(conn)
                report = generate_changelog(
                    root, since, audience=audience, output_format=output_format, conn=conn
                )
                written = write_narrative_events(conn, report, root)
            finally:
                conn.close()
            click.echo(
                f"Cerebrofy: wrote {written} narrative event(s) to narrative_events.",
                err=True,
            )
        else:
            conn = open_db_readonly(db_path)
            try:
                check_schema_version(conn)
                report = generate_changelog(
                    root, since, audience=audience, output_format=output_format, conn=conn
                )
            finally:
                conn.close()
    except ChangelogError as exc:
        click.echo(f"Error: [{exc.code}] {exc.message}", err=True)
        sys.exit(1)
    except ValueError as exc:
        if "schema" in str(exc).lower():
            click.echo(f"Error: {exc}. Run 'cerebrofy migrate'.", err=True)
        else:
            click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if report is None:  # defensive: both branches above assign or exit
        click.echo("Error: [NO_INDEX] Changelog generation failed.", err=True)
        sys.exit(1)

    if report.note:
        click.echo(f"Cerebrofy: {report.note}", err=True)
    click.echo(report.full_text, nl=False)
