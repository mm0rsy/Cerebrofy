"""Codebase Narrative Engine — generates NARRATIVE.md from health, memories, git."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Hard ceiling for NARRATIVE.md (Idea #26 spec): oldest eras collapse first.
MAX_NARRATIVE_BYTES = 50 * 1024

#: Era transition thresholds (spec): a structural step larger than these starts
#: a new era. ``lobe_count`` changes always start a new era.
COUPLING_THRESHOLD = 0.10
BLAST_THRESHOLD = 0.20

_EVENT_LIMIT = 20
_EVENT_TABLE_LIMIT = 10


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    """A single health snapshot from the database."""

    build_ts: int
    commit_hash: str | None
    coupling: float
    avg_blast: float
    neuron_count: int
    edge_count: int
    test_surface: float
    lobe_count: int = 0


@dataclass(frozen=True, slots=True)
class Era:
    """A detected architectural era."""

    name: str
    start_ts: int
    end_ts: int
    trigger_snapshot: HealthSnapshot
    key_changes: list[str]
    structural_state: dict[str, object]


@dataclass(frozen=True, slots=True)
class NarrativeData:
    """Complete narrative data for rendering."""

    project_name: str
    last_updated: int
    era_count: int
    event_count: int
    eras: list[Era]
    significant_events: list[dict[str, object]]
    architectural_dna: str
    trajectory: str
    current_era: dict[str, object]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_narrative_data(cerebrofy_dir: Path) -> NarrativeData:
    """Build the narrative data without writing ``NARRATIVE.md``.

    Read-only counterpart of :func:`generate_narrative`, shared by the MCP tool
    and the CLI so structured fields never have to be re-derived from markdown.
    """
    db_path = _db_path(cerebrofy_dir)
    if not db_path.exists():
        raise FileNotFoundError("Index not found. Run 'cerebrofy build' first.")
    snapshots = _load_health_snapshots(db_path)
    return _assemble_narrative(cerebrofy_dir, snapshots)


def generate_narrative(
    cerebrofy_dir: Path,
    force: bool = False,
) -> NarrativeData:
    """Generate the codebase narrative and atomically write ``NARRATIVE.md``.

    ``force=True`` renders a document even with fewer than three snapshots
    (one era); the non-forced path raises ``INSUFFICIENT_HISTORY`` naming the
    missing prerequisite.
    """
    db_path = _db_path(cerebrofy_dir)
    if not db_path.exists():
        raise FileNotFoundError("Index not found. Run 'cerebrofy build' first.")

    snapshots = _load_health_snapshots(db_path)
    if len(snapshots) < 3 and not force:
        raise ValueError(
            "INSUFFICIENT_HISTORY: Found "
            f"{len(snapshots)} health snapshot(s); era detection needs at least "
            "3 builds. Run 'cerebrofy update' a few more times (or "
            "'cerebrofy build') to accumulate history."
        )

    narrative = _assemble_narrative(cerebrofy_dir, snapshots)
    _write_narrative_file(cerebrofy_dir, narrative)
    return narrative


def maybe_update_narrative(cerebrofy_dir: Path) -> bool:
    """Cheap auto-update gate used by build, insight, and session hooks.

    Regenerates only when ``NARRATIVE.md`` is absent or when the latest health
    snapshot crosses an era threshold relative to the last rendered era end.
    Never raises: hooks must stay non-fatal. Returns ``True`` when a document
    was (re)written.
    """
    try:
        db_path = _db_path(cerebrofy_dir)
        if not db_path.exists():
            return False
        snapshots = _load_health_snapshots(db_path)
        if not snapshots:
            return False

        narrative_path = cerebrofy_dir / "NARRATIVE.md"
        if not narrative_path.exists():
            generate_narrative(cerebrofy_dir, force=True)
            return True

        last_end = _last_rendered_era_end(narrative_path)
        baseline = (
            _snapshot_at_or_before(snapshots, last_end)
            if last_end is not None
            else snapshots[0]
        )
        latest = snapshots[-1]
        if latest.build_ts <= baseline.build_ts:
            return False
        if _is_transition(baseline, latest):
            generate_narrative(cerebrofy_dir, force=True)
            return True
        return False
    except Exception:  # noqa: BLE001 — narrative upkeep must never fail a hook
        return False


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _db_path(cerebrofy_dir: Path) -> Path:
    return cerebrofy_dir / "db" / "cerebrofy.db"


def _load_health_snapshots(db_path: Path) -> list[HealthSnapshot]:
    """Load health snapshots ordered by build_ts.

    Tolerates old databases without ``lobe_count`` (treated as 0/unknown) and
    a missing ``health_snapshots`` table.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "health_snapshots" not in tables:
            return []
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(health_snapshots)")
        }
        lobe_expr = "lobe_count" if "lobe_count" in columns else "0 AS lobe_count"
        rows = conn.execute(
            f"""
            SELECT build_ts, commit_hash, coupling, avg_blast, neuron_count,
                   edge_count, test_surface, {lobe_expr}
            FROM health_snapshots
            ORDER BY build_ts ASC, id ASC
            """
        ).fetchall()
        return [
            HealthSnapshot(
                build_ts=_as_int(row["build_ts"]),
                commit_hash=str(row["commit_hash"]) if row["commit_hash"] else None,
                coupling=_as_float(row["coupling"]),
                avg_blast=_as_float(row["avg_blast"]),
                neuron_count=_as_int(row["neuron_count"]),
                edge_count=_as_int(row["edge_count"]),
                test_surface=_as_float(row["test_surface"]),
                lobe_count=_as_int(row["lobe_count"]),
            )
            for row in rows
        ]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _assemble_narrative(
    cerebrofy_dir: Path,
    snapshots: list[HealthSnapshot],
) -> NarrativeData:
    eras = _detect_eras(snapshots)
    events = _load_significant_events(cerebrofy_dir)
    trajectory = _load_trajectory(cerebrofy_dir)
    dna = _synthesize_dna(cerebrofy_dir, eras)
    return NarrativeData(
        project_name=_project_name(cerebrofy_dir),
        last_updated=int(time.time()),
        era_count=len(eras),
        event_count=len(events),
        eras=eras,
        significant_events=events,
        architectural_dna=dna,
        trajectory=trajectory,
        current_era=era_to_dict(eras[-1]) if eras else {},
    )


# ---------------------------------------------------------------------------
# Era detection
# ---------------------------------------------------------------------------


def _detect_eras(snapshots: list[HealthSnapshot]) -> list[Era]:
    """Detect architectural eras from health snapshots."""
    if not snapshots:
        return []

    eras: list[Era] = []
    current_era_start = snapshots[0]

    for i, snapshot in enumerate(snapshots[1:], 1):
        prev = snapshots[i - 1]
        if not _is_transition(prev, snapshot):
            continue

        # The closing era ends at the last snapshot before the boundary; the
        # next era starts at the snapshot that crossed it (no overlap).
        eras.append(
            Era(
                name=_era_name(prev, snapshot),
                start_ts=current_era_start.build_ts,
                end_ts=prev.build_ts,
                trigger_snapshot=snapshot,
                key_changes=_identify_key_changes(prev, snapshot),
                structural_state=_structural_state(snapshot),
            )
        )
        current_era_start = snapshot

    last = snapshots[-1]
    eras.append(
        Era(
            name=_era_name(current_era_start, last),
            start_ts=current_era_start.build_ts,
            end_ts=last.build_ts,
            trigger_snapshot=last,
            key_changes=_identify_key_changes(current_era_start, last),
            structural_state=_structural_state(last),
        )
    )
    return eras


def _is_transition(prev: HealthSnapshot, curr: HealthSnapshot) -> bool:
    """Return True when the step between two snapshots starts a new era."""
    if curr.lobe_count != prev.lobe_count:
        return True
    if prev.coupling > 0:
        if abs(curr.coupling - prev.coupling) / prev.coupling > COUPLING_THRESHOLD:
            return True
    if prev.avg_blast > 0:
        if abs(curr.avg_blast - prev.avg_blast) / prev.avg_blast > BLAST_THRESHOLD:
            return True
    return False


def _era_name(start: HealthSnapshot, end: HealthSnapshot) -> str:
    """Describe an era from the change that triggered it.

    The writer owns the numeric prefix (``## Era N: ...``); this name must not
    contain it, otherwise headings render as ``## Era 1: Era 1``.
    """
    labels: list[str] = []
    if end.lobe_count > start.lobe_count:
        labels.append("Expansion")
    elif end.lobe_count < start.lobe_count:
        labels.append("Consolidation")

    if start.coupling > 0:
        change = abs(end.coupling - start.coupling) / start.coupling
        if change > COUPLING_THRESHOLD:
            labels.append("Coupling shift")

    if start.avg_blast > 0:
        change = abs(end.avg_blast - start.avg_blast) / start.avg_blast
        if change > BLAST_THRESHOLD:
            labels.append("Blast-radius shift")

    if not labels and end.neuron_count != start.neuron_count:
        labels.append(
            "Neuron growth"
            if end.neuron_count > start.neuron_count
            else "Neuron contraction"
        )
    return " & ".join(labels[:2]) if labels else "Stability"


def _identify_key_changes(prev: HealthSnapshot, curr: HealthSnapshot) -> list[str]:
    """Identify key changes between two snapshots (deterministic order)."""
    changes: list[str] = []

    if curr.lobe_count != prev.lobe_count:
        changes.append(
            f"Lobe count changed from {prev.lobe_count} to {curr.lobe_count}"
        )

    if prev.coupling > 0:
        pct = ((curr.coupling - prev.coupling) / prev.coupling) * 100
        if abs(pct) > COUPLING_THRESHOLD * 100:
            direction = "increased" if pct > 0 else "decreased"
            changes.append(f"Coupling {direction} by {abs(pct):.0f}%")

    if prev.avg_blast > 0:
        pct = ((curr.avg_blast - prev.avg_blast) / prev.avg_blast) * 100
        if abs(pct) > BLAST_THRESHOLD * 100:
            direction = "increased" if pct > 0 else "decreased"
            changes.append(f"Avg blast radius {direction} by {abs(pct):.0f}%")

    if curr.neuron_count != prev.neuron_count:
        diff = curr.neuron_count - prev.neuron_count
        changes.append(f"Neuron count changed by {diff:+d}")

    return changes


def _structural_state(snapshot: HealthSnapshot) -> dict[str, object]:
    return {
        "lobes": snapshot.lobe_count,
        "neurons": snapshot.neuron_count,
        "coupling": snapshot.coupling,
        "avg_blast_radius": snapshot.avg_blast,
    }


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def _load_significant_events(cerebrofy_dir: Path) -> list[dict[str, object]]:
    """Merge changelog ``narrative_events`` with decision/warning/incident memories.

    Events are deduped by ``(title, date)``, sorted newest-first, and capped at
    20 so NARRATIVE.md stays compact and deterministic.
    """
    merged: list[dict[str, object]] = []
    merged.extend(_load_narrative_events(cerebrofy_dir))
    merged.extend(_load_memory_events(cerebrofy_dir))

    unique: dict[tuple[str, int], dict[str, object]] = {}
    for event in merged:
        key = (str(event["event"]), _as_int(event["date"]))
        unique.setdefault(key, event)

    ordered = sorted(
        unique.values(),
        key=lambda event: (-_as_int(event["date"]), str(event["event"]).lower()),
    )
    return ordered[:_EVENT_LIMIT]


def _load_narrative_events(cerebrofy_dir: Path) -> list[dict[str, object]]:
    db_path = _db_path(cerebrofy_dir)
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        if "narrative_events" not in tables:
            return []
        rows = conn.execute(
            """
            SELECT ts, type, title, lobes_affected, blast_radius_delta
            FROM narrative_events
            ORDER BY ts DESC
            LIMIT ?
            """,
            (_EVENT_LIMIT,),
        ).fetchall()
        events: list[dict[str, object]] = []
        for row in rows:
            title = str(row["title"] or "").strip()
            if not title:
                continue
            events.append(
                {
                    "date": _as_int(row["ts"]),
                    "event": title,
                    "lobes_affected": _json_list(row["lobes_affected"]),
                    "impact": _impact_label(
                        row["type"], row["blast_radius_delta"]
                    ),
                }
            )
        return events
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _load_memory_events(cerebrofy_dir: Path) -> list[dict[str, object]]:
    memories_db = cerebrofy_dir / "db" / "memories.db"
    if not memories_db.exists():
        return []
    conn = sqlite3.connect(memories_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, type, title, body, lobe, created_ts, tags
            FROM memories
            WHERE type IN ('decision', 'warning', 'incident')
            ORDER BY created_ts DESC
            LIMIT ?
            """,
            (_EVENT_LIMIT,),
        ).fetchall()
        return [
            {
                "date": _as_int(row["created_ts"]),
                "event": str(row["title"]),
                "lobes_affected": [str(row["lobe"])] if row["lobe"] else [],
                "impact": str(row["type"]).capitalize(),
            }
            for row in rows
        ]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _impact_label(raw_type: object, blast_delta: object) -> str:
    label = str(raw_type or "event").capitalize()
    if blast_delta is not None:
        label += f" (blast Δ {_as_float(blast_delta):+.1f})"
    return label


def _json_list(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    text = str(raw).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        return [text]
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return [str(parsed)]


# ---------------------------------------------------------------------------
# Intent and DNA
# ---------------------------------------------------------------------------


def _load_trajectory(cerebrofy_dir: Path) -> str:
    """Render the ``Where It's Going`` section from ``.cerebrofy/intent.yaml``."""
    try:
        from cerebrofy.intent.loader import load_intent

        intent = load_intent(cerebrofy_dir)
    except Exception:  # noqa: BLE001 — malformed intent must not fail generation
        return "Could not parse intent.yaml — check its YAML syntax."

    if intent is None:
        return (
            "No intent.yaml found — add .cerebrofy/intent.yaml to record sprint "
            "goals, incidents, and architectural direction."
        )

    parts: list[str] = []
    if intent.sprint and intent.sprint.goal.strip():
        goal = intent.sprint.goal.strip()
        name = intent.sprint.name.strip()
        parts.append(f"Sprint goal ({name}): {goal}" if name else f"Sprint goal: {goal}")

    open_incidents = [
        incident
        for incident in intent.incidents
        if incident.status.strip().lower() not in {"closed", "patched", "resolved"}
    ]
    for incident in open_incidents:
        severity = incident.severity.strip() or "unknown"
        status = incident.status.strip() or "open"
        description = incident.description.strip() or incident.id.strip() or "incident"
        parts.append(f"Open incident ({severity}): {description} [{status}]")

    if intent.architecture:
        direction = intent.architecture.direction.strip()
        if direction:
            parts.append(f"Architectural direction: {direction}")
        goals = [goal.strip() for goal in intent.architecture.principles if goal.strip()]
        if goals:
            parts.append(f"Architectural goals: {', '.join(goals)}")

    if not parts:
        return (
            "Intent file present but no sprint goal, open incidents, or "
            "architectural direction is set."
        )
    return " | ".join(parts)


def _synthesize_dna(cerebrofy_dir: Path, eras: list[Era]) -> str:
    """Synthesize architectural DNA from arch rules and health trends.

    Malformed ``arch-rules.yaml`` never raises: the DNA section degrades to the
    health-trend sentence.
    """
    dna_parts: list[str] = []

    try:
        from cerebrofy.config.loader import load_arch_rules

        rules = load_arch_rules(cerebrofy_dir.parent)
    except Exception:  # noqa: BLE001 — malformed rules must not fail generation
        rules = None

    if rules is not None and rules.rules:
        names = list(rules.rule_names)
        shown = ", ".join(names[:5])
        suffix = f" (+{len(names) - 5} more)" if len(names) > 5 else ""
        dna_parts.append(
            f"Enforces {len(names)} architecture rule(s): {shown}{suffix}"
        )

    if eras:
        first = eras[0].structural_state
        last = eras[-1].structural_state

        coupling_trend = _state_float(last, "coupling") - _state_float(
            first, "coupling"
        )
        if coupling_trend > 0.05:
            dna_parts.append(
                "Trending toward higher coupling — modularization needed"
            )
        elif coupling_trend < -0.05:
            dna_parts.append("Successfully reducing coupling over time")

        first_neurons = _state_float(first, "neurons")
        last_neurons = _state_float(last, "neurons")
        if first_neurons > 0:
            growth = (last_neurons - first_neurons) / first_neurons
            if growth > 0.10:
                dna_parts.append(
                    f"Growing fast ({growth * 100:.0f}% more neurons since the first era)"
                )
            elif growth < -0.10:
                dna_parts.append("Shrinking through consolidation")

        blast_trend = _state_float(last, "avg_blast_radius") - _state_float(
            first, "avg_blast_radius"
        )
        if blast_trend > 2.0:
            dna_parts.append("Avg blast radius rising — changes are reaching further")
        elif blast_trend < -2.0:
            dna_parts.append("Avg blast radius falling — changes are getting safer")

    if not dna_parts:
        dna_parts.append(
            "Architectural DNA still being established — run more builds to refine."
        )
    return ". ".join(dna_parts)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def era_to_dict(era: Era) -> dict[str, object]:
    """Serialise an era for the MCP output schema (ISO date, not a commit hash)."""
    return {
        "name": era.name,
        "started": _iso_date(era.start_ts),
        "key_changes": list(era.key_changes),
        "structural_state": dict(era.structural_state),
        "commit": (
            era.trigger_snapshot.commit_hash[:8]
            if era.trigger_snapshot.commit_hash
            else "unknown"
        ),
    }


def _write_narrative_file(cerebrofy_dir: Path, narrative: NarrativeData) -> None:
    """Atomically write ``.cerebrofy/NARRATIVE.md`` (tmp file + replace)."""
    narrative_path = cerebrofy_dir / "NARRATIVE.md"
    document = _render_document(cerebrofy_dir, narrative)
    tmp_path = narrative_path.with_name(narrative_path.name + ".tmp")
    try:
        tmp_path.write_text(document, encoding="utf-8")
        os.replace(tmp_path, narrative_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _render_document(cerebrofy_dir: Path, narrative: NarrativeData) -> str:
    commit_count = _commit_count(cerebrofy_dir)
    commit_label = str(commit_count) if commit_count is not None else "unknown"

    header = "\n".join(
        [
            f"# The Story of {narrative.project_name}",
            "",
            "*Auto-generated by Cerebrofy Narrative Engine. Last updated: "
            f"{_iso_date(narrative.last_updated)}*",
            f"*Covers: {commit_label} commits | {narrative.era_count} architectural "
            f"eras | {narrative.event_count} significant events*",
        ]
    )

    era_blocks = [
        _render_era(index, era) for index, era in enumerate(narrative.eras, 1)
    ]
    collapsed = 0

    def render() -> str:
        pieces: list[str] = [header]
        if collapsed:
            pieces.append(
                f"*Note: the {collapsed} oldest era(s) are summarized below to "
                "keep this document under 50 KB.*"
            )
        pieces.extend(era_blocks)
        pieces.append(_render_events(narrative.significant_events))
        pieces.append(f"## Architectural DNA\n{narrative.architectural_dna}")
        pieces.append(f"## Where It's Going\n{narrative.trajectory}")
        return "\n\n".join(pieces) + "\n"

    document = render()
    while (
        len(document.encode("utf-8")) > MAX_NARRATIVE_BYTES
        and collapsed < max(len(narrative.eras) - 1, 0)
    ):
        era_blocks[collapsed] = _render_era_summary(
            collapsed + 1, narrative.eras[collapsed]
        )
        collapsed += 1
        document = render()
    return document


def _render_era(index: int, era: Era) -> str:
    lines = [
        f"## Era {index}: {era.name}",
        f"Period: {_iso_date(era.start_ts)} to {_iso_date(era.end_ts)}",
        "",
        "### Key Changes",
    ]
    if era.key_changes:
        lines.extend(f"- {change}" for change in era.key_changes)
    else:
        lines.append("- No metric crossed the era thresholds in this period.")
    lines.extend(
        [
            "",
            "### Structural State",
            f"- Lobes: {_as_int(era.structural_state.get('lobes'))}",
            f"- Neurons: {_as_int(era.structural_state.get('neurons'))}",
            "- Coupling: "
            f"{_state_float(era.structural_state, 'coupling'):.3f}",
            "- Avg Blast Radius: "
            f"{_state_float(era.structural_state, 'avg_blast_radius'):.1f}",
        ]
    )
    return "\n".join(lines)


def _render_era_summary(index: int, era: Era) -> str:
    return (
        f"- Era {index} ({_iso_date(era.start_ts)}–{_iso_date(era.end_ts)}): "
        f"{_as_int(era.structural_state.get('neurons'))} neurons, coupling "
        f"{_state_float(era.structural_state, 'coupling'):.3f} (summarized)"
    )


def _render_events(events: list[dict[str, object]]) -> str:
    lines = [
        "## Significant Events",
        "| Date | Event | Lobes Affected | Impact |",
        "|------|-------|----------------|--------|",
    ]
    if not events:
        lines.append("| — | No significant events recorded | — | — |")
    for event in events[:_EVENT_TABLE_LIMIT]:
        date_str = _iso_date(_as_int(event["date"]))
        title = str(event["event"]).replace("|", "\\|")
        raw_lobes = event["lobes_affected"]
        lobes = (
            ", ".join(str(lobe) for lobe in raw_lobes)
            if isinstance(raw_lobes, list) and raw_lobes
            else "—"
        )
        lines.append(f"| {date_str} | {title} | {lobes} | {event['impact']} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_name(cerebrofy_dir: Path) -> str:
    name = cerebrofy_dir.parent.name.strip()
    if not name or name in {"/", ".", ".."}:
        return "this codebase"
    return name


def _commit_count(cerebrofy_dir: Path) -> int | None:
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=cerebrofy_dir.parent,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return None


def _last_rendered_era_end(narrative_path: Path) -> int | None:
    """Return the end-of-day timestamp of the last full era in NARRATIVE.md."""
    try:
        text = narrative_path.read_text(encoding="utf-8")
    except OSError:
        return None
    last: int | None = None
    for line in text.splitlines():
        if not line.startswith("Period: "):
            continue
        _, _, end = line.partition(" to ")
        if not end:
            continue
        try:
            parsed = time.strptime(end.strip(), "%Y-%m-%d")
        except ValueError:
            continue
        last = int(time.mktime(parsed)) + 86399
    return last


def _snapshot_at_or_before(
    snapshots: list[HealthSnapshot], timestamp: int
) -> HealthSnapshot:
    for snapshot in reversed(snapshots):
        if snapshot.build_ts <= timestamp:
            return snapshot
    return snapshots[0]


def _iso_date(timestamp: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(timestamp))


def _state_float(state: dict[str, object], key: str) -> float:
    return _as_float(state.get(key))


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
