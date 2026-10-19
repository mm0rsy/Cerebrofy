"""Dependency-safe migration step sequencing for refactor plans (Idea #12).

Reuses the reverse topological sort from the refactor-impact module
(``cerebrofy.analysis.sequence`` — Idea #07): callers-before-callees order,
reversed, so the deepest callees inside the cluster move first.

Step order (spec):
  1. Create the new module skeleton (empty target files).
  2. Move cluster neurons, file-group by file-group, callees before callers.
  3. Update external callers (safe: re-export stubs were added during the move).
  4. RUNTIME_BOUNDARY callers — manual verification warning (Law II).
  5. Remove backward-compat re-exports and verify with the test suite.

Every neuron appears in at most one step and the sequence is a linear list, so
ordering can never be circular (cycles degrade to a deterministic tail order).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from cerebrofy.analysis.sequence import _build_caller_graph, _topological_sort
from cerebrofy.planning.extractor import ClusterNeuron


@dataclass(frozen=True)
class MigrationStep:
    """One ordered step of the migration plan."""

    step_number: int
    description: str
    neurons_affected: list[str]
    callers_break: bool


def _reverse_topo_order(cluster_ids: set[str], conn: sqlite3.Connection) -> list[str]:
    """Reverse-topo order of the cluster (callees first), deterministic.

    ``analysis.sequence._build_caller_graph`` now inserts nodes/edges in
    stable sorted-id order and ``_topological_sort`` seeds its queue
    deterministically, so the reverse order is stable without any re-keying
    here.
    """
    graph = _build_caller_graph(cluster_ids, conn)
    order = _topological_sort(graph)
    order.reverse()
    return order


def _ordered_file_groups(
    cluster: list[ClusterNeuron],
    conn: sqlite3.Connection,
) -> list[tuple[str, list[ClusterNeuron]]]:
    """Group cluster neurons by source file, ordered callees-first."""
    order = _reverse_topo_order({n.id for n in cluster}, conn)
    rank = {nid: position for position, nid in enumerate(order)}
    by_file: dict[str, list[ClusterNeuron]] = {}
    for neuron in cluster:
        by_file.setdefault(neuron.file, []).append(neuron)

    def group_key(item: tuple[str, list[ClusterNeuron]]) -> tuple[int, str]:
        _file, neurons = item
        return (min(rank.get(n.id, len(rank)) for n in neurons), _file)

    groups = sorted(by_file.items(), key=group_key)
    for _file, neurons in groups:
        neurons.sort(key=lambda n: (rank.get(n.id, len(rank)), n.name))
    return groups


def build_migration_steps(
    *,
    cluster: list[ClusterNeuron],
    callers: list[ClusterNeuron],
    runtime_boundary_callers: list[str],
    conn: sqlite3.Connection,
    new_module: str,
    file_map: dict[str, str],
) -> list[MigrationStep]:
    """Build the ordered migration steps for an extraction cluster."""
    steps: list[MigrationStep] = []

    target_files = sorted(set(file_map.values()))
    skeleton_names = ", ".join(Path(f).name for f in target_files)
    steps.append(MigrationStep(
        step_number=len(steps) + 1,
        description=(
            f"Create skeleton for '{new_module}/' — "
            f"{len(target_files)} new file(s): {skeleton_names}"
        ),
        neurons_affected=[],
        callers_break=False,
    ))

    moved_ids: list[str] = []
    for source_file, neurons in _ordered_file_groups(cluster, conn):
        target_file = file_map.get(source_file, source_file)
        names = ", ".join(n.name for n in neurons)
        steps.append(MigrationStep(
            step_number=len(steps) + 1,
            description=(
                f"Move {len(neurons)} neuron(s) from {source_file} → {target_file} "
                f"(copy + re-export stub): {names}"
            ),
            neurons_affected=[n.id for n in neurons],
            callers_break=False,
        ))
        moved_ids.extend(n.id for n in neurons)

    if callers:
        caller_files = sorted({c.file for c in callers})
        steps.append(MigrationStep(
            step_number=len(steps) + 1,
            description=(
                f"Update {len(callers)} caller(s) across {len(caller_files)} file(s) "
                f"to import from '{new_module}/'"
            ),
            neurons_affected=[c.id for c in callers],
            callers_break=False,
        ))

    if runtime_boundary_callers:
        steps.append(MigrationStep(
            step_number=len(steps) + 1,
            description=(
                f"⚠️  {len(runtime_boundary_callers)} RUNTIME_BOUNDARY caller(s) detected — "
                "these cross process/framework boundaries and need manual verification"
            ),
            neurons_affected=list(runtime_boundary_callers),
            callers_break=True,
        ))

    steps.append(MigrationStep(
        step_number=len(steps) + 1,
        description=(
            f"Remove backward-compat re-exports from {len(file_map)} file(s) "
            "and run the test suite"
        ),
        neurons_affected=moved_ids,
        callers_break=False,
    ))

    return steps
