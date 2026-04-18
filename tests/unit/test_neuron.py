"""Unit tests for cerebrofy.parser.neuron."""

from __future__ import annotations

from cerebrofy.parser.neuron import (
    Neuron,
    ParseResult,
    RawCapture,
    deduplicate_neurons,
)


def _make_neuron(
    name: str,
    file: str = "f.py",
    line_start: int = 1,
    line_end: int = 10,
) -> Neuron:
    return Neuron(
        id=f"{file}::{name}",
        name=name,
        type="function",
        file=file,
        line_start=line_start,
        line_end=line_end,
        signature=f"def {name}():",
    )


# ---------------------------------------------------------------------------
# Neuron dataclass
# ---------------------------------------------------------------------------


def test_neuron_is_hashable() -> None:
    n = _make_neuron("foo")
    assert hash(n) is not None


def test_neuron_equality_by_value() -> None:
    n1 = _make_neuron("foo")
    n2 = _make_neuron("foo")
    assert n1 == n2


def test_neuron_inequality_different_name() -> None:
    assert _make_neuron("foo") != _make_neuron("bar")


def test_neuron_optional_fields_default_none() -> None:
    n = Neuron(id="f.py::fn", name="fn", type="function", file="f.py", line_start=1, line_end=2)
    assert n.signature is None
    assert n.docstring is None


def test_neuron_frozen_cannot_be_mutated() -> None:
    import pytest
    n = _make_neuron("foo")
    with pytest.raises(Exception):
        n.name = "bar"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ParseResult dataclass
# ---------------------------------------------------------------------------


def test_parse_result_defaults_to_empty_lists() -> None:
    pr = ParseResult(file="f.py")
    assert pr.neurons == []
    assert pr.warnings == []
    assert pr.raw_captures == ()


def test_parse_result_with_neurons() -> None:
    n = _make_neuron("foo")
    pr = ParseResult(file="f.py", neurons=[n])
    assert len(pr.neurons) == 1
    assert pr.neurons[0].name == "foo"


# ---------------------------------------------------------------------------
# RawCapture
# ---------------------------------------------------------------------------


def test_raw_capture_is_frozen() -> None:
    import pytest
    rc = RawCapture(capture_name="call", text="foo()", file="f.py", line=5)
    with pytest.raises(Exception):
        rc.text = "bar()"  # type: ignore[misc]


def test_raw_capture_equality() -> None:
    rc1 = RawCapture(capture_name="call", text="foo()", file="f.py", line=5)
    rc2 = RawCapture(capture_name="call", text="foo()", file="f.py", line=5)
    assert rc1 == rc2


# ---------------------------------------------------------------------------
# deduplicate_neurons
# ---------------------------------------------------------------------------


def test_deduplicate_neurons_keeps_first_by_line() -> None:
    n1 = _make_neuron("foo", line_start=1)
    n2 = Neuron(id="f.py::foo", name="foo", type="class", file="f.py", line_start=10, line_end=20)
    result = deduplicate_neurons([n2, n1])
    assert len(result) == 1
    # n1 has line_start=1, so it comes first after sort
    assert result[0].line_start == 1


def test_deduplicate_neurons_unique_ids_kept() -> None:
    neurons = [_make_neuron("a"), _make_neuron("b"), _make_neuron("c")]
    result = deduplicate_neurons(neurons)
    assert len(result) == 3


def test_deduplicate_neurons_empty_list() -> None:
    assert deduplicate_neurons([]) == []


def test_deduplicate_neurons_ordered_by_line_start() -> None:
    n1 = _make_neuron("z", line_start=50)
    n2 = _make_neuron("a", line_start=1)
    n3 = _make_neuron("m", line_start=25)
    result = deduplicate_neurons([n1, n2, n3])
    assert [r.line_start for r in result] == [1, 25, 50]
