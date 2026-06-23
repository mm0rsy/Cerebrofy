"""DB query and graph-analysis functions for the Onboarding Navigator."""
from __future__ import annotations

import heapq
import os
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from cerebrofy.onboard.planner import EntryPoint, Hotspot, LobeSection, SafeZone


def _lobe_for_file(file: str, lobes: dict[str, str]) -> str:
    """Map a file path to its configured lobe name (same as health/metrics.py)."""
    for lobe_name, lobe_path in lobes.items():
        norm = lobe_path.rstrip("/")
        if file.startswith(norm + "/") or file == norm:
            return lobe_name
    return "__unknown__"


def _is_test_file(file: str) -> bool:
    basename = os.path.basename(file)
    return basename.startswith("test_") or basename.endswith("_test.py")


def build_adjacency(
    conn: sqlite3.Connection,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, set[str]],
    dict[str, set[str]],
    list[tuple[str, str, str]],
]:
    """Fetch nodes and edges once; return (node_map, in_adj, out_adj, valid_edges).

    node_map: {id: {name, type, file, line_start, signature, docstring}}
    """
    rows = conn.execute(
        "SELECT id, name, type, file, line_start, signature, docstring FROM nodes"
    ).fetchall()
    node_map: dict[str, dict[str, Any]] = {
        r[0]: {
            "name": r[1], "type": r[2], "file": r[3],
            "line_start": r[4], "signature": r[5], "docstring": r[6],
        }
        for r in rows
    }

    edges = conn.execute(
        "SELECT src_id, dst_id, rel_type FROM edges WHERE rel_type != 'RUNTIME_BOUNDARY'"
    ).fetchall()

    in_adj: dict[str, set[str]] = defaultdict(set)
    out_adj: dict[str, set[str]] = defaultdict(set)
    valid_edges: list[tuple[str, str, str]] = []
    for src, dst, rel in edges:
        if src in node_map and dst in node_map:
            out_adj[src].add(dst)
            in_adj[dst].add(src)
            valid_edges.append((src, dst, rel))

    return node_map, in_adj, out_adj, valid_edges


def compute_node_lobes(
    node_map: dict[str, dict[str, Any]],
    lobes: dict[str, str],
) -> dict[str, str]:
    """Return {node_id: lobe_name} for every node."""
    return {nid: _lobe_for_file(info["file"], lobes) for nid, info in node_map.items()}


def fetch_lobe_reading_order(
    node_lobe: dict[str, str],
    lobes: dict[str, str],
    in_adj: dict[str, set[str]],
    out_adj: dict[str, set[str]],
) -> list[str]:
    """Kahn's topological sort of the lobe dependency graph.

    Direction: src_lobe calls dst_lobe → dst_lobe is a prerequisite → read dst_lobe first.
    Cycle-breaking: inject the lobe with fewest remaining unread prerequisites.
    """
    known = set(lobes.keys())

    # prerequisites[src] = {dst_lobes that src depends on}
    prerequisites: dict[str, set[str]] = {lb: set() for lb in known}
    for nid, lb in node_lobe.items():
        if lb not in known:
            continue
        for dep_id in out_adj.get(nid, set()):
            dep_lb = node_lobe.get(dep_id, "__unknown__")
            if dep_lb != lb and dep_lb in known:
                prerequisites[lb].add(dep_lb)

    # reading_in_degree[src] = number of unread prerequisites
    reading_in_degree: dict[str, int] = {lb: len(p) for lb, p in prerequisites.items()}
    # successors[dst] = lobes that can be unlocked once dst is read
    successors: dict[str, list[str]] = defaultdict(list)
    for lb, prereqs in prerequisites.items():
        for dep_lb in prereqs:
            successors[dep_lb].append(lb)

    # Kahn's BFS — heap for stable alphabetical tie-breaking
    heap: list[tuple[int, str]] = [
        (0, lb) for lb in known if reading_in_degree[lb] == 0
    ]
    heapq.heapify(heap)
    result: list[str] = []
    in_result: set[str] = set()

    while heap:
        _, lobe = heapq.heappop(heap)
        if lobe in in_result:
            continue
        result.append(lobe)
        in_result.add(lobe)
        for dependent in successors[lobe]:
            if dependent not in in_result:
                reading_in_degree[dependent] -= 1
                if reading_in_degree[dependent] == 0:
                    heapq.heappush(heap, (0, dependent))

    # Cycle-breaking: inject remaining lobes by fewest unread prerequisites
    remaining = set(known) - in_result
    while remaining:
        best = min(remaining, key=lambda lb: reading_in_degree[lb])
        result.append(best)
        in_result.add(best)
        remaining.discard(best)
        for dependent in successors[best]:
            if dependent in remaining:
                reading_in_degree[dependent] -= 1
                if reading_in_degree[dependent] <= 0:
                    result.append(dependent)
                    in_result.add(dependent)
                    remaining.discard(dependent)

    return result


def fetch_entry_points(
    node_map: dict[str, dict[str, Any]],
    in_adj: dict[str, set[str]],
    out_adj: dict[str, set[str]],
    node_lobe: dict[str, str],
    limit: int = 10,
) -> list[EntryPoint]:
    """Return neurons with in_degree==0 and out_degree>0, sorted by out_degree desc."""
    candidates = [
        nid for nid, info in node_map.items()
        if not in_adj.get(nid) and out_adj.get(nid)
        and not _is_test_file(info["file"])
        and node_lobe.get(nid, "__unknown__") != "__unknown__"
    ]
    candidates.sort(key=lambda nid: len(out_adj.get(nid, set())), reverse=True)
    result: list[EntryPoint] = []
    for nid in candidates[:limit]:
        info = node_map[nid]
        raw_doc = (info["docstring"] or "")[:120]
        result.append(EntryPoint(
            name=info["name"],
            file=info["file"],
            line_start=info["line_start"],
            signature=info["signature"],
            docstring=raw_doc or None,
            lobe=node_lobe.get(nid, "__unknown__"),
        ))
    return result


def fetch_hotspots(
    node_map: dict[str, dict[str, Any]],
    in_adj: dict[str, set[str]],
    node_lobe: dict[str, str],
    limit: int = 10,
) -> list[Hotspot]:
    """Top-N neurons by caller_count × lobe_spread (same formula as health/metrics.py)."""
    scored: list[tuple[int, str]] = []
    for nid, info in node_map.items():
        if _is_test_file(info["file"]):
            continue
        callers = in_adj.get(nid, set())
        caller_lobes = {node_lobe[c] for c in callers if c in node_lobe}
        score = len(callers) * max(len(caller_lobes), 1)
        scored.append((score, nid))
    scored.sort(reverse=True)

    result: list[Hotspot] = []
    for _score, nid in scored[:limit]:
        info = node_map[nid]
        callers = in_adj.get(nid, set())
        caller_lobes = {node_lobe[c] for c in callers if c in node_lobe}
        result.append(Hotspot(
            name=info["name"],
            file=info["file"],
            line_start=info["line_start"],
            caller_count=len(callers),
            lobe_spread=len(caller_lobes),
            lobe=node_lobe.get(nid, "__unknown__"),
        ))
    return result


def fetch_lobe_sections(
    lobes: dict[str, str],
    node_map: dict[str, dict[str, Any]],
    node_lobe: dict[str, str],
    in_adj: dict[str, set[str]],
    out_adj: dict[str, set[str]],
    reading_order: list[str],
) -> tuple[LobeSection, ...]:
    """Compute per-lobe metrics and return LobeSections in reading order."""
    lobe_nodes: dict[str, set[str]] = defaultdict(set)
    for nid, lb in node_lobe.items():
        if lb in lobes:
            lobe_nodes[lb].add(nid)

    lobe_out_total: dict[str, int] = defaultdict(int)
    lobe_out_cross: dict[str, int] = defaultdict(int)
    lobe_intra: dict[str, int] = defaultdict(int)
    for lb, nodes in lobe_nodes.items():
        for nid in nodes:
            for dst in out_adj.get(nid, set()):
                lobe_out_total[lb] += 1
                if node_lobe.get(dst) == lb:
                    lobe_intra[lb] += 1
                else:
                    lobe_out_cross[lb] += 1

    seen: set[str] = set()
    result: list[LobeSection] = []
    for lobe_name in reading_order:
        seen.add(lobe_name)
        nodes = lobe_nodes.get(lobe_name, set())
        ep_count = sum(1 for nid in nodes if not in_adj.get(nid) and out_adj.get(nid))
        total_out = lobe_out_total.get(lobe_name, 0)
        cross_out = lobe_out_cross.get(lobe_name, 0)
        intra = lobe_intra.get(lobe_name, 0)
        coupling = cross_out / total_out if total_out > 0 else 0.0
        cohesion = intra / total_out if total_out > 0 else 0.0
        result.append(LobeSection(
            name=lobe_name,
            directory=lobes.get(lobe_name, lobe_name),
            neuron_count=len(nodes),
            entry_point_count=ep_count,
            coupling_ratio=round(coupling, 3),
            cohesion=round(cohesion, 3),
        ))

    # Include config lobes absent from the reading order (e.g. isolated lobes)
    for lobe_name, lobe_dir in lobes.items():
        if lobe_name not in seen:
            nodes = lobe_nodes.get(lobe_name, set())
            result.append(LobeSection(
                name=lobe_name, directory=lobe_dir,
                neuron_count=len(nodes), entry_point_count=0,
                coupling_ratio=0.0, cohesion=0.0,
            ))

    return tuple(result)


def fetch_safe_zones(
    lobes: dict[str, str],
    node_map: dict[str, dict[str, Any]],
    node_lobe: dict[str, str],
    in_adj: dict[str, set[str]],
    out_adj: dict[str, set[str]],
) -> list[SafeZone]:
    """Return per-lobe SafeZone metrics, sorted safest first (low dead, high coverage)."""
    lobe_nodes: dict[str, set[str]] = defaultdict(set)
    for nid, lb in node_lobe.items():
        if lb in lobes:
            lobe_nodes[lb].add(nid)

    # BFS from test entry points to find reachable non-test nodes
    test_ids = {nid for nid, info in node_map.items() if _is_test_file(info["file"])}
    reachable: set[str] = set()
    visited: set[str] = set(test_ids)
    frontier = set(test_ids)
    while frontier:
        next_f: set[str] = set()
        for nid in frontier:
            for dst in out_adj.get(nid, set()):
                if dst not in visited:
                    visited.add(dst)
                    next_f.add(dst)
                    dst_file = node_map.get(dst, {}).get("file", "")
                    if not _is_test_file(dst_file):
                        reachable.add(dst)
        frontier = next_f

    zones: list[SafeZone] = []
    for lobe_name, nodes in lobe_nodes.items():
        if not nodes:
            continue
        dead = sum(1 for nid in nodes if not in_adj.get(nid) and not out_adj.get(nid))
        dead_pct = dead / len(nodes) * 100
        test_surf = len(nodes & reachable) / len(nodes) * 100
        zones.append(SafeZone(
            lobe=lobe_name,
            dead_code_pct=round(dead_pct, 1),
            test_surface=round(test_surf, 1),
        ))

    # Safest = low dead code and high test surface
    zones.sort(key=lambda z: (z.dead_code_pct, -z.test_surface))
    return zones


def fetch_things_to_know(cerebrofy_dir: Path) -> tuple[list[str], bool]:
    """Read warning + decision memory titles.

    Returns (titles, memories_available).
    memories_available is False only when memories.db does not exist.
    """
    memories_db = cerebrofy_dir / "db" / "memories.db"
    if not memories_db.exists():
        return [], False
    try:
        from cerebrofy.memory.store import list_memories, open_memories_db
        conn = open_memories_db(cerebrofy_dir)
        try:
            warnings = list_memories(conn, type_filter="warning", include_stale=False)
            decisions = list_memories(conn, type_filter="decision", include_stale=False)
        finally:
            conn.close()
        seen: set[str] = set()
        titles: list[str] = []
        for m in warnings + decisions:
            if m.id not in seen:
                seen.add(m.id)
                titles.append(m.title)
        return titles, True
    except Exception:
        return [], True
