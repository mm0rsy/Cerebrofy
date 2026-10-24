"""Tests for the Codebase Narrative Engine (#26)."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

import pytest

from cerebrofy.commands.build import _preserve_history
from cerebrofy.db.schema import create_schema, ensure_health_schema
from cerebrofy.health.metrics import HealthMetrics
from cerebrofy.health.snapshot import fetch_latest_snapshot, record_snapshot
from cerebrofy.narrative import generator
from cerebrofy.narrative.generator import (
    generate_narrative,
    maybe_update_narrative,
)

BASE_DAY = "2026-01-01"


def _ts(day: str) -> int:
    return int(time.mktime(time.strptime(day, "%Y-%m-%d")))


def _day(offset: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(_ts(BASE_DAY) + offset * 86400))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed(
    tmp_path: Path,
    snapshots: list[tuple[int, float, float, int, int]],
    *,
    events: list[tuple[int, str, list[str], str, float]] | None = None,
    memories: list[tuple[str, str, int, str | None]] | None = None,
    intent: str | None = None,
    rules: str | None = None,
) -> Path:
    """Create ``<tmp>/.cerebrofy`` with a real schema and narrative inputs.

    ``snapshots`` tuples are ``(build_ts, coupling, avg_blast, neurons, lobes)``.
    """
    cerebrofy_dir = tmp_path / ".cerebrofy"
    db_dir = cerebrofy_dir / "db"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "cerebrofy.db"
    conn = sqlite3.connect(db_path)
    create_schema(conn, 0)
    for index, (build_ts, coupling, blast, neurons, lobes) in enumerate(snapshots):
        conn.execute(
            """
            INSERT INTO health_snapshots (
                build_ts, commit_hash, coupling, avg_blast, dead_code_pct,
                cohesion, test_surface, drift_velocity, hub_concentration,
                neuron_count, edge_count, lobe_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                build_ts,
                f"hash{index}",
                coupling,
                blast,
                0.0,
                0.5,
                50.0,
                0.0,
                10.0,
                neurons,
                neurons * 2,
                lobes,
            ),
        )
    for event_id, ts, title, lobes, blast_delta in events or []:
        conn.execute(
            """
            INSERT INTO narrative_events (
                id, ts, commit_ref, type, title, body, lobes_affected,
                blast_radius_delta, health_delta
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                ts,
                "abc1234",
                "security",
                title,
                "body",
                json.dumps(lobes),
                blast_delta,
                "{}",
            ),
        )
    conn.commit()
    conn.close()

    if memories:
        mem_conn = sqlite3.connect(db_dir / "memories.db")
        mem_conn.execute(
            """
            CREATE TABLE memories (
                id TEXT PRIMARY KEY,
                neuron_id TEXT,
                lobe TEXT,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                author TEXT,
                created_ts INTEGER NOT NULL,
                tags TEXT,
                decay_score REAL NOT NULL DEFAULT 1.0,
                status TEXT NOT NULL DEFAULT 'active'
            )
            """
        )
        for memory_id, title, created_ts, lobe in memories:
            mem_conn.execute(
                """
                INSERT INTO memories (
                    id, neuron_id, lobe, type, title, body, author,
                    created_ts, tags, decay_score, status
                ) VALUES (?, NULL, ?, 'decision', ?, 'body', 'dev', ?, NULL, 1.0, 'active')
                """,
                (memory_id, lobe, title, created_ts),
            )
        mem_conn.commit()
        mem_conn.close()

    if intent is not None:
        (cerebrofy_dir / "intent.yaml").write_text(intent, encoding="utf-8")
    if rules is not None:
        (cerebrofy_dir / "arch-rules.yaml").write_text(rules, encoding="utf-8")
    return cerebrofy_dir


def _standard_snapshots() -> list[tuple[int, float, float, int, int]]:
    return [
        (_ts(_day(0)), 0.10, 2.0, 100, 2),
        (_ts(_day(1)), 0.20, 2.0, 100, 3),  # lobe change -> era boundary
        (_ts(_day(2)), 0.21, 2.0, 105, 3),  # below thresholds
        (_ts(_day(3)), 0.35, 2.0, 110, 4),  # coupling + lobe change -> boundary
    ]


# ---------------------------------------------------------------------------
# B1 / B2 / M6 — era naming, lobe count, boundaries
# ---------------------------------------------------------------------------


def test_era_names_describe_change_without_numeric_prefix(tmp_path: Path) -> None:
    cerebrofy_dir = _seed(tmp_path, _standard_snapshots())
    narrative = generate_narrative(cerebrofy_dir, force=True)
    content = (cerebrofy_dir / "NARRATIVE.md").read_text(encoding="utf-8")

    assert "## Era 1: Era 1" not in content
    assert "## Era 1: Expansion" in content
    assert "## Era 3: Stability" in content
    assert [era.name for era in narrative.eras] == [
        "Expansion & Coupling shift",
        "Expansion & Coupling shift",
        "Stability",
    ]


def test_era_structural_state_uses_real_lobe_count(tmp_path: Path) -> None:
    cerebrofy_dir = _seed(tmp_path, _standard_snapshots())
    narrative = generate_narrative(cerebrofy_dir, force=True)
    content = (cerebrofy_dir / "NARRATIVE.md").read_text(encoding="utf-8")

    assert narrative.eras[-1].structural_state["lobes"] == 4
    assert narrative.eras[-1].structural_state["neurons"] == 110
    assert "- Lobes: 4" in content
    assert "- Lobe count changed from 3 to 4" in content


def test_era_boundaries_do_not_overlap(tmp_path: Path) -> None:
    cerebrofy_dir = _seed(tmp_path, _standard_snapshots())
    narrative = generate_narrative(cerebrofy_dir, force=True)
    eras = narrative.eras

    assert eras[0].end_ts == _ts(_day(0))
    assert eras[1].start_ts == _ts(_day(1))
    assert eras[1].end_ts == _ts(_day(2))
    assert eras[2].start_ts == _ts(_day(3))
    assert eras[2].end_ts == _ts(_day(3))


# ---------------------------------------------------------------------------
# B3 — history preserved across the build DB swap
# ---------------------------------------------------------------------------


def test_preserve_history_copies_snapshots_and_events(tmp_path: Path) -> None:
    old_db = tmp_path / "old.db"
    new_db = tmp_path / "new.db"
    for path in (old_db, new_db):
        conn = sqlite3.connect(path)
        create_schema(conn, 0)
        conn.close()

    old = sqlite3.connect(old_db)
    old.execute(
        "INSERT INTO health_snapshots (build_ts, commit_hash, coupling, lobe_count) "
        "VALUES (?, ?, ?, ?)",
        (123, "abc", 0.2, 3),
    )
    old.execute(
        "INSERT INTO narrative_events (id, ts, type, title) VALUES (?, ?, ?, ?)",
        ("e1", 123, "feat", "Something shipped"),
    )
    old.commit()
    old.close()

    _preserve_history(old_db, new_db)

    new = sqlite3.connect(new_db)
    try:
        snap = new.execute(
            "SELECT build_ts, commit_hash, coupling, lobe_count FROM health_snapshots"
        ).fetchone()
        event = new.execute(
            "SELECT id, ts, title FROM narrative_events"
        ).fetchone()
    finally:
        new.close()

    assert snap == (123, "abc", 0.2, 3)
    assert event == ("e1", 123, "Something shipped")


def test_preserve_history_is_idempotent_and_ignores_missing_old_db(
    tmp_path: Path,
) -> None:
    old_db = tmp_path / "old.db"
    new_db = tmp_path / "new.db"
    for path in (old_db, new_db):
        conn = sqlite3.connect(path)
        create_schema(conn, 0)
        conn.close()

    conn = sqlite3.connect(old_db)
    conn.execute(
        "INSERT INTO health_snapshots (build_ts, lobe_count) VALUES (?, ?)",
        (1, 2),
    )
    conn.commit()
    conn.close()

    _preserve_history(old_db, new_db)
    _preserve_history(old_db, new_db)
    _preserve_history(tmp_path / "absent.db", new_db)

    conn = sqlite3.connect(new_db)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM health_snapshots"
        ).fetchone()[0] == 1
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# B4 — narrative_events merged with memories
# ---------------------------------------------------------------------------


def test_events_merge_narrative_events_and_memories_deduped(
    tmp_path: Path,
) -> None:
    event_ts = _ts(_day(5))
    newer_ts = _ts(_day(6))
    cerebrofy_dir = _seed(
        tmp_path,
        _standard_snapshots(),
        events=[
            ("n1", event_ts, "Auth incident — clock skew", ["auth"], 1.5),
            ("n2", newer_ts, "Viz feature merged", ["viz", "commands"], 0.0),
        ],
        memories=[
            ("m1", "Auth incident — clock skew", event_ts, "auth"),  # duplicate
            ("m2", "Chose SQLite over Postgres", _ts(_day(4)), "db"),
        ],
    )

    narrative = generate_narrative(cerebrofy_dir, force=True)
    titles = [event["event"] for event in narrative.significant_events]

    assert titles.count("Auth incident — clock skew") == 1
    assert "Viz feature merged" in titles
    assert "Chose SQLite over Postgres" in titles
    assert titles[0] == "Viz feature merged"  # newest first
    assert narrative.event_count == 3

    content = (cerebrofy_dir / "NARRATIVE.md").read_text(encoding="utf-8")
    assert "| Auth incident — clock skew | auth |" in content
    assert "Security (blast Δ +1.5)" in content


# ---------------------------------------------------------------------------
# B5 — intent schema via load_intent
# ---------------------------------------------------------------------------


def test_trajectory_uses_real_intent_schema(tmp_path: Path) -> None:
    intent = """
sprint:
  name: Sprint 9
  goal: Ship the narrative engine
  deadline: "2099-12-31"
incidents:
  - id: INC-1
    date: "2026-01-01"
    severity: high
    description: Auth outage
    status: open
  - id: INC-2
    date: "2026-01-02"
    severity: low
    description: Already handled
    status: closed
architecture:
  direction: Reduce cross-lobe coupling
  principles:
    - Keep hooks non-fatal
"""
    cerebrofy_dir = _seed(tmp_path, _standard_snapshots(), intent=intent)
    narrative = generate_narrative(cerebrofy_dir, force=True)

    assert "Ship the narrative engine" in narrative.trajectory
    assert "Open incident (high): Auth outage [open]" in narrative.trajectory
    assert "Already handled" not in narrative.trajectory
    assert "Reduce cross-lobe coupling" in narrative.trajectory
    assert "Keep hooks non-fatal" in narrative.trajectory

    content = (cerebrofy_dir / "NARRATIVE.md").read_text(encoding="utf-8")
    assert "## Where It's Going" in content
    assert "Ship the narrative engine" in content


def test_missing_or_malformed_intent_degrades_gracefully(tmp_path: Path) -> None:
    cerebrofy_dir = _seed(tmp_path, _standard_snapshots())
    narrative = generate_narrative(cerebrofy_dir, force=True)
    assert "No intent.yaml found" in narrative.trajectory

    (cerebrofy_dir / "intent.yaml").write_text("sprint: [unbalanced", encoding="utf-8")
    narrative = generate_narrative(cerebrofy_dir, force=True)
    assert "Could not parse intent.yaml" in narrative.trajectory


# ---------------------------------------------------------------------------
# M1 — current era started is an ISO date
# ---------------------------------------------------------------------------


def test_current_era_started_is_iso_date(tmp_path: Path) -> None:
    cerebrofy_dir = _seed(tmp_path, _standard_snapshots())
    narrative = generate_narrative(cerebrofy_dir, force=True)
    current = narrative.current_era

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(current["started"]))
    assert current["commit"] == "hash3"
    assert current["structural_state"] == {
        "lobes": 4,
        "neurons": 110,
        "coupling": 0.35,
        "avg_blast_radius": 2.0,
    }


# ---------------------------------------------------------------------------
# M2 / M4 — MCP structured output and section extraction
# ---------------------------------------------------------------------------


def test_mcp_returns_real_structured_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("mcp")
    from cerebrofy.mcp.tools.narrative import handle_narrative

    cerebrofy_dir = _seed(
        tmp_path,
        _standard_snapshots(),
        events=[("n1", _ts(_day(5)), "Auth incident", ["auth"], 1.5)],
    )
    generate_narrative(cerebrofy_dir, force=True)
    monkeypatch.chdir(tmp_path)

    result = handle_narrative({"section": "all"})
    payload = json.loads(result[0].text)

    assert payload["era_count"] == 3
    assert payload["event_count"] == 1
    assert payload["last_updated"] > 0
    assert payload["current_era"]["name"] == "Stability"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", payload["current_era"]["started"])

    eras = json.loads(handle_narrative({"section": "eras"})[0].text)
    assert eras["narrative_markdown"].count("## Era ") == 3

    trajectory = json.loads(
        handle_narrative({"section": "trajectory"})[0].text
    )
    assert "Where It's Going" in trajectory["narrative_markdown"]
    assert "Where It's Going" not in eras["narrative_markdown"]

    first_era = json.loads(handle_narrative({"era": 1})[0].text)
    assert first_era["current_era"]["name"] == "Expansion & Coupling shift"
    assert "Expansion & Coupling shift" in first_era["narrative_markdown"]

    updated = json.loads(handle_narrative({"update": True})[0].text)
    assert updated["era_count"] == 3


# ---------------------------------------------------------------------------
# M3 — --since filtering
# ---------------------------------------------------------------------------


def test_cli_since_filters_and_rejects_bad_dates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from click.testing import CliRunner

    from cerebrofy.commands.narrative import cerebrofy_narrative

    cerebrofy_dir = _seed(
        tmp_path,
        _standard_snapshots(),
        events=[
            ("n1", _ts(_day(12)), "Recent event", ["auth"], 0.0),
            ("n2", _ts(_day(2)), "Old event", ["db"], 0.0),
        ],
        memories=[("m1", "Memory in range", _ts(_day(11)), "api")],
    )
    generate_narrative(cerebrofy_dir, force=True)
    monkeypatch.chdir(tmp_path)

    runner = CliRunner()
    result = runner.invoke(cerebrofy_narrative, ["--since", _day(10)])
    assert result.exit_code == 0, result.output
    assert "Significant events since" in result.output
    assert "Recent event" in result.output
    assert "Memory in range" in result.output
    assert "Old event" not in result.output

    bad = runner.invoke(cerebrofy_narrative, ["--since", "not-a-date"])
    assert bad.exit_code == 1
    assert "invalid --since date" in bad.output


# ---------------------------------------------------------------------------
# M5 — 50 KB cap collapses oldest eras
# ---------------------------------------------------------------------------


def test_document_cap_collapses_oldest_eras(tmp_path: Path) -> None:
    snapshots = []
    for index in range(400):
        coupling = 0.10 if index % 2 == 0 else 0.30
        snapshots.append(
            (_ts(_day(index)), coupling, 2.0, 100 + index, 2 + index)
        )
    cerebrofy_dir = _seed(tmp_path, snapshots)
    narrative = generate_narrative(cerebrofy_dir, force=True)
    content = (cerebrofy_dir / "NARRATIVE.md").read_text(encoding="utf-8")

    assert len(content.encode("utf-8")) <= 50 * 1024
    assert "(summarized)" in content
    assert "oldest era(s) are summarized" in content
    assert f"## Era {narrative.era_count}:" in content


# ---------------------------------------------------------------------------
# M7 — auto-update gate
# ---------------------------------------------------------------------------


def test_maybe_update_gate_writes_absent_and_crossing_only(
    tmp_path: Path,
) -> None:
    cerebrofy_dir = _seed(tmp_path, _standard_snapshots())
    narrative_path = cerebrofy_dir / "NARRATIVE.md"

    assert maybe_update_narrative(cerebrofy_dir) is True
    assert narrative_path.exists()

    assert maybe_update_narrative(cerebrofy_dir) is False

    conn = sqlite3.connect(cerebrofy_dir / "db" / "cerebrofy.db")
    conn.execute(
        """
        INSERT INTO health_snapshots (
            build_ts, commit_hash, coupling, avg_blast, neuron_count,
            edge_count, test_surface, lobe_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (_ts(_day(4)), "hash4", 0.90, 2.0, 120, 240, 50.0, 4),
    )
    conn.commit()
    conn.close()

    assert maybe_update_narrative(cerebrofy_dir) is True


# ---------------------------------------------------------------------------
# M9 — commit count header with fallback
# ---------------------------------------------------------------------------


def test_header_includes_commits_and_uses_unknown_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cerebrofy_dir = _seed(tmp_path, _standard_snapshots())
    monkeypatch.setattr(generator, "_commit_count", lambda _dir: None)
    generate_narrative(cerebrofy_dir, force=True)
    content = (cerebrofy_dir / "NARRATIVE.md").read_text(encoding="utf-8")
    assert (
        "*Covers: unknown commits | 3 architectural eras | 0 significant events*"
        in content
    )


# ---------------------------------------------------------------------------
# M10 — DNA from load_arch_rules + health trend, never raises
# ---------------------------------------------------------------------------


def test_dna_uses_arch_rules_and_health_trend(tmp_path: Path) -> None:
    rules = """
rules:
  - name: no-direct-db
    severity: warning
    check:
      no_edge:
        from_lobe: api
        to_lobe: db
  - name: no-cycles
    severity: error
    check:
      no_cycles:
        scope: lobes
"""
    cerebrofy_dir = _seed(tmp_path, _standard_snapshots(), rules=rules)
    narrative = generate_narrative(cerebrofy_dir, force=True)

    assert "Enforces 2 architecture rule(s): no-direct-db, no-cycles" in (
        narrative.architectural_dna
    )
    assert "Trending toward higher coupling" in narrative.architectural_dna


def test_dna_never_raises_on_malformed_rules(tmp_path: Path) -> None:
    cerebrofy_dir = _seed(
        tmp_path, _standard_snapshots(), rules="rules: not-a-list"
    )
    narrative = generate_narrative(cerebrofy_dir, force=True)
    assert narrative.architectural_dna
    assert "Trending toward higher coupling" in narrative.architectural_dna


# ---------------------------------------------------------------------------
# Minor — m1..m4
# ---------------------------------------------------------------------------


def test_insufficient_history_names_prerequisite_and_cli_suggests_update(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cerebrofy_dir = _seed(tmp_path, _standard_snapshots()[:1])
    with pytest.raises(ValueError, match=r"INSUFFICIENT_HISTORY.*3 builds"):
        generate_narrative(cerebrofy_dir)

    from click.testing import CliRunner

    from cerebrofy.commands.narrative import cerebrofy_narrative

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(cerebrofy_narrative, [])
    assert result.exit_code == 1
    assert "INSUFFICIENT_HISTORY" in result.output
    assert "cerebrofy update" in result.output


def test_force_allows_one_era_document(tmp_path: Path) -> None:
    cerebrofy_dir = _seed(tmp_path, _standard_snapshots()[:1])
    narrative = generate_narrative(cerebrofy_dir, force=True)
    assert narrative.era_count == 1
    content = (cerebrofy_dir / "NARRATIVE.md").read_text(encoding="utf-8")
    assert "## Era 1: Stability" in content


def test_output_is_deterministic(tmp_path: Path) -> None:
    cerebrofy_dir = _seed(
        tmp_path,
        _standard_snapshots(),
        events=[
            ("n1", _ts(_day(5)), "B event", ["b"], 0.0),
            ("n2", _ts(_day(5)), "A event", ["a"], 0.0),
        ],
        memories=[("m1", "C event", _ts(_day(4)), "c")],
    )
    generate_narrative(cerebrofy_dir, force=True)
    first = (cerebrofy_dir / "NARRATIVE.md").read_text(encoding="utf-8")
    generate_narrative(cerebrofy_dir, force=True)
    second = (cerebrofy_dir / "NARRATIVE.md").read_text(encoding="utf-8")

    assert first == second
    assert first.index("A event") < first.index("B event")


def test_project_name_prefers_directory_with_fallback(tmp_path: Path) -> None:
    assert generator._project_name(tmp_path / ".cerebrofy") == tmp_path.name
    assert generator._project_name(Path("/") / ".cerebrofy") == "this codebase"


def test_write_is_atomic_and_preserves_old_file_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cerebrofy_dir = _seed(tmp_path, _standard_snapshots())
    narrative_path = cerebrofy_dir / "NARRATIVE.md"
    narrative_path.write_text("original narrative", encoding="utf-8")

    def _boom(src: object, dst: object) -> None:
        raise RuntimeError("replace failed")

    monkeypatch.setattr(generator.os, "replace", _boom)
    with pytest.raises(RuntimeError, match="replace failed"):
        generate_narrative(cerebrofy_dir, force=True)

    assert narrative_path.read_text(encoding="utf-8") == "original narrative"
    assert not (cerebrofy_dir / "NARRATIVE.md.tmp").exists()


# ---------------------------------------------------------------------------
# Schema upgrade + lobe_count persistence
# ---------------------------------------------------------------------------


def test_ensure_health_schema_adds_lobe_count_to_old_db() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            """
            CREATE TABLE health_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                build_ts INTEGER NOT NULL,
                commit_hash TEXT,
                coupling REAL,
                avg_blast REAL,
                dead_code_pct REAL,
                cohesion REAL,
                test_surface REAL,
                drift_velocity REAL,
                hub_concentration REAL,
                neuron_count INTEGER,
                edge_count INTEGER
            )
            """
        )
        ensure_health_schema(conn)
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(health_snapshots)")
        }
        assert "lobe_count" in columns

        metrics = HealthMetrics(
            coupling=0.2,
            avg_blast=3.0,
            dead_code_pct=1.0,
            cohesion=0.6,
            test_surface=55.0,
            drift_velocity=0.5,
            hub_concentration=10.0,
            neuron_count=42,
            edge_count=84,
            hotspots=(),
        )
        record_snapshot(conn, metrics, repo_root="/tmp", lobe_count=7)
        conn.commit()
        latest = fetch_latest_snapshot(conn)
        assert latest is not None
        assert latest["lobe_count"] == 7
    finally:
        conn.close()
