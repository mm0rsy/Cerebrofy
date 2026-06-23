"""Onboarding Navigator — data model and plan orchestrator."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EntryPoint:
    name: str
    file: str
    line_start: int
    signature: str | None
    docstring: str | None
    lobe: str


@dataclass(frozen=True)
class Hotspot:
    name: str
    file: str
    line_start: int
    caller_count: int
    lobe_spread: int
    blast_radius: int   # transitive caller count via BFS
    lobe: str


@dataclass(frozen=True)
class SafeZone:
    lobe: str
    dead_code_pct: float
    test_surface: float


@dataclass(frozen=True)
class LobeSection:
    name: str
    directory: str
    neuron_count: int
    entry_point_count: int
    coupling_ratio: float   # cross-lobe out-edges / total out-edges (0 = fully cohesive)
    cohesion: float         # intra-lobe edge ratio (1 = fully cohesive)


@dataclass(frozen=True)
class OnboardPlan:
    repo_name: str
    generated_ts: int
    depth: str              # "junior" | "senior" — hint for AI agents, not enforced here
    name: str | None        # --name option
    focus_lobe: str | None
    lobe_reading_order: tuple[LobeSection, ...]
    entry_points: tuple[EntryPoint, ...]
    hotspots: tuple[Hotspot, ...]
    safe_zones: tuple[SafeZone, ...]
    things_to_know: tuple[str, ...]   # memory titles (warning + decision types)
    memories_available: bool          # False if memories.db absent
    map_md_path: str | None
    neuron_count: int
    edge_count: int
    team_context: dict[str, Any] | None = None   # from intent.yaml (sprint, incidents, arch)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_plan(
    conn: sqlite3.Connection,
    lobes: dict[str, str],
    cerebrofy_dir: Path,
    repo_name: str,
    depth: str = "junior",
    name: str | None = None,
    focus_lobe: str | None = None,
) -> OnboardPlan:
    """Build the complete OnboardPlan from an open read-only DB connection."""
    from cerebrofy.onboard.queries import (
        build_adjacency,
        compute_node_lobes,
        fetch_entry_points,
        fetch_hotspots,
        fetch_lobe_reading_order,
        fetch_lobe_sections,
        fetch_safe_zones,
        fetch_things_to_know,
    )

    node_map, in_adj, out_adj, valid_edges = build_adjacency(conn)
    node_lobe = compute_node_lobes(node_map, lobes)

    reading_order_names = fetch_lobe_reading_order(node_lobe, lobes, in_adj, out_adj)
    lobe_sections = fetch_lobe_sections(
        lobes, node_map, node_lobe, in_adj, out_adj, reading_order_names
    )

    if focus_lobe:
        neighbours = _lobe_neighbours(focus_lobe, node_lobe, in_adj, out_adj)
        keep = {focus_lobe} | neighbours
        lobe_sections = tuple(s for s in lobe_sections if s.name in keep)
        reading_order_names = [n for n in reading_order_names if n in keep]

    entry_points = fetch_entry_points(node_map, in_adj, out_adj, node_lobe)
    hotspots = fetch_hotspots(node_map, in_adj, node_lobe)
    safe_zones = fetch_safe_zones(lobes, node_map, node_lobe, in_adj, out_adj)
    things_to_know, memories_available = fetch_things_to_know(cerebrofy_dir)
    team_context = _load_team_context(cerebrofy_dir)

    map_md = cerebrofy_dir / "cerebrofy_map.md"
    map_md_path = str(map_md) if map_md.exists() else None

    return OnboardPlan(
        repo_name=repo_name,
        generated_ts=int(time.time()),
        depth=depth,
        name=name,
        focus_lobe=focus_lobe,
        lobe_reading_order=tuple(lobe_sections),
        entry_points=tuple(entry_points),
        hotspots=tuple(hotspots),
        safe_zones=tuple(safe_zones),
        things_to_know=tuple(things_to_know),
        memories_available=memories_available,
        map_md_path=map_md_path,
        neuron_count=len(node_map),
        edge_count=len(valid_edges),
        team_context=team_context,
    )


def _load_team_context(cerebrofy_dir: Path) -> dict[str, Any] | None:
    """Load sprint goal, open incidents, and arch direction from intent.yaml.

    Returns None if intent.yaml is absent or unparseable.
    Gracefully degrades — never raises.
    """
    try:
        from cerebrofy.intent.loader import load_intent
        intent = load_intent(cerebrofy_dir)
        if intent is None:
            return None
        ctx: dict[str, Any] = {}
        if intent.sprint and intent.sprint.goal:
            ctx["sprint_goal"] = intent.sprint.goal
            if intent.sprint.deadline:
                ctx["sprint_deadline"] = intent.sprint.deadline
        open_incidents = [
            inc for inc in intent.incidents
            if inc.status not in ("closed", "patched")
        ]
        if open_incidents:
            ctx["open_incidents"] = [
                {"id": inc.id, "severity": inc.severity, "description": inc.description}
                for inc in open_incidents
            ]
        if intent.architecture:
            if intent.architecture.direction:
                ctx["arch_direction"] = intent.architecture.direction
            if intent.architecture.avoid_patterns:
                ctx["avoid_patterns"] = list(intent.architecture.avoid_patterns)
        if intent.team_context and intent.team_context.concerns:
            ctx["concerns"] = list(intent.team_context.concerns)
        return ctx or None
    except Exception:
        return None


def _lobe_neighbours(
    focus_lobe: str,
    node_lobe: dict[str, str],
    in_adj: dict[str, set[str]],
    out_adj: dict[str, set[str]],
) -> set[str]:
    """Return lobes directly connected to focus_lobe (callers and callees)."""
    focus_nodes = {nid for nid, lb in node_lobe.items() if lb == focus_lobe}
    neighbours: set[str] = set()
    for nid in focus_nodes:
        for dep in out_adj.get(nid, set()):
            lb = node_lobe.get(dep, "")
            if lb and lb != focus_lobe:
                neighbours.add(lb)
        for caller in in_adj.get(nid, set()):
            lb = node_lobe.get(caller, "")
            if lb and lb != focus_lobe:
                neighbours.add(lb)
    return neighbours
