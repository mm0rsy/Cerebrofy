"""Changelog generator: orchestration only.

Delegates to focused modules:
- ``types``: ChangelogEntry / ChangelogReport data structures
- ``classifier``: change classification (existing)
- ``collector``: evidence loaders (DB, git, memories, docstrings)
- ``renderer``: entry text templates and report rendering
- ``narrative``: narrative event persistence (#26)

Template-based generation only (spec: template path; the optional LLM-assisted
path is intentionally not implemented — see the TODO markers in ``renderer``).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from cerebrofy.changelog.classifier import (
    CollectedChanges,
    collect_changes,
    classify_changes,
    validate_git_ref,
)
from cerebrofy.changelog.collector import (
    _docstrings,
    _git_output,
    _health_delta,
    _load_memories,
)
from cerebrofy.changelog.narrative import _intent_entry, write_narrative_events
from cerebrofy.changelog.renderer import (
    _AUDIENCE_TYPES,
    _breaking_changes,
    _first_sentence,
    build_entries,
    with_full_text,
)
from cerebrofy.changelog.types import ChangelogEntry, ChangelogReport
from cerebrofy.config.loader import ChangelogConfig, load_config

# Re-export for backward compatibility (tests/importers import from generator).
__all__ = [
    "ChangelogEntry",
    "ChangelogReport",
    "build_entries",
    "generate_changelog",
    "write_narrative_events",
    "_first_sentence",
]


def generate_changelog(
    repo_root: Path,
    since: str,
    audience: str = "developer",
    output_format: str = "markdown",
    *,
    conn: sqlite3.Connection,
    config: ChangelogConfig | None = None,
) -> ChangelogReport:
    """Generate a semantic changelog for ``since``..HEAD.

    The caller owns *conn* (open and close); this function never opens or closes
    connections itself (T1, testability finding #7).

    Raises:
        ChangelogError(REF_NOT_FOUND): the git ref cannot be resolved.
        ValueError: invalid audience or output format.
    """
    if audience not in _AUDIENCE_TYPES:
        raise ValueError(
            f"Invalid audience '{audience}'. Choose from: {', '.join(_AUDIENCE_TYPES)}."
        )
    if output_format not in ("markdown", "github", "slack"):
        raise ValueError(
            f"Invalid format '{output_format}'. Choose from: markdown, github, slack."
        )

    # Validate git ref format
    if since not in ("last-build", "project-start"):
        validate_git_ref(since)

    cerebrofy_dir = repo_root / ".cerebrofy"

    full_config: object = None
    config_path = cerebrofy_dir / "config.yaml"
    if config_path.exists():
        try:
            full_config = load_config(config_path)
        except Exception:
            full_config = None

    # Determine the changelog-specific config (m11):
    # an explicitly-passed config wins; otherwise derive from the loaded full
    # config; otherwise default. The ``breaking_cross_lobe_threshold`` literal is
    # not duplicated here — it lives on ChangelogConfig and is threaded through.
    changelog_cfg: ChangelogConfig
    if config is not None:
        changelog_cfg = config
    elif full_config is not None:
        changelog_cfg = getattr(full_config, "changelog", None) or ChangelogConfig()
    else:
        changelog_cfg = ChangelogConfig()

    cfg_lobes = getattr(full_config, "lobes", None) or None

    memories_by_neuron = _load_memories(cerebrofy_dir)
    collected: CollectedChanges = collect_changes(
        repo_root, conn, since, config=full_config, resolved=None
    )

    classified = classify_changes(
        collected.changes, conn, memories_by_neuron, cfg_lobes, config=changelog_cfg
    )

    docstrings = _docstrings(conn)
    entries = list(build_entries(classified, audience, docstrings))

    intent_entry = _intent_entry(repo_root, collected.files, audience)
    if intent_entry is not None and intent_entry.audience_text:
        entries.append(intent_entry)

    # TODO(integration-11): seed entry summaries from the Session Recorder's
    # task descriptions once #11 lands (no #11 imports in this lane).
    # TODO(llm): optional LLM-assisted descriptions via the #02 context
    # optimizer — template-based generation only for now.

    until = collected.range.until_ref
    entries_tuple = tuple(entries)
    report = ChangelogReport(
        since=collected.range.since_label,
        until=until,
        entries=entries_tuple,
        breaking_changes=_breaking_changes(entries_tuple),
        health_delta=_health_delta(conn),
        full_text="",
        audience=audience,
        format=output_format,
        until_short=until[:7],
        until_date=(_git_output(
            ["show", "-s", "--format=%cs", validate_git_ref(until)], repo_root
        ) or ""),
        note=collected.range.note,
    )
    return with_full_text(report)
