"""Read cerebrofy.db and produce a VizGraph JSON payload for the viz server."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

ANATOMICAL_REGIONS = ["frontal", "parietal", "temporal", "occipital", "limbic"]


@dataclass(frozen=True)
class VizNode:
    id: str
    name: str
    type: str
    lobe: str    # code lobe name (from DB)
    region: str  # anatomical region (one of ANATOMICAL_REGIONS)
    file: str
    line: int


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


def export_graph(db_path: Path) -> VizGraph:
    """Read nodes and edges from cerebrofy.db and return a VizGraph."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        node_rows = con.execute(
            "SELECT id, name, type, lobe, file, line_start FROM nodes ORDER BY lobe, name"
        ).fetchall()

        seen: set[str] = set()
        unique_lobes: list[str] = []
        for r in node_rows:
            if r["lobe"] not in seen:
                unique_lobes.append(r["lobe"])
                seen.add(r["lobe"])
        lobe_index = {lobe: i for i, lobe in enumerate(unique_lobes)}

        nodes = [
            VizNode(
                id=r["id"],
                name=r["name"],
                type=r["type"],
                lobe=r["lobe"],
                region=_assign_region(r["lobe"], lobe_index),
                file=r["file"],
                line=r["line_start"],
            )
            for r in node_rows
        ]

        edge_rows = con.execute(
            "SELECT src_id, dst_id, rel_type FROM edges"
            " WHERE rel_type != 'RUNTIME_BOUNDARY'"
        ).fetchall()
        edges = [
            VizEdge(src=r["src_id"], dst=r["dst_id"], rel=r["rel_type"])
            for r in edge_rows
        ]

        # repo name = grandparent of .cerebrofy/db/cerebrofy.db
        repo = db_path.parent.parent.parent.name

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
