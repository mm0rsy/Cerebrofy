"""Changelog narrative event persistence (feeds Idea #26 — this lane only writes).

Split from ``generator.py`` (M3).
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Sequence
from pathlib import Path

from cerebrofy.changelog.classifier import (
    INTENT_UPDATE,
    ChangelogError,
    validate_git_ref,
)
from cerebrofy.changelog.collector import _git_output
from cerebrofy.changelog.types import ChangelogEntry, ChangelogReport
from cerebrofy.db.schema import ensure_narrative_schema
from cerebrofy.intent.loader import load_intent


def _intent_entry(
    repo_root: Path, files: Sequence[str], audience: str
) -> ChangelogEntry | None:
    """Record a #23 product-intent update as an ``intent_update`` entry."""
    if ".cerebrofy/intent.yaml" not in files:
        return None
    try:
        intent = load_intent(repo_root / ".cerebrofy")
    except Exception as exc:  # noqa: BLE001
        return None
    if intent is None or intent.sprint is None:
        return None

    sprint = intent.sprint
    title = f"Sprint intent updated: {sprint.name}"
    description = f"Sprint '{sprint.name}' — goal: {sprint.goal}"
    if audience == "user":
        text = f"Product direction updated: {sprint.goal}."
    elif audience == "pm":
        text = f"Sprint goal set: {sprint.goal}."
    else:
        text = f"**{title}** — {sprint.goal} (priority lobes: {', '.join(sprint.priority_lobes) or 'none'})"
    return ChangelogEntry(
        type=INTENT_UPDATE,
        title=title,
        description=description,
        neurons=(),
        blast_radius=0,
        audience_text=text,
        lobes=tuple(sprint.priority_lobes),
    )


def _commit_ts(repo_root: Path | None, commit_ref: str) -> int:
    if repo_root is not None:
        try:
            validated = validate_git_ref(commit_ref)
        except ChangelogError:
            return int(time.time())
        out = _git_output(["show", "-s", "--format=%ct", validated], repo_root)
        if out and out.isdigit():
            return int(out)
    return int(time.time())


def write_narrative_events(
    conn: sqlite3.Connection,
    report: ChangelogReport,
    repo_root: Path | None = None,
) -> int:
    """Write every entry as a narrative event row; idempotent per range.

    Event ids are derived deterministically from (commit_ref, type, title), so
    replaying the same range replaces rows instead of duplicating them.

    # TODO(integration-26): the Codebase Narrative Engine will read this table
    # to synthesise eras and stories — this lane only writes events.
    """
    ensure_narrative_schema(conn)
    ts = _commit_ts(repo_root, report.until)
    health_json = json.dumps(report.health_delta)
    written = 0
    for entry in report.entries:
        event_id = hashlib.sha1(
            f"{report.until}|{entry.type}|{entry.title}".encode()
        ).hexdigest()[:20]
        conn.execute(
            "INSERT OR REPLACE INTO narrative_events "
            "(id, ts, commit_ref, type, title, body, lobes_affected, "
            " blast_radius_delta, health_delta) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                event_id,
                ts,
                report.until,
                entry.type,
                entry.title,
                entry.description,
                json.dumps(list(entry.lobes)),
                float(entry.blast_radius),
                health_json,
            ),
        )
        written += 1
    conn.commit()
    return written
