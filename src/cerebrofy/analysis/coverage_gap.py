"""Test Coverage Gap Predictor: rank uncovered neurons by blast_radius × velocity."""

from __future__ import annotations

import sqlite3
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GapNeuron:
    """Risk profile for a single uncovered neuron."""

    id: str
    name: str
    file: str
    line_start: int
    line_end: int
    lobe: str
    caller_count: int       # total d1 + d2 callers
    velocity: int           # git commits touching file in last N days
    gap_score: float        # risk_score(blast) × velocity
    risk_label: str         # LOW / MEDIUM / HIGH / CRITICAL
    risk_icon: str
    coverage_source: str    # "coverage_xml" | "graph_topology"


@dataclass
class GapReport:
    """Full coverage gap report."""

    neurons: list[GapNeuron] = field(default_factory=list)
    total_neurons_scanned: int = 0
    uncovered_count: int = 0
    coverage_source: str = "graph_topology"
    as_of_commit: str | None = None
    velocity_days: int = 30


# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------

def _gap_risk_label(score: float) -> str:
    if score >= 100.0:
        return "CRITICAL"
    if score >= 25.0:
        return "HIGH"
    if score >= 5.0:
        return "MEDIUM"
    return "LOW"


def _gap_risk_icon(label: str) -> str:
    return {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(label, "⚪")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _get_current_commit(repo_root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=str(repo_root), capture_output=True, text=True, check=False,
    )
    return result.stdout.strip() or None if result.returncode == 0 else None


def _to_posix(file_path: str) -> str:
    return file_path.replace("\\", "/")


def _file_velocity(file_path: str, repo_root: Path, days: int) -> int:
    """Count git commits touching file_path in the last N days."""
    result = subprocess.run(
        ["git", "log", "--format=%H", f"--since={days} days ago", "--", _to_posix(file_path)],
        cwd=str(repo_root), capture_output=True, text=True, check=False, timeout=30,
    )
    if result.returncode != 0:
        return 0
    return sum(1 for line in result.stdout.splitlines() if line.strip())


# ---------------------------------------------------------------------------
# Coverage detection
# ---------------------------------------------------------------------------

def _parse_coverage_xml(xml_path: Path, conn: sqlite3.Connection) -> set[str]:
    """Parse coverage.xml and return neuron IDs with at least one covered line."""
    try:
        tree = ET.parse(str(xml_path))
    except ET.ParseError:
        return set()

    # Build {normalized_file: set[covered_line_numbers]}
    file_covered_lines: dict[str, set[int]] = {}
    for cls in tree.iter("class"):
        filename = cls.get("filename", "")
        if not filename:
            continue
        norm = filename.replace("\\", "/")
        covered: set[int] = set()
        for line in cls.iter("line"):
            try:
                if int(line.get("hits", "0")) > 0:
                    covered.add(int(line.get("number", "0")))
            except ValueError:
                pass
        if covered:
            file_covered_lines[norm] = file_covered_lines.get(norm, set()) | covered

    if not file_covered_lines:
        return set()

    covered_ids: set[str] = set()
    rows = conn.execute(
        "SELECT id, file, line_start, line_end FROM nodes WHERE type != 'module'"
    ).fetchall()
    for neuron_id, file_path, line_start, line_end in rows:
        if not file_path or not line_start:
            continue
        norm_file = file_path.replace("\\", "/")
        covered_lines = file_covered_lines.get(norm_file, set())
        if not covered_lines:
            continue
        end = line_end or line_start
        if covered_lines & set(range(line_start, end + 1)):
            covered_ids.add(neuron_id)

    return covered_ids


def _topology_covered_neurons(conn: sqlite3.Connection) -> set[str]:
    """Return neuron IDs that have at least one test-file caller (single SQL query)."""
    rows = conn.execute("""
        SELECT DISTINCT e.dst_id
        FROM edges e
        JOIN nodes src ON src.id = e.src_id
        WHERE src.file LIKE 'tests/%'
    """).fetchall()
    return {row[0] for row in rows}


def _detect_covered_neurons(
    repo_root: Path,
    conn: sqlite3.Connection,
) -> tuple[set[str], str]:
    """Return (covered_neuron_ids, coverage_source).

    Prefers coverage.xml when present and non-empty; falls back to graph-topology.
    """
    xml_path = repo_root / "coverage.xml"
    if xml_path.exists():
        covered = _parse_coverage_xml(xml_path, conn)
        if covered:
            return covered, "coverage_xml"
    return _topology_covered_neurons(conn), "graph_topology"


# ---------------------------------------------------------------------------
# Memory writes
# ---------------------------------------------------------------------------

def _write_gap_memories(
    neurons: list[GapNeuron], cerebrofy_dir: Path, velocity_days: int = 30
) -> None:
    """Write warning memories to HIGH/CRITICAL gap neurons (non-fatal)."""
    import time
    import uuid
    try:
        from cerebrofy.memory.embedder import embed_memory
        from cerebrofy.memory.store import Memory, open_memories_db, write_memory

        mconn = open_memories_db(cerebrofy_dir)
        try:
            for n in neurons:
                if n.risk_label not in ("HIGH", "CRITICAL"):
                    continue
                title = f"Coverage gap: {n.name}"
                body = (
                    f"{n.risk_icon} {n.risk_label} coverage gap — "
                    f"{n.caller_count} callers, velocity={n.velocity} commits/{velocity_days} days, "
                    f"gap_score={n.gap_score:.1f}. "
                    "No tests reach this function. High change rate + wide blast radius = "
                    "elevated production risk if a bug is introduced here."
                )
                mem = Memory(
                    id=str(uuid.uuid4()),
                    neuron_id=n.id,
                    lobe=n.lobe,
                    type="warning",
                    title=title,
                    body=body,
                    author="agent:coverage-gap-predictor",
                    created_ts=int(time.time()),
                    tags=("coverage-gap", "untested", n.lobe),
                    decay_score=1.0,
                    status="active",
                )
                embedding = embed_memory(title, body)
                write_memory(mconn, mem, embedding)
            mconn.commit()
        finally:
            mconn.close()
    except Exception:
        pass  # Non-fatal — memory writes never block the report


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_coverage_gap_report(
    conn: sqlite3.Connection,
    repo_root: Path,
    days: int = 30,
    depth: int = 2,
    min_blast: float = 0.0,
    top: int = 20,
    lobe_filter: str | None = None,
    risk_filter: str | None = None,
    write_memories: bool = False,
    cerebrofy_dir: Path | None = None,
) -> GapReport:
    """Rank uncovered neurons by blast_radius × velocity.

    Algorithm:
      1. Fetch all non-test, non-module neurons from the index.
      2. Detect covered neurons via coverage.xml (preferred) or graph-topology fallback.
      3. Filter to uncovered neurons only.
      4. For each uncovered neuron: BFS callers → risk_score; git log → velocity.
      5. gap_score = risk_score × velocity.
      6. Filter, sort by gap_score desc, return top N.
    """
    from cerebrofy.analysis.blast_radius import _lobe_from_file, bfs_callers
    from cerebrofy.analysis.risk_scorer import compute_risk_score

    rows = conn.execute(
        "SELECT id, name, file, line_start, line_end FROM nodes "
        "WHERE type != 'module' AND file NOT LIKE 'tests/%'"
    ).fetchall()

    covered_ids, coverage_source = _detect_covered_neurons(repo_root, conn)

    uncovered_rows = [row for row in rows if row[0] not in covered_ids]
    uncovered_count = len(uncovered_rows)

    all_lobes = {_lobe_from_file(row[2]) for row in rows if row[2]}
    total_lobes = max(len(all_lobes), 1)

    velocity_cache: dict[str, int] = {}
    results: list[GapNeuron] = []

    for neuron_id, name, file_path, line_start, line_end in uncovered_rows:
        if not file_path or not line_start:
            continue

        lobe = _lobe_from_file(file_path)
        if lobe_filter and lobe_filter.lower() not in lobe.lower():
            continue

        d1, d2, _ = bfs_callers(neuron_id, conn, max_depth=depth)
        caller_count = len(d1) + len(d2)

        blast_weighted = len(d1) + 0.4 * len(d2)
        if blast_weighted < min_blast:
            continue

        lobes_calling = len({lobe} | {n.lobe for n in d1} | {n.lobe for n in d2})
        risk_score = compute_risk_score(
            direct_callers=len(d1),
            indirect_callers=len(d2),
            total_lobes=total_lobes,
            lobes_calling=lobes_calling,
            test_coverage_ratio=0.0,
        )

        if file_path not in velocity_cache:
            velocity_cache[file_path] = _file_velocity(file_path, repo_root, days)
        velocity = velocity_cache[file_path]

        gap_score = round(risk_score * velocity, 2)
        label = _gap_risk_label(gap_score)

        if risk_filter and risk_filter.upper() != label:
            continue

        results.append(GapNeuron(
            id=neuron_id,
            name=name,
            file=file_path,
            line_start=line_start,
            line_end=line_end or line_start,
            lobe=lobe,
            caller_count=caller_count,
            velocity=velocity,
            gap_score=gap_score,
            risk_label=label,
            risk_icon=_gap_risk_icon(label),
            coverage_source=coverage_source,
        ))

    results.sort(key=lambda n: n.gap_score, reverse=True)
    top_results = results[:top]

    if write_memories and cerebrofy_dir is not None:
        _write_gap_memories(top_results, cerebrofy_dir, days)

    return GapReport(
        neurons=top_results,
        total_neurons_scanned=len(rows),
        uncovered_count=uncovered_count,
        coverage_source=coverage_source,
        as_of_commit=_get_current_commit(repo_root),
        velocity_days=days,
    )
