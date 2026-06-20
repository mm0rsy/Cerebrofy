"""Refactoring sequence generator via reverse topological sort of the caller graph."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cerebrofy.analysis.impact import ImpactNeuron
from cerebrofy.graph.edges import RUNTIME_BOUNDARY


@dataclass(frozen=True)
class SequenceStep:
    """One step in the recommended refactoring sequence."""

    step: int
    description: str
    neuron_ids: list[str]
    is_runtime_boundary: bool = False


def _build_caller_graph(
    neuron_ids: set[str],
    conn: sqlite3.Connection,
) -> dict[str, set[str]]:
    """Build adjacency map (caller → set of callees) restricted to neuron_ids."""
    graph: dict[str, set[str]] = {nid: set() for nid in neuron_ids}
    for nid in neuron_ids:
        rows = conn.execute(
            "SELECT dst_id, rel_type FROM edges WHERE src_id = ? AND rel_type != ?",
            (nid, RUNTIME_BOUNDARY),
        ).fetchall()
        for dst_id, _ in rows:
            if dst_id in neuron_ids:
                graph[nid].add(dst_id)
    return graph


def _topological_sort(graph: dict[str, set[str]]) -> list[str]:
    """Kahn's algorithm — returns nodes in topological order (callers before callees)."""
    in_degree: dict[str, int] = {nid: 0 for nid in graph}
    for deps in graph.values():
        for dep in deps:
            in_degree[dep] = in_degree.get(dep, 0) + 1

    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    order: list[str] = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for dep in sorted(graph.get(node, [])):
            in_degree[dep] -= 1
            if in_degree[dep] == 0:
                queue.append(dep)

    # Append any remaining nodes (handles cycles gracefully)
    remaining = [nid for nid in graph if nid not in order]
    order.extend(remaining)
    return order


def _group_by_file(neurons: list[ImpactNeuron]) -> dict[str, list[ImpactNeuron]]:
    groups: dict[str, list[ImpactNeuron]] = {}
    for n in neurons:
        groups.setdefault(n.file, []).append(n)
    return groups


def build_sequence(
    target: ImpactNeuron,
    callers_by_depth: dict[int, list[ImpactNeuron]],
    runtime_boundary_callers: list[str],
    conn: sqlite3.Connection,
) -> list[SequenceStep]:
    """Generate a refactoring sequence from deepest leaf callers up to the target.

    Strategy:
    1. Reverse-topological sort: leaves first, target last.
    2. Group neurons in the same file into one step.
    3. Tests are not in callers_by_depth — they are added as a verification step.
    4. RUNTIME_BOUNDARY callers get a dedicated warning step.
    """
    all_callers: list[ImpactNeuron] = [n for ns in callers_by_depth.values() for n in ns]
    all_ids: set[str] = {n.id for n in all_callers} | {target.id}

    caller_graph = _build_caller_graph(all_ids, conn)
    topo_order = _topological_sort(caller_graph)

    # Reverse so deepest leaves (no callers of their own) come first
    topo_order.reverse()

    id_to_neuron: dict[str, ImpactNeuron] = {n.id: n for n in all_callers}
    id_to_neuron[target.id] = target

    steps: list[SequenceStep] = []
    step_num = 1

    # Group by file following topo order
    seen_files: set[str] = set()
    file_order: list[str] = []
    for nid in topo_order:
        neuron = id_to_neuron.get(nid)
        if neuron and neuron.file not in seen_files and neuron.id != target.id:
            seen_files.add(neuron.file)
            file_order.append(neuron.file)

    for file in file_order:
        file_neurons = [n for n in all_callers if n.file == file]
        if not file_neurons:
            continue
        names = ", ".join(n.name for n in file_neurons)
        short_file = Path(file).name
        steps.append(SequenceStep(
            step=step_num,
            description=f"Update {short_file} — {names}",
            neuron_ids=[n.id for n in file_neurons],
        ))
        step_num += 1

    # Target itself
    steps.append(SequenceStep(
        step=step_num,
        description=f"Update target: {target.file} — {target.name}",
        neuron_ids=[target.id],
    ))
    step_num += 1

    # RUNTIME_BOUNDARY warning step (if any)
    if runtime_boundary_callers:
        steps.append(SequenceStep(
            step=step_num,
            description=(
                f"⚠️  {len(runtime_boundary_callers)} RUNTIME_BOUNDARY caller(s) detected — "
                "these cross process/framework boundaries and require manual verification"
            ),
            neuron_ids=runtime_boundary_callers,
            is_runtime_boundary=True,
        ))
        step_num += 1

    return steps
