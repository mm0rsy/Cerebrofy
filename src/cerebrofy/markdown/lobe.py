"""Write per-lobe Markdown documentation from the committed cerebrofy.db."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def write_lobe_md(
    conn: sqlite3.Connection,
    lobe_name: str,
    lobe_path: str,
    out_dir: Path,
) -> None:
    """Write {lobe_name}_lobe.md to out_dir from the committed index."""
    # Query all nodes whose file path falls under this lobe.
    # Special case: "." means the repo root — match all files.
    if lobe_path in (".", "./", ""):
        prefix = "%"
    else:
        prefix = lobe_path.rstrip("/") + "/%"
    rows = conn.execute(
        "SELECT id, name, type, signature, docstring, line_start, line_end "
        "FROM nodes WHERE file LIKE ? ORDER BY file, line_start",
        (prefix,),
    ).fetchall()

    # Inbound / outbound call counts (exclude RUNTIME_BOUNDARY)
    inbound_raw = conn.execute(
        "SELECT dst_id, COUNT(*) FROM edges "
        "WHERE rel_type != 'RUNTIME_BOUNDARY' GROUP BY dst_id"
    ).fetchall()
    outbound_raw = conn.execute(
        "SELECT src_id, COUNT(*) FROM edges "
        "WHERE rel_type != 'RUNTIME_BOUNDARY' GROUP BY src_id"
    ).fetchall()

    inbound: dict[str, int] = {nid: cnt for nid, cnt in inbound_raw}
    outbound: dict[str, int] = {nid: cnt for nid, cnt in outbound_raw}

    last_indexed = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines: list[str] = [
        f"# {lobe_name} Lobe",
        "",
        f"**Path**: `{lobe_path}`",
        f"**Last indexed**: {last_indexed}",
        "",
        "## Neurons",
        "",
        "| Name | Type | Signature | Docstring | Lines |",
        "|------|------|-----------|-----------|-------|",
    ]

    for nid, name, ntype, sig, doc, line_start, line_end in rows:
        sig_cell = (sig or "").replace("|", "\\|")[:80]
        doc_cell = (doc or "").replace("|", "\\|")[:60]
        lines.append(
            f"| {name} | {ntype} | {sig_cell} | {doc_cell} | L{line_start}–L{line_end} |"
        )

    lines += [
        "",
        "## Synaptic Projections",
        "",
        "| Neuron | Inbound Calls | Outbound Calls |",
        "|--------|--------------|----------------|",
    ]

    for nid, name, *_ in rows:
        in_cnt = inbound.get(nid, 0)
        out_cnt = outbound.get(nid, 0)
        lines.append(f"| {name} | {in_cnt} | {out_cnt} |")

    out_path = out_dir / f"{lobe_name}_lobe.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
