"""Unit tests for cerebrofy.changelog.generator + formatter wiring."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cerebrofy.changelog.generator import (
    ChangelogEntry,
    ChangelogReport,
    build_entries,
    generate_changelog,
    write_narrative_events,
    _audience_text,
    _entry_title,
    _health_delta,
    _load_memories,
)
from cerebrofy.changelog.classifier import (
    BREAKING,
    FEAT,
    FIX,
    INTERNAL,
    PERF,
    REFACTOR,
    SECURITY,
    ChangelogError,
    ClassifiedChange,
    NeuronChange,
    ResolvedRange,
)
from cerebrofy.memory.store import Memory
from cerebrofy.update.change_detector import ChangeSet, FileChange
from cerebrofy.validate.drift_classifier import DriftRecord, NeuronDrift

_NODES_DDL = (
    "CREATE TABLE nodes (id TEXT PRIMARY KEY, name TEXT, file TEXT, type TEXT, "
    "line_start INT, line_end INT, signature TEXT, docstring TEXT, hash TEXT)"
)
_EDGES_DDL = (
    "CREATE TABLE edges (src_id TEXT, dst_id TEXT, rel_type TEXT, file TEXT, "
    "PRIMARY KEY (src_id, dst_id, rel_type))"
)


def _fixture_conn() -> sqlite3.Connection:
    """Graph mirroring the classifier fixture: validate_token (5 callers) + fmt.

    All caller nodes are present in `nodes` so `bfs_callers` can resolve them.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(_NODES_DDL)
    conn.execute(_EDGES_DDL)
    conn.execute("CREATE TABLE file_hashes (file TEXT PRIMARY KEY, hash TEXT NOT NULL)")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "CREATE TABLE health_snapshots (id INTEGER PRIMARY KEY, build_ts INTEGER, "
        "commit_hash TEXT, coupling REAL, avg_blast REAL)"
    )
    conn.executemany(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("src/auth/tokens.py::validate_token", "validate_token", "src/auth/tokens.py",
             "function", 10, 20, "def validate_token(strict=False):", None, "h1"),
            ("src/auth/tokens.py::login_handler", "login_handler", "src/auth/tokens.py",
             "function", 30, 40, "def login_handler():", None, "h2"),
            ("src/payment/process.py::charge_card", "charge_card", "src/payment/process.py",
             "function", 5, 15, "def charge_card():", None, "h3"),
            ("src/payment/process.py::refund", "refund", "src/payment/process.py",
             "function", 20, 30, "def refund():", None, "h4"),
            ("src/api/views.py::route_guard", "route_guard", "src/api/views.py",
             "function", 1, 8, "def route_guard():", None, "h5"),
            ("src/api/views.py::public_endpoint", "public_endpoint", "src/api/views.py",
             "function", 50, 60, "def public_endpoint():", None, "h6"),
            ("src/utils/helpers.py::fmt", "fmt", "src/utils/helpers.py",
             "function", 1, 9, "def fmt():", None, "h7"),
        ],
    )
    conn.executemany(
        "INSERT INTO edges VALUES (?,?,?,?)",
        [
            ("src/api/views.py::route_guard", "src/auth/tokens.py::validate_token",
             "LOCAL_CALL", "src/api/views.py"),
            ("src/auth/tokens.py::login_handler", "src/auth/tokens.py::validate_token",
             "LOCAL_CALL", "src/auth/tokens.py"),
            ("src/payment/process.py::charge_card", "src/auth/tokens.py::validate_token",
             "LOCAL_CALL", "src/payment/process.py"),
            ("src/payment/process.py::refund", "src/auth/tokens.py::validate_token",
             "LOCAL_CALL", "src/payment/process.py"),
            ("src/api/views.py::public_endpoint", "src/auth/tokens.py::validate_token",
             "LOCAL_CALL", "src/api/views.py"),
        ],
    )
    conn.executemany("INSERT INTO health_snapshots VALUES (?,?,?,?,?)", [
        (1, 1, "aaa", 0.2, 3.0),
        (2, 2, "bbb", 0.5, 5.0),
    ])
    conn.execute("INSERT INTO meta VALUES (?,?)", ("schema_version", "1"))
    conn.commit()
    return conn


def _make_config(tmp_path: Path) -> None:
    """Write a valid lobes config so collect_changes maps cross-lobe callers."""
    cfg = tmp_path / ".cerebrofy" / "config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(
        "lobes:\n"
        "  auth: src/auth\n"
        "  payment: src/payment\n"
        "  api: src/api\n"
        "  utils: src/utils\n"
        "tracked_extensions: [.py]\n"
        "embedding_model: local\n",
        encoding="utf-8",
    )


def _patched_collect(monkeypatch) -> None:
    """Monkeypatch collect_changes' three collaborators deterministically."""
    monkeypatch.setattr(
        "cerebrofy.changelog.classifier.resolve_range",
        lambda repo, since, conn: ResolvedRange(since_label="v1.0.0", since_ref="aaa", until_ref="bbb"),
    )
    monkeypatch.setattr(
        "cerebrofy.changelog.classifier.detect_changes_between_refs",
        lambda repo, since_ref, until_ref="HEAD": ChangeSet(
            changes=(
                FileChange("src/auth/tokens.py", "M"),
                FileChange("src/utils/helpers.py", "M"),
            ),
            detected_via="git",
        ),
    )
    monkeypatch.setattr(
        "cerebrofy.validate.drift_classifier.classify_drift",
        lambda files, conn, config, repo_root: [
            DriftRecord(
                file="src/auth/tokens.py", drift_type="structural",
                changed_neurons=("validate_token", "new_guard"), drift_detail="sig+add",
                neuron_details=(
                    NeuronDrift(name="validate_token", kind="signature_changed",
                                neuron_type="function"),
                    NeuronDrift(name="new_guard", kind="added", neuron_type="function"),
                ),
            ),
            DriftRecord(
                file="src/utils/helpers.py", drift_type="structural",
                changed_neurons=("fmt",), drift_detail="mod",
                neuron_details=(NeuronDrift(name="fmt", kind="modified", neuron_type="function"),),
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Pure generator helpers
# ---------------------------------------------------------------------------


def test_entry_titles_per_type() -> None:
    ch = NeuronChange("f::n", "n", "f", "lobe", "added")
    for t, expected in [
        (FEAT, "Added n"), (FIX, "Fixed n"), (REFACTOR, "Refactored n"),
        (INTERNAL, "Changed n"),
    ]:
        assert _entry_title(t, (ch,)) == expected
    assert _entry_title(SECURITY, (ch,)) == "Patched security issue in n"
    assert _entry_title(BREAKING, (ch,)) == "BREAKING: n changed"
    assert _entry_title(PERF, (ch,)) == "Improved performance of n"


def test_audience_text_developer_pm_user() -> None:
    change = NeuronChange("f::n", "n", "f", "auth", "added")
    cc = ClassifiedChange(
        entry_type=FEAT, neurons=(change,), direct_callers=2, cross_lobe_callers=1,
        blast_radius=2, is_breaking=False, public_surface=True, memories=(),
    )
    assert "n" in _audience_text(cc, "developer", {})
    assert "auth" in _audience_text(cc, "pm", {})
    assert _audience_text(cc, "user", {})  # user text non-empty for feat


def test_build_entries_orders_breaking_first_and_filters_audience() -> None:
    internal = ClassifiedChange(
        entry_type=INTERNAL, neurons=(NeuronChange("f::b", "b", "f", "x", "modified"),),
        direct_callers=0, cross_lobe_callers=0, blast_radius=0, is_breaking=False,
        public_surface=False, memories=(),
    )
    breaking = ClassifiedChange(
        entry_type=BREAKING, neurons=(NeuronChange("f::a", "a", "f", "x", "signature_changed"),),
        direct_callers=2, cross_lobe_callers=3, blast_radius=2, is_breaking=True,
        public_surface=True, memories=(),
    )
    entries = build_entries([internal, breaking], "developer", {})
    assert entries[0].type == BREAKING
    assert [e.type for e in entries] == [BREAKING, INTERNAL]


def test_build_entries_excludes_internal_for_pm_and_user() -> None:
    internal = ClassifiedChange(
        entry_type=INTERNAL, neurons=(NeuronChange("f::b", "b", "f", "x", "modified"),),
        direct_callers=0, cross_lobe_callers=0, blast_radius=0, is_breaking=False,
        public_surface=False, memories=(),
    )
    for audience in ("pm", "user"):
        entries = build_entries([internal], audience, {})
        # internal entries still appear but their audience_text is empty → filtered by formatter
        assert all(e.audience_text == "" for e in entries)


def test_load_memories_degrades_when_absent(tmp_path: Path) -> None:
    assert _load_memories(tmp_path) == {}


def test_health_delta_zero_when_insufficient_snapshots() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE health_snapshots (build_ts INTEGER, coupling REAL, avg_blast REAL)")
    assert _health_delta(conn) == {"coupling": 0.0, "avg_blast": 0.0}


def test_health_delta_computes_delta() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE health_snapshots (build_ts INTEGER, coupling REAL, avg_blast REAL)")
    conn.executemany(
        "INSERT INTO health_snapshots VALUES (?,?,?)",
        [(1, 0.2, 3.0), (2, 0.5, 5.0)],
    )
    delta = _health_delta(conn)
    assert delta == {"coupling": 0.3, "avg_blast": 2.0}


# ---------------------------------------------------------------------------
# generate_changelog end-to-end (git/parse mocked; real graph db)
# ---------------------------------------------------------------------------


def test_generate_changelog_end_to_end(monkeypatch, tmp_path: Path) -> None:
    conn = _fixture_conn()
    _make_config(tmp_path)
    _patched_collect(monkeypatch)
    monkeypatch.setattr(
        "cerebrofy.changelog.generator._load_memories",
        lambda d: {"src/utils/helpers.py::fmt": [
            Memory(id="m", neuron_id="src/utils/helpers.py::fmt", lobe="src/utils",
                   type="warning", title="fmt rounded wrong", body="CVE-2024-xx rounding",
                   author="a", created_ts=1, tags=("security",), decay_score=1.0,
                   status="active")
        ]},
    )
    report = generate_changelog(tmp_path, "v1.0.0", audience="developer", output_format="markdown", conn=conn)

    # Spec output schema (exact keys)
    data = report.to_dict()
    assert set(data) == {"since", "until", "entries", "breaking_changes", "health_delta", "full_text"}
    assert report.since == "v1.0.0"
    assert report.until == "bbb"
    assert set(data["entries"][0]) == {"type", "title", "description", "neurons", "blast_radius", "audience_text"}

    by_type = {e.type: e for e in report.entries}
    assert BREAKING in by_type
    assert FEAT in by_type
    assert SECURITY in by_type  # fmt with security memory beats the warning memory (precedence)
    # breaking_changes mirrors the breaking entry
    assert report.breaking_changes[0]["title"] == by_type[BREAKING].title
    # health delta from the two snapshots
    assert report.health_delta == {"coupling": 0.3, "avg_blast": 2.0}
    assert report.full_text  # formatted markdown non-empty


def test_generate_changelog_no_index_raises(tmp_path: Path) -> None:
    with pytest.raises(ChangelogError) as exc_info:
        generate_changelog(tmp_path, "v1.0.0", conn=None)
    assert exc_info.value.code == "NO_INDEX"


def test_generate_changelog_ref_not_found_propagates(monkeypatch, tmp_path: Path) -> None:
    conn = _fixture_conn()
    monkeypatch.setattr(
        "cerebrofy.changelog.classifier.resolve_range",
        lambda repo, since, conn_: (_ for _ in ()).throw(
            ChangelogError("REF_NOT_FOUND", "nope")
        ),
    )
    with pytest.raises(ChangelogError) as exc_info:
        generate_changelog(tmp_path, "nope", conn=conn)
    assert exc_info.value.code == "REF_NOT_FOUND"


def test_generate_changelog_invalid_audience(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        generate_changelog(tmp_path, "v1.0.0", audience="boardroom", conn=sqlite3.connect(":memory:"))


def test_generate_changelog_invalid_format(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        generate_changelog(tmp_path, "v1.0.0", output_format="rst", conn=sqlite3.connect(":memory:"))


def test_generate_changelog_three_formats_render(monkeypatch, tmp_path: Path) -> None:
    conn = _fixture_conn()
    _make_config(tmp_path)
    _patched_collect(monkeypatch)
    monkeypatch.setattr("cerebrofy.changelog.generator._load_memories", lambda d: {})
    for fmt in ("markdown", "github", "slack"):
        report = generate_changelog(tmp_path, "v1.0.0", output_format=fmt, conn=conn)
        assert report.format == fmt
        assert report.full_text


def test_generate_changelog_github_contains_release_header(monkeypatch, tmp_path: Path) -> None:
    conn = _fixture_conn()
    _make_config(tmp_path)
    _patched_collect(monkeypatch)
    monkeypatch.setattr("cerebrofy.changelog.generator._load_memories", lambda d: {})
    report = generate_changelog(tmp_path, "v1.0.0", output_format="github", conn=conn)
    assert "What's Changed" in report.full_text


def test_generate_changelog_slack_bolds_headers(monkeypatch, tmp_path: Path) -> None:
    conn = _fixture_conn()
    _make_config(tmp_path)
    _patched_collect(monkeypatch)
    monkeypatch.setattr("cerebrofy.changelog.generator._load_memories", lambda d: {})
    report = generate_changelog(tmp_path, "v1.0.0", output_format="slack", conn=conn)
    assert report.full_text.startswith("*📦 Release")


# ---------------------------------------------------------------------------
# narrative events idempotency
# ---------------------------------------------------------------------------


def test_write_narrative_events_idempotent(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(_NODES_DDL)
    conn.execute(
        "CREATE TABLE health_snapshots (id INTEGER PRIMARY KEY, build_ts INTEGER, "
        "commit_hash TEXT, coupling REAL, avg_blast REAL)"
    )
    conn.executemany("INSERT INTO health_snapshots VALUES (?,?,?,?,?)", [(1, 1, "a", 0.1, 1.0), (2, 2, "b", 0.2, 2.0)])

    report = ChangelogReport(
        since="v1.0.0", until="bbb",
        entries=(
            ChangelogEntry(type=FEAT, title="Added foo", description="d", neurons=("n1",),
                           blast_radius=0, audience_text="**foo**: Added foo.", lobes=(), memory_notes=()),
            ChangelogEntry(type=INTERNAL, title="Changed bar", description="d2", neurons=("n2",),
                           blast_radius=1, audience_text="**bar**: Changed bar.", lobes=("src",), memory_notes=()),
        ),
        breaking_changes=(), health_delta={"coupling": 0.0, "avg_blast": 0.0},
        full_text="", audience="developer", format="markdown",
    )
    n1 = write_narrative_events(conn, report, repo_root=tmp_path)
    n2 = write_narrative_events(conn, report, repo_root=tmp_path)
    assert n1 == len(report.entries)
    assert n2 == len(report.entries)  # idempotent: replaces, no duplicates
    count = conn.execute("SELECT COUNT(*) FROM narrative_events").fetchone()[0]
    assert count == len(report.entries)
    types = {r[0] for r in conn.execute("SELECT type FROM narrative_events").fetchall()}
    assert types == {FEAT, INTERNAL}


def test_narrative_events_schema_columns(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    from cerebrofy.db.schema import ensure_narrative_schema
    ensure_narrative_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(narrative_events)").fetchall()}
    assert cols == {
        "id", "ts", "commit_ref", "type", "title", "body", "lobes_affected",
        "blast_radius_delta", "health_delta",
    }
    # idempotent re-create
    ensure_narrative_schema(conn)
