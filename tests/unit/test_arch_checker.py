"""Unit tests for cerebrofy.arch.checker — rule evaluation over an in-memory graph."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from cerebrofy.arch.checker import (
    UNKNOWN_LOBE,
    Violation,
    changed_files_since,
    fix_hint,
    run_arch_check,
)
from cerebrofy.arch.rules import (
    AllowedCallersCheck,
    ArchRule,
    MaxBlastRadiusCheck,
    NoCyclesCheck,
    NoEdgeCheck,
    RulesConfig,
)
from cerebrofy.epistemic.state import EpistemicState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE nodes (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, file TEXT NOT NULL,
          type TEXT, line_start INTEGER, line_end INTEGER,
          signature TEXT, docstring TEXT, hash TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE edges (
          src_id TEXT, dst_id TEXT, rel_type TEXT NOT NULL, file TEXT,
          PRIMARY KEY (src_id, dst_id, rel_type)
        )
        """
    )
    return conn


def _add_node(
    conn: sqlite3.Connection,
    nid: str,
    *,
    name: str | None = None,
    file: str | None = None,
    type: str = "function",
    line: int = 1,
) -> None:
    name = name or nid.split("::")[-1]
    file = file or nid.split("::")[0]
    conn.execute(
        "INSERT INTO nodes (id, name, file, type, line_start) VALUES (?, ?, ?, ?, ?)",
        (nid, name, file, type, line),
    )


def _add_edge(
    conn: sqlite3.Connection, src: str, dst: str, rel_type: str = "LOCAL_CALL"
) -> None:
    conn.execute(
        "INSERT INTO edges (src_id, dst_id, rel_type, file) VALUES (?, ?, ?, ?)",
        (src, dst, rel_type, src.split("::")[0]),
    )


_LOBES = {
    "api": "src/api/",
    "db": "src/db/",
    "commands": "src/commands/",
    "embedder": "src/embedder/",
}


# ---------------------------------------------------------------------------
# no_edge (lobe selectors)
# ---------------------------------------------------------------------------


def _edge_rule(name: str, severity: str = "error", **kwargs: object) -> ArchRule:
    return ArchRule(
        name=name,
        severity=severity,
        check=NoEdgeCheck(**kwargs),  # type: ignore[arg-type]
        description="desc",
    )


def test_no_edge_violation_and_location_fields() -> None:
    conn = _make_conn()
    _add_node(conn, "src/api/views.py::endpoint", line=7)
    _add_node(conn, "src/db/writer.py::write_nodes")
    _add_edge(conn, "src/api/views.py::endpoint", "src/db/writer.py::write_nodes")

    result = run_arch_check(
        RulesConfig(rules=(_edge_rule("no-db", from_lobe="api", to_lobe="db"),)),
        conn,
        _LOBES,
    )

    assert result.result == "FAIL"
    assert len(result.error_violations) == 1
    v = result.error_violations[0]
    assert isinstance(v, Violation)
    assert v.rule_name == "no-db"
    assert v.location == "src/api/views.py::endpoint → src/db/writer.py::write_nodes"
    assert v.file == "src/api/views.py"
    assert v.line == 7
    assert v.detail == "api → db"
    assert result.passing_rules == ()


def test_no_edge_runtime_boundary_always_excluded() -> None:
    conn = _make_conn()
    _add_node(conn, "src/api/views.py::endpoint")
    _add_node(conn, "src/db/writer.py::write_nodes")
    _add_edge(
        conn, "src/api/views.py::endpoint", "src/db/writer.py::write_nodes", "RUNTIME_BOUNDARY"
    )

    result = run_arch_check(
        RulesConfig(rules=(_edge_rule("no-db", from_lobe="api", to_lobe="db"),)),
        conn,
        _LOBES,
    )
    assert result.result == "PASS"
    assert result.passing_rules == ("no-db",)


def test_no_edge_ignores_external_dst_nodes() -> None:
    conn = _make_conn()
    _add_node(conn, "src/api/views.py::endpoint")
    _add_node(conn, "src/db/writer.py::write_nodes")
    _add_edge(conn, "src/api/views.py::endpoint", "src/db/writer.py::write_nodes")
    _add_edge(conn, "src/api/views.py::endpoint", "external::os.system", "EXTERNAL_CALL")

    result = run_arch_check(
        RulesConfig(rules=(_edge_rule("no-db", from_lobe="api", to_lobe="db"),)),
        conn,
        _LOBES,
    )
    assert len(result.error_violations) == 1


def test_no_edge_pattern_selectors(tmp_path: Path) -> None:
    _ = tmp_path
    conn = _make_conn()
    _add_node(conn, "tests/unit/x_test.py::test_x")
    _add_node(conn, "src/core/private/impl.py::impl")
    _add_edge(conn, "tests/unit/x_test.py::test_x", "src/core/private/impl.py::impl")
    _add_node(conn, "src/api/pub.py::pub")
    _add_edge(conn, "tests/unit/x_test.py::test_x", "src/api/pub.py::pub")

    rule = ArchRule(
        name="no-private-tests",
        severity="warning",
        check=NoEdgeCheck(from_patterns=("tests/**",), to_patterns=("*/private/**",)),
    )
    result = run_arch_check(RulesConfig(rules=(rule,)), conn, {})
    assert result.result == "WARN"
    assert len(result.warning_violations) == 1
    assert result.warning_violations[0].location.endswith("private/impl.py::impl")


def test_no_edge_mixed_lobe_and_pattern_selectors() -> None:
    conn = _make_conn()
    _add_node(conn, "src/api/views.py::endpoint")
    _add_node(conn, "src/db/writer.py::write_nodes")
    _add_edge(conn, "src/api/views.py::endpoint", "src/db/writer.py::write_nodes")

    # from_lobe api + to_pattern that does NOT match db/writer.py → no violation
    rule = ArchRule(
        name="mixed",
        severity="error",
        check=NoEdgeCheck(from_lobe="api", to_patterns=("zzz/**",)),
    )
    result = run_arch_check(RulesConfig(rules=(rule,)), conn, _LOBES)
    assert result.result == "PASS"

    # to_pattern that DOES match → violation
    rule2 = ArchRule(
        name="mixed2",
        severity="error",
        check=NoEdgeCheck(from_lobe="api", to_patterns=("src/db/**",)),
    )
    result2 = run_arch_check(RulesConfig(rules=(rule2,)), conn, _LOBES)
    assert result2.result == "FAIL"


def test_unknown_lobe_in_rule_is_config_error() -> None:
    conn = _make_conn()
    _add_node(conn, "src/api/views.py::endpoint")
    _add_node(conn, "src/db/writer.py::write_nodes")
    _add_edge(conn, "src/api/views.py::endpoint", "src/db/writer.py::write_nodes")

    result = run_arch_check(
        RulesConfig(rules=(_edge_rule("typo", from_lobe="ap", to_lobe="db"),)),
        conn,
        _LOBES,
    )
    assert result.result == "PASS"  # config errors do not fail the run
    config_errors = result.config_errors
    assert config_errors and config_errors[0][0] == "typo"
    assert "unknown lobe(s) ap" in config_errors[0][1]
    assert result.passing_rules == ()


def test_rule_name_filter_and_unknown_rule() -> None:
    conn = _make_conn()
    _add_node(conn, "src/api/views.py::endpoint")
    _add_node(conn, "src/db/writer.py::write_nodes")
    _add_edge(conn, "src/api/views.py::endpoint", "src/db/writer.py::write_nodes")

    rules = RulesConfig(
        rules=(
            _edge_rule("a", from_lobe="api", to_lobe="db"),
            _edge_rule("b", severity="warning", from_lobe="api", to_lobe="db"),
        )
    )
    result = run_arch_check(rules, conn, _LOBES, rule_name="b")
    assert len(result.rule_results) == 1
    assert result.result == "WARN"

    with pytest.raises(ValueError, match="not found"):
        run_arch_check(rules, conn, _LOBES, rule_name="nope")


# ---------------------------------------------------------------------------
# no_cycles (scope: lobes)
# ---------------------------------------------------------------------------


def _cycle_graph() -> sqlite3.Connection:
    """commands → embedder → db → commands cycle plus an acyclic api lobe."""
    conn = _make_conn()
    files = {
        "src/commands/build.py::build": "commands",
        "src/embedder/local.py::embed": "embedder",
        "src/db/writer.py::write": "db",
        "src/api/views.py::endpoint": "api",
    }
    nid = {}
    for nid_str, lobe in files.items():
        _add_node(conn, nid_str)
        nid[lobe] = nid_str
    _add_edge(conn, nid["commands"], nid["embedder"])
    _add_edge(conn, nid["embedder"], nid["db"])
    _add_edge(conn, nid["db"], nid["commands"])
    _add_edge(conn, nid["commands"], nid["api"])  # acyclic branch
    return conn


def test_no_cycles_detects_lobe_cycle() -> None:
    rule = ArchRule(name="no-cycles", severity="error", check=NoCyclesCheck(scope="lobes"))
    result = run_arch_check(RulesConfig(rules=(rule,)), _cycle_graph(), _LOBES)
    assert result.result == "FAIL"
    assert len(result.error_violations) == 1
    v = result.error_violations[0]
    assert v.kind == "cycle"
    assert "commands → embedder → db → commands" in v.location
    assert "3 lobes" in v.detail
    assert v.file == "src/db/writer.py"  # closing edge src


def test_no_cycles_passes_when_acyclic() -> None:
    conn = _make_conn()
    _add_node(conn, "src/api/views.py::endpoint")
    _add_node(conn, "src/db/writer.py::write")
    _add_edge(conn, "src/api/views.py::endpoint", "src/db/writer.py::write")

    rule = ArchRule(name="no-cycles", severity="error", check=NoCyclesCheck(scope="lobes"))
    result = run_arch_check(RulesConfig(rules=(rule,)), conn, _LOBES)
    assert result.result == "PASS"


def test_no_cycles_ignores_self_loops_and_unknown_lobes() -> None:
    conn = _make_conn()
    _add_node(conn, "src/api/views.py::endpoint")
    _add_node(conn, "src/db/writer.py::write")
    _add_node(conn, "unmatched/file.py::thing")
    _add_edge(conn, "src/api/views.py::endpoint", "src/api/views2.py::other")
    _add_node(conn, "src/api/views2.py::other")
    _add_edge(conn, "unmatched/file.py::thing", "src/db/writer.py::write")

    rule = ArchRule(name="no-cycles", severity="error", check=NoCyclesCheck(scope="lobes"))
    result = run_arch_check(RulesConfig(rules=(rule,)), conn, _LOBES)
    assert result.result == "PASS"
    assert result.passing_rules == ("no-cycles",)


# ---------------------------------------------------------------------------
# allowed_callers
# ---------------------------------------------------------------------------


def test_allowed_callers_violates_disallowed_lobe() -> None:
    conn = _make_conn()
    _add_node(conn, "src/commands/ingest.py::ingest_doc")
    _add_node(conn, "src/embedder/local.py::embed")
    _add_node(conn, "src/embedder/other.py::other")
    _add_edge(conn, "src/commands/ingest.py::ingest_doc", "src/embedder/local.py::embed")
    _add_edge(conn, "src/commands/ingest.py::ingest_doc", "src/embedder/other.py::other")
    _add_node(conn, "src/embedder/pipeline.py::pipeline")  # allowed caller
    _add_edge(conn, "src/embedder/pipeline.py::pipeline", "src/embedder/local.py::embed")

    rule = ArchRule(
        name="embedder-isolated",
        severity="warning",
        check=AllowedCallersCheck(neuron="*embedder/*", from_lobes=("embedder",)),
    )
    result = run_arch_check(RulesConfig(rules=(rule,)), conn, _LOBES)
    assert result.result == "WARN"
    assert len(result.warning_violations) == 2  # both commands→embedder edges
    v = result.warning_violations[0]
    assert "caller lobe 'commands' is not in allowed embedder" in v.detail
    assert v.file == "src/commands/ingest.py"
    assert {x.dst_name for x in result.warning_violations} == {"embed", "other"}


def test_allowed_callers_matches_by_name() -> None:
    conn = _make_conn()
    _add_node(conn, "src/api/views.py::embed")
    _add_node(conn, "src/db/writer.py::write")
    _add_edge(conn, "src/db/writer.py::write", "src/api/views.py::embed")

    rule = ArchRule(
        name="embed-fn-isolated",
        severity="error",
        check=AllowedCallersCheck(neuron="embed", from_lobes=("api",)),
    )
    result = run_arch_check(RulesConfig(rules=(rule,)), conn, _LOBES)
    assert result.result == "FAIL"
    assert result.error_violations[0].src_name == "write"


def test_allowed_callers_silent_when_no_targets() -> None:
    conn = _make_conn()
    _add_node(conn, "src/api/views.py::endpoint")
    _add_node(conn, "src/db/writer.py::write")
    _add_edge(conn, "src/api/views.py::endpoint", "src/db/writer.py::write")

    rule = ArchRule(
        name="no-target",
        severity="error",
        check=AllowedCallersCheck(neuron="*nonexistent/*", from_lobes=("api",)),
    )
    result = run_arch_check(RulesConfig(rules=(rule,)), conn, _LOBES)
    assert result.result == "PASS"


# ---------------------------------------------------------------------------
# max_blast_radius
# ---------------------------------------------------------------------------


def test_max_blast_radius_counts_depth_1_and_2() -> None:
    conn = _make_conn()
    # hub <- a1, a2 (depth 1); a1 <- b1 (depth 2); a2 <- b2 (depth 2)
    _add_node(conn, "src/core/hub.py::hub")
    _add_node(conn, "src/api/a1.py::a1")
    _add_node(conn, "src/api/a2.py::a2")
    _add_node(conn, "src/db/b1.py::b1")
    _add_node(conn, "src/db/b2.py::b2")
    _add_edge(conn, "src/api/a1.py::a1", "src/core/hub.py::hub")
    _add_edge(conn, "src/api/a2.py::a2", "src/core/hub.py::hub")
    _add_edge(conn, "src/db/b1.py::b1", "src/api/a1.py::a1")
    _add_edge(conn, "src/db/b2.py::b2", "src/api/a2.py::a2")

    rule = ArchRule(name="r", severity="warning", check=MaxBlastRadiusCheck(limit=3))
    result = run_arch_check(RulesConfig(rules=(rule,)), conn, _LOBES)
    # hub = 2 direct + 2 indirect = 4 > 3 → violation with detail blast_radius=4
    assert result.result == "WARN"
    v = result.warning_violations[0]
    assert v.location == "src/core/hub.py::hub"
    assert v.detail == "blast_radius=4 (limit: 3)"
    assert v.dst_name is None


def test_max_blast_radius_dedupe_and_module_exclusion() -> None:
    conn = _make_conn()
    _add_node(conn, "src/core/hub.py::hub")
    _add_node(conn, "src/core/hub.py", name="hub", type="module")
    _add_node(conn, "src/api/a1.py::a1")
    _add_edge(conn, "src/api/a1.py::a1", "src/core/hub.py::hub")
    _add_edge(conn, "src/api/a1.py::a1", "src/core/hub.py::hub", "IMPORT")  # duplicate pair

    # hub: 1 unique direct caller, 0 indirect → radius 1 = limit → pass
    rules = RulesConfig(
        rules=(ArchRule(name="r", severity="warning", check=MaxBlastRadiusCheck(limit=1)),)
    )
    result = run_arch_check(rules, conn, _LOBES)
    assert result.passing_rules == ("r",)


def test_max_blast_radius_skips_module_nodes() -> None:
    conn = _make_conn()
    _add_node(conn, "src/core/big.py", name="big", type="module")
    _add_node(conn, "src/api/a1.py::a1")
    _add_node(conn, "src/api/a2.py::a2")
    _add_edge(conn, "src/api/a1.py::a1", "src/core/big.py")
    _add_edge(conn, "src/api/a2.py::a2", "src/core/big.py")

    rules = RulesConfig(
        rules=(ArchRule(name="r", severity="warning", check=MaxBlastRadiusCheck(limit=0)),)
    )
    result = run_arch_check(rules, conn, _LOBES)
    assert result.result == "PASS"  # module-type neurons are not assessed


# ---------------------------------------------------------------------------
# shared blast-radius metric (Idea #01)
# ---------------------------------------------------------------------------


def _blast_graph() -> tuple[sqlite3.Connection, str]:
    """Hub with 2 direct + 2 indirect callers, a self-loop, and a downstream edge."""
    conn = _make_conn()
    hub = "src/core/hub.py::hub"
    for nid in (
        hub,
        "src/api/a1.py::a1",
        "src/api/a2.py::a2",
        "src/db/b1.py::b1",
        "src/db/b2.py::b2",
        "src/core/hub2.py::hub2",
    ):
        _add_node(conn, nid)
    _add_edge(conn, "src/api/a1.py::a1", hub)
    _add_edge(conn, "src/api/a2.py::a2", hub)
    _add_edge(conn, "src/db/b1.py::b1", "src/api/a1.py::a1")
    _add_edge(conn, "src/db/b2.py::b2", "src/api/a2.py::a2")
    _add_edge(conn, hub, hub)  # self-loop is not its own caller
    _add_edge(conn, hub, "src/core/hub2.py::hub2")  # downstream edge is not a caller
    return conn, hub


def test_shared_metric_matches_bfs_callers() -> None:
    """Idea #01: the checker metric and blast-radius BFS count identical callers."""
    from cerebrofy.analysis.blast_radius import bfs_callers, caller_ids_within_depth2

    conn, hub = _blast_graph()
    d1, d2, _ = bfs_callers(hub, conn)
    bfs_ids = {n.id for n in d1} | {n.id for n in d2}
    assert bfs_ids == {
        "src/api/a1.py::a1",
        "src/api/a2.py::a2",
        "src/db/b1.py::b1",
        "src/db/b2.py::b2",
    }

    # in_adj as _load_graph builds it: incoming edges between known nodes
    in_adj: dict[str, set[str]] = {}
    for src, dst in conn.execute("SELECT src_id, dst_id FROM edges"):
        in_adj.setdefault(dst, set()).add(src)
    assert caller_ids_within_depth2(hub, in_adj) == bfs_ids


def test_max_blast_radius_detail_matches_shared_metric() -> None:
    from cerebrofy.analysis.blast_radius import bfs_callers

    conn, hub = _blast_graph()
    d1, d2, _ = bfs_callers(hub, conn)
    expected = len({n.id for n in d1} | {n.id for n in d2})

    rule = ArchRule(name="r", severity="warning", check=MaxBlastRadiusCheck(limit=3))
    result = run_arch_check(RulesConfig(rules=(rule,)), conn, _LOBES)
    assert result.result == "WARN"
    v = result.warning_violations[0]
    assert v.location == hub
    assert v.detail == f"blast_radius={expected} (limit: 3)"


# ---------------------------------------------------------------------------
# --since filtering
# ---------------------------------------------------------------------------


def test_changed_files_filter_drops_untouched_violations() -> None:
    conn = _make_conn()
    _add_node(conn, "src/api/views.py::endpoint")
    _add_node(conn, "src/db/writer.py::write_nodes")
    _add_edge(conn, "src/api/views.py::endpoint", "src/db/writer.py::write_nodes")

    rules = RulesConfig(
        rules=(_edge_rule("no-db", from_lobe="api", to_lobe="db"),)
    )
    everything = run_arch_check(rules, conn, _LOBES)
    assert everything.result == "FAIL"

    scoped = run_arch_check(
        rules, conn, _LOBES, changed_files=frozenset({"src/api/other.py"})
    )
    assert scoped.result == "PASS"
    assert scoped.error_violations == ()

    touched = run_arch_check(
        rules, conn, _LOBES, changed_files=frozenset({"src/api/views.py"})
    )
    assert touched.result == "FAIL"


# ---------------------------------------------------------------------------
# Introduced-in attribution (monkeypatched git)
# ---------------------------------------------------------------------------


def test_introduced_in_attribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cerebrofy.arch import checker

    (tmp_path / ".git").mkdir()  # passes the "is a git repo" pre-check

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            list(args), 0, "abc1234|alice@co.com|2 hours ago\n", ""
        )

    monkeypatch.setattr(checker.subprocess, "run", fake_run)
    cache: dict[str, str | None] = {}
    text = checker._introduced_in(tmp_path, "src/api/views.py", cache)
    assert text == "commit abc1234 by alice@co.com (2 hours ago)"
    # cached on second call
    assert checker._introduced_in(tmp_path, "src/api/views.py", cache) == text


def test_introduced_in_garbage_output_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cerebrofy.arch import checker

    (tmp_path / ".git").mkdir()

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(list(args), 0, "%h|%ae|%ar\n", "")

    monkeypatch.setattr(checker.subprocess, "run", fake_run)
    cache: dict[str, str | None] = {}
    assert checker._introduced_in(tmp_path, "src/x.py", cache) is None


def test_introduced_in_no_git_dir() -> None:
    from cerebrofy.arch import checker

    cache: dict[str, str | None] = {}
    assert checker._introduced_in(Path("/does/not/exist"), "src/x.py", cache) is None


def test_changed_files_since_raises_on_bad_ref(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()  # not a repo → git fails
    with pytest.raises(ValueError, match="could not diff"):
        changed_files_since(tmp_path, "HEAD~1")


# ---------------------------------------------------------------------------
# fix_hint
# ---------------------------------------------------------------------------


def test_fix_hint_prefers_description() -> None:
    assert fix_hint("edge", "custom fix") == "custom fix"
    assert "intermediate" in fix_hint("edge", "")
    assert "cycle" in fix_hint("cycle", "").lower()
    assert "splitting" in fix_hint("blast_radius", "")


def test_unknown_lobe_constant() -> None:
    assert UNKNOWN_LOBE == "__unknown__"


# ---------------------------------------------------------------------------
# sprint-priority escalation (Idea #23)
# ---------------------------------------------------------------------------


def _edge_db() -> sqlite3.Connection:
    conn = _make_conn()
    _add_node(conn, "src/api/views.py::endpoint")
    _add_node(conn, "src/db/writer.py::write_nodes")
    _add_edge(conn, "src/api/views.py::endpoint", "src/db/writer.py::write_nodes")
    return conn


def test_priority_lobes_escalate_warning_to_error() -> None:
    rule = _edge_rule("no-db", severity="warning", from_lobe="api", to_lobe="db")
    result = run_arch_check(
        RulesConfig(rules=(rule,)), _edge_db(), _LOBES, priority_lobes=frozenset({"api"})
    )
    assert result.result == "FAIL"
    assert len(result.error_violations) == 1
    assert result.warning_violations == ()
    assert result.error_violations[0].severity == "error"
    rr = result.rule_results[0]
    assert rr.rule.severity == "error"  # effective severity for this run
    assert rr.escalated_lobes == ("api",)


def test_priority_lobes_no_escalation_outside_overlap() -> None:
    rule = _edge_rule("no-db", severity="warning", from_lobe="api", to_lobe="db")
    result = run_arch_check(
        RulesConfig(rules=(rule,)), _edge_db(), _LOBES, priority_lobes=frozenset({"commands"})
    )
    assert result.result == "WARN"
    assert result.rule_results[0].escalated_lobes == ()
    assert result.rule_results[0].rule.severity == "warning"


def test_error_rules_do_not_mark_escalation() -> None:
    rule = _edge_rule("no-db", severity="error", from_lobe="api", to_lobe="db")
    result = run_arch_check(
        RulesConfig(rules=(rule,)), _edge_db(), _LOBES, priority_lobes=frozenset({"api"})
    )
    assert result.result == "FAIL"
    assert result.rule_results[0].escalated_lobes == ()


def test_rules_without_explicit_lobes_never_escalate() -> None:
    cycle_rule = ArchRule(name="c", severity="warning", check=NoCyclesCheck(scope="lobes"))
    result = run_arch_check(
        RulesConfig(rules=(cycle_rule,)),
        _cycle_graph(),
        _LOBES,
        priority_lobes=frozenset({"commands", "embedder", "db"}),
    )
    assert result.result == "WARN"
    assert result.rule_results[0].escalated_lobes == ()

    radius = ArchRule(name="r", severity="warning", check=MaxBlastRadiusCheck(limit=0))
    result2 = run_arch_check(
        RulesConfig(rules=(radius,)),
        _edge_db(),
        _LOBES,
        priority_lobes=frozenset({"api", "db"}),
    )
    assert result2.result == "WARN"  # nodes have callers > 0 → violation stays a warning
    assert result2.rule_results[0].escalated_lobes == ()


def test_escalated_lobes_sorted_and_full_overlap() -> None:
    from cerebrofy.arch.checker import escalated_priority_lobes

    rule = _edge_rule("no-db", severity="warning", from_lobe="api", to_lobe="db")
    assert escalated_priority_lobes(rule, frozenset({"db", "api"})) == ("api", "db")
    assert escalated_priority_lobes(rule, frozenset()) == ()


# ---------------------------------------------------------------------------
# epistemic enrichment (Idea #22)
# ---------------------------------------------------------------------------


def _epistemic_sentinel() -> EpistemicState:
    return EpistemicState(
        graph_age_hours=1.0,
        neurons_changed_since_build=0,
        unindexed_languages=(),
        dynamic_dispatch_count=0,
        memory_stale_count=0,
        missing_test_paths=0,
        overall_confidence=0.9,
        caveats=(),
        recommendation="Looks good.",
    )


def test_epistemic_attached_when_tracked_extensions_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cerebrofy.arch import checker

    sentinel = _epistemic_sentinel()
    monkeypatch.setattr(checker, "compute_epistemic_state", lambda *a, **k: sentinel)
    result = run_arch_check(
        RulesConfig(rules=()),
        _make_conn(),
        _LOBES,
        repo_root=tmp_path,
        tracked_extensions=[".py"],
    )
    assert result.epistemic is sentinel


def test_epistemic_skipped_without_tracked_extensions(tmp_path: Path) -> None:
    result = run_arch_check(
        RulesConfig(rules=()), _make_conn(), _LOBES, repo_root=tmp_path
    )
    assert result.epistemic is None


def test_epistemic_failure_is_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from cerebrofy.arch import checker

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("git unavailable")

    monkeypatch.setattr(checker, "compute_epistemic_state", boom)
    result = run_arch_check(
        RulesConfig(rules=()),
        _make_conn(),
        _LOBES,
        repo_root=tmp_path,
        tracked_extensions=[".py"],
    )
    assert result.epistemic is None  # never fails the check


def test_lobe_references_public_helper() -> None:
    from cerebrofy.arch.checker import lobe_references

    assert lobe_references(NoEdgeCheck(from_lobe="api", to_lobe=None)) == {"api"}
    assert lobe_references(NoEdgeCheck(from_patterns=("src/**",), to_lobe="db")) == {"db"}
    assert lobe_references(NoCyclesCheck(scope="lobes")) == set()
    assert lobe_references(MaxBlastRadiusCheck(limit=5)) == set()
    assert lobe_references(
        AllowedCallersCheck(neuron="*x/*", from_lobes=("api", "db"))
    ) == {"api", "db"}
