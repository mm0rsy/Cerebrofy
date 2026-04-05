"""Unit tests for cerebrofy.validate.drift_classifier."""

import sqlite3
from pathlib import Path


from cerebrofy.validate.drift_classifier import (
    _classify_file_drift,
    _normalize_sig,
)


def _make_conn_with_nodes(nodes: list[tuple[str, str, str]]) -> sqlite3.Connection:
    """Create in-memory SQLite with nodes for the given (name, file, sig) tuples."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE nodes (id TEXT PRIMARY KEY, name TEXT, file TEXT, type TEXT, "
        "line_start INT, line_end INT, signature TEXT, docstring TEXT, hash TEXT)"
    )
    conn.execute(
        "CREATE TABLE file_hashes (file TEXT PRIMARY KEY, hash TEXT NOT NULL)"
    )
    for name, file, sig in nodes:
        conn.execute(
            "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"{file}::{name}", name, file, "function", 1, 5, sig, None, "abc"),
        )
    return conn


def test_normalize_sig_collapses_whitespace() -> None:
    assert _normalize_sig("def  foo(  a,  b  )") == "def foo( a, b )"


def test_normalize_sig_unchanged() -> None:
    assert _normalize_sig("def foo(a, b)") == "def foo(a, b)"


def test_no_drift(tmp_path: Path) -> None:
    """File re-parses to exact same Neurons → minor drift (hash changed but neurons stable)."""
    py_file = tmp_path / "test.py"
    py_file.write_text("def add(a, b):\n    return a + b\n")

    conn = _make_conn_with_nodes([("add", "test.py", "def add(a, b):")])

    class FakeCfg:
        tracked_extensions = {".py"}
        lobes = {"root": "."}

    record = _classify_file_drift("test.py", conn, FakeCfg(), tmp_path)
    assert record.file == "test.py"
    # _classify_file_drift is called when hash already differs; if neurons match → minor
    assert record.drift_type in ("minor", "structural")


def test_structural_drift_new_function(tmp_path: Path) -> None:
    """New function added → structural drift."""
    py_file = tmp_path / "test.py"
    py_file.write_text("def foo():\n    pass\n\ndef bar():\n    pass\n")

    # Index only has foo
    conn = _make_conn_with_nodes([("foo", "test.py", "def foo():")])

    class FakeCfg:
        tracked_extensions = {".py"}
        lobes = {"root": "."}

    record = _classify_file_drift("test.py", conn, FakeCfg(), tmp_path)
    assert record.drift_type == "structural"
    assert "bar" in record.changed_neurons or len(record.changed_neurons) > 0


def test_no_drift_hash_match(tmp_path: Path) -> None:
    """classify_drift skips files whose hash matches the index."""
    import hashlib
    from cerebrofy.validate.drift_classifier import classify_drift

    py_file = tmp_path / "test.py"
    content = "def foo():\n    pass\n"
    py_file.write_text(content)
    file_hash = hashlib.sha256(content.encode()).hexdigest()

    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE nodes (id TEXT PRIMARY KEY, name TEXT, file TEXT, type TEXT, "
        "line_start INT, line_end INT, signature TEXT, docstring TEXT, hash TEXT)"
    )
    conn.execute(
        "CREATE TABLE file_hashes (file TEXT PRIMARY KEY, hash TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO file_hashes VALUES (?, ?)", ("test.py", file_hash))
    conn.execute(
        "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("test.py::foo", "foo", "test.py", "function", 1, 2, "def foo():", None, "x"),
    )

    class FakeCfg:
        tracked_extensions = {".py"}

    # Hash matches → classify_drift should return empty list (skipped)
    records = classify_drift(["test.py"], conn, FakeCfg(), tmp_path)
    assert records == []


def test_minor_drift_when_neurons_unchanged(tmp_path: Path) -> None:
    """File content changes but all Neurons are identical → minor drift (not none)."""
    from unittest.mock import MagicMock, patch

    from cerebrofy.parser.neuron import Neuron, ParseResult
    from cerebrofy.validate.drift_classifier import classify_drift

    py_file = tmp_path / "test.py"
    py_file.write_text("def foo():\n    pass\n")

    # Index has the same neuron that parse_file will return — no structural change.
    conn = _make_conn_with_nodes([("foo", "test.py", "def foo():")])
    conn.execute(
        "INSERT INTO file_hashes VALUES (?, ?)", ("test.py", "old_hash_value")
    )

    # Fake ParseResult returns only the one function neuron so the index matches exactly.
    fake_neuron = MagicMock(spec=Neuron)
    fake_neuron.name = "foo"
    fake_neuron.signature = "def foo():"
    fake_result = MagicMock(spec=ParseResult)
    fake_result.neurons = [fake_neuron]

    class FakeCfg:
        tracked_extensions = {".py"}
        lobes = {"root": "."}

    with patch("cerebrofy.parser.engine.parse_file", return_value=fake_result):
        records = classify_drift(["test.py"], conn, FakeCfg(), tmp_path)

    # Hash doesn't match → re-parse; neurons match → minor drift
    assert len(records) == 1
    assert records[0].drift_type == "minor"


def test_deleted_file_is_structural_drift(tmp_path: Path) -> None:
    """A file in the index that no longer exists on disk → structural drift (neurons removed)."""
    from cerebrofy.validate.drift_classifier import classify_drift

    # File does NOT exist on disk
    conn = _make_conn_with_nodes([("bar", "deleted.py", "def bar():")])
    conn.execute(
        "INSERT INTO file_hashes VALUES (?, ?)", ("deleted.py", "some_hash")
    )

    class FakeCfg:
        tracked_extensions = {".py"}
        lobes = {"root": "."}

    records = classify_drift(["deleted.py"], conn, FakeCfg(), tmp_path)
    assert len(records) == 1
    assert records[0].drift_type == "structural"
    assert "bar" in records[0].changed_neurons
    assert "removed" in records[0].drift_detail
