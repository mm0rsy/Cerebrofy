"""cerebrofy init — scaffold .cerebrofy/, install hooks, register MCP."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import rich_click as click

from cerebrofy.config.loader import build_default_config, write_config
from cerebrofy.hooks.installer import add_gitignore_entry, install_hooks
from cerebrofy.ignore.ruleset import DEFAULT_IGNORE_CONTENT
from cerebrofy.skills.installer import AI_SKILL_ROOTS, SUPPORTED_AI_CLIENTS, install_skills, installed_skills
from cerebrofy.mcp.registrar import (
    MCP_FALLBACK_SNIPPET,
    find_writable_mcp_config,
    has_cerebrofy_mcp_entry,
    warn_if_multiple_installations,
    write_mcp_entry,
)

# Monorepo manifest filenames used for Lobe auto-detection.
_MANIFESTS = {"package.json", "pyproject.toml", "go.mod", "Cargo.toml", "pom.xml"}


def detect_lobes(root: Path) -> dict[str, str]:
    """Auto-detect Lobes from repo layout. Returns {name: path/} mapping."""
    # Strategy 1: src/ layout
    src = root / "src"
    if src.is_dir():
        lobes = {
            d.name: f"src/{d.name}/"
            for d in sorted(src.iterdir())
            if d.is_dir()
        }
        if lobes:
            return lobes

    # Strategy 2: monorepo — top-level dirs containing a manifest
    lobes = {}
    for candidate in sorted(root.iterdir()):
        if not candidate.is_dir() or candidate.name.startswith("."):
            continue
        if any((candidate / m).exists() for m in _MANIFESTS):
            lobes[candidate.name] = f"{candidate.name}/"
        else:
            # depth-2 scan
            for sub in sorted(candidate.iterdir()):
                if sub.is_dir() and any((sub / m).exists() for m in _MANIFESTS):
                    lobes[sub.name] = f"{candidate.name}/{sub.name}/"
    if lobes:
        return lobes

    # Strategy 3: any top-level directories
    lobes = {
        d.name: f"{d.name}/"
        for d in sorted(root.iterdir())
        if d.is_dir() and not d.name.startswith(".")
    }
    if lobes:
        return lobes

    # Fallback: single root Lobe
    return {"root": "."}


def create_scaffold_directories(root: Path) -> None:
    """Create the .cerebrofy/ directory tree."""
    for subdir in (".cerebrofy/db", ".cerebrofy/queries", ".cerebrofy/scripts/migrations"):
        (root / subdir).mkdir(parents=True, exist_ok=True)


def copy_query_files(root: Path, force: bool = False) -> None:
    """Copy bundled .scm files from the package into root/.cerebrofy/queries/."""
    queries_src = Path(__file__).parent.parent / "queries"
    queries_dst = root / ".cerebrofy" / "queries"
    for scm in queries_src.glob("*.scm"):
        dst = queries_dst / scm.name
        if not dst.exists() or force:
            shutil.copy2(scm, dst)


def write_cerebrofy_ignore(root: Path) -> None:
    """Write .cerebrofy-ignore with default content (no-op if already exists)."""
    target = root / ".cerebrofy-ignore"
    if not target.exists():
        target.write_text(DEFAULT_IGNORE_CONTENT, encoding="utf-8")


@click.command("init")
@click.option("--here", is_flag=True, default=False,
              help="Initialize in the current working directory (explicit alias for default behaviour).")
@click.option("--global", "global_mcp", is_flag=True, default=False,
              help="Register MCP entry globally (~/.config/mcp/servers.json).")
@click.option("--no-mcp", is_flag=True, default=False,
              help="Skip MCP registration entirely.")
@click.option("--force", is_flag=True, default=False,
              help="Re-initialize an already-initialized repo.")
@click.option("--ai", "ai_client", default=None,
              type=click.Choice(SUPPORTED_AI_CLIENTS, case_sensitive=False),
              help=(
                  "Install Cerebrofy skill files for the given AI assistant. "
                  f"Supported: {', '.join(SUPPORTED_AI_CLIENTS)}. "
                  "Skills are written to .<ai>/skills/<skill-name>/SKILL.md."
              ))
def cerebrofy_init(
    here: bool,
    global_mcp: bool,
    no_mcp: bool,
    force: bool,
    ai_client: str | None,
) -> None:
    """Scaffold .cerebrofy/, install git hooks, and register the MCP server."""
    # --here is an explicit alias for the current directory (matches 'cerebrofy init --here')
    # behaviour is identical to omitting the flag — both operate on Path.cwd().
    _ = here  # consumed; kept for CLI ergonomics only
    root = Path.cwd()

    # Guard: must be a git repo
    if not (root / ".git").is_dir():
        click.echo("Error: Not a git repository. Run `git init` first.", err=True)
        sys.exit(1)

    # Guard: already initialized
    cerebrofy_dir = root / ".cerebrofy"
    if cerebrofy_dir.exists() and not force:
        click.echo(
            "Warning: .cerebrofy/ already exists. Use --force to re-initialize.", err=True
        )
        return

    click.echo("Cerebrofy: Scanning project structure...")
    lobes = detect_lobes(root)
    lobe_names = ", ".join(lobes)

    if "root" in lobes and len(lobes) == 1:
        click.echo("Cerebrofy: No subdirectories found — creating single root Lobe.")

    click.echo(f"Cerebrofy: Detected lobes: {lobe_names}")

    create_scaffold_directories(root)
    copy_query_files(root, force=force)

    click.echo("Cerebrofy: Writing .cerebrofy/config.yaml")
    write_config(build_default_config(lobes), cerebrofy_dir / "config.yaml")

    click.echo("Cerebrofy: Writing .cerebrofy-ignore")
    write_cerebrofy_ignore(root)
    click.echo("Cerebrofy: Installing git hooks (warn-only mode)")
    hook_warnings = install_hooks(root)
    for w in hook_warnings:
        click.echo(w, err=True)

    # FR-019: keep .cerebrofy/db/ out of git
    add_gitignore_entry(root)

    if not no_mcp:
        try:
            if global_mcp:
                from pathlib import Path as _Path
                mcp_path = _Path("~/.config/mcp/servers.json").expanduser()
                mcp_path.parent.mkdir(parents=True, exist_ok=True)
            else:
                mcp_path = find_writable_mcp_config()

            if has_cerebrofy_mcp_entry(mcp_path):
                click.echo(f"Cerebrofy: MCP server already registered at {mcp_path}")
            else:
                write_mcp_entry(mcp_path)
                click.echo(f"Cerebrofy: MCP server registered at {mcp_path}")

            warn_if_multiple_installations()
        except OSError:
            click.echo(
                "Warning: Could not write MCP config (permission denied). "
                "Add this entry manually:",
                err=True,
            )
            click.echo(MCP_FALLBACK_SNIPPET, err=True)

    if ai_client:
        _install_ai_skills(root, ai_client, force)

    click.echo("Cerebrofy initialized. Run `cerebrofy build` to index your codebase.")


def _install_ai_skills(root: Path, ai_client: str, force: bool) -> None:
    """Install skill templates for the requested AI client and report results."""
    client_lower = ai_client.lower()
    click.echo(f"Cerebrofy: Installing skills for {client_lower}...")
    warnings = install_skills(root, client_lower, force=force)
    for w in warnings:
        click.echo(w, err=True)

    skills = installed_skills(root, client_lower)
    dest_root = root / AI_SKILL_ROOTS[client_lower] / "skills"
    if skills:
        skill_names = ", ".join(p.parent.name for p in skills)
        click.echo(
            f"Cerebrofy: Skills written to {dest_root}/ "
            f"({len(skills)} skills: {skill_names})"
        )
    else:
        click.echo(f"Cerebrofy: No new skills installed (all already exist at {dest_root}/).")
