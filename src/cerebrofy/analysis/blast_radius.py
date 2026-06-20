"""Core BFS blast radius engine: changed neuron set → caller graph + risk scores."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from cerebrofy.graph.edges import RUNTIME_BOUNDARY
from cerebrofy.analysis.risk_scorer import compute_risk_score, risk_label, risk_icon


@dataclass(frozen=True)
class BlastNeuron:
    """Lightweight neuron reference used in blast radius results."""

    id: str
    name: str
    file: str
    line_start: int
    lobe: str


@dataclass
class NeuronBlastRadius:
    """Blast radius result for a single changed neuron."""

    neuron: BlastNeuron
    callers_depth1: list[BlastNeuron] = field(default_factory=list)
    callers_depth2: list[BlastNeuron] = field(default_factory=list)
    covering_tests: list[BlastNeuron] = field(default_factory=list)
    uncovered_callers: list[str] = field(default_factory=list)
    runtime_boundary_callers: list[str] = field(default_factory=list)
    lobe_spread: int = 1
    risk_score: float = 0.0
    risk_label: str = "LOW"
    risk_icon: str = "🟢"


@dataclass
class BlastRadiusReport:
    """Full blast radius report across all changed neurons in a diff."""

    changed_neurons: list[NeuronBlastRadius] = field(default_factory=list)

    @property
    def total_affected(self) -> int:
        seen: set[str] = set()
        for nbr in self.changed_neurons:
            seen.update(n.id for n in nbr.callers_depth1)
            seen.update(n.id for n in nbr.callers_depth2)
        return len(seen)

    @property
    def highest_risk_label(self) -> str:
        labels = [nbr.risk_label for nbr in self.changed_neurons]
        if "HIGH" in labels:
            return "HIGH"
        if "MEDIUM" in labels:
            return "MEDIUM"
        return "LOW"


def _lobe_from_file(file: str) -> str:
    parts = Path(file).parts
    return parts[0] if len(parts) > 1 else file


def _row_to_blast_neuron(row: tuple[str, str, str, int]) -> BlastNeuron:
    node_id, name, file, line_start = row
    return BlastNeuron(id=node_id, name=name, file=file, line_start=line_start, lobe=_lobe_from_file(file))


def neurons_for_changed_files(
    changed_files: list[str],
    conn: sqlite3.Connection,
) -> list[BlastNeuron]:
    """Return all non-module neurons whose file is in changed_files."""
    if not changed_files:
        return []
    placeholders = ",".join("?" * len(changed_files))
    rows = conn.execute(
        f"SELECT id, name, file, line_start FROM nodes "
        f"WHERE file IN ({placeholders}) AND type != 'module'",
        changed_files,
    ).fetchall()
    return [_row_to_blast_neuron(r) for r in rows]


def neuron_for_target(target: str, conn: sqlite3.Connection) -> BlastNeuron | None:
    """Resolve a single target string (file::name, file:line, or name) to a BlastNeuron."""
    if "::" in target:
        file_part, name_part = target.split("::", 1)
        row = conn.execute(
            "SELECT id, name, file, line_start FROM nodes WHERE file = ? AND name = ? LIMIT 1",
            (file_part, name_part),
        ).fetchone()
        if row:
            return _row_to_blast_neuron(row)

    if ":" in target:
        parts = target.rsplit(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            file_part, line_str = parts
            line = int(line_str)
            row = conn.execute(
                "SELECT id, name, file, line_start FROM nodes "
                "WHERE file = ? AND line_start <= ? AND line_end >= ? AND type != 'module' LIMIT 1",
                (file_part, line, line),
            ).fetchone()
            if row:
                return _row_to_blast_neuron(row)

    row = conn.execute(
        "SELECT id, name, file, line_start FROM nodes WHERE name = ? AND type != 'module' LIMIT 1",
        (target,),
    ).fetchone()
    return _row_to_blast_neuron(row) if row else None


def bfs_callers(
    neuron_id: str,
    conn: sqlite3.Connection,
    max_depth: int = 2,
) -> tuple[list[BlastNeuron], list[BlastNeuron], list[str]]:
    """BFS upstream from neuron_id.

    Returns (callers_depth1, callers_depth2, runtime_boundary_caller_ids).
    RUNTIME_BOUNDARY edges are excluded from traversal (Law II) and collected separately.
    """
    visited: set[str] = {neuron_id}
    runtime_boundaries: list[str] = []
    results: dict[int, list[BlastNeuron]] = {}
    frontier = [neuron_id]

    for depth in range(1, max_depth + 1):
        next_frontier: list[str] = []
        depth_neurons: list[BlastNeuron] = []
        for node_id in frontier:
            rows = conn.execute(
                "SELECT src_id, rel_type FROM edges WHERE dst_id = ?", (node_id,)
            ).fetchall()
            for src_id, rel_type in rows:
                if rel_type == RUNTIME_BOUNDARY:
                    if depth == 1 and src_id not in runtime_boundaries:
                        runtime_boundaries.append(src_id)
                    continue
                if src_id in visited:
                    continue
                visited.add(src_id)
                next_frontier.append(src_id)
                neuron_row = conn.execute(
                    "SELECT id, name, file, line_start FROM nodes WHERE id = ? LIMIT 1",
                    (src_id,),
                ).fetchone()
                if neuron_row:
                    depth_neurons.append(_row_to_blast_neuron(neuron_row))
        results[depth] = depth_neurons
        frontier = next_frontier
        if not frontier:
            break

    return results.get(1, []), results.get(2, []), runtime_boundaries


def find_covering_tests(
    neuron_id: str,
    caller_ids: set[str],
    conn: sqlite3.Connection,
) -> tuple[list[BlastNeuron], list[str]]:
    """Return (test_neurons_covering, uncovered_caller_ids).

    A caller is covered if any test neuron (file LIKE 'tests/%') has an edge to it.
    """
    all_ids = caller_ids | {neuron_id}
    test_neurons: list[BlastNeuron] = []
    covered: set[str] = set()

    for nid in all_ids:
        rows = conn.execute("SELECT src_id FROM edges WHERE dst_id = ?", (nid,)).fetchall()
        for (src_id,) in rows:
            row = conn.execute(
                "SELECT id, name, file, line_start FROM nodes "
                "WHERE id = ? AND file LIKE 'tests/%' LIMIT 1",
                (src_id,),
            ).fetchone()
            if row:
                covered.add(nid)
                test = _row_to_blast_neuron(row)
                if not any(t.id == test.id for t in test_neurons):
                    test_neurons.append(test)

    uncovered = [
        nid for nid in all_ids
        if nid not in covered and not nid.startswith("external::")
    ]
    return test_neurons, uncovered


def _count_total_lobes(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COUNT(DISTINCT substr(file, 1, instr(file||'/', '/') - 1)) FROM nodes WHERE type != 'module'"
    ).fetchone()
    return max(int(row[0]) if row else 1, 1)


def compute_neuron_blast_radius(
    neuron: BlastNeuron,
    conn: sqlite3.Connection,
    depth: int = 2,
) -> NeuronBlastRadius:
    """Full blast radius computation for one neuron."""
    d1, d2, runtime_boundaries = bfs_callers(neuron.id, conn, max_depth=depth)
    all_caller_ids = {n.id for n in d1} | {n.id for n in d2}

    lobes = {neuron.lobe} | {n.lobe for n in d1} | {n.lobe for n in d2}
    lobe_spread = len(lobes)
    total_lobes = _count_total_lobes(conn)

    tests, uncovered = find_covering_tests(neuron.id, all_caller_ids, conn)
    test_coverage_ratio = len(tests) / max(len(d1), 1)

    score = compute_risk_score(
        direct_callers=len(d1),
        indirect_callers=len(d2),
        total_lobes=total_lobes,
        lobes_calling=lobe_spread,
        test_coverage_ratio=test_coverage_ratio,
    )
    label = risk_label(score)

    return NeuronBlastRadius(
        neuron=neuron,
        callers_depth1=d1,
        callers_depth2=d2,
        covering_tests=tests,
        uncovered_callers=uncovered,
        runtime_boundary_callers=runtime_boundaries,
        lobe_spread=lobe_spread,
        risk_score=score,
        risk_label=label,
        risk_icon=risk_icon(label),
    )


def compute_blast_radius_report(
    neurons: list[BlastNeuron],
    conn: sqlite3.Connection,
    depth: int = 2,
) -> BlastRadiusReport:
    """Compute blast radius for a list of changed neurons."""
    report = BlastRadiusReport()
    for neuron in neurons:
        report.changed_neurons.append(compute_neuron_blast_radius(neuron, conn, depth=depth))
    return report


def format_pr_comment(report: BlastRadiusReport) -> str:
    """Format the blast radius report as a GitHub PR comment in Markdown."""
    lines: list[str] = [
        "## 🧠 Cerebrofy — Blast Radius Report",
        "",
        f"### Changed Neurons ({len(report.changed_neurons)})",
        "",
        "| Function | File | Callers (depth-2) | Tests Covering | Risk |",
        "|---|---|---|---|---|",
    ]

    for nbr in report.changed_neurons:
        total_callers = len(nbr.callers_depth1) + len(nbr.callers_depth2)
        lines.append(
            f"| `{nbr.neuron.name}` | {nbr.neuron.file}:{nbr.neuron.line_start} "
            f"| {total_callers} | {len(nbr.covering_tests)} "
            f"| {nbr.risk_icon} {nbr.risk_label} |"
        )

    lines.append("")

    for nbr in report.changed_neurons:
        if not nbr.callers_depth1 and not nbr.callers_depth2:
            continue
        lines.append("<details>")
        lines.append(f"<summary><code>{nbr.neuron.name}</code> — full caller tree</summary>")
        lines.append("")
        if nbr.callers_depth1:
            d1_names = ", ".join(n.name for n in nbr.callers_depth1)
            lines.append(f"**Depth 1:** {d1_names}")
        if nbr.callers_depth2:
            d2_names = ", ".join(f"`{n.name}`" for n in nbr.callers_depth2)
            lines.append(f"**Depth 2:** {d2_names}")
        if nbr.runtime_boundary_callers:
            lines.append(f"**⚠️ RUNTIME_BOUNDARY:** {', '.join(nbr.runtime_boundary_callers)}")
        lines.append("")
        lines.append("</details>")
        lines.append("")

    uncovered_all = [
        name
        for nbr in report.changed_neurons
        for name in nbr.uncovered_callers
        if not name.startswith("external::")
    ]
    if uncovered_all:
        lines.append(f"**Uncovered callers (no test reaches them):** {', '.join(uncovered_all[:10])}")
        if len(uncovered_all) > 10:
            lines.append(f"_…and {len(uncovered_all) - 10} more_")
        lines.append("")

    lines.append(
        f"> Total affected neurons: **{report.total_affected}** | "
        f"Highest risk: **{report.highest_risk_label}**"
    )

    return "\n".join(lines)
