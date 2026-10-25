"""Golden parser tests for tree-sitter adapter (workstream 4 / hardening plan item 4).

Regression guard: tree-sitter 0.23+ adapter (tree-sitter-language-pack + Query/QueryCursor
API) must produce the same Neurons as the previously-pinned tree-sitter 0.21 behaviour.
"""

from __future__ import annotations

from pathlib import Path

from cerebrofy.parser.engine import extract_neurons, load_language_parser, load_query, parse_file
from cerebrofy.parser.neuron import Neuron


def _parse(tmp_path: Path, source: str, ext: str = ".py") -> list[Neuron]:
    source_path = tmp_path / f"fixture{ext}"
    source_path.write_text(source, encoding="utf-8")
    queries_dir = Path(__file__).resolve().parents[3] / "src" / "cerebrofy" / "queries"
    return parse_file(source_path, queries_dir, repo_root=tmp_path).neurons


def test_golden_python_functions(tmp_path: Path) -> None:
    neurons = _parse(
        tmp_path,
        "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n",
    )
    names = [n.name for n in neurons if n.type == "function"]
    assert names == ["add", "mul"]


def test_golden_python_module_neuron_appended(tmp_path: Path) -> None:
    neurons = _parse(tmp_path, "x = 1\n")
    assert any(n.type == "module" and n.file == "fixture.py" for n in neurons)


def test_adapter_language_loads(tmp_path: Path) -> None:
    lang = load_language_parser(".py")
    assert lang is not None


def test_adapter_query_loads(tmp_path: Path) -> None:
    query = load_query(".py", Path(__file__).resolve().parents[3] / "src" / "cerebrofy" / "queries")
    assert query is not None


def test_adapter_run_query_captures(tmp_path: Path) -> None:
    lang = load_language_parser(".py")
    query = load_query(".py", Path(__file__).resolve().parents[3] / "src" / "cerebrofy" / "queries")
    assert lang is not None and query is not None
    source_path = tmp_path / "fixture.py"
    source_path.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    source = source_path.read_bytes()
    tree = lang and __import__("tree_sitter", fromlist=["Parser"]).Parser(lang).parse(source)
    assert tree is not None
    captures = extract_neurons(tree, source, "fixture.py", query)[0]
    assert captures
