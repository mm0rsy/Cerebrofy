"""cerebrofy upgrade — dependency upgrade navigator (offline, graph-aware)."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import rich_click as click

from cerebrofy.db.connection import check_schema_version
from cerebrofy.errors import NO_INDEX
from cerebrofy.upgrade.fixer import FixResult, FixerError, apply_fixes
from cerebrofy.upgrade.manifest import ManifestError, find_manifest
from cerebrofy.upgrade.planner import UpgradePlan, build_plan, render_markdown
from cerebrofy.upgrade.scanner import scan_package
from cerebrofy.upgrade.validator import ValidationResult, validate_upgrade


def _parse_steps(raw: str | None) -> list[int] | None:
    """Parse ``--step 1,2`` into ``[1, 2]`` (None means "all auto-fixable")."""
    if raw is None or not raw.strip():
        return None
    steps: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            value = int(token)
        except ValueError as exc:
            raise ValueError(f"--step expects comma-separated integers, got {raw!r}.") from exc
        if value <= 0:
            raise ValueError("--step values must be positive integers.")
        if value not in steps:
            steps.append(value)
    if not steps:
        raise ValueError("--step did not contain any step numbers.")
    return steps


def _render_json(
    plan: UpgradePlan,
    fixes: list[FixResult],
    validation: ValidationResult | None,
) -> None:
    payload = plan.to_dict()
    payload["auto_fix_results"] = [fix.to_dict() for fix in fixes]
    if validation is not None:
        payload["validation"] = validation.to_dict()
    click.echo(json.dumps(payload, indent=2))


@click.command("upgrade")
@click.argument("package", required=False)
@click.option("--package", "package_option", default=None, help="Package name (alternative to PACKAGE).")
@click.option("--from", "from_version", default=None, help="Current version (e.g. 1.10.0).")
@click.option("--to", "to_version", default=None, help="Target version (e.g. 2.0.0).")
@click.option("--breaking-only", is_flag=True, default=False, help="Only report breaking changes.")
@click.option(
    "--manifest",
    "manifest_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Custom YAML/JSON breaking-change manifest.",
)
@click.option(
    "--diff",
    "diff_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Custom API diff (JSON or YAML; alias for --manifest).",
)
@click.option(
    "--manifest-dir",
    "manifest_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory of manifest files to search before the bundled set.",
)
@click.option(
    "--auto-fix",
    is_flag=True,
    default=False,
    help="Apply mechanical AST fixes (explicit opt-in).",
)
@click.option("--step", "step_spec", default=None, help="Comma-separated steps to auto-fix (e.g. 1,2).")
@click.option(
    "--validate",
    "validate_only",
    is_flag=True,
    default=False,
    help="Rescan for remaining old API patterns (post-upgrade).",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["markdown", "json"]),
    default="markdown",
    show_default=True,
    help="Output format.",
)
def cerebrofy_upgrade(
    package: str | None,
    package_option: str | None,
    from_version: str | None,
    to_version: str | None,
    breaking_only: bool,
    manifest_path: Path | None,
    diff_path: Path | None,
    manifest_dir: Path | None,
    auto_fix: bool,
    step_spec: str | None,
    validate_only: bool,
    output_format: str,
) -> None:
    """Plan (and optionally fix) a dependency upgrade from a curated manifest.

    \b
    Examples:
      cerebrofy upgrade pydantic --from v1 --to v2
      cerebrofy upgrade requests --breaking-only
      cerebrofy upgrade pydantic --manifest ./pydantic.yaml --auto-fix --step 1,2
      cerebrofy upgrade pydantic --validate
    """
    name = (package or package_option or "").strip()
    if not name:
        click.echo("[error] Provide a PACKAGE name (e.g. 'cerebrofy upgrade pydantic').")
        sys.exit(1)
    if package and package_option and package.strip() != package_option.strip():
        click.echo("[error] PACKAGE and --package disagree; provide only one.")
        sys.exit(1)

    if manifest_path is not None and diff_path is not None:
        click.echo("[error] Use either --manifest or --diff, not both.")
        sys.exit(1)
    chosen_manifest = manifest_path if manifest_path is not None else diff_path

    root = Path.cwd()
    db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
    if not db_path.exists():
        click.echo(f"[{NO_INDEX}] No index found. Run 'cerebrofy build' first.")
        sys.exit(1)

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        check_schema_version(conn)
        try:
            manifest = find_manifest(
                name,
                from_version,
                to_version,
                manifest_path=chosen_manifest,
                manifest_dir=manifest_dir,
                extra_dirs=(root / ".cerebrofy" / "upgrades",),
            )
        except ManifestError as exc:
            click.echo(f"[{exc.code}] {exc.message}")
            sys.exit(1)

        # Pure validation: do not require the package import to still exist.
        if validate_only and not auto_fix:
            validation_result = validate_upgrade(manifest, conn, root)
            if output_format == "json":
                click.echo(json.dumps(validation_result.to_dict(), indent=2))
            else:
                click.echo(
                    f"# 🧠 Cerebrofy — Upgrade Validation: {manifest.package}\n\n"
                    f"{validation_result.to_markdown()}"
                )
            sys.exit(0 if validation_result.passed else 1)

        scan = scan_package(name, manifest, conn, root)
        try:
            scan.require_used()
        except ManifestError as exc:
            click.echo(f"[{exc.code}] {exc.message}")
            sys.exit(1)

        plan = build_plan(name, manifest, scan, conn, breaking_only=breaking_only)

        fixes: list[FixResult] = []
        validation: ValidationResult | None = None
        if auto_fix:
            try:
                steps = _parse_steps(step_spec)
            except ValueError as exc:
                click.echo(f"[error] {exc}")
                sys.exit(1)
            try:
                fixes = apply_fixes(plan, manifest, scan, root, steps)
            except FixerError as exc:
                click.echo(f"[{exc.code}] {exc.message}")
                sys.exit(1)
            if validate_only:
                validation = validate_upgrade(manifest, conn, root)

    finally:
        conn.close()

    if output_format == "json":
        _render_json(plan, fixes, validation)
    else:
        click.echo(render_markdown(plan, validation=validation, fix_results=fixes))

    if validation is not None and not validation.passed:
        sys.exit(1)
