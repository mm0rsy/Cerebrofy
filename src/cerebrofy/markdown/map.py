"""Write cerebrofy_map.md — the master index of all Lobes."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def write_map_md(
    conn: sqlite3.Connection,
    lobes: dict[str, str],
    state_hash: str,
    out_dir: Path,
) -> None:
    """Write cerebrofy_map.md to out_dir from the committed index."""
    last_build_row = conn.execute(
        "SELECT value FROM meta WHERE key='last_build'"
    ).fetchone()
    last_build = last_build_row[0] if last_build_row else "unknown"

    lines: list[str] = [
        "# Cerebrofy Map",
        "",
        f"**State Hash**: `{state_hash}`",
        f"**Last Build**: {last_build}",
        f"**Lobes**: {len(lobes)}",
        "",
        "## Lobes",
        "",
        "| Lobe | Path | Neurons | File |",
        "|------|------|---------|------|",
    ]

    for lobe_name, lobe_path in lobes.items():
        if lobe_path in (".", "./", ""):
            prefix = "%"
        else:
            prefix = lobe_path.rstrip("/") + "/%"
        count = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE file LIKE ?", (prefix,)
        ).fetchone()[0]
        lobe_file = f"{lobe_name}_lobe.md"
        lines.append(
            f"| {lobe_name} | {lobe_path} | {count} | [{lobe_file}]({lobe_file}) |"
        )

    out_path = out_dir / "cerebrofy_map.md"
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
