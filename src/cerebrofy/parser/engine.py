"""Universal Parser engine — Tree-sitter runner with zero language-specific logic."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING, cast

import tree_sitter_languages  # type: ignore[import-untyped]

from cerebrofy.config.loader import CerebrоfyConfig
from cerebrofy.ignore.ruleset import IgnoreRuleSet
from cerebrofy.parser.neuron import Neuron, ParseResult, deduplicate_neurons

# Suppress tree-sitter 0.21 FutureWarning about Language(path, name) constructor.
# Must be set before any get_language() call (fires lazily, not at import time).
warnings.filterwarnings("ignore", category=FutureWarning, module="tree_sitter")

if TYPE_CHECKING:
    from tree_sitter import Language, Node, Query, Tree

# Maps file extension → tree-sitter-languages grammar name.
# .h maps to "c_header" so load_query resolves to c_header.scm (declarations, not definitions).
EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c_header",
}


def load_language_parser(extension: str) -> "Language | None":
    """Return the Language object for the given file extension, or None."""
    lang_name = EXTENSION_TO_LANGUAGE.get(extension)
    if not lang_name:
        return None
    try:
        return cast("Language", tree_sitter_languages.get_language(lang_name))
    except Exception:
        return None


def load_query(extension: str, queries_dir: Path) -> "Query | None":
    """Load and compile the .scm query for the extension from queries_dir, or None."""
    lang_name = EXTENSION_TO_LANGUAGE.get(extension)
    if not lang_name:
        return None
    scm_path = queries_dir / f"{lang_name}.scm"
    if not scm_path.exists():
        return None
    try:
        lang = cast("Language", tree_sitter_languages.get_language(lang_name))
        scm_text = scm_path.read_text(encoding="utf-8")
        return lang.query(scm_text)
    except Exception:
        return None


def extract_signature(node: "Node", source: bytes) -> str | None:
    """Return the first line (declaration) of a function node, stripped."""
    node_text = source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
    first_line = node_text.split("\n")[0].strip()
    return first_line or None


def extract_docstring(node: "Node", source: bytes) -> str | None:
    """Return the first docstring or comment immediately inside the node body, or None."""
    for child in node.children:
        # Python: body block contains expression_statement wrapping a string
        if child.type in ("block", "statement_block", "function_body", "declaration_list"):
            for body_child in child.children:
                if body_child.type == "expression_statement":
                    for expr in body_child.children:
                        if expr.type == "string":
                            text = source[expr.start_byte:expr.end_byte].decode(
                                "utf-8", errors="replace"
                            ).strip("'\"` \t\n")
                            return text or None
                    break
                elif body_child.type in ("comment", "line_comment", "block_comment"):
                    return source[body_child.start_byte:body_child.end_byte].decode(
                        "utf-8", errors="replace"
                    ).strip()
                elif body_child.is_named and body_child.type not in (
                    "comment", "line_comment", "block_comment"
                ):
                    break
    return None


def map_capture_to_neuron(
    capture_name: str,
    node: "Node",
    source: bytes,
    file: str,
) -> Neuron | None:
    """Convert a tree-sitter capture to a Neuron, or None for non-Neuron captures.

    Law V: zero language-specific logic here — all exclusions live in .scm files.
    """
    if "import" in capture_name or "call" in capture_name or capture_name == "name":
        return None

    if "function" in capture_name or "method" in capture_name:
        neuron_type = "function"
    elif any(k in capture_name for k in ("class", "struct", "interface", "type")):
        neuron_type = "class"
    else:
        return None

    # Extract name from the first identifier-like child
    name: str | None = None
    _NAME_TYPES = {
        "identifier", "type_identifier", "field_identifier",
        "property_identifier", "namespace_identifier", "constant",
    }
    for child in node.children:
        if child.type in _NAME_TYPES:
            name = source[child.start_byte:child.end_byte].decode(
                "utf-8", errors="replace"
            ).strip()
            break

    if not name:
        return None

    signature = extract_signature(node, source) if neuron_type == "function" else None
    docstring = extract_docstring(node, source)

    return Neuron(
        id=f"{file}::{name}",
        name=name,
        type=neuron_type,
        file=file,
        line_start=node.start_point[0] + 1,
        line_end=node.end_point[0] + 1,
        signature=signature,
        docstring=docstring,
    )


def build_module_neuron(file: str, total_lines: int) -> Neuron:
    """Synthesize a module-level Neuron for the file."""
    name = Path(file).stem
    return Neuron(
        id=f"{file}::{name}",
        name=name,
        type="module",
        file=file,
        line_start=1,
        line_end=total_lines,
        signature=None,
        docstring=None,
    )


def extract_neurons(
    tree: "Tree",
    source: bytes,
    file: str,
    query: "Query",
) -> list[Neuron]:
    """Run query captures and map them to Neurons (plus module Neuron)."""
    captures = query.captures(tree.root_node)  # list[(Node, capture_name)]
    neurons: list[Neuron] = []
    for node, capture_name in captures:
        neuron = map_capture_to_neuron(capture_name, node, source, file)
        if neuron is not None:
            neurons.append(neuron)

    total_lines = source.count(b"\n") + 1
    neurons.append(build_module_neuron(file, total_lines))

    return deduplicate_neurons(neurons)


def parse_file(file_path: Path, queries_dir: Path, repo_root: Path) -> ParseResult:
    """Parse a single source file and return a ParseResult."""
    rel_path = str(file_path.relative_to(repo_root)).replace("\\", "/")
    extension = file_path.suffix.lower()

    lang = load_language_parser(extension)
    query = load_query(extension, queries_dir)

    if lang is None or query is None:
        return ParseResult(
            file=rel_path,
            neurons=[],
            warnings=[f"No parser for {extension}"],
        )

    source = file_path.read_bytes()
    lang_name = EXTENSION_TO_LANGUAGE[extension]
    parser = tree_sitter_languages.get_parser(lang_name)
    tree = parser.parse(source)

    warnings: list[str] = []
    if tree.root_node.has_error:
        warnings.append(f"Syntax error in {rel_path}: file partially parsed.")

    neurons = extract_neurons(tree, source, rel_path, query)
    return ParseResult(file=rel_path, neurons=neurons, warnings=warnings)


def parse_directory(
    root: Path,
    config: CerebrоfyConfig,
    ignore_rules: IgnoreRuleSet,
    queries_dir: Path | None = None,
) -> list[ParseResult]:
    """Walk root recursively and parse all tracked, non-ignored files."""
    if queries_dir is None:
        queries_dir = root / ".cerebrofy" / "queries"

    results: list[ParseResult] = []
    for file_path in sorted(root.rglob("*")):
        if not file_path.is_file():
            continue
        rel_path = str(file_path.relative_to(root)).replace("\\", "/")
        if ignore_rules.matches(rel_path):
            continue
        if file_path.suffix.lower() not in config.tracked_extensions:
            continue
        results.append(parse_file(file_path, queries_dir, root))
    return results
