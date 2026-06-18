"""Read cerebrofy.db and produce a VizGraph JSON payload for the viz server."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

ANATOMICAL_REGIONS = ["frontal", "parietal", "temporal", "occipital", "limbic"]


@dataclass(frozen=True)
class VizNode:
    id: str
    name: str
    type: str
    lobe: str      # code lobe name (from config.yaml lobes mapping)
    region: str    # anatomical region (one of ANATOMICAL_REGIONS)
    file: str
    line: int
    docstring: str
    in_degree: int   # edges arriving at this node
    out_degree: int  # edges leaving this node
    is_entry: bool   # True for CLI entry points (commands/ or cli.py)


@dataclass(frozen=True)
class VizEdge:
    src: str
    dst: str
    rel: str


@dataclass
class VizMeta:
    repo: str
    node_count: int
    edge_count: int
    lobe_count: int


@dataclass
class VizGraph:
    nodes: list[VizNode]
    edges: list[VizEdge]
    meta: VizMeta

    def to_json(self) -> str:
        return json.dumps({
            "nodes": [asdict(n) for n in self.nodes],
            "edges": [asdict(e) for e in self.edges],
            "meta": asdict(self.meta),
        })


def _assign_region(lobe: str, lobe_index: dict[str, int]) -> str:
    """Stable round-robin: maps any code lobe name to one of 5 anatomical regions."""
    return ANATOMICAL_REGIONS[lobe_index.get(lobe, 0) % len(ANATOMICAL_REGIONS)]


def _load_lobe_map(db_path: Path) -> dict[str, str]:
    """Read config.yaml and return {lobe_name: directory_prefix} mapping."""
    config_path = db_path.parent.parent / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open() as f:
        cfg: dict[str, object] = yaml.safe_load(f) or {}
    raw = cfg.get("lobes")
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v) for k, v in raw.items()}


def _file_to_lobe(file: str, lobe_map: dict[str, str]) -> str:
    """Return the lobe name whose directory prefix best matches the file path."""
    best_lobe, best_len = "unknown", 0
    for lobe, prefix in lobe_map.items():
        if file.startswith(prefix) and len(prefix) > best_len:
            best_lobe, best_len = lobe, len(prefix)
    return best_lobe


def export_graph(db_path: Path) -> VizGraph:
    """Read nodes and edges from cerebrofy.db and return a VizGraph."""
    lobe_map = _load_lobe_map(db_path)

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        node_rows = con.execute(
            "SELECT id, name, type, file, line_start, docstring FROM nodes ORDER BY file, name"
        ).fetchall()

        seen: set[str] = set()
        unique_lobes: list[str] = []
        row_lobes: list[str] = []
        for r in node_rows:
            lobe = _file_to_lobe(r["file"], lobe_map)
            row_lobes.append(lobe)
            if lobe not in seen:
                unique_lobes.append(lobe)
                seen.add(lobe)
        lobe_index = {lobe: i for i, lobe in enumerate(unique_lobes)}

        # Collect valid rows (exclude unknown-lobe files such as tests)
        valid_rows = [
            (i, r) for i, r in enumerate(node_rows) if row_lobes[i] != "unknown"
        ]
        valid_ids = {r["id"] for _, r in valid_rows}

        # Build edges first so we can compute per-node degree before freezing VizNodes
        edge_rows = con.execute(
            "SELECT src_id, dst_id, rel_type FROM edges"
            " WHERE rel_type != 'RUNTIME_BOUNDARY'"
        ).fetchall()
        edges = [
            VizEdge(src=r["src_id"], dst=r["dst_id"], rel=r["rel_type"])
            for r in edge_rows
            if r["src_id"] in valid_ids and r["dst_id"] in valid_ids
        ]

        in_degrees: dict[str, int] = {r["id"]: 0 for _, r in valid_rows}
        out_degrees: dict[str, int] = {r["id"]: 0 for _, r in valid_rows}
        for e in edges:
            out_degrees[e.src] += 1
            in_degrees[e.dst] += 1

        nodes = [
            VizNode(
                id=r["id"],
                name=r["name"],
                type=r["type"],
                lobe=row_lobes[i],
                region=_assign_region(row_lobes[i], lobe_index),
                file=r["file"],
                line=r["line_start"],
                docstring=r["docstring"] or "",
                in_degree=in_degrees.get(r["id"], 0),
                out_degree=out_degrees.get(r["id"], 0),
                is_entry=in_degrees.get(r["id"], 0) == 0 and out_degrees.get(r["id"], 0) > 0,
            )
            for i, r in valid_rows
        ]

        repo = db_path.parent.parent.parent.resolve().name

        return VizGraph(
            nodes=nodes,
            edges=edges,
            meta=VizMeta(
                repo=repo,
                node_count=len(nodes),
                edge_count=len(edges),
                lobe_count=len(unique_lobes),
            ),
        )
    finally:
        con.close()
