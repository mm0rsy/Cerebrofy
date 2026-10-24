"""Cross-Session Pattern Synthesizer — session data loading + statistical analysis."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlite3 import Connection

from cerebrofy.memory.embedder import embed_memory
from cerebrofy.memory.store import (
    Memory as MemoryRecord,
    get_memory,
    open_memories_db,
    write_memory,
)

_logger = logging.getLogger(__name__)

# Confidence thresholds from the Idea #24 spec.
_FAILURE_LIFT = 2.0
_MISSING_STEP_LIFT = 2.0
_BLIND_SPOT_FAILURE_RATE = 0.85
_EFFORT_CONFIDENCE = 0.80
_MIN_SAMPLE = 5
_MAX_SEQUENCE_CANDIDATES = 500


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
    lobe: str | None = None


@dataclass(frozen=True, slots=True)
class StoredPattern:
    """A pattern read back from the memory store."""

    id: str
    type: str
    title: str
    body: str
    confidence: float
    lobe: str | None
    sessions_analyzed: int
    sample_size: int
    created_ts: int


@dataclass(frozen=True, slots=True)
class SynthesisResult:
    """Outcome of one synthesis run."""

    patterns: list[Pattern]
    sessions_analyzed: int
    written: int
    updated: int


def synthesize(
    cerebrofy_dir: Path,
    min_sessions: int = 10,
    min_confidence: float = 0.7,
) -> SynthesisResult:
    """Run cross-session synthesis and persist patterns as memories.

    The returned :class:`SynthesisResult` reports every detected pattern even
    when the memory write fails — a storage problem never discards analysis.
    """
    sessions_db = cerebrofy_dir / "db" / "sessions.db"
    if not sessions_db.exists():
        return SynthesisResult(patterns=[], sessions_analyzed=0, written=0, updated=0)

    conn = sqlite3.connect(sessions_db)
    conn.row_factory = sqlite3.Row

    try:
        sessions = _load_sessions(conn)
        if len(sessions) < min_sessions:
            return SynthesisResult(
                patterns=[], sessions_analyzed=len(sessions), written=0, updated=0
            )

        # m5: one timestamp for the whole run, not one per detector/pattern.
        created_ts = int(time.time())
        flagged: set[str] = set()

        raw_patterns: list[Pattern] = []
        raw_patterns.extend(detect_failure_correlations(sessions, min_confidence, flagged))
        raw_patterns.extend(detect_lobe_fragility(sessions, min_confidence))
        raw_patterns.extend(detect_effort_calibration(sessions, min_confidence))
        raw_patterns.extend(detect_missing_step(sessions, min_confidence, excluded=flagged))
        raw_patterns.extend(detect_agent_blind_spot(sessions, min_confidence))

        patterns = [replace(p, created_ts=created_ts) for p in raw_patterns]
    finally:
        conn.close()

    written = 0
    updated = 0
    if patterns:
        try:
            written, updated = _persist_patterns(cerebrofy_dir, patterns)
        except Exception:
            # B2: pattern computation must survive a broken memory store.
            _logger.exception("cross-session synthesis could not write patterns")

    return SynthesisResult(
        patterns=patterns,
        sessions_analyzed=len(sessions),
        written=written,
        updated=updated,
    )


def run_synthesis(
    cerebrofy_dir: Path,
    min_sessions: int = 10,
    min_confidence: float = 0.7,
) -> list[Pattern]:
    """Run synthesis and return the detected patterns (compatibility wrapper)."""
    return synthesize(
        cerebrofy_dir, min_sessions=min_sessions, min_confidence=min_confidence
    ).patterns


def _pattern_id(pattern: Pattern) -> str:
    """Deterministic id per ``(type, title)`` so repeated runs are idempotent."""
    base = f"pattern-{pattern.type}-{pattern.title}"
    return hashlib.sha256(base.encode()).hexdigest()[:24]


def _pattern_tags(pattern: Pattern) -> tuple[str, ...]:
    """Serialize a pattern's machine-readable fields into memory tags."""
    return (
        "synthesized",
        pattern.type,
        f"confidence={pattern.confidence:.2f}",
        f"sessions={pattern.sessions_analyzed}",
        f"sample={pattern.sample_size}",
    )


def _persist_patterns(
    cerebrofy_dir: Path, patterns: list[Pattern]
) -> tuple[int, int]:
    """Upsert patterns into memories.db. Returns ``(written, updated)``."""
    conn = open_memories_db(cerebrofy_dir)
    written = 0
    updated = 0
    try:
        for pattern in patterns:
            pattern_id = _pattern_id(pattern)
            tags = _pattern_tags(pattern)
            existing = get_memory(conn, pattern_id)
            if existing is None:
                memory = MemoryRecord(
                    id=pattern_id,
                    neuron_id=None,
                    lobe=pattern.lobe,
                    type="pattern",
                    title=pattern.title,
                    body=pattern.body,
                    author="cerebrofy-synthesizer",
                    created_ts=pattern.created_ts,
                    tags=tags,
                    decay_score=1.0,
                    status="active",
                )
                write_memory(
                    conn=conn,
                    memory=memory,
                    embedding=embed_memory(pattern.title, pattern.body),
                )
                written += 1
                continue

            # M1: keep the original created_ts for stable patterns. Rewrite
            # only when the measured body/lobe/tags actually changed.
            if (
                existing.body == pattern.body
                and existing.lobe == pattern.lobe
                and existing.tags == tags
            ):
                continue

            conn.execute(
                "UPDATE memories SET body = ?, lobe = ?, tags = ?, "
                "decay_score = 1.0, status = 'active' WHERE id = ?",
                (pattern.body, pattern.lobe, ",".join(tags), pattern_id),
            )
            row = conn.execute(
                "SELECT rowid FROM memories WHERE id = ?", (pattern_id,)
            ).fetchone()
            if row is not None:
                conn.execute(
                    "DELETE FROM vec_memories WHERE rowid = ?", (int(row[0]),)
                )
                conn.execute(
                    "INSERT INTO vec_memories(rowid, embedding) VALUES (?, vec_f32(?))",
                    (
                        int(row[0]),
                        json.dumps(embed_memory(pattern.title, pattern.body)),
                    ),
                )
            updated += 1
        conn.commit()
    finally:
        conn.close()
    return written, updated


def _load_sessions(conn: Connection) -> list[Session]:
    """Load all closed sessions with their tool sequences."""
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
            (row[0],),
        ).fetchall()
        tool_sequence = [r[0] for r in tool_rows]

        neurons = _parse_neurons_touched(row[7])

        sessions.append(
            Session(
                id=row[0],
                started_at=row[1],
                ended_at=row[2],
                agent=row[3],
                task=row[4],
                outcome=row[5],
                outcome_notes=row[6],
                neurons_touched=neurons,
                blast_radius_before=row[8] or 0,
                blast_radius_after=row[9] or 0,
                tool_sequence=tool_sequence,
            )
        )
    return sessions


def _parse_neurons_touched(raw: object) -> list[str]:
    """Parse JSON-array text, falling back to an empty list when corrupt (B3)."""
    if not raw:
        return []
    try:
        loaded = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError, ValueError):
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded]


def _lobe_of(neuron: str) -> str | None:
    """Extract the lobe (first path segment) from a neuron id."""
    if "/" not in neuron:
        return None
    lobe = neuron.split("/", 1)[0].strip()
    return lobe or None


def _has_sequence(tools: list[str], sequence: tuple[str, ...]) -> bool:
    """Return True when *sequence* occurs contiguously in *tools*."""
    size = len(sequence)
    if size == 0 or size > len(tools):
        return False
    return any(
        tuple(tools[index : index + size]) == sequence
        for index in range(len(tools) - size + 1)
    )


def _generate_tool_sequence_candidates(
    sessions: list[Session],
) -> list[tuple[str, ...]]:
    """Generate sorted tool-sequence candidates of length 2-4 (m2)."""
    candidates: set[tuple[str, ...]] = set()
    for session in sessions:
        tools = session.tool_sequence
        for start in range(len(tools)):
            for length in range(2, min(5, len(tools) - start + 1)):
                candidates.add(tuple(tools[start : start + length]))
    # Sorting makes analysis order deterministic; the cap bounds pathological
    # sessions without changing the common case.
    return sorted(candidates)[:_MAX_SEQUENCE_CANDIDATES]


def detect_failure_correlations(
    sessions: list[Session],
    min_confidence: float,
    flagged: set[str] | None = None,
) -> list[Pattern]:
    """Detect tool sequences that correlate with failures."""
    patterns: list[Pattern] = []

    for candidate in _generate_tool_sequence_candidates(sessions):
        candidate_text = " → ".join(candidate)
        with_pattern = [s for s in sessions if _has_sequence(s.tool_sequence, candidate)]
        without_pattern = [
            s for s in sessions if not _has_sequence(s.tool_sequence, candidate)
        ]

        if len(with_pattern) < _MIN_SAMPLE:
            continue

        failure_rate_with = sum(
            1 for s in with_pattern if s.outcome == "failed"
        ) / len(with_pattern)
        failure_rate_without = sum(
            1 for s in without_pattern if s.outcome == "failed"
        ) / max(len(without_pattern), 1)

        # M2: perfect predictors (0% failure without the sequence) are the
        # strongest signal — use the spec floor instead of dropping them.
        lift = failure_rate_with / max(failure_rate_without, 0.01)
        if lift <= _FAILURE_LIFT:
            continue

        confidence = min(lift / 3, 1.0)
        if confidence < min_confidence:
            continue

        lobes = sorted(
            {
                lobe
                for session in with_pattern
                for neuron in session.neurons_touched
                if (lobe := _lobe_of(neuron)) is not None
            }
        )
        single_lobe = lobes[0] if len(lobes) == 1 else None

        patterns.append(
            Pattern(
                type="failure_correlation",
                title=(
                    f"Tool sequence '{candidate_text}' correlates with "
                    f"{lift:.1f}× failure rate"
                ),
                body=(
                    f"Analyzed {len(sessions)} sessions. Sessions with "
                    f"'{candidate_text}' had {failure_rate_with * 100:.0f}% failure "
                    f"rate vs {failure_rate_without * 100:.0f}% without. "
                    f"Confidence: {confidence:.2f}. Sample: {len(with_pattern)} with "
                    f"pattern, {len(without_pattern)} without."
                ),
                confidence=confidence,
                sessions_analyzed=len(sessions),
                sample_size=len(with_pattern),
                affected_lobes=lobes,
                created_ts=0,
                lobe=single_lobe,
            )
        )
        if flagged is not None:
            flagged.add(candidate_text)

    return patterns


def detect_lobe_fragility(
    sessions: list[Session], min_confidence: float
) -> list[Pattern]:
    """Detect lobes with high failure rates."""
    patterns: list[Pattern] = []

    # m1: a session touching several neurons in one lobe counts once.
    lobe_sessions: dict[str, dict[str, Session]] = {}
    for session in sessions:
        lobes = {
            lobe
            for neuron in session.neurons_touched
            if (lobe := _lobe_of(neuron)) is not None
        }
        for lobe in lobes:
            lobe_sessions.setdefault(lobe, {})[session.id] = session

    for lobe, unique_sessions in sorted(lobe_sessions.items()):
        lobe_sess = list(unique_sessions.values())
        if len(lobe_sess) < _MIN_SAMPLE:
            continue

        failed = sum(1 for s in lobe_sess if s.outcome == "failed")
        failure_rate = failed / len(lobe_sess)

        if failure_rate > 0.7 and failure_rate >= min_confidence:
            patterns.append(
                Pattern(
                    type="lobe_fragility",
                    title=(
                        f"Sessions touching {lobe}/ fail in "
                        f"{failure_rate * 100:.0f}% of cases"
                    ),
                    body=(
                        f"Analyzed {len(lobe_sess)} sessions involving {lobe}/. "
                        f"{failed} failed ({failure_rate * 100:.0f}% failure rate)."
                    ),
                    confidence=failure_rate,
                    sessions_analyzed=len(sessions),
                    sample_size=len(lobe_sess),
                    affected_lobes=[lobe],
                    created_ts=0,
                    lobe=lobe,
                )
            )

    return patterns


def detect_effort_calibration(
    sessions: list[Session], min_confidence: float
) -> list[Pattern]:
    """Detect systematic effort estimation errors from measured ratios."""
    patterns: list[Pattern] = []

    upgrade_sessions = [
        s
        for s in sessions
        if "upgrade" in s.task.lower() or "cerebrofy_upgrade" in s.tool_sequence
    ]

    ratios: list[float] = []
    for session in upgrade_sessions:
        predicted = session.blast_radius_before
        actual = session.blast_radius_after
        if predicted > 0:
            ratios.append(actual / predicted)

    # m6: the spec requires a >=5 sample before this pattern may fire.
    if len(ratios) < _MIN_SAMPLE:
        return patterns

    ratio = sum(ratios) / len(ratios)
    over_two = sum(1 for value in ratios if value > 2.0)
    confidence = over_two / len(ratios)

    if confidence < max(min_confidence, _EFFORT_CONFIDENCE):
        return patterns

    patterns.append(
        Pattern(
            type="effort_calibration",
            title=f"Upgrade sessions average {ratio:.1f}× the predicted blast radius",
            body=(
                f"Measured across {len(ratios)} upgrade sessions with a recorded "
                f"blast-radius prediction: mean actual/predicted ratio "
                f"{ratio:.2f}×; {over_two} of {len(ratios)} sessions "
                f"({confidence * 100:.0f}%) exceeded 2×. Confidence: "
                f"{confidence:.2f}."
            ),
            confidence=confidence,
            sessions_analyzed=len(sessions),
            sample_size=len(ratios),
            affected_lobes=[],
            created_ts=0,
        )
    )

    return patterns


def detect_missing_step(
    sessions: list[Session],
    min_confidence: float,
    excluded: set[str] | None = None,
) -> list[Pattern]:
    """Detect tool sequences that correlate with success (M8: no duplicates)."""
    patterns: list[Pattern] = []
    excluded = excluded or set()

    for candidate in _generate_tool_sequence_candidates(sessions):
        candidate_text = " → ".join(candidate)
        # M8: a sequence already reported as a failure correlation must not be
        # reported as a success pattern for the same underlying data.
        if candidate_text in excluded:
            continue

        with_pattern = [s for s in sessions if _has_sequence(s.tool_sequence, candidate)]
        without_pattern = [
            s for s in sessions if not _has_sequence(s.tool_sequence, candidate)
        ]

        if len(with_pattern) < _MIN_SAMPLE or len(without_pattern) < _MIN_SAMPLE:
            continue

        success_rate_with = sum(
            1 for s in with_pattern if s.outcome == "success"
        ) / len(with_pattern)
        success_rate_without = sum(
            1 for s in without_pattern if s.outcome == "success"
        ) / len(without_pattern)

        lift = success_rate_with / max(success_rate_without, 0.01)
        if lift <= _MISSING_STEP_LIFT:
            continue

        confidence = min(lift / 3, 1.0)
        if confidence < min_confidence:
            continue

        patterns.append(
            Pattern(
                type="missing_step",
                title=f"Sessions with '{candidate_text}' succeed {lift:.1f}× more often",
                body=(
                    f"Analyzed {len(sessions)} sessions. Sessions with "
                    f"'{candidate_text}' had {success_rate_with * 100:.0f}% success "
                    f"rate vs {success_rate_without * 100:.0f}% without. "
                    f"Confidence: {confidence:.2f}. Sample: {len(with_pattern)} with "
                    f"pattern, {len(without_pattern)} without."
                ),
                confidence=confidence,
                sessions_analyzed=len(sessions),
                sample_size=len(with_pattern),
                affected_lobes=[],
                created_ts=0,
            )
        )

    return patterns


def detect_agent_blind_spot(
    sessions: list[Session], min_confidence: float
) -> list[Pattern]:
    """Detect modules agents consistently miss when changing a related module.

    For every module pair ``(A, B)`` co-occurring in at least five successful
    sessions, measure the failure rate of sessions that touch ``A`` but not
    ``B``. A rate >= 85% over >= 5 such sessions means ``B`` is a blind spot.
    """
    patterns: list[Pattern] = []

    def modules_of(session: Session) -> set[str]:
        return {
            module
            for neuron in session.neurons_touched
            if (module := _lobe_of(neuron)) is not None
        }

    pair_counts: dict[tuple[str, str], int] = {}
    for session in sessions:
        if session.outcome != "success":
            continue
        modules = sorted(modules_of(session))
        for index, first in enumerate(modules):
            for second in modules[index + 1 :]:
                pair_counts[(first, second)] = pair_counts.get((first, second), 0) + 1

    for (first, second), count in sorted(pair_counts.items()):
        if count < _MIN_SAMPLE:
            continue
        for trigger, missed in ((first, second), (second, first)):
            sample = [
                session
                for session in sessions
                if trigger in modules_of(session) and missed not in modules_of(session)
            ]
            if len(sample) < _MIN_SAMPLE:
                continue
            failure_rate = sum(
                1 for session in sample if session.outcome == "failed"
            ) / len(sample)
            if failure_rate < _BLIND_SPOT_FAILURE_RATE or failure_rate < min_confidence:
                continue

            patterns.append(
                Pattern(
                    type="agent_blind_spot",
                    title=(
                        f"Agents miss {missed}/ when changing {trigger}/ — "
                        f"{failure_rate * 100:.0f}% of such sessions fail"
                    ),
                    body=(
                        f"Across {len(sessions)} sessions, {missed}/ and {trigger}/ "
                        f"co-occurred in {count} successful sessions. Sessions "
                        f"touching {trigger}/ but not {missed}/ failed "
                        f"{failure_rate * 100:.0f}% of the time ({len(sample)} "
                        f"samples). Confidence: {failure_rate:.2f}."
                    ),
                    confidence=failure_rate,
                    sessions_analyzed=len(sessions),
                    sample_size=len(sample),
                    affected_lobes=[trigger, missed],
                    created_ts=0,
                    lobe=trigger,
                )
            )

    return patterns


# ---------------------------------------------------------------------------
# Automatic trigger + read helpers
# ---------------------------------------------------------------------------


def closed_session_count(cerebrofy_dir: Path) -> int:
    """Return the number of closed sessions (0 when the DB/table is absent)."""
    sessions_db = cerebrofy_dir / "db" / "sessions.db"
    if not sessions_db.exists():
        return 0
    try:
        conn = sqlite3.connect(sessions_db)
    except sqlite3.Error:
        return 0
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE ended_at IS NOT NULL"
        ).fetchone()
    except sqlite3.Error:
        return 0
    finally:
        conn.close()
    return int(row[0]) if row else 0


def sessions_until_next_synthesis(cerebrofy_dir: Path, every_n: int = 10) -> int:
    """Return how many more closed sessions until the next automatic run."""
    if every_n <= 0:
        return 0
    count = closed_session_count(cerebrofy_dir)
    return every_n - (count % every_n)


def synthesis_interval(cerebrofy_dir: Path) -> int:
    """Read ``synthesis.every_n_sessions`` from config, defaulting to 10."""
    try:
        from cerebrofy.config.loader import load_config

        config_path = cerebrofy_dir / "config.yaml"
        if config_path.exists():
            return load_config(config_path).synthesis.every_n_sessions
    except Exception:
        _logger.warning("could not read synthesis config; using default 10")
    return 10


def maybe_run_synthesis(
    cerebrofy_dir: Path,
    every_n: int = 10,
    min_sessions: int = 10,
    min_confidence: float = 0.7,
) -> list[Pattern]:
    """Run synthesis only on a closed-session boundary (M4).

    Repeated calls at the same count are safe: deterministic ids plus the
    writer's upsert make synthesis idempotent.
    """
    if every_n <= 0:
        return []
    count = closed_session_count(cerebrofy_dir)
    if count <= 0 or count % every_n != 0:
        return []
    return run_synthesis(
        cerebrofy_dir,
        min_sessions=min_sessions,
        min_confidence=min_confidence,
    )


def _pattern_type(tags: tuple[str, ...]) -> str:
    """Return the detector type from a serialized pattern tag list."""
    for tag in tags:
        if tag == "synthesized" or "=" in tag:
            continue
        return tag
    return "pattern"


def _tag_value(tags: tuple[str, ...], key: str) -> str | None:
    prefix = f"{key}="
    for tag in tags:
        if tag.startswith(prefix):
            return tag[len(prefix) :]
    return None


def parse_pattern_confidence(tags: tuple[str, ...]) -> float:
    """Parse persisted confidence, defaulting to 1.0 when absent (M7)."""
    raw = _tag_value(tags, "confidence")
    if raw is None:
        return 1.0
    try:
        return float(raw)
    except ValueError:
        return 1.0


def _tag_int(tags: tuple[str, ...], key: str) -> int:
    raw = _tag_value(tags, key)
    if raw is None:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


def list_synthesized_patterns(
    conn: Connection,
    lobe: str | None = None,
    limit: int = 50,
) -> list[StoredPattern]:
    """Read synthesized patterns from memories.db, newest first.

    When *lobe* is given only patterns attached to that lobe are returned;
    ``None`` returns every synthesized pattern.
    """
    query = (
        "SELECT id, lobe, title, body, created_ts, tags FROM memories "
        "WHERE type = 'pattern' AND tags LIKE '%synthesized%'"
    )
    params: list[object] = []
    if lobe is not None:
        query += " AND lobe = ?"
        params.append(lobe)
    query += " ORDER BY created_ts DESC LIMIT ?"
    params.append(max(1, limit))

    patterns: list[StoredPattern] = []
    for row in conn.execute(query, params).fetchall():
        tags = tuple(
            tag.strip() for tag in (row[5] or "").split(",") if tag.strip()
        )
        patterns.append(
            StoredPattern(
                id=str(row[0]),
                type=_pattern_type(tags),
                title=str(row[2]),
                body=str(row[3]),
                confidence=parse_pattern_confidence(tags),
                lobe=row[1],
                sessions_analyzed=_tag_int(tags, "sessions"),
                sample_size=_tag_int(tags, "sample"),
                created_ts=int(row[4]),
            )
        )
    return patterns
