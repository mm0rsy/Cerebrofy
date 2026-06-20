"""Core impact computation: BFS caller traversal, test mapping, LoC estimate."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from cerebrofy.graph.edges import RUNTIME_BOUNDARY


@dataclass(frozen=True)
class ImpactNeuron:
    """Lightweight neuron reference used in impact results."""

    id: str
    name: str
    file: str
    line_start: int
    line_end: int
    lobe: str  # derived from file path (first directory component)


@dataclass
class ImpactResult:
    """Full result of an impact prediction for one target neuron."""

    target: ImpactNeuron
    callers_by_depth: dict[int, list[ImpactNeuron]] = field(default_factory=dict)
    covering_tests: list[ImpactNeuron] = field(default_factory=list)
    uncovered_callers: list[str] = field(default_factory=list)
    runtime_boundary_callers: list[str] = field(default_factory=list)
    lobe_spread: int = 0
    estimated_loc: int = 0
    complexity_rating: str = "LOW"


def _lobe_from_file(file: str) -> str:
    parts = Path(file).parts
    return parts[0] if parts else "root"


def _row_to_neuron(row: tuple[str, str, str, int, int]) -> ImpactNeuron:
    node_id, name, file, line_start, line_end = row
    return ImpactNeuron(
        id=node_id,
        name=name,
        file=file,
        line_start=line_start,
        line_end=line_end,
        lobe=_lobe_from_file(file),
    )


def resolve_target(target: str, conn: sqlite3.Connection) -> ImpactNeuron | None:
    """Resolve a target string to a neuron.

    Accepts:
    - file::name  (e.g. auth/tokens.py::validate_token)
    - file:line   (e.g. auth/tokens.py:42)
    - plain name  (e.g. validate_token)
    """
    # file::name
    if "::" in target:
        file_part, name_part = target.split("::", 1)
        row = conn.execute(
            "SELECT id, name, file, line_start, line_end FROM nodes WHERE file = ? AND name = ? LIMIT 1",
            (file_part, name_part),
        ).fetchone()
        if row:
            return _row_to_neuron(row)

    # file:line
    if ":" in target and not target.startswith("external::"):
        parts = target.rsplit(":", 1)
        if len(parts) == 2 and parts[1].isdigit():
            file_part, line_str = parts
            line = int(line_str)
            row = conn.execute(
                "SELECT id, name, file, line_start, line_end FROM nodes "
                "WHERE file = ? AND line_start <= ? AND line_end >= ? "
                "AND type != 'module' LIMIT 1",
                (file_part, line, line),
            ).fetchone()
            if row:
                return _row_to_neuron(row)

    # plain name — return first non-module match
    row = conn.execute(
        "SELECT id, name, file, line_start, line_end FROM nodes "
        "WHERE name = ? AND type != 'module' LIMIT 1",
        (target,),
    ).fetchone()
    if row:
        return _row_to_neuron(row)

    return None


def bfs_callers(
    target_id: str,
    conn: sqlite3.Connection,
    max_depth: int = 2,
) -> dict[int, list[ImpactNeuron]]:
    """BFS upstream from target_id collecting callers up to max_depth.

    Returns a dict mapping depth (1, 2, …) to the list of caller neurons at that depth.
    RUNTIME_BOUNDARY edges are skipped per Law II — collected separately via
    runtime_boundary_callers in compute_impact().
    """
    visited: set[str] = {target_id}
    frontier: list[str] = [target_id]
    result: dict[int, list[ImpactNeuron]] = {}

    for depth in range(1, max_depth + 1):
        next_frontier: list[str] = []
        depth_neurons: list[ImpactNeuron] = []

        for node_id in frontier:
            rows = conn.execute(
                "SELECT src_id, rel_type FROM edges WHERE dst_id = ?",
                (node_id,),
            ).fetchall()
            for src_id, rel_type in rows:
                if src_id in visited:
                    continue
                if rel_type == RUNTIME_BOUNDARY:
                    continue
                visited.add(src_id)
                next_frontier.append(src_id)
                neuron_row = conn.execute(
                    "SELECT id, name, file, line_start, line_end FROM nodes WHERE id = ? LIMIT 1",
                    (src_id,),
                ).fetchone()
                if neuron_row:
                    depth_neurons.append(_row_to_neuron(neuron_row))

        if depth_neurons:
            result[depth] = depth_neurons
        frontier = next_frontier
        if not frontier:
            break

    return result


def find_runtime_boundary_callers(target_id: str, conn: sqlite3.Connection) -> list[str]:
    """Return src_ids that reach target_id via a RUNTIME_BOUNDARY edge."""
    rows = conn.execute(
        "SELECT src_id FROM edges WHERE dst_id = ? AND rel_type = ?",
        (target_id, RUNTIME_BOUNDARY),
    ).fetchall()
    return [r[0] for r in rows]


def find_covering_tests(
    all_caller_ids: set[str],
    target_id: str,
    conn: sqlite3.Connection,
) -> tuple[list[ImpactNeuron], list[str]]:
    """Return (covering_tests, uncovered_caller_ids).

    A test covers a caller if the caller is reachable from a test neuron.
    We check this by seeing if any test neuron is in the set of ancestors of each caller.
    Simplified: a caller is "covered" if any test neuron exists that calls it (directly or
    via a path). For efficiency we check if any test neuron is in callers_by_depth going
    in the other direction (callee BFS from test neurons is expensive), so instead we look
    for test neurons that appear as callers.
    """
    test_neurons: list[ImpactNeuron] = []
    covered_ids: set[str] = set()

    ids_to_check = all_caller_ids | {target_id}

    for node_id in ids_to_check:
        rows = conn.execute(
            "SELECT src_id FROM edges WHERE dst_id = ?",
            (node_id,),
        ).fetchall()
        for (src_id,) in rows:
            neuron_row = conn.execute(
                "SELECT id, name, file, line_start, line_end FROM nodes "
                "WHERE id = ? AND file LIKE 'tests/%' LIMIT 1",
                (src_id,),
            ).fetchone()
            if neuron_row:
                covered_ids.add(node_id)
                test_neuron = _row_to_neuron(neuron_row)
                if not any(t.id == test_neuron.id for t in test_neurons):
                    test_neurons.append(test_neuron)

    uncovered = [nid for nid in ids_to_check if nid not in covered_ids and not nid.startswith("external::")]
    return test_neurons, uncovered


def _compute_loc(neurons: list[ImpactNeuron]) -> int:
    return sum(max(0, n.line_end - n.line_start + 1) for n in neurons)


def _complexity_rating(lobe_spread: int, total_callers: int) -> str:
    if lobe_spread >= 3 or total_callers >= 10:
        return "HIGH"
    if lobe_spread >= 2 or total_callers >= 4:
        return "MEDIUM"
    return "LOW"


def compute_impact(
    target: ImpactNeuron,
    conn: sqlite3.Connection,
    depth: int = 2,
    show_tests: bool = True,
) -> ImpactResult:
    """Run full impact computation for target neuron."""
    callers_by_depth = bfs_callers(target.id, conn, max_depth=depth)
    runtime_boundary = find_runtime_boundary_callers(target.id, conn)

    all_callers: list[ImpactNeuron] = [n for ns in callers_by_depth.values() for n in ns]
    all_caller_ids = {n.id for n in all_callers}

    lobes = {target.lobe} | {n.lobe for n in all_callers}
    lobe_spread = len(lobes)

    estimated_loc = _compute_loc([target] + all_callers)
    complexity = _complexity_rating(lobe_spread, len(all_callers))

    covering_tests: list[ImpactNeuron] = []
    uncovered_callers: list[str] = []
    if show_tests:
        covering_tests, uncovered_callers = find_covering_tests(all_caller_ids, target.id, conn)

    return ImpactResult(
        target=target,
        callers_by_depth=callers_by_depth,
        covering_tests=covering_tests,
        uncovered_callers=uncovered_callers,
        runtime_boundary_callers=runtime_boundary,
        lobe_spread=lobe_spread,
        estimated_loc=estimated_loc,
        complexity_rating=complexity,
    )
