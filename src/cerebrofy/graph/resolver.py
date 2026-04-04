"""Two-pass call graph resolver: name registry + edge resolution.

Law V compliant: zero language-specific logic. All language rules live in .scm files.
Name-based lookup only — no import semantics or language-specific heuristics.
"""

from __future__ import annotations

from cerebrofy.graph.edges import EXTERNAL_CALL, IMPORT_REL, LOCAL_CALL, RUNTIME_BOUNDARY, Edge


def build_name_registry(parse_results: list) -> dict[str, list]:  # type: ignore[type-arg]
    """Build a mapping of neuron name → list of Neurons with that name across all files."""
    registry: dict[str, list] = {}  # type: ignore[type-arg]
    for pr in parse_results:
        for neuron in pr.neurons:
            registry.setdefault(neuron.name, []).append(neuron)
    return registry


def find_containing_neuron(neurons: list, line: int) -> str | None:  # type: ignore[type-arg]
    """Return the id of the Neuron whose [line_start, line_end] contains line, or None."""
    for neuron in neurons:
        if neuron.line_start <= line <= neuron.line_end:
            return neuron.id  # type: ignore[no-any-return]
    return None


def resolve_local_edges(parse_result: object, name_registry: dict) -> list:  # type: ignore[type-arg]
    """Resolve intra-file call edges (LOCAL_CALL) for one ParseResult."""
    edges: list[Edge] = []
    for capture in parse_result.raw_captures:  # type: ignore[union-attr]
        if "call" not in capture.capture_name:
            continue
        callee_name = capture.text.split("(")[0].strip()
        caller_id = find_containing_neuron(parse_result.neurons, capture.line)  # type: ignore[union-attr]
        if caller_id is None:
            continue
        matches = name_registry.get(callee_name, [])
        for match in matches:
            if match.file == parse_result.file:  # type: ignore[union-attr]
                edges.append(Edge(
                    src_id=caller_id,
                    dst_id=match.id,
                    rel_type=LOCAL_CALL,
                    file=parse_result.file,  # type: ignore[union-attr]
                ))
                break  # first match in same file is sufficient
    return edges


def resolve_cross_module_edges(parse_result: object, name_registry: dict) -> list:  # type: ignore[type-arg]
    """Resolve cross-file call edges (EXTERNAL_CALL or RUNTIME_BOUNDARY) for one ParseResult."""
    edges: list[Edge] = []
    for capture in parse_result.raw_captures:  # type: ignore[union-attr]
        if "call" not in capture.capture_name:
            continue
        callee_name = capture.text.split("(")[0].strip()
        caller_id = find_containing_neuron(parse_result.neurons, capture.line)  # type: ignore[union-attr]
        if caller_id is None:
            continue
        matches = name_registry.get(callee_name, [])
        external_matches = [m for m in matches if m.file != parse_result.file]  # type: ignore[union-attr]
        if external_matches:
            edges.append(Edge(
                src_id=caller_id,
                dst_id=external_matches[0].id,
                rel_type=EXTERNAL_CALL,
                file=parse_result.file,  # type: ignore[union-attr]
            ))
        elif not matches:
            # Not found anywhere — synthetic external node
            dst_id = f"external::{callee_name}"
            edges.append(Edge(
                src_id=caller_id,
                dst_id=dst_id,
                rel_type=RUNTIME_BOUNDARY,
                file=parse_result.file,  # type: ignore[union-attr]
            ))
    return edges


def resolve_import_edges(parse_result: object, name_registry: dict) -> list:  # type: ignore[type-arg]
    """Resolve import-statement edges (IMPORT) for one ParseResult."""
    edges: list[Edge] = []

    # Find the module-level Neuron for this file (type == "module") to use as src_id
    module_neuron_id: str | None = None
    for neuron in parse_result.neurons:  # type: ignore[union-attr]
        if neuron.type == "module":
            module_neuron_id = neuron.id
            break
    if module_neuron_id is None:
        return edges

    for capture in parse_result.raw_captures:  # type: ignore[union-attr]
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
            if match.file != parse_result.file:  # type: ignore[union-attr]
                edges.append(Edge(
                    src_id=module_neuron_id,
                    dst_id=match.id,
                    rel_type=IMPORT_REL,
                    file=parse_result.file,  # type: ignore[union-attr]
                ))
                break
    return edges
