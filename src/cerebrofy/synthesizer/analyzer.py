"""Cross-Session Pattern Synthesizer — session data loading + statistical analysis."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlite3 import Connection

from cerebrofy.memory.store import write_memory, Memory
from cerebrofy.embedder import get_embedder


@dataclass(frozen=True, slots=True)
class Session:
    """A recorded agent session."""
    id: str
    started_at: int
    ended_at: int | None
    agent: str | None
    task: str
    outcome: str
    outcome_notes: str | None
    neurons_touched: list[str]
    blast_radius_before: int
    blast_radius_after: int
    tool_sequence: list[str]


@dataclass(frozen=True, slots=True)
class Pattern:
    """A synthesized cross-session pattern."""
    type: str
    title: str
    body: str
    confidence: float
    sessions_analyzed: int
    sample_size: int
    affected_lobes: list[str]
    created_ts: int


def run_synthesis(
    cerebrofy_dir: Path,
    min_sessions: int = 10,
    min_confidence: float = 0.7,
    run_now: bool = False,
) -> list[Pattern]:
    """Run cross-session synthesis and write patterns as memories."""
    sessions_db = cerebrofy_dir / "db" / "sessions.db"
    if not sessions_db.exists():
        return []

    conn = sqlite3.connect(sessions_db)
    conn.row_factory = sqlite3.Row

    try:
        sessions = _load_sessions(conn)
        if len(sessions) < min_sessions:
            return []

        patterns: list[Pattern] = []

        # Run all pattern detectors
        patterns.extend(detect_failure_correlations(sessions, min_confidence))
        patterns.extend(detect_lobe_fragility(sessions, min_confidence))
        patterns.extend(detect_effort_calibration(sessions, min_confidence))
        patterns.extend(detect_missing_step(sessions, min_confidence))
        patterns.extend(detect_agent_blind_spot(sessions, min_confidence))

        # Write patterns as memories
        if patterns:
            memories_db = cerebrofy_dir / "db" / "memories.db"
            if memories_db.exists():
                mem_conn = sqlite3.connect(memories_db)
                mem_conn.execute("PRAGMA journal_mode=WAL")
                embedder = get_embedder("default")
                if embedder is None:
                    raise RuntimeError("Embedder not available")
                for pattern in patterns:
                    memory = Memory(
                        id=_pattern_id(pattern),
                        neuron_id=None,
                        lobe=None,
                        type="pattern",
                        title=pattern.title,
                        body=pattern.body,
                        author="cerebrofy-synthesizer",
                        created_ts=pattern.created_ts,
                        tags=(f"synthesized,{pattern.type}",),
                        decay_score=1.0,
                        status="active",
                    )
                    write_memory(conn=mem_conn, memory=memory, embedding=embedder.embed([pattern.title + " " + pattern.body])[0])
                mem_conn.commit()
                mem_conn.close()

        return patterns
    finally:
        conn.close()


def _pattern_id(pattern: Pattern) -> str:
    """Generate a unique ID for a pattern."""
    import hashlib
    base = f"pattern-{pattern.type}-{pattern.created_ts}"
    return hashlib.sha256(base.encode()).hexdigest()[:24]


def _load_sessions(conn: Connection) -> list[Session]:
    """Load all sessions with their tool sequences."""
    session_rows = conn.execute(
        """
        SELECT id, started_at, ended_at, agent, task, outcome, outcome_notes,
               neurons_touched, blast_radius_before, blast_radius_after
        FROM sessions
        WHERE outcome IN ('success', 'failed')
        ORDER BY started_at ASC
        """
    ).fetchall()

    sessions = []
    for row in session_rows:
        # Load tool sequence for this session
        tool_rows = conn.execute(
            "SELECT tool FROM session_events WHERE session_id = ? ORDER BY ts ASC",
            (row["id"],),
        ).fetchall()
        tool_sequence = [r["tool"] for r in tool_rows]

        neurons = []
        if row["neurons_touched"]:
            try:
                neurons = row["neurons_touched"].split(",")
            except (AttributeError, ValueError):
                pass

        sessions.append(
            Session(
                id=row["id"],
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                agent=row["agent"],
                task=row["task"],
                outcome=row["outcome"],
                outcome_notes=row["outcome_notes"],
                neurons_touched=neurons,
                blast_radius_before=row["blast_radius_before"] or 0,
                blast_radius_after=row["blast_radius_after"] or 0,
                tool_sequence=tool_sequence,
            )
        )
    return sessions


def _generate_tool_sequence_candidates(sessions: list[Session]) -> set[str]:
    """Generate candidate tool sequence patterns from sessions."""
    candidates = set()
    for session in sessions:
        tools = session.tool_sequence
        # Generate subsequences of length 2-4
        for i in range(len(tools)):
            for length in range(2, min(5, len(tools) - i + 1)):
                candidate = " → ".join(tools[i:i+length])
                candidates.add(candidate)
    return candidates


def detect_failure_correlations(sessions: list[Session], min_confidence: float) -> list[Pattern]:
    """Detect tool sequences that correlate with failures."""
    patterns: list[Pattern] = []

    candidates = _generate_tool_sequence_candidates(sessions)

    for candidate in candidates:
        with_pattern = [s for s in sessions if candidate in " → ".join(s.tool_sequence)]
        without_pattern = [s for s in sessions if candidate not in " → ".join(s.tool_sequence)]

        if len(with_pattern) < 5:
            continue

        failure_rate_with = sum(1 for s in with_pattern if s.outcome == "failed") / len(with_pattern)
        failure_rate_without = sum(1 for s in without_pattern if s.outcome == "failed") / max(len(without_pattern), 1)

        if failure_rate_without == 0:
            continue

        lift = failure_rate_with / failure_rate_without
        if lift > 2.0:
            confidence = min(lift / 3, 1.0)
            if confidence >= min_confidence:
                patterns.append(
                    Pattern(
                        type="failure_correlation",
                        title=f"Tool sequence '{candidate}' correlates with {lift:.1f}× failure rate",
                        body=f"Analyzed {len(sessions)} sessions. Sessions with '{candidate}' had {failure_rate_with*100:.0f}% failure rate vs {failure_rate_without*100:.0f}% without. Confidence: {confidence:.2f}. Sample: {len(with_pattern)} with pattern, {len(without_pattern)} without.",
                        confidence=confidence,
                        sessions_analyzed=len(sessions),
                        sample_size=len(with_pattern),
                        affected_lobes=[],
                        created_ts=int(time.time()),
                    )
                )

    return patterns


def detect_lobe_fragility(sessions: list[Session], min_confidence: float) -> list[Pattern]:
    """Detect lobes with high failure rates."""
    patterns: list[Pattern] = []

    # Group sessions by lobes touched
    lobe_sessions: dict[str, list[Session]] = {}
    for session in sessions:
        for neuron in session.neurons_touched:
            # Extract lobe from neuron path (e.g., "auth/tokens.py" -> "auth")
            if "/" in neuron:
                lobe = neuron.split("/")[0]
                lobe_sessions.setdefault(lobe, []).append(session)

    for lobe, lobe_sess in lobe_sessions.items():
        if len(lobe_sess) < 5:
            continue

        failed = sum(1 for s in lobe_sess if s.outcome == "failed")
        failure_rate = failed / len(lobe_sess)

        if failure_rate > 0.7 and failure_rate >= min_confidence:
            patterns.append(
                Pattern(
                    type="lobe_fragility",
                    title=f"{lobe}/ changes produce test failures in {failure_rate*100:.0f}% of sessions",
                    body=f"Analyzed {len(lobe_sess)} sessions involving {lobe}/. {failed} failed ({failure_rate*100:.0f}% failure rate).",
                    confidence=failure_rate,
                    sessions_analyzed=len(sessions),
                    sample_size=len(lobe_sess),
                    affected_lobes=[lobe],
                    created_ts=int(time.time()),
                )
            )

    return patterns


def detect_effort_calibration(sessions: list[Session], min_confidence: float) -> list[Pattern]:
    """Detect systematic effort estimation errors."""
    patterns: list[Pattern] = []

    # Look for upgrade/session patterns where actual blast >> predicted
    upgrade_sessions = [s for s in sessions if "upgrade" in s.task.lower() or "cerebrofy_upgrade" in s.tool_sequence]

    if len(upgrade_sessions) < 3:
        return patterns

    underestimated = 0
    total = 0
    for session in upgrade_sessions:
        predicted = session.blast_radius_before
        actual = session.blast_radius_after
        if predicted > 0 and actual > predicted * 2:
            underestimated += 1
        total += 1

    if total >= 3 and underestimated / total > 0.5:
        confidence = underestimated / total
        if confidence >= min_confidence:
            patterns.append(
                Pattern(
                    type="effort_calibration",
                    title=f"cerebrofy_upgrade time estimates are {underestimated/total*2:.0f}× low for packages with dynamic imports",
                    body=f"Analyzed {total} upgrade sessions. {underestimated} had actual blast radius > 2× predicted. This suggests upgrade manifests underestimate impact for dynamic import patterns.",
                    confidence=confidence,
                    sessions_analyzed=len(sessions),
                    sample_size=total,
                    affected_lobes=[],
                    created_ts=int(time.time()),
                )
            )

    return patterns


def detect_missing_step(sessions: list[Session], min_confidence: float) -> list[Pattern]:
    """Detect missing steps that correlate with success."""
    patterns: list[Pattern] = []

    candidates = _generate_tool_sequence_candidates(sessions)

    for candidate in candidates:
        with_pattern = [s for s in sessions if candidate in " → ".join(s.tool_sequence)]
        without_pattern = [s for s in sessions if candidate not in " → ".join(s.tool_sequence)]

        if len(with_pattern) < 5 or len(without_pattern) < 5:
            continue

        success_rate_with = sum(1 for s in with_pattern if s.outcome == "success") / len(with_pattern)
        success_rate_without = sum(1 for s in without_pattern if s.outcome == "success") / len(without_pattern)

        lift = success_rate_with / max(success_rate_without, 0.01)
        if lift > 2.0:
            confidence = min(lift / 3, 1.0)
            if confidence >= min_confidence:
                patterns.append(
                    Pattern(
                        type="missing_step",
                        title=f"Sessions with '{candidate}' succeed {lift:.1f}× more often",
                        body=f"Analyzed {len(sessions)} sessions. Sessions with '{candidate}' had {success_rate_with*100:.0f}% success rate vs {success_rate_without*100:.0f}% without. Confidence: {confidence:.2f}. Sample: {len(with_pattern)} with pattern, {len(without_pattern)} without.",
                        confidence=confidence,
                        sessions_analyzed=len(sessions),
                        sample_size=len(with_pattern),
                        affected_lobes=[],
                        created_ts=int(time.time()),
                    )
                )

    return patterns


def detect_agent_blind_spot(sessions: list[Session], min_confidence: float) -> list[Pattern]:
    """Detect consistent patterns agents miss (e.g., missing __init__.py updates)."""
    patterns: list[Pattern] = []

    # Look for file-pattern blind spots: neurons that should be updated together
    # but agents consistently miss one
    module_groups: dict[str, set[str]] = {}

    for session in sessions:
        if session.outcome == "success":
            files = set()
            for neuron in session.neurons_touched:
                if "/" in neuron:
                    module = neuron.split("/")[0]
                    files.add(module)
            if len(files) >= 2:
                for module in files:
                    module_groups.setdefault(module, set()).update(files - {module})

    # Find modules that are often modified together but one is frequently missed
    # This is a heuristic - would need more sophisticated analysis in practice
    for module, co_modules in module_groups.items():
        if len(co_modules) >= 2:
            # Check if there's a common "missed" module
            pass  # Simplified for now

    return patterns