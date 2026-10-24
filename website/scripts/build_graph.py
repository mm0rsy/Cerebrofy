#!/usr/bin/env python3
"""Generate website/graph.js: the module import graph of src/cerebrofy.

The landing page draws Cerebrofy's own source as a brain. Run this from anywhere:

    python website/scripts/build_graph.py

Standard library only, deterministic output (no timestamps), so it is safe to run in CI.
"""
from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "src" / "cerebrofy"
OUT = ROOT / "website" / "graph.js"


def module_name(path: Path) -> str:
    parts = list(path.relative_to(PKG.parent).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def main() -> None:
    files = sorted(PKG.rglob("*.py"))
    mods = {module_name(p): p for p in files}
    names = set(mods)
    nodes: list[dict] = []
    edges: set[tuple[str, str]] = set()

    for name, path in mods.items():
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        pieces = name.split(".")
        nodes.append({"id": name, "lobe": pieces[1] if len(pieces) > 1 else "core", "loc": len(text.splitlines())})
        pkg = pieces if path.name == "__init__.py" else pieces[:-1]
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base = pkg[: len(pkg) - (node.level - 1)]
                    mod = ".".join(base + (node.module.split(".") if node.module else []))
                else:
                    mod = node.module or ""
                targets.append(mod)
                targets += [f"{mod}.{a.name}" for a in node.names]
            elif isinstance(node, ast.Import):
                targets += [a.name for a in node.names]
            for t in targets:
                if t in names and t != name:
                    edges.add((name, t))

    index = {n["id"]: i for i, n in enumerate(nodes)}
    data = {
        "version": tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"],
        "nodes": nodes,
        "edges": sorted([index[a], index[b]] for a, b in edges if a in index and b in index),
    }
    OUT.write_text("window.CEREBROFY_GRAPH=" + json.dumps(data, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(nodes)} modules, {len(data['edges'])} edges, v{data['version']}")


if __name__ == "__main__":
    main()
