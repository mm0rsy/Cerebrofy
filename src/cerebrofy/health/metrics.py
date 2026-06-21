"""Compute 8 graph-derived health metrics from an open cerebrofy.db connection."""

from __future__ import annotations

import os
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True)
class HealthMetrics:
    coupling: float           # cross-lobe edge ratio (0–1, lower = better)
    avg_blast: float          # mean depth-2 caller count per neuron
    dead_code_pct: float      # % neurons with no in/out edges (excluding entry points)
    cohesion: float           # mean intra-lobe edge ratio per lobe (0–1, higher = better)
    test_surface: float       # % non-test neurons reachable from test entry points
    drift_velocity: float     # structural changes per day (rolling 7-day)
    hub_concentration: float  # % edges touching top-5% degree nodes
    neuron_count: int
    edge_count: int
    hotspots: tuple[dict[str, Any], ...]  # top-10 by caller_count × lobe_spread


def _lobe_for_file(file: str, lobes: dict[str, str]) -> str:
    for lobe_name, lobe_path in lobes.items():
        norm = lobe_path.rstrip("/")
        if file.startswith(norm + "/") or file == norm:
            return lobe_name
    return "__unknown__"


def _is_test_file(file: str) -> bool:
    basename = os.path.basename(file)
    return basename.startswith("test_") or basename.endswith("_test.py")


def compute_metrics(
    conn: sqlite3.Connection,
    lobes: dict[str, str],
    prior_snapshots: list[dict[str, Any]] | None = None,
) -> HealthMetrics:
    """Compute all 8 health metrics from the current DB state."""
    nodes = conn.execute("SELECT id, name, file FROM nodes").fetchall()
    neuron_count = len(nodes)

    if neuron_count == 0:
        return HealthMetrics(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, ())

    node_map: dict[str, dict[str, str]] = {
        row[0]: {"name": row[1], "file": row[2]} for row in nodes
    }

    edges = conn.execute(
        "SELECT src_id, dst_id, rel_type FROM edges WHERE rel_type != 'RUNTIME_BOUNDARY'"
    ).fetchall()
    edge_count = len(edges)

    # Build bidirectional adjacency (only for nodes that exist in node_map)
    out_adj: dict[str, set[str]] = defaultdict(set)
    in_adj: dict[str, set[str]] = defaultdict(set)
    valid_edges = []
    for src, dst, rel in edges:
        if src in node_map and dst in node_map:
            out_adj[src].add(dst)
            in_adj[dst].add(src)
            valid_edges.append((src, dst, rel))

    node_lobe: dict[str, str] = {
        nid: _lobe_for_file(info["file"], lobes)
        for nid, info in node_map.items()
    }

    coupling = _coupling(valid_edges, node_lobe, edge_count)
    avg_blast = _avg_blast_radius(node_map, in_adj)
    dead_code_pct = _dead_code_pct(node_map, in_adj, out_adj)
    cohesion = _lobe_cohesion(valid_edges, node_lobe)
    test_surface = _test_surface(node_map, in_adj, out_adj)
    drift_velocity = _drift_velocity(prior_snapshots, neuron_count)
    hub_concentration = _hub_concentration(valid_edges, node_map, in_adj, out_adj, edge_count)
    hotspots = _complexity_hotspots(node_map, in_adj, node_lobe)

    return HealthMetrics(
        coupling=round(coupling, 4),
        avg_blast=round(avg_blast, 2),
        dead_code_pct=round(dead_code_pct, 2),
        cohesion=round(cohesion, 4),
        test_surface=round(test_surface, 2),
        drift_velocity=round(drift_velocity, 2),
        hub_concentration=round(hub_concentration, 2),
        neuron_count=neuron_count,
        edge_count=edge_count,
        hotspots=hotspots,
    )


def _coupling(
    valid_edges: list[tuple[str, str, str]],
    node_lobe: dict[str, str],
    total_edge_count: int,
) -> float:
    if total_edge_count == 0:
        return 0.0
    cross = sum(1 for src, dst, _ in valid_edges if node_lobe.get(src) != node_lobe.get(dst))
    return cross / total_edge_count


def _avg_blast_radius(
    node_map: dict[str, dict[str, str]],
    in_adj: dict[str, set[str]],
) -> float:
    total = 0
    for nid in node_map:
        depth1 = in_adj[nid]
        depth2: set[str] = set()
        for caller in depth1:
            depth2 |= in_adj[caller]
        total += len(depth1 | depth2)
    return total / len(node_map)


def _dead_code_pct(
    node_map: dict[str, dict[str, str]],
    in_adj: dict[str, set[str]],
    out_adj: dict[str, set[str]],
) -> float:
    # Entry points (in=0, out>0) are intentionally isolated — not dead code
    dead = sum(
        1 for nid in node_map
        if not in_adj[nid] and not out_adj[nid]
    )
    return dead / len(node_map) * 100


def _lobe_cohesion(
    valid_edges: list[tuple[str, str, str]],
    node_lobe: dict[str, str],
) -> float:
    lobe_intra: dict[str, int] = defaultdict(int)
    lobe_total: dict[str, int] = defaultdict(int)
    for src, dst, _ in valid_edges:
        src_lobe = node_lobe.get(src, "__unknown__")
        lobe_total[src_lobe] += 1
        if node_lobe.get(dst) == src_lobe:
            lobe_intra[src_lobe] += 1
    if not lobe_total:
        return 0.0
    return sum(lobe_intra[lb] / lobe_total[lb] for lb in lobe_total) / len(lobe_total)


def _test_surface(
    node_map: dict[str, dict[str, str]],
    in_adj: dict[str, set[str]],
    out_adj: dict[str, set[str]],
) -> float:
    test_ids = {nid for nid, info in node_map.items() if _is_test_file(info["file"])}
    non_test_ids = set(node_map) - test_ids
    if not non_test_ids:
        return 0.0
    reachable: set[str] = set()
    frontier = set(test_ids)
    while frontier:
        next_f: set[str] = set()
        for nid in frontier:
            for dst in out_adj[nid]:
                if dst in non_test_ids and dst not in reachable:
                    reachable.add(dst)
                    next_f.add(dst)
        frontier = next_f
    return len(reachable) / len(non_test_ids) * 100


def _drift_velocity(
    prior_snapshots: list[dict[str, Any]] | None,
    current_count: int,
) -> float:
    if not prior_snapshots:
        return 0.0
    now = time.time()
    week_ago = now - 7 * 86400
    recent = sorted(
        [s for s in prior_snapshots if (s.get("build_ts") or 0) >= week_ago],
        key=lambda s: s["build_ts"],
    )
    if not recent:
        return 0.0
    days_elapsed: float = max((now - cast(float, recent[0]["build_ts"])) / 86400, 0.01)
    step_changes = [
        abs(cast(int, recent[i]["neuron_count"] or 0) - cast(int, recent[i - 1]["neuron_count"] or 0))
        for i in range(1, len(recent))
    ]
    last_delta = abs(current_count - cast(int, recent[-1]["neuron_count"] or 0))
    total: int = sum(step_changes) + last_delta
    return float(total) / days_elapsed


def _hub_concentration(
    valid_edges: list[tuple[str, str, str]],
    node_map: dict[str, dict[str, str]],
    in_adj: dict[str, set[str]],
    out_adj: dict[str, set[str]],
    total_edge_count: int,
) -> float:
    if total_edge_count == 0:
        return 0.0
    degrees = {nid: len(out_adj[nid]) + len(in_adj[nid]) for nid in node_map}
    sorted_deg = sorted(degrees.values(), reverse=True)
    cutoff = max(1, int(len(sorted_deg) * 0.05))
    threshold = sorted_deg[cutoff - 1] if cutoff <= len(sorted_deg) else 0
    hub_ids = {nid for nid, d in degrees.items() if d >= threshold and d > 0}
    hub_edges = sum(1 for src, dst, _ in valid_edges if src in hub_ids or dst in hub_ids)
    return hub_edges / total_edge_count * 100


def _complexity_hotspots(
    node_map: dict[str, dict[str, str]],
    in_adj: dict[str, set[str]],
    node_lobe: dict[str, str],
) -> tuple[dict[str, Any], ...]:
    scored = []
    for nid, info in node_map.items():
        callers = in_adj[nid]
        caller_lobes = {node_lobe[c] for c in callers if c in node_lobe}
        lobe_spread = len(caller_lobes)
        score = len(callers) * max(lobe_spread, 1)
        scored.append({
            "name": info["name"],
            "file": info["file"],
            "caller_count": len(callers),
            "lobe_spread": lobe_spread,
            "score": score,
        })
    top10 = sorted(scored, key=lambda x: cast(int, x["score"]), reverse=True)[:10]
    return tuple(top10)
