"""MCP Resource handlers for cerebrofy — URI-addressable ambient context.

Resources expose codebase graph data for AI clients as ambient context
(no explicit tool call required). Nine resource types are supported:

  cerebrofy://graph/map                     → cerebrofy_map.md (full codebase map)
  cerebrofy://graph/entry-points            → entry-point neurons JSON
  cerebrofy://health/current                → latest health snapshot JSON
  cerebrofy://lobes/{name}                  → {name}_lobe.md summary Markdown
  cerebrofy://neurons/{neuron_id}           → single neuron details + source + callers JSON
  cerebrofy://neurons/file/{file_path}      → all neurons in a source file JSON
  cerebrofy://neurons/search?q={query}      → hybrid semantic search results JSON
  cerebrofy://memories/{neuron_id}          → memories attached to a neuron JSON
  cerebrofy://blast-radius/{neuron_id}      → blast radius JSON (computed on demand)

`list_resource_entries` is the single source of truth for the resource
catalog — both the server's `resources/list` handler and the
`cerebrofy_list_resources` convenience tool build from it.
"""

from __future__ import annotations

import dataclasses
import sqlite3
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

def _docs_dir(root: Path) -> Path:
    return root / "docs" / "cerebrofy"


def read_map(root: Path) -> str:
    """Return cerebrofy_map.md content, raising FileNotFoundError if missing."""
    path = _docs_dir(root) / "cerebrofy_map.md"
    if not path.exists():
        raise FileNotFoundError(
            "cerebrofy_map.md not found. Run 'cerebrofy build' first."
        )
    return path.read_text(encoding="utf-8")


def read_lobe(name: str, root: Path) -> str:
    """Return {name}_lobe.md content, raising FileNotFoundError if not indexed.

    The name must match an indexed lobe, so crafted URIs such as
    ``cerebrofy://lobes/../../secret`` cannot escape the docs directory.
    """
    if name not in list_lobe_names(root):
        raise FileNotFoundError(
            f"Lobe '{name}' not found. Run 'cerebrofy build' first."
        )
    return (_docs_dir(root) / f"{name}_lobe.md").read_text(encoding="utf-8")


def list_lobe_names(root: Path) -> list[str]:
    """Return sorted lobe names derived from *_lobe.md files on disk."""
    docs = _docs_dir(root)
    if not docs.exists():
        return []
    return sorted(
        p.stem[: -len("_lobe")]
        for p in docs.glob("*_lobe.md")
        if p.stem.endswith("_lobe")
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def entry_points(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return neurons with no incoming non-RUNTIME_BOUNDARY edges but with outgoing edges."""
    rows = conn.execute("""
        SELECT n.id, n.name, n.file, n.line_start, n.type
        FROM nodes n
        WHERE n.type != 'module'
          AND NOT EXISTS (
              SELECT 1 FROM edges e
              WHERE e.dst_id = n.id AND e.rel_type != 'RUNTIME_BOUNDARY'
          )
          AND EXISTS (SELECT 1 FROM edges e WHERE e.src_id = n.id)
        ORDER BY n.file, n.line_start
    """).fetchall()
    return [
        {"id": r[0], "name": r[1], "file": r[2], "line_start": r[3], "type": r[4]}
        for r in rows
    ]


def get_neuron(neuron_id: str, conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Fetch a single neuron by ID, returning None if not found."""
    row = conn.execute(
        "SELECT id, name, file, type, line_start, line_end, signature, docstring, hash "
        "FROM nodes WHERE id = ? LIMIT 1",
        (neuron_id,),
    ).fetchone()
    if not row:
        return None
    cols = ("id", "name", "file", "type", "line_start", "line_end",
            "signature", "docstring", "hash")
    return dict(zip(cols, row))


def neuron_source(neuron: dict[str, Any], root: Path) -> str | None:
    """Return the neuron's exact source text, or None if the file is unreadable."""
    file_rel = str(neuron.get("file") or "")
    line_start = neuron.get("line_start")
    if not file_rel or not isinstance(line_start, int) or line_start < 1:
        return None
    try:
        text = (root / file_rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    line_end = neuron.get("line_end")
    end = line_end if isinstance(line_end, int) and line_end >= line_start else line_start
    return "\n".join(text.splitlines()[line_start - 1 : end])


def neuron_callers(neuron_id: str, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return direct (depth-1) callers of a neuron for the neuron resource."""
    from cerebrofy.analysis.blast_radius import (
        compute_blast_radius_report,
        neuron_for_target,
    )

    neuron = neuron_for_target(neuron_id, conn)
    if neuron is None:
        return []
    report = compute_blast_radius_report([neuron], conn, depth=1)
    return [
        {"name": n.name, "file": n.file, "line": n.line_start}
        for n in report.changed_neurons[0].callers_depth1
    ]


# ---------------------------------------------------------------------------
# Memory helper
# ---------------------------------------------------------------------------

def memories_for_neuron(neuron_id: str, root: Path) -> list[dict[str, Any]]:
    """Return memories attached to neuron_id. Returns [] if memories.db absent."""
    memories_db = root / ".cerebrofy" / "db" / "memories.db"
    if not memories_db.exists():
        return []
    try:
        from cerebrofy.memory.store import list_memories, open_memories_db
        conn = open_memories_db(root / ".cerebrofy")
        try:
            return [dataclasses.asdict(m) for m in list_memories(conn, neuron_id=neuron_id)]
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return []


# ---------------------------------------------------------------------------
# Health helper
# ---------------------------------------------------------------------------

def current_health(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Return the latest health snapshot dict, or None if none recorded yet."""
    from cerebrofy.health.snapshot import fetch_latest_snapshot
    return fetch_latest_snapshot(conn)


# ---------------------------------------------------------------------------
# Neuron helpers
# ---------------------------------------------------------------------------

_NEURON_COLS = ("id", "name", "type", "file", "line_start", "line_end", "signature")


def file_neurons(file_path: str, conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return all neurons defined in *file_path* (exact or suffix match).

    Path separators are normalised to POSIX so Windows clients can pass
    backslash paths. Substring matching uses ``instr`` (not ``LIKE``) so
    underscores and percent signs in file names are treated literally.
    """
    path = file_path.replace("\\", "/").removeprefix("./").strip()
    if not path:
        return []
    rows = conn.execute(
        "SELECT id, name, type, file, line_start, line_end, signature "
        "FROM nodes WHERE file = ? ORDER BY line_start",
        (path,),
    ).fetchall()
    if not rows:
        rows = conn.execute(
            "SELECT id, name, type, file, line_start, line_end, signature "
            "FROM nodes WHERE instr(file, ?) > 0 ORDER BY file, line_start LIMIT 200",
            (path,),
        ).fetchall()
    return [dict(zip(_NEURON_COLS, r)) for r in rows]


def search_resource_results(query: str, root: Path, top_k: int = 10) -> list[dict[str, Any]]:
    """Run hybrid semantic search and return compact hit dicts.

    Mirrors the ``search_code`` MCP tool output shape (plus the neuron ``id``
    so clients can follow up with ``cerebrofy://neurons/{id}``).
    """
    from cerebrofy.config.loader import load_config
    from cerebrofy.search.hybrid import embed_query, hybrid_search

    config = load_config(root / ".cerebrofy" / "config.yaml")
    embedding = embed_query(query, config.embedding_model)
    result = hybrid_search(
        query=query,
        db_path=root / ".cerebrofy" / "db" / "cerebrofy.db",
        embedding=embedding,
        top_k=top_k,
        lobes=config.lobes,
        repo_root=root,
    )
    return [
        {
            "id": n.id,
            "name": n.name,
            "type": n.type,
            "file": n.file,
            "line": n.line_start,
            "similarity": n.similarity,
            "summary": (n.docstring or n.signature or "")[:200],
        }
        for n in result.matched_neurons
    ]


# ---------------------------------------------------------------------------
# Blast radius helper
# ---------------------------------------------------------------------------

def blast_radius_summary(
    target: str,
    conn: sqlite3.Connection,
    depth: int = 2,
) -> dict[str, Any] | None:
    """Compute the blast-radius JSON payload for *target*, or None if not found.

    Payload shape matches the ``cerebrofy_blast_radius`` MCP tool, including
    the ``summary`` field (PR-comment Markdown).
    """
    from cerebrofy.analysis.blast_radius import (
        compute_blast_radius_report,
        format_pr_comment,
        neuron_for_target,
    )

    neuron = neuron_for_target(target, conn)
    if neuron is None:
        return None

    report = compute_blast_radius_report([neuron], conn, depth=depth)
    nbr = report.changed_neurons[0]
    return {
        "target_neuron": {
            "name": nbr.neuron.name,
            "file": nbr.neuron.file,
            "line": nbr.neuron.line_start,
        },
        "callers": [
            {"name": n.name, "file": n.file, "line": n.line_start, "depth": 1}
            for n in nbr.callers_depth1
        ] + [
            {"name": n.name, "file": n.file, "line": n.line_start, "depth": 2}
            for n in nbr.callers_depth2
        ],
        "uncovered_callers": nbr.uncovered_callers,
        "risk_score": round(nbr.risk_score, 3),
        "risk_label": nbr.risk_label,
        "lobe_spread": nbr.lobe_spread,
        "runtime_boundary_callers": nbr.runtime_boundary_callers,
        "summary": format_pr_comment(report),
    }


# ---------------------------------------------------------------------------
# Resource catalog
# ---------------------------------------------------------------------------

_FILTER_ALIASES: dict[str, str] = {
    "all": "all",
    "graph": "graph",
    "health": "health",
    "lobes": "lobes",
    "neurons": "neurons",
    "memories": "memories",
    "blast-radius": "blast-radius",
}


def list_resource_entries(root: Path) -> list[dict[str, Any]]:
    """Return the full resource catalog: static resources, URI templates, and lobes.

    Entries carry ``category`` (for filtering) and ``template`` (True for
    URI-template entries, which are advertised via ``resources/templates/list``
    rather than ``resources/list``).
    """
    entries: list[dict[str, Any]] = [
        {
            "uri": "cerebrofy://graph/map",
            "name": "Codebase Map",
            "description": "Full codebase map — all lobes, neurons, and edges in Markdown.",
            "mime_type": "text/markdown",
            "category": "graph",
            "template": False,
        },
        {
            "uri": "cerebrofy://graph/entry-points",
            "name": "Entry Points",
            "description": "Entry-point neurons — no non-runtime callers, with outgoing edges.",
            "mime_type": "application/json",
            "category": "graph",
            "template": False,
        },
        {
            "uri": "cerebrofy://health/current",
            "name": "Health Snapshot",
            "description": "Latest codebase health metrics from the graph.",
            "mime_type": "application/json",
            "category": "health",
            "template": False,
        },
        {
            "uri": "cerebrofy://neurons/{neuron_id}",
            "name": "Neuron",
            "description": "Full details for a neuron by ID (file::name): source, signature, direct callers.",
            "mime_type": "application/json",
            "category": "neurons",
            "template": True,
        },
        {
            "uri": "cerebrofy://neurons/file/{file_path}",
            "name": "File Neurons",
            "description": "All neurons defined in a source file (path suffix match).",
            "mime_type": "application/json",
            "category": "neurons",
            "template": True,
        },
        {
            "uri": "cerebrofy://neurons/search{?q}",
            "name": "Neuron Search",
            "description": "Hybrid semantic search results for a query — read-only navigation.",
            "mime_type": "application/json",
            "category": "neurons",
            "template": True,
        },
        {
            "uri": "cerebrofy://memories/{neuron_id}",
            "name": "Neuron Memories",
            "description": "All memories attached to a neuron.",
            "mime_type": "application/json",
            "category": "memories",
            "template": True,
        },
        {
            "uri": "cerebrofy://blast-radius/{neuron_id}",
            "name": "Blast Radius",
            "description": "Blast radius for a neuron — callers, risk score, PR comment.",
            "mime_type": "application/json",
            "category": "blast-radius",
            "template": True,
        },
    ]
    for lobe in list_lobe_names(root):
        entries.append({
            "uri": f"cerebrofy://lobes/{lobe}",
            "name": f"Lobe: {lobe}",
            "description": f"Summary of the {lobe} module — neurons, edges, and highlights.",
            "mime_type": "text/markdown",
            "category": "lobes",
            "template": False,
        })
    return entries


def filter_resource_entries(
    entries: list[dict[str, Any]],
    filter_value: str = "all",
) -> list[dict[str, Any]]:
    """Filter catalog entries by category. Raises ValueError on unknown filters."""
    key = (filter_value or "all").strip().lower()
    if key not in _FILTER_ALIASES:
        valid = ", ".join(sorted(_FILTER_ALIASES))
        raise ValueError(f"Unknown filter '{filter_value}'. Valid filters: {valid}.")
    if key == "all":
        return entries
    return [e for e in entries if e["category"] == key]


# ---------------------------------------------------------------------------
# Change detection (resource subscription support)
# ---------------------------------------------------------------------------

def index_fingerprint(
    root: Path,
) -> tuple[Any, Any, Any]:
    """Return a cheap change signature of the index and generated docs.

    Tuple shape: ``(db_sig, memories_db_sig, docs_sig)`` where each signature
    is a ``(mtime_ns, size)`` pair, a tuple of per-file signatures for the
    docs directory, or None when the path does not exist. Comparing two
    fingerprints tells the MCP server whether ``cerebrofy build``/``update``
    changed anything worth notifying subscribed clients about.
    """
    def _stat(path: Path) -> tuple[int, int] | None:
        try:
            st = path.stat()
        except OSError:
            return None
        return (st.st_mtime_ns, st.st_size)

    docs = root / "docs" / "cerebrofy"
    docs_sig: Any = None
    if docs.is_dir():
        docs_sig = tuple(
            sorted(
                (p.name, sig) for p in docs.glob("*.md")
                if (sig := _stat(p)) is not None
            )
        )
    return (
        _stat(root / ".cerebrofy" / "db" / "cerebrofy.db"),
        _stat(root / ".cerebrofy" / "db" / "memories.db"),
        docs_sig,
    )
