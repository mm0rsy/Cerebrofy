"""Two-pass call graph resolver: name registry + edge resolution.

Law V compliant: zero language-specific logic. All language rules live in .scm files.
Name-based lookup only — no import semantics or language-specific heuristics.
"""

from __future__ import annotations

from cerebrofy.graph.edges import EXTERNAL_CALL, IMPORT_REL, LOCAL_CALL, RUNTIME_BOUNDARY, Edge
from cerebrofy.parser.neuron import Neuron, ParseResult


def build_name_registry(parse_results: list[ParseResult]) -> dict[str, list[Neuron]]:
    """Build a mapping of neuron name → list of Neurons with that name across all files."""
    registry: dict[str, list[Neuron]] = {}
    for pr in parse_results:
        for neuron in pr.neurons:
            registry.setdefault(neuron.name, []).append(neuron)
    return registry


def find_containing_neuron(neurons: list[Neuron], line: int) -> str | None:
    """Return the id of the Neuron whose [line_start, line_end] contains line, or None."""
    for neuron in neurons:
        if neuron.line_start <= line <= neuron.line_end:
            return neuron.id
    return None


def resolve_local_edges(parse_result: ParseResult, name_registry: dict[str, list[Neuron]]) -> list[Edge]:
    """Resolve intra-file call edges (LOCAL_CALL) for one ParseResult."""
    edges: list[Edge] = []
    for capture in parse_result.raw_captures:
        if "call" not in capture.capture_name:
            continue
        callee_name = capture.text.split("(")[0].strip()
        caller_id = find_containing_neuron(parse_result.neurons, capture.line)
        if caller_id is None:
            continue
        matches = name_registry.get(callee_name, [])
        for match in matches:
            if match.file == parse_result.file:
                edges.append(Edge(
                    src_id=caller_id,
                    dst_id=match.id,
                    rel_type=LOCAL_CALL,
                    file=parse_result.file,
                ))
                break  # first match in same file is sufficient
    return edges


def resolve_cross_module_edges(parse_result: ParseResult, name_registry: dict[str, list[Neuron]]) -> list[Edge]:
    """Resolve cross-file call edges (EXTERNAL_CALL or RUNTIME_BOUNDARY) for one ParseResult."""
    edges: list[Edge] = []
    for capture in parse_result.raw_captures:
        if "call" not in capture.capture_name:
            continue
        callee_name = capture.text.split("(")[0].strip()
        caller_id = find_containing_neuron(parse_result.neurons, capture.line)
        if caller_id is None:
            continue
        matches = name_registry.get(callee_name, [])
        external_matches = [m for m in matches if m.file != parse_result.file]
        if external_matches:
            edges.append(Edge(
                src_id=caller_id,
                dst_id=external_matches[0].id,
                rel_type=EXTERNAL_CALL,
                file=parse_result.file,
            ))
        elif not matches:
            # Not found anywhere — synthetic external node
            dst_id = f"external::{callee_name}"
            edges.append(Edge(
                src_id=caller_id,
                dst_id=dst_id,
                rel_type=RUNTIME_BOUNDARY,
                file=parse_result.file,
            ))
    return edges


def resolve_import_edges(parse_result: ParseResult, name_registry: dict[str, list[Neuron]]) -> list[Edge]:
    """Resolve import-statement edges (IMPORT) for one ParseResult."""
    edges: list[Edge] = []

    # Find the module-level Neuron for this file (type == "module") to use as src_id
    module_neuron_id: str | None = None
    for neuron in parse_result.neurons:
        if neuron.type == "module":
            module_neuron_id = neuron.id
            break
    if module_neuron_id is None:
        return edges

    for capture in parse_result.raw_captures:
        if "import" not in capture.capture_name:
            continue
        # Extract the last token after "import" keyword as the imported name
        parts = capture.text.split("import")
        if len(parts) < 2:
            continue
        imported_name = parts[-1].strip().split()[0] if parts[-1].strip() else ""
        if not imported_name:
            continue
        matches = name_registry.get(imported_name, [])
        for match in matches:
            if match.file != parse_result.file:
                edges.append(Edge(
                    src_id=module_neuron_id,
                    dst_id=match.id,
                    rel_type=IMPORT_REL,
                    file=parse_result.file,
                ))
                break
    return edges
