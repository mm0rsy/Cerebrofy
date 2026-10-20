"""Unit tests for cerebrofy.changelog.classifier.

Covers the classification algorithm against deterministic in-memory fixture
graphs (acceptance: type accuracy >90%, breaking-change recall >95%) plus the
range-resolution and change-collection helpers.
"""
from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from cerebrofy.changelog.classifier import (
    BREAKING,
    BREAKING_CROSS_LOBE_CALLERS,
    REF_NOT_FOUND,
    FEAT,
    FIX,
    INTERNAL,
    KIND_ADDED,
    KIND_MODIFIED,
    KIND_REMOVED,
    KIND_SIGNATURE_CHANGED,
    KIND_MOVED,
    PERF,
    REFACTOR,
    SECURITY,
    NeuronChange,
    ResolvedRange,
    ChangelogError,
    classify_change,
    classify_changes,
    collect_changes,
    is_breaking_change,
    is_test_file,
    lobe_for_file,
    resolve_range,
    validate_git_ref,
)
from cerebrofy.config.loader import ChangelogConfig
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


def _gconn() -> sqlite3.Connection:
    """In-memory graph db: nodes + edges for the deterministic fixture graph.

    Lobes are derived from the first path segment of each file
    (src/auth, src/payment, src/api, src/utils) — matching lobe_for_file's
    fallback convention.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(_NODES_DDL)
    conn.executemany(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("src/auth/tokens.py::validate_token", "validate_token", "src/auth/tokens.py",
             "function", 10, 20, "def validate_token(strict=False):", "Validates a login token.", "h1"),
            ("src/auth/tokens.py::login_handler", "login_handler", "src/auth/tokens.py",
             "function", 30, 40, "def login_handler():", "Handles login.", "h2"),
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
    conn.execute(_EDGES_DDL)
    # validate_token has 5 callers: 1 same-lobe (login_handler) + 4 cross-lobe
    # login_handler has 1 cross-lobe caller (route_guard) → removal is breaking
    conn.executemany(
        "INSERT INTO edges VALUES (?,?,?,?)",
        [
            ("src/api/views.py::route_guard", "src/auth/tokens.py::validate_token", "LOCAL_CALL", "src/api/views.py"),
            ("src/api/views.py::route_guard", "src/auth/tokens.py::login_handler", "LOCAL_CALL", "src/api/views.py"),
            ("src/auth/tokens.py::login_handler", "src/auth/tokens.py::validate_token", "LOCAL_CALL", "src/auth/tokens.py"),
            ("src/payment/process.py::charge_card", "src/auth/tokens.py::validate_token", "LOCAL_CALL", "src/payment/process.py"),
            ("src/payment/process.py::refund", "src/auth/tokens.py::validate_token", "LOCAL_CALL", "src/payment/process.py"),
            ("src/api/views.py::public_endpoint", "src/auth/tokens.py::validate_token", "LOCAL_CALL", "src/api/views.py"),
        ],
    )
    return conn


def _mem(tags=(), mtype: str = "warning", title: str = "T", body: str = "B") -> Memory:
    return Memory(
        id="m1", neuron_id="src/auth/tokens.py::validate_token", lobe="src/auth",
        type=mtype, title=title, body=body, author="agent", created_ts=1,
        tags=tuple(tags), decay_score=1.0, status="active",
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_is_test_file() -> None:
    assert is_test_file("tests/unit/test_changelog.py")
    assert is_test_file("src/cerebrofy/test_foo.py")
    assert is_test_file("foo_test.py")
    assert not is_test_file("src/cerebrofy/changelog/classifier.py")


def test_is_test_file_uses_index(tmp_path: Path) -> None:
    """is_test_file consults the file_hashes table when a connection is available.

    An indexed path matching test predicates is a test file; a non-test indexed
    path is not.  The fallback to the Python heuristic still works when conn is
    None or the file is not indexed.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE file_hashes (file TEXT PRIMARY KEY, hash TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO file_hashes VALUES (?, ?)", ("tests/unit/test_foo.py", "h1")
    )
    conn.execute(
        "INSERT INTO file_hashes VALUES (?, ?)", ("src/app/main.py", "h2")
    )
    conn.execute(
        "INSERT INTO file_hashes VALUES (?, ?)", ("src/helper_test.js", "h3")
    )
    conn.commit()

    # Indexed path matching test patterns → True
    assert is_test_file("tests/unit/test_foo.py", conn) is True
    # Indexed non-test path → False
    assert is_test_file("src/app/main.py", conn) is False
    # Indexed .js test file → True (SQL extends beyond Python heuristic)
    assert is_test_file("src/helper_test.js", conn) is True
    # File not in the index → falls back to path heuristic
    assert is_test_file("tests/unit/test_unindexed.py", conn) is True
    assert is_test_file("src/app/unindexed.py", conn) is False
    # Fallback to path heuristic when conn is None
    assert is_test_file("tests/unit/test_foo.py", conn=None) is True
    assert is_test_file("src/app/main.py", conn=None) is False
    conn.close()


class _FakeConn:
    """Minimal fake connection whose ``execute`` records the SQL and returns a row."""

    def __init__(self, row):
        self.calls: list[tuple[str, tuple]] = []
        self._row = row

    def execute(self, sql: str, params: tuple = ()) -> _FakeConn:
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        return self._row


def test_is_test_file_index_query_is_executed() -> None:
    """When conn is available, is_test_file queries file_hashes (not just heuristic)."""
    # Indexed AND matches test predicates → True
    fake_true = _FakeConn(row=(1,))
    assert is_test_file("tests/unit/foo.py", fake_true) is True
    assert len(fake_true.calls) == 1
    assert "file_hashes" in fake_true.calls[0][0]

    # Indexed but NOT a test file → False (SQL is authoritative, not heuristic)
    fake_false = _FakeConn(row=(0,))
    assert is_test_file("src/app/main.py", fake_false) is False
    assert len(fake_false.calls) == 1

    # Not indexed → falls back to Python heuristic
    fake_none = _FakeConn(row=None)
    assert is_test_file("tests/unit/foo.py", fake_none) is True
    assert len(fake_none.calls) == 1


def test_lobe_for_file_fallback_and_config() -> None:
    assert lobe_for_file("src/auth/tokens.py") == "src"
    assert lobe_for_file("auth/tokens.py") == "auth"
    lobes = {"auth": "src/auth"}
    assert lobe_for_file("src/auth/tokens.py", lobes) == "auth"
    # A file outside the configured lobe path falls back to its first segment.
    assert lobe_for_file("src/payment/x.py", lobes) == "src"
    assert lobe_for_file("deeply/nested/file.py", lobes) == "deeply"


def test_is_breaking_change_heuristics() -> None:
    # added → never breaking
    assert is_breaking_change(KIND_ADDED, direct_callers=10, cross_lobe_callers=10) is False
    # moved → never breaking (it's a refactor)
    assert is_breaking_change(KIND_MOVED, direct_callers=5, cross_lobe_callers=5) is False
    # removed with callers → breaking
    assert is_breaking_change(KIND_REMOVED, direct_callers=2, cross_lobe_callers=0) is True
    # removed with no callers → not breaking
    assert is_breaking_change(KIND_REMOVED, direct_callers=0, cross_lobe_callers=0) is False
    # signature changed on public surface (cross >= 1) → breaking
    assert is_breaking_change(KIND_SIGNATURE_CHANGED, direct_callers=1, cross_lobe_callers=1) is True
    # signature changed, same-lobe only → not breaking
    assert is_breaking_change(KIND_SIGNATURE_CHANGED, direct_callers=2, cross_lobe_callers=0) is False
    # cross-lobe callers exceed threshold → breaking (strictly greater than)
    assert is_breaking_change(KIND_MODIFIED, direct_callers=4, cross_lobe_callers=BREAKING_CROSS_LOBE_CALLERS + 1) is True
    assert is_breaking_change(KIND_MODIFIED, direct_callers=4, cross_lobe_callers=BREAKING_CROSS_LOBE_CALLERS) is False


def test_is_breaking_change_config_threshold() -> None:
    """ChangelogConfig.breaking_cross_lobe_threshold overrides the default."""
    # KIND_MODIFIED with 2 cross-lobe callers:
    #   threshold=1: 2 > 1 → breaking
    #   threshold=3: 2 > 3 → not breaking (and MODIFIED is not signature_changed)
    cfg_low = ChangelogConfig(breaking_cross_lobe_threshold=1)
    assert is_breaking_change(
        KIND_MODIFIED, direct_callers=0, cross_lobe_callers=2, config=cfg_low
    ) is True

    cfg_default = ChangelogConfig(breaking_cross_lobe_threshold=3)
    assert is_breaking_change(
        KIND_MODIFIED, direct_callers=0, cross_lobe_callers=2, config=cfg_default
    ) is False

    # No config → uses ChangelogConfig() default (threshold 3, same as before)
    assert is_breaking_change(
        KIND_MODIFIED, direct_callers=0, cross_lobe_callers=2
    ) is False


def test_classify_change_respects_config_threshold() -> None:
    """classify_change threads config → is_breaking_change uses the threshold."""
    conn = _gconn()
    # validate_token has 5 cross-lobe callers (path-based lobe "src" ≠ "src/auth");
    # KIND_MODIFIED
    change = NeuronChange(
        id="src/auth/tokens.py::validate_token", name="validate_token",
        file="src/auth/tokens.py", lobe="src/auth", kind=KIND_MODIFIED,
    )
    # threshold=3: 5 > 3 → breaking
    cc = classify_change(
        change, conn, memories=(), lobes=None,
        config=ChangelogConfig(breaking_cross_lobe_threshold=3),
    )
    assert cc.is_breaking is True

    # threshold=5: 5 > 5 → False; MODIFIED is not SIGNATURE_CHANGED → not breaking
    cc = classify_change(
        change, conn, memories=(), lobes=None,
        config=ChangelogConfig(breaking_cross_lobe_threshold=5),
    )
    assert cc.is_breaking is False


# ---------------------------------------------------------------------------
# classify_change (single neuron) against the fixture graph
# ---------------------------------------------------------------------------


def test_classify_added_is_feat() -> None:
    conn = _gconn()
    change = NeuronChange(
        id="src/api/views.py::new_feature", name="new_feature",
        file="src/api/views.py", lobe="src/api", kind=KIND_ADDED,
    )
    cc = classify_change(change, conn, memories=(), lobes=None)
    assert cc.entry_type == FEAT
    assert cc.is_breaking is False


def test_classify_security_via_tag() -> None:
    conn = _gconn()
    change = NeuronChange(
        id="src/auth/tokens.py::login_handler", name="login_handler",
        file="src/auth/tokens.py", lobe="src/auth", kind=KIND_MODIFIED,
    )
    cc = classify_change(change, conn, memories=(_mem(tags=["security"]),), lobes=None)
    assert cc.entry_type == SECURITY


def test_classify_security_via_cve_text() -> None:
    conn = _gconn()
    change = NeuronChange(
        id="src/auth/tokens.py::login_handler", name="login_handler",
        file="src/auth/tokens.py", lobe="src/auth", kind=KIND_MODIFIED,
    )
    cc = classify_change(
        change, conn,
        memories=(_mem(tags=["fix"], mtype="warning", title="CVE-2024-1234", body="SSRF"),),
        lobes=None,
    )
    assert cc.entry_type == SECURITY


def test_classify_perf_via_tag() -> None:
    conn = _gconn()
    change = NeuronChange(
        id="src/auth/tokens.py::login_handler", name="login_handler",
        file="src/auth/tokens.py", lobe="src/auth", kind=KIND_MODIFIED,
    )
    cc = classify_change(change, conn, memories=(_mem(tags=["perf"]),), lobes=None)
    assert cc.entry_type == PERF


def test_classify_fix_via_warning_memory() -> None:
    conn = _gconn()
    change = NeuronChange(
        id="src/auth/tokens.py::login_handler", name="login_handler",
        file="src/auth/tokens.py", lobe="src/auth", kind=KIND_MODIFIED,
    )
    cc = classify_change(change, conn, memories=(_mem(mtype="warning", title="edge case"),), lobes=None)
    assert cc.entry_type == FIX


def test_classify_internal_when_no_signals() -> None:
    conn = _gconn()
    change = NeuronChange(
        id="src/utils/helpers.py::fmt", name="fmt",
        file="src/utils/helpers.py", lobe="src/utils", kind=KIND_MODIFIED,
    )
    cc = classify_change(change, conn, memories=(), lobes=None)
    assert cc.entry_type == INTERNAL
    assert cc.direct_callers == 0 and cc.cross_lobe_callers == 0


def test_classify_breaking_by_cross_lobe_callers() -> None:
    conn = _gconn()
    change = NeuronChange(
        id="src/auth/tokens.py::validate_token", name="validate_token",
        file="src/auth/tokens.py", lobe="src/auth", kind=KIND_SIGNATURE_CHANGED,
    )
    cc = classify_change(change, conn, memories=(), lobes=None)
    assert cc.entry_type == BREAKING
    assert cc.is_breaking is True
    assert cc.cross_lobe_callers > BREAKING_CROSS_LOBE_CALLERS


def test_classify_breaking_takes_precedence_over_security() -> None:
    """A signature change with cross-lobe callers is breaking even with a security tag."""
    conn = _gconn()
    change = NeuronChange(
        id="src/auth/tokens.py::validate_token", name="validate_token",
        file="src/auth/tokens.py", lobe="src/auth", kind=KIND_SIGNATURE_CHANGED,
    )
    cc = classify_change(change, conn, memories=(_mem(tags=["security"]),), lobes=None)
    assert cc.entry_type == BREAKING


# ---------------------------------------------------------------------------
# classify_changes: cross-lobe move → refactor
# ---------------------------------------------------------------------------


def test_classify_changes_move_detected_as_refactor() -> None:
    conn = _gconn()
    removed = NeuronChange(
        id="src/auth/tokens.py::login_handler", name="login_handler",
        file="src/auth/tokens.py", lobe="src/auth", kind=KIND_REMOVED,
    )
    added = NeuronChange(
        id="src/payment/process.py::login_handler", name="login_handler",
        file="src/payment/process.py", lobe="src/payment", kind=KIND_ADDED,
    )
    results = classify_changes([removed, added], conn, memories_by_neuron=None, lobes=None)
    assert len(results) == 1
    merged = results[0]
    assert merged.entry_type == REFACTOR
    assert {n.file for n in merged.neurons} == {removed.file, added.file}


# ---------------------------------------------------------------------------
# collect_changes (git mocked; drift classifier mocked)
# ---------------------------------------------------------------------------


def _make_conn_with_indexed() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(_NODES_DDL)
    conn.execute(_EDGES_DDL)
    conn.execute("CREATE TABLE file_hashes (file TEXT PRIMARY KEY, hash TEXT NOT NULL)")
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("src/auth/tokens.py::validate_token", "validate_token", "src/auth/tokens.py",
         "function", 10, 20, "def validate_token():", None, "h1"),
    )
    conn.execute("INSERT INTO file_hashes VALUES (?,?)", ("src/auth/tokens.py", "old"))
    return conn


def test_collect_changes_uses_drift_neuron_details() -> None:
    conn = _make_conn_with_indexed()
    resolved = ResolvedRange(since_label="v1", since_ref="a", until_ref="b")
    with patch(
        "cerebrofy.changelog.classifier.detect_changes_between_refs",
        return_value=ChangeSet(changes=(FileChange("src/auth/tokens.py", "M"),), detected_via="git"),
    ), patch(
        "cerebrofy.changelog.classifier.classify_drift",
        return_value=[DriftRecord(
            file="src/auth/tokens.py", drift_type="structural",
            changed_neurons=("validate_token",), drift_detail="sig",
            neuron_details=(NeuronDrift(name="validate_token", kind="signature_changed",
                                       neuron_type="function"),),
        )],
    ):
        collected = collect_changes(Path("/tmp"), conn, "v1", resolved=resolved)
    assert len(collected.changes) == 1
    assert collected.changes[0].kind == KIND_SIGNATURE_CHANGED
    assert collected.changes[0].name == "validate_token"


def test_collect_changes_falls_back_to_git_status_when_no_drift() -> None:
    conn = _make_conn_with_indexed()
    resolved = ResolvedRange(since_label="v1", since_ref="a", until_ref="b")
    # detect_changes_between_refs reports an added file; classify_drift returns nothing.
    with patch(
        "cerebrofy.changelog.classifier.detect_changes_between_refs",
        return_value=ChangeSet(changes=(FileChange("src/auth/tokens.py", "A"),), detected_via="git"),
    ), patch(
        "cerebrofy.changelog.classifier.classify_drift", return_value=[]
    ):
        collected = collect_changes(Path("/tmp"), conn, "v1", resolved=resolved)
    assert len(collected.changes) == 1
    assert collected.changes[0].kind == KIND_ADDED


def test_collect_changes_deleted_file_emits_removed() -> None:
    conn = _make_conn_with_indexed()
    resolved = ResolvedRange(since_label="v1", since_ref="a", until_ref="b")
    with patch(
        "cerebrofy.changelog.classifier.detect_changes_between_refs",
        return_value=ChangeSet(changes=(FileChange("src/auth/tokens.py", "D"),), detected_via="git"),
    ), patch(
        "cerebrofy.validate.drift_classifier.classify_drift", return_value=[]
    ):
        collected = collect_changes(Path("/tmp"), conn, "v1", resolved=resolved)
    assert len(collected.changes) == 1
    assert collected.changes[0].kind == KIND_REMOVED


# ---------------------------------------------------------------------------
# resolve_range (real git repo in tmp_path)
# ---------------------------------------------------------------------------


def _git_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "first"], cwd=repo, check=True)
    first = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    (repo / "b.txt").write_text("b", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "second"], cwd=repo, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    return repo, first, head


def test_resolve_range_tag_or_hash(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    repo, first, head = _git_repo(tmp_path)
    r = resolve_range(repo, first, conn)
    assert r.since_ref == first
    assert r.until_ref == head
    assert r.since_label == first


def test_resolve_range_project_start(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    repo, first, head = _git_repo(tmp_path)
    r = resolve_range(repo, "project-start", conn)
    assert r.since_ref == first
    assert r.until_ref == head


def test_resolve_range_last_build_uses_snapshot(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE health_snapshots (id INTEGER PRIMARY KEY, build_ts INTEGER, commit_hash TEXT, coupling REAL, avg_blast REAL)")
    repo, first, head = _git_repo(tmp_path)
    conn.execute("INSERT INTO health_snapshots (build_ts, commit_hash) VALUES (?, ?)", (1, first))
    conn.commit()
    r = resolve_range(repo, "last-build", conn)
    assert r.since_ref == first


def test_resolve_range_last_build_falls_back_when_no_snapshot(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE health_snapshots (id INTEGER PRIMARY KEY, build_ts INTEGER, commit_hash TEXT, coupling REAL, avg_blast REAL)")
    conn.commit()
    repo, first, head = _git_repo(tmp_path)
    r = resolve_range(repo, "last-build", conn)
    assert r.note is not None
    assert r.since_ref == r.until_ref == head


def test_resolve_range_bad_ref_raises(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    repo, first, head = _git_repo(tmp_path)
    with pytest.raises(ChangelogError) as exc_info:
        resolve_range(repo, "does-not-exist", conn)
    assert exc_info.value.code == "REF_NOT_FOUND"


def test_resolve_range_not_a_git_repo_raises(tmp_path: Path) -> None:
    conn = sqlite3.connect(":memory:")
    with pytest.raises(ChangelogError) as exc_info:
        resolve_range(tmp_path, "HEAD", conn)
    assert exc_info.value.code == "REF_NOT_FOUND"


# ---------------------------------------------------------------------------
# Acceptance: deterministic fixture-graph accuracy + breaking recall
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "change, memories, expected",
    [
        # feat: brand-new neuron, no callers
        (NeuronChange("src/api/views.py::new_feature", "new_feature", "src/api/views.py",
                      "src/api", KIND_ADDED), (), FEAT),
        # fix: existing neuron + warning memory, no cross-lobe callers
        (NeuronChange("src/utils/helpers.py::fmt", "fmt", "src/utils/helpers.py",
                      "src/utils", KIND_MODIFIED),
         (_mem(mtype="warning", title="fmt edge case"),), FIX),
        # security: tag
        (NeuronChange("src/utils/helpers.py::fmt", "fmt", "src/utils/helpers.py",
                      "src/utils", KIND_MODIFIED),
         (_mem(tags=["security"]),), SECURITY),
        # perf: tag
        (NeuronChange("src/utils/helpers.py::fmt", "fmt", "src/utils/helpers.py",
                      "src/utils", KIND_MODIFIED),
         (_mem(tags=["performance"]),), PERF),
        # internal: no signals
        (NeuronChange("src/utils/helpers.py::fmt", "fmt", "src/utils/helpers.py",
                      "src/utils", KIND_MODIFIED), (), INTERNAL),
        # breaking: signature change on validate_token (4 cross-lobe callers > 3)
        (NeuronChange("src/auth/tokens.py::validate_token", "validate_token",
                      "src/auth/tokens.py", "src/auth", KIND_SIGNATURE_CHANGED), (), BREAKING),
        # breaking: removal with callers (login_handler removed, validate_token still calls it)
        (NeuronChange("src/auth/tokens.py::login_handler", "login_handler",
                      "src/auth/tokens.py", "src/auth", KIND_REMOVED), (), BREAKING),
    ],
)
def test_fixture_graph_accuracy(change, memories, expected) -> None:
    conn = _gconn()
    cc = classify_change(change, conn, memories=memories, lobes=None)
    assert cc.entry_type == expected


def test_fixture_graph_breaking_recall() -> None:
    """Every breaking-triggering scenario must be classified breaking (>95% recall)."""
    conn = _gconn()
    breaking_scenarios = [
        # signature change, 4 cross-lobe callers
        NeuronChange("src/auth/tokens.py::validate_token", "validate_token",
                     "src/auth/tokens.py", "src/auth", KIND_SIGNATURE_CHANGED),
        # signature change, 4 cross-lobe callers + a security tag (still breaking, precedence)
        NeuronChange("src/auth/tokens.py::validate_token", "validate_token",
                     "src/auth/tokens.py", "src/auth", KIND_SIGNATURE_CHANGED),
        # removal with callers
        NeuronChange("src/auth/tokens.py::login_handler", "login_handler",
                     "src/auth/tokens.py", "src/auth", KIND_REMOVED),
    ]
    memories = [(_mem(tags=["security"]),), (), ()]
    detected = sum(
        1 for ch, mem in zip(breaking_scenarios, memories)
        if classify_change(ch, conn, memories=mem, lobes=None).is_breaking
    )
    recall = detected / len(breaking_scenarios)
    assert recall >= 0.95
    assert detected == len(breaking_scenarios)


# ---------------------------------------------------------------------------
# validate_git_ref: reject malicious/option-like refs
# ---------------------------------------------------------------------------


def test_validate_git_ref_rejects_empty() -> None:
    with pytest.raises(ChangelogError) as exc_info:
        validate_git_ref("")
    assert exc_info.value.code == REF_NOT_FOUND


def test_validate_git_ref_rejects_option_like() -> None:
    """Refs starting with '-' must be rejected before they reach git as options."""
    bad_refs = ["--help", "--upload-pack=x", "-x"]
    for ref in bad_refs:
        with pytest.raises(ChangelogError) as exc_info:
            validate_git_ref(ref)
        assert exc_info.value.code == REF_NOT_FOUND


def test_validate_git_ref_rejects_shell_metacharacters() -> None:
    bad_refs = ["foo; rm -rf /", "foo|bar", "foo$BAR", "foo`bar", "foo\nbar", "foo bar"]
    for ref in bad_refs:
        with pytest.raises(ChangelogError) as exc_info:
            validate_git_ref(ref)
        assert exc_info.value.code == REF_NOT_FOUND


def test_validate_git_ref_accepts_valid_refs() -> None:
    """Tags, hashes, HEAD~1, HEAD^, HEAD@{1}, branch names with / and . pass."""
    valid_refs = [
        "HEAD", "HEAD~1", "HEAD~5", "HEAD^", "HEAD@{1}",
        "v1.0.0", "v2.3.4-rc1", "abcdef1234567890",
        "feature/foo", "release/2.0", "main",
    ]
    for ref in valid_refs:
        assert validate_git_ref(ref) == ref


# ---------------------------------------------------------------------------
# resolve_range: malicious refs raise before git is invoked
# ---------------------------------------------------------------------------


def test_resolve_range_rejects_malicious_ref(tmp_path: Path) -> None:
    """Option-like refs raise REF_NOT_FOUND and never reach git as options."""
    conn = sqlite3.connect(":memory:")
    repo, first, head = _git_repo(tmp_path)
    bad_refs = ["--help", "--upload-pack=x", "", "foo; rm -rf /"]
    for bad_ref in bad_refs:
        with pytest.raises(ChangelogError) as exc_info:
            resolve_range(repo, bad_ref, conn)
        assert exc_info.value.code == "REF_NOT_FOUND"


def test_resolve_range_rejects_malicious_ref_without_git_invocation(tmp_path: Path) -> None:
    """validate_git_ref raises before _run_git is ever called for malicious refs."""
    conn = sqlite3.connect(":memory:")
    repo, first, head = _git_repo(tmp_path)

    def mock_run_git(args: list[str], repo_root: Path) -> str | None:
        joined = " ".join(args)
        # Malicious refs must never reach git — validate_git_ref blocks them first
        if "--help" in joined or "--upload-pack" in joined:
            raise AssertionError(f"git should not be called with malicious ref: {args}")
        # HEAD rev-parse is legitimate — return the head hash
        if "rev-parse" in args and "HEAD" in args:
            return head
        return None

    with patch("cerebrofy.changelog.classifier._run_git", side_effect=mock_run_git):
        with pytest.raises(ChangelogError) as exc_info:
            resolve_range(repo, "--help", conn)
        assert exc_info.value.code == "REF_NOT_FOUND"


# ---------------------------------------------------------------------------
# Rename detection (git mv → A+D pair → MOVED → REFACTOR)
# ---------------------------------------------------------------------------


def test_collect_changes_rename_detected_as_moved(tmp_path: Path) -> None:
    """A git mv (A+D pair, same neuron name, different lobes) → KIND_MOVED → REFACTOR."""
    repo = tmp_path
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)

    # File in auth/ lobe with a neuron
    (repo / "auth").mkdir()
    (repo / "auth" / "tokens.py").write_text(
        "def validate_token():\n    pass\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add tokens"], cwd=repo, check=True)
    first = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    # git mv to utils/ lobe (different first path segment → different lobe)
    (repo / "utils").mkdir()
    subprocess.run(["git", "mv", "auth/tokens.py", "utils/tokens.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "move tokens"], cwd=repo, check=True)

    # DB with the neuron indexed under the OLD path
    conn = sqlite3.connect(":memory:")
    conn.execute(_NODES_DDL)
    conn.execute(_EDGES_DDL)
    conn.execute("CREATE TABLE file_hashes (file TEXT PRIMARY KEY, hash TEXT NOT NULL)")
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?)",
        ("auth/tokens.py::validate_token", "validate_token", "auth/tokens.py",
         "function", 1, 8, "def validate_token():", None, "h1"),
    )
    conn.commit()

    # Mock classify_drift to report the neuron as added at the new path
    with patch(
        "cerebrofy.changelog.classifier.classify_drift",
        return_value=[DriftRecord(
            file="utils/tokens.py", drift_type="structural",
            changed_neurons=("validate_token",), drift_detail="add",
            neuron_details=(
                NeuronDrift(name="validate_token", kind="added", neuron_type="function"),
            ),
        )],
    ):
        collected = collect_changes(repo, conn, first)

    kinds = {c.kind for c in collected.changes}
    assert KIND_REMOVED in kinds  # old path neuron (from DB index)
    assert KIND_ADDED in kinds  # new path neuron (from drift)

    # classify_changes merges same-name, different-lobe move into REFACTOR
    classified = classify_changes(collected.changes, conn, memories_by_neuron=None, lobes=None)
    refactors = [c for c in classified if c.entry_type == REFACTOR]
    assert len(refactors) == 1
    assert any(n.kind == KIND_MOVED for n in refactors[0].neurons)
    assert {n.file for n in refactors[0].neurons} == {"auth/tokens.py", "utils/tokens.py"}
