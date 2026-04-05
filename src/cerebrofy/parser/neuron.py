"""Neuron dataclass and ParseResult — the fundamental output unit of the Universal Parser."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Neuron:
    """A single named code unit extracted from a source file."""

    id: str
    name: str
    type: str  # "function" | "class" | "module"
    file: str
    line_start: int
    line_end: int
    signature: str | None = None
    docstring: str | None = None


@dataclass(frozen=True)
class ParseResult:
    """Output of a single parser run on one source file."""

    file: str
    neurons: list[Neuron] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def deduplicate_neurons(neurons: list[Neuron]) -> list[Neuron]:
    """Return a new list keeping only the first Neuron per id, ordered by line_start."""
    sorted_neurons = sorted(neurons, key=lambda n: n.line_start)
    seen: dict[str, Neuron] = {}
    for neuron in sorted_neurons:
        if neuron.id not in seen:
            seen[neuron.id] = neuron
    return list(seen.values())
