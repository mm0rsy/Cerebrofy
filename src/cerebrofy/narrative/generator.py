"""Codebase Narrative Engine — generates NARRATIVE.md from health, memories, git."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlite3 import Connection


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


def generate_narrative(
    cerebrofy_dir: Path,
    force: bool = False,
) -> NarrativeData:
    """Generate the codebase narrative and write NARRATIVE.md."""
    db_path = cerebrofy_dir / "db" / "cerebrofy.db"
    if not db_path.exists():
        raise FileNotFoundError("Index not found. Run 'cerebrofy build' first.")

    # Load health snapshots
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    snapshots = _load_health_snapshots(conn)
    conn.close()

    if len(snapshots) < 3 and not force:
        raise ValueError("INSUFFICIENT_HISTORY: Fewer than 3 builds — not enough history for era detection")

    # Detect eras
    eras = _detect_eras(snapshots)

    # Load significant events from memories
    events = _load_significant_events(cerebrofy_dir)

    # Load intent for trajectory
    trajectory = _load_trajectory(cerebrofy_dir)

    # Generate architectural DNA
    dna = _synthesize_dna(cerebrofy_dir, eras)

    # Build narrative data
    narrative = NarrativeData(
        project_name=cerebrofy_dir.parent.name,
        last_updated=int(time.time()),
        era_count=len(eras),
        event_count=len(events),
        eras=eras,
        significant_events=events,
        architectural_dna=dna,
        trajectory=trajectory,
        current_era=_current_era_data(eras[-1]) if eras else {},
    )

    # Write NARRATIVE.md
    _write_narrative_file(cerebrofy_dir, narrative)

    return narrative


def _load_health_snapshots(conn: Connection) -> list[HealthSnapshot]:
    """Load health snapshots ordered by build_ts."""
    rows = conn.execute(
        """
        SELECT build_ts, commit_hash, coupling, avg_blast, neuron_count, edge_count, test_surface
        FROM health_snapshots
        ORDER BY build_ts ASC
        """
    ).fetchall()

    return [
        HealthSnapshot(
            build_ts=row["build_ts"],
            commit_hash=row["commit_hash"],
            coupling=row["coupling"],
            avg_blast=row["avg_blast"],
            neuron_count=row["neuron_count"],
            edge_count=row["edge_count"],
            test_surface=row["test_surface"],
        )
        for row in rows
    ]


def _detect_eras(snapshots: list[HealthSnapshot]) -> list[Era]:
    """Detect architectural eras from health snapshots."""
    if len(snapshots) < 2:
        return []

    eras: list[Era] = []
    current_era_start = snapshots[0]

    for i, snapshot in enumerate(snapshots[1:], 1):
        prev = snapshots[i - 1]

        coupling_change = 0.0
        if prev.coupling > 0:
            coupling_change = abs(snapshot.coupling - prev.coupling) / prev.coupling

        blast_change = 0.0
        if prev.avg_blast > 0:
            blast_change = abs(snapshot.avg_blast - prev.avg_blast) / prev.avg_blast

        lobe_change = snapshot.neuron_count != prev.neuron_count  # rough proxy

        if coupling_change > 0.10 or blast_change > 0.20 or lobe_change:
            # Era transition detected
            key_changes = _identify_key_changes(prev, snapshot)
            eras.append(
                Era(
                    name=_era_name(len(eras) + 1, prev, snapshot),
                    start_ts=current_era_start.build_ts,
                    end_ts=snapshot.build_ts,
                    trigger_snapshot=snapshot,
                    key_changes=key_changes,
                    structural_state={
                        "lobes": 0,  # Would need lobe detection
                        "neurons": snapshot.neuron_count,
                        "coupling": snapshot.coupling,
                        "avg_blast_radius": snapshot.avg_blast,
                    },
                )
            )
            current_era_start = snapshot

    # Final era
    if current_era_start:
        last = snapshots[-1]
        key_changes = _identify_key_changes(current_era_start, last)
        eras.append(
            Era(
                name=_era_name(len(eras) + 1, current_era_start, last),
                start_ts=current_era_start.build_ts,
                end_ts=last.build_ts,
                trigger_snapshot=last,
                key_changes=key_changes,
                structural_state={
                    "lobes": 0,
                    "neurons": last.neuron_count,
                    "coupling": last.coupling,
                    "avg_blast_radius": last.avg_blast,
                },
            )
        )

    return eras


def _era_name(num: int, start: HealthSnapshot, end: HealthSnapshot) -> str:
    """Generate an era name."""
    # Simplified - could be enhanced with date ranges
    return f"Era {num}"


def _identify_key_changes(prev: HealthSnapshot, curr: HealthSnapshot) -> list[str]:
    """Identify key changes between two snapshots."""
    changes = []

    if prev.coupling > 0:
        pct = ((curr.coupling - prev.coupling) / prev.coupling) * 100
        if abs(pct) > 10:
            direction = "increased" if pct > 0 else "decreased"
            changes.append(f"Coupling {direction} by {abs(pct):.0f}%")

    if prev.avg_blast > 0:
        pct = ((curr.avg_blast - prev.avg_blast) / prev.avg_blast) * 100
        if abs(pct) > 20:
            direction = "increased" if pct > 0 else "decreased"
            changes.append(f"Avg blast radius {direction} by {abs(pct):.0f}%")

    if curr.neuron_count != prev.neuron_count:
        diff = curr.neuron_count - prev.neuron_count
        changes.append(f"Neuron count changed by {diff:+d}")

    return changes


def _load_significant_events(cerebrofy_dir: Path) -> list[dict[str, object]]:
    """Load significant decision/warning memories as narrative events."""
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
            LIMIT 20
            """
        ).fetchall()

        events: list[dict[str, object]] = []
        for row in rows:
            events.append({
                "date": int(row["created_ts"]),
                "event": str(row["title"]),
                "lobes_affected": [str(row["lobe"])] if row["lobe"] else [],
                "impact": str(row["type"]).capitalize(),
            })
        return events
    finally:
        conn.close()


def _load_trajectory(cerebrofy_dir: Path) -> str:
    """Load trajectory from intent.yaml."""
    intent_path = cerebrofy_dir / "intent.yaml"
    if not intent_path.exists():
        return "No active sprint goal defined. Configure intent.yaml to set direction."

    try:
        import yaml
        with open(intent_path) as f:
            data = yaml.safe_load(f)
        if not data:
            return "No active sprint goal defined."

        parts = []
        if data.get("sprint_goal"):
            parts.append(f"Sprint Goal: {data['sprint_goal']}")
        if data.get("active_incidents"):
            parts.append(f"Active Incidents: {', '.join(data['active_incidents'])}")
        if data.get("architectural_direction"):
            parts.append(f"Architectural Direction: {data['architectural_direction']}")
        return " | ".join(parts) if parts else "Intent file present but empty."
    except Exception:
        return "Could not parse intent.yaml."


def _synthesize_dna(cerebrofy_dir: Path, eras: list[Era]) -> str:
    """Synthesize architectural DNA from arch rules and memories."""
    # Load arch rules
    rules_path = cerebrofy_dir / "arch-rules.yaml"
    dna_parts: list[str] = []

    if rules_path.exists():
        try:
            import yaml
            with open(rules_path) as f:
                rules = yaml.safe_load(f)
            if rules and rules.get("rules"):
                rule_names = [r.get("id", "") for r in rules["rules"] if r.get("enabled", True)]
                if rule_names:
                    dna_parts.append(f"Enforces {len(rule_names)} architecture rules: {', '.join(rule_names[:5])}")
        except Exception:
            pass

    # Add health trend
    if eras:
        first = eras[0].structural_state
        last = eras[-1].structural_state
        coupling_trend = float(str(last.get("coupling", 0.0))) - float(str(first.get("coupling", 0.0)))
        if coupling_trend > 0.05:
            dna_parts.append("Trending toward higher coupling — modularization needed")
        elif coupling_trend < -0.05:
            dna_parts.append("Successfully reducing coupling over time")

    if not dna_parts:
        dna_parts.append("Architectural DNA still being established — run more builds to refine.")

    return ". ".join(dna_parts)


def _current_era_data(era: Era) -> dict[str, object]:
    """Build current era data for output."""
    return {
        "name": era.name,
        "started": era.trigger_snapshot.commit_hash[:8] if era.trigger_snapshot.commit_hash else "unknown",
        "key_changes": era.key_changes,
        "structural_state": era.structural_state,
    }


def _write_narrative_file(cerebrofy_dir: Path, narrative: NarrativeData) -> None:
    """Write NARRATIVE.md to .cerebrofy/NARRATIVE.md."""
    narrative_path = cerebrofy_dir / "NARRATIVE.md"

    lines = [
        f"# The Story of {narrative.project_name}",
        "",
        f"*Auto-generated by Cerebrofy Narrative Engine. Last updated: {time.strftime('%Y-%m-%d', time.localtime(narrative.last_updated))}*",
        f"*Covers: {narrative.era_count} architectural eras | {narrative.event_count} significant events*",
        "",
    ]

    for i, era in enumerate(narrative.eras, 1):
        lines.extend([
            f"## Era {i}: {era.name}",
            f"Period: {time.strftime('%Y-%m-%d', time.localtime(era.start_ts))} to {time.strftime('%Y-%m-%d', time.localtime(era.end_ts))}",
            "",
            "### Key Changes",
        ])
        for change in era.key_changes:
            lines.append(f"- {change}")
        lines.extend([
            "",
            "### Structural State",
            f"- Neurons: {era.structural_state['neurons']}",
            f"- Coupling: {era.structural_state['coupling']:.3f}",
            f"- Avg Blast Radius: {era.structural_state['avg_blast_radius']:.1f}",
            "",
        ])

    lines.extend([
        "## Significant Events",
        "| Date | Event | Lobes Affected | Impact |",
        "|------|-------|----------------|--------|",
    ])
    for event in narrative.significant_events[:10]:
        date_val = event["date"]
        date_int = int(str(date_val))
        date_str = time.strftime('%Y-%m-%d', time.localtime(date_int))
        lobes_list = event["lobes_affected"]
        if isinstance(lobes_list, list):
            lobes = ", ".join(str(lobe) for lobe in lobes_list) if lobes_list else "—"
        else:
            lobes = "—"
        lines.append(f"| {date_str} | {event['event']} | {lobes} | {event['impact']} |")

    lines.extend([
        "",
        "## Architectural DNA",
        narrative.architectural_dna,
        "",
        "## Where It's Going",
        narrative.trajectory,
    ])

    narrative_path.write_text("\n".join(lines), encoding="utf-8")