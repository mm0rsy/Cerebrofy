"""Changelog generator: classified changes → audience-specific entries.

Template-based generation only (spec: template path; the optional LLM-assisted
path is intentionally not implemented — see the TODO markers below).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cerebrofy.changelog.classifier import (
    BREAKING,
    ENTRY_TYPES,
    FEAT,
    FIX,
    INTERNAL,
    INTENT_UPDATE,
    PERF,
    REFACTOR,
    SECURITY,
    ChangelogError,
    ClassifiedChange,
    CollectedChanges,
    NeuronChange,
    classify_changes,
    collect_changes,
    validate_git_ref,
)
from cerebrofy.config.loader import ChangelogConfig, load_config
from cerebrofy.constants import DEFAULT_GIT_TIMEOUT_SECONDS
from cerebrofy.db.schema import ensure_narrative_schema
from cerebrofy.intent.loader import load_intent
from cerebrofy.memory.store import Memory
from cerebrofy.memory.store import list_memories as _list_memories
from cerebrofy.memory.store import open_memories_db as _open_memories_db

#: Display order for entry types (severity first).
_ENTRY_ORDER: tuple[str, ...] = (
    BREAKING,
    SECURITY,
    FEAT,
    FIX,
    PERF,
    REFACTOR,
    INTERNAL,
    INTENT_UPDATE,
)

#: Audience -> entries eligible for that audience's prose.
_AUDIENCE_TYPES: dict[str, frozenset[str]] = {
    "developer": frozenset(ENTRY_TYPES),
    "pm": frozenset({BREAKING, SECURITY, FEAT, FIX, PERF, REFACTOR}),
    "user": frozenset({BREAKING, SECURITY, FEAT, FIX}),
}


def _open_index_db(db_path: Path) -> sqlite3.Connection:
    """Open the changelog index DB read-only, or raise NO_INDEX.

    Separated from ``generate_changelog`` so the connection-opening seam is
    independently testable (testability finding #7).
    """
    if not db_path.exists():
        raise ChangelogError(
            "NO_INDEX", "Index not found. Run 'cerebrofy build' first."
        )
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


# ---------------------------------------------------------------------------
# Output structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChangelogEntry:
    """One changelog entry (spec output schema + generation context)."""

    type: str
    title: str
    description: str
    neurons: tuple[str, ...]
    blast_radius: int
    audience_text: str
    # Generation-only context (not serialised to the spec output schema).
    lobes: tuple[str, ...] = ()
    memory_notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the exact spec entry schema (6 keys)."""
        return {
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "neurons": list(self.neurons),
            "blast_radius": self.blast_radius,
            "audience_text": self.audience_text,
        }


@dataclass(frozen=True)
class ChangelogReport:
    """Full changelog report for a range at a given audience and format."""

    since: str
    until: str
    entries: tuple[ChangelogEntry, ...]
    breaking_changes: tuple[dict[str, Any], ...]
    health_delta: dict[str, float]
    full_text: str
    audience: str = "developer"
    format: str = "markdown"
    until_short: str = ""
    until_date: str = ""
    note: str | None = None  # non-fatal range-resolution note (e.g. last-build fallback)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the exact spec output schema."""
        return {
            "since": self.since,
            "until": self.until,
            "entries": [e.to_dict() for e in self.entries],
            "breaking_changes": [dict(b) for b in self.breaking_changes],
            "health_delta": dict(self.health_delta),
            "full_text": self.full_text,
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# Evidence loaders (all degrade gracefully)
# ---------------------------------------------------------------------------


def _load_memories(cerebrofy_dir: Path) -> dict[str, list[Memory]]:
    """Memories grouped by neuron id; empty mapping when #05 is absent."""
    if not (cerebrofy_dir / "db" / "memories.db").exists():
        return {}
    try:
        conn = _open_memories_db(cerebrofy_dir)
        try:
            memories = _list_memories(conn, include_stale=False)
        finally:
            conn.close()
    except Exception:
        return {}

    grouped: dict[str, list[Memory]] = {}
    for memory in memories:
        if memory.neuron_id:
            grouped.setdefault(memory.neuron_id, []).append(memory)
    return grouped


def _health_delta(conn: sqlite3.Connection) -> dict[str, float]:
    """Coupling / avg-blast change between the two newest health snapshots."""
    zero = {"coupling": 0.0, "avg_blast": 0.0}
    try:
        rows = conn.execute(
            "SELECT coupling, avg_blast FROM health_snapshots ORDER BY build_ts DESC LIMIT 2"
        ).fetchall()
    except sqlite3.OperationalError:
        return zero
    if len(rows) < 2:
        return zero
    (cur_c, cur_b), (prev_c, prev_b) = rows[0], rows[1]
    return {
        "coupling": round(float(cur_c or 0.0) - float(prev_c or 0.0), 4),
        "avg_blast": round(float(cur_b or 0.0) - float(prev_b or 0.0), 2),
    }


def _git_output(args: list[str], repo_root: Path) -> str | None:
    # Validate git arguments to prevent command injection (though we use list form).
    # User-supplied refs are validated via validate_git_ref at call sites; this
    # is a defence-in-depth check that also allows git option characters.
    for arg in args:
        if not re.match(r"^[a-zA-Z0-9._/=%-]+$", arg):
            return None
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=DEFAULT_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _docstrings(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = conn.execute(
            "SELECT id, docstring FROM nodes WHERE docstring IS NOT NULL AND docstring != ''"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {row[0]: row[1] for row in rows}


# ---------------------------------------------------------------------------
# Text templates
# ---------------------------------------------------------------------------


#: Lowercase tokens whose trailing period must not be treated as a sentence end.
_ABBREVIATIONS = frozenset({"e.g", "i.e", "etc", "vs"})

#: Regex matching known abbreviations (with their trailing period) preceded by a
#: non-letter boundary, so the period is preserved during sentence splitting.
_ABBR_RE = re.compile(r'(?<![A-Za-z])(?:e\.g\.|i\.e\.|etc\.|vs\.)', re.IGNORECASE)


def _first_sentence(text: str, limit: int = 140) -> str:
    """Extract the first sentence of *text* for use as a summary.

    Handles common abbreviations (``e.g.``, ``i.e.``, ``etc.``, ``vs.``) so their
    trailing periods do not prematurely terminate an entry.  Only the first line is
    considered (docstring summaries are single-line).  If no terminal punctuation
    is found the full first line is returned.
    """
    text = text.strip()
    if not text:
        return ""
    first_line = text.split("\n", 1)[0].strip()
    if not first_line:
        return ""

    # Record period positions that belong to known abbreviations so they are
    # skipped during sentence-end detection.
    skip_periods: set[int] = set()
    for match in _ABBR_RE.finditer(first_line):
        for i in range(match.start(), match.end()):
            if first_line[i] == ".":
                skip_periods.add(i)

    for i, ch in enumerate(first_line):
        if ch in ".!?" and i not in skip_periods:
            if i + 1 >= len(first_line) or first_line[i + 1].isspace():
                sentence = first_line[: i + 1].strip()
                return sentence[:limit]

    return first_line[:limit]


def _names(neurons: Sequence[NeuronChange]) -> str:
    names = [n.name for n in neurons]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:3]) + (f" +{len(names) - 3} more" if len(names) > 3 else "")


def _entry_title(entry_type: str, neurons: Sequence[NeuronChange]) -> str:
    names = _names(neurons)
    templates = {
        FEAT: f"Added {names}",
        FIX: f"Fixed {names}",
        SECURITY: f"Patched security issue in {names}",
        BREAKING: f"BREAKING: {names} changed",
        PERF: f"Improved performance of {names}",
        REFACTOR: f"Refactored {names}",
        INTERNAL: f"Changed {names}",
    }
    return templates.get(entry_type, f"Changed {names}")


def _entry_description(change: ClassifiedChange) -> str:
    parts = [
        f"{n.file}::{n.name} ({n.kind})" for n in change.neurons
    ]
    suffix = f". Callers: {change.direct_callers} direct"
    if change.cross_lobe_callers:
        suffix += f" ({change.cross_lobe_callers} cross-lobe)"
    suffix += f". Blast radius: {change.blast_radius}."
    if change.memories:
        why = change.memories[0]
        suffix += f" Why: {why.title} — {_first_sentence(why.body, 160)}"
    return "; ".join(parts) + suffix


def _why_text(change: ClassifiedChange, docstrings: Mapping[str, str]) -> str | None:
    if change.memories:
        return change.memories[0].title
    for neuron in change.neurons:
        docstring = docstrings.get(neuron.id)
        if docstring:
            return _first_sentence(docstring)
    return None


def _developer_text(
    change: ClassifiedChange, docstrings: Mapping[str, str]
) -> str:
    names = _names(change.neurons)
    files = sorted({n.file for n in change.neurons})
    location = files[0] if len(files) == 1 else ", ".join(files[:2])
    text = f"**{names}** ({location})"
    why = _why_text(change, docstrings)
    detail = _entry_title(change.entry_type, change.neurons)
    text += f": {detail}."
    if change.direct_callers:
        text += f" Callers: {change.direct_callers} direct"
        if change.cross_lobe_callers:
            text += f" ({change.cross_lobe_callers} cross-lobe)"
        text += "."
    if why and why not in detail:
        text += f" Why: {why}"
    return text


def _pm_text(
    change: ClassifiedChange, docstrings: Mapping[str, str]
) -> str:
    lobe = change.neurons[0].lobe
    why = _why_text(change, docstrings)
    names = _names(change.neurons)
    if change.entry_type == FEAT:
        base = f"New capability in the {lobe} area ({names})"
        return f"{base}: {why}." if why else f"{base}."
    if change.entry_type == BREAKING:
        return f"Important change in the {lobe} area — integrations calling {names} must be updated."
    if change.entry_type == SECURITY:
        return f"Security hardening in the {lobe} area: {why or names}."
    if change.entry_type == FIX:
        return f"Reliability fix in the {lobe} area: {why or names}."
    if change.entry_type == PERF:
        return f"Performance improvement in the {lobe} area: {why or names}."
    return "Internal restructuring — no change in functionality."


def _user_text(change: ClassifiedChange, docstrings: Mapping[str, str]) -> str:
    why = _why_text(change, docstrings)
    names = _names(change.neurons)
    if change.entry_type == FEAT:
        return f"New: {why or names}."
    if change.entry_type == FIX:
        return f"Fixed: {why or names}."
    if change.entry_type == SECURITY:
        return f"Security improvement: {why or 'hardened validation and access controls'}."
    if change.entry_type == BREAKING:
        return f"Important: {names} changed — update to the latest version for the best experience."
    return ""


def _audience_text(
    change: ClassifiedChange, audience: str, docstrings: Mapping[str, str]
) -> str:
    if audience == "pm":
        return _pm_text(change, docstrings)
    if audience == "user":
        return _user_text(change, docstrings)
    return _developer_text(change, docstrings)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def build_entries(
    changes: Sequence[ClassifiedChange],
    audience: str,
    docstrings: Mapping[str, str],
) -> tuple[ChangelogEntry, ...]:
    ordered = sorted(
        changes,
        key=lambda c: (_ENTRY_ORDER.index(c.entry_type), c.neurons[0].name),
    )
    entries: list[ChangelogEntry] = []
    eligible = _AUDIENCE_TYPES.get(audience, _AUDIENCE_TYPES["developer"])
    for change in ordered:
        entries.append(
            ChangelogEntry(
                type=change.entry_type,
                title=_entry_title(change.entry_type, change.neurons),
                description=_entry_description(change),
                neurons=tuple(n.id for n in change.neurons),
                blast_radius=change.blast_radius,
                audience_text=_audience_text(change, audience, docstrings)
                if change.entry_type in eligible
                else "",
                lobes=tuple(sorted({n.lobe for n in change.neurons})),
                memory_notes=tuple(m.title for m in change.memories),
            )
        )
    return tuple(entries)


def _intent_entry(
    repo_root: Path, files: Sequence[str], audience: str
) -> ChangelogEntry | None:
    """Record a #23 product-intent update as an ``intent_update`` entry."""
    if ".cerebrofy/intent.yaml" not in files:
        return None
    try:
        intent = load_intent(repo_root / ".cerebrofy")
    except Exception:
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


def _breaking_changes(
    entries: Sequence[ChangelogEntry],
) -> tuple[dict[str, Any], ...]:
    out: list[dict[str, Any]] = []
    for entry in entries:
        if entry.type != BREAKING:
            continue
        out.append(
            {
                "title": entry.title,
                "description": entry.description,
                "neurons": list(entry.neurons),
            }
        )
    return tuple(out)


def generate_changelog(
    repo_root: Path,
    since: str,
    audience: str = "developer",
    output_format: str = "markdown",
    conn: sqlite3.Connection | None = None,
    config: ChangelogConfig | None = None,
) -> ChangelogReport:
    """Generate a semantic changelog for ``since``..HEAD.

    Raises:
        ChangelogError(CODE_NO_INDEX): the cerebrofy index is missing.
        ChangelogError(CODE_REF_NOT_FOUND): the git ref cannot be resolved.
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
    db_path = cerebrofy_dir / "db" / "cerebrofy.db"
    owns_conn = conn is None
    if owns_conn:
        conn = _open_index_db(db_path)

    assert conn is not None  # narrowed by the owns_conn branch above
    try:
        full_config: object = None
        config_path = cerebrofy_dir / "config.yaml"
        if config_path.exists():
            try:
                full_config = load_config(config_path)
            except Exception:
                full_config = None

        memories_by_neuron = _load_memories(cerebrofy_dir)
        collected: CollectedChanges = collect_changes(
            repo_root, conn, since, config=full_config, resolved=None
        )

        cfg_lobes = getattr(full_config, "lobes", None) or None
        # Determine the changelog-specific config: an explicitly-passed config
        # wins; otherwise derive from the loaded full config; otherwise default.
        changelog_cfg: ChangelogConfig
        if config is not None:
            changelog_cfg = config
        elif full_config is not None:
            changelog_cfg = getattr(full_config, "changelog", None) or ChangelogConfig()
        else:
            changelog_cfg = ChangelogConfig()

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
        return _with_full_text(report)
    finally:
        if owns_conn and conn is not None:
            conn.close()


def _with_full_text(report: ChangelogReport) -> ChangelogReport:
    # ``format_changelog`` is imported at function scope to avoid a circular
    # import: formatter.py imports ChangelogEntry/ChangelogReport from this
    # module at module scope, so this module must not import formatter at module
    # scope.
    from cerebrofy.changelog.formatter import format_changelog

    return ChangelogReport(
        since=report.since,
        until=report.until,
        entries=report.entries,
        breaking_changes=report.breaking_changes,
        health_delta=report.health_delta,
        full_text=format_changelog(report),
        audience=report.audience,
        format=report.format,
        until_short=report.until_short,
        until_date=report.until_date,
        note=report.note,
    )


# ---------------------------------------------------------------------------
# Narrative events (feeds Idea #26 — this lane only writes the table)
# ---------------------------------------------------------------------------


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