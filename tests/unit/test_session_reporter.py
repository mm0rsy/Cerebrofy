"""Unit tests for cerebrofy.session.reporter (Idea #11)."""

from __future__ import annotations

from typing import Any

from cerebrofy.session.recorder import SessionEvent, SessionRecord
from cerebrofy.session.replay import SessionDiff
from cerebrofy.session.reporter import (
    format_duration,
    format_utc,
    render_html,
    render_markdown,
)


def _session(**overrides: Any) -> SessionRecord:
    base: dict[str, Any] = {
        "id": "sess_abcd1234",
        "task": "Add rate limiting",
        "agent": "claude",
        "started_at": 1_700_000_000,
        "ended_at": 1_700_000_135,
        "outcome": "partial",
        "outcome_notes": "Edge cases left for follow-up",
        "neurons_touched": ("a.py::hub", "b.py::leaf"),
        "blast_radius_before": 3,
        "blast_radius_after": 5,
        "event_count": 2,
    }
    base.update(overrides)
    return SessionRecord(**base)


def _events() -> list[SessionEvent]:
    return [
        SessionEvent(
            session_id="sess_abcd1234",
            ts=1_700_000_010,
            tool="search_code",
            args={"query": "login"},
            result_summary="3 hits",
        ),
        SessionEvent(
            session_id="sess_abcd1234",
            ts=1_700_000_020,
            tool="cerebrofy_impact",
            args={"target": "hub"},
            result_summary=None,
        ),
    ]


def _diff(**overrides: Any) -> SessionDiff:
    base: dict[str, Any] = {
        "touched": ("a.py::hub",),
        "present": ("a.py::hub",),
        "missing": (),
        "appeared": (),
        "graph_refreshed": False,
        "blast_radius_before": 3,
        "blast_radius_after": 5,
    }
    base.update(overrides)
    return SessionDiff(**base)


# ---------------------------------------------------------------------------
# format_utc / format_duration
# ---------------------------------------------------------------------------

def test_format_utc_none_and_epoch() -> None:
    assert format_utc(None) == "—"
    assert format_utc(0) == "1970-01-01 00:00:00 UTC"
    assert format_utc(1_700_000_000) == "2023-11-14 22:13:20 UTC"


def test_format_duration_buckets() -> None:
    assert format_duration(0) == "0s"
    assert format_duration(59) == "59s"
    assert format_duration(60) == "1m 0s"
    assert format_duration(135) == "2m 15s"
    assert format_duration(3600) == "1h 0m"
    assert format_duration(7380) == "2h 3m"


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def test_render_markdown_contains_session_facts_and_timeline() -> None:
    md = render_markdown(_session(), _events(), _diff())
    assert "# Session Replay — `sess_abcd1234`" in md
    assert "**Task:** Add rate limiting" in md
    assert "**Agent:** claude" in md
    assert "**Outcome:** 🟡 partial" in md
    assert "Edge cases left for follow-up" in md
    assert "2m 15s" in md
    assert "`search_code`" in md
    assert "query=login" in md
    assert "3 hits" in md
    assert "`cerebrofy_impact`" in md
    assert "⚠️ increased" in md


def test_render_markdown_empty_events_and_no_diff() -> None:
    md = render_markdown(_session(event_count=0, blast_radius_before=None,
                                 blast_radius_after=None), [], None)
    assert "_No events recorded._" in md
    assert "| Blast radius before | — |" in md
    assert "| Verdict | ⚪ unknown |" in md
    assert "## Graph Diff" not in md


def test_render_markdown_running_session_shows_running() -> None:
    md = render_markdown(_session(ended_at=None, outcome="unknown", outcome_notes=None), [], None)
    assert "(running)" in md
    assert "**Outcome:** ⚪ unknown" in md


def test_render_markdown_diff_details_and_escaped_pipes() -> None:
    diff = _diff(
        touched=("a.py::hub", "a.py::caller"),
        missing=("b.py::leaf",),
        appeared=("c.py::new",),
        graph_refreshed=True,
    )
    event = SessionEvent(
        session_id="sess_abcd1234",
        ts=1_700_000_010,
        tool="search_code",
        args={"query": "a|b"},
        result_summary="left|right",
    )
    md = render_markdown(_session(), [event], diff)
    assert "**Touched**: 2 neuron(s) — `hub`, `caller`" in md
    assert "**No longer in index**: `leaf`" in md
    assert "**Appeared during session**: `new`" in md
    assert "**Index refreshed mid-session**" in md
    assert "query=a\\|b" in md
    assert "left\\|right" in md


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def test_render_html_is_self_contained() -> None:
    html_doc = render_html(_session(), _events(), _diff())
    assert html_doc.startswith("<!DOCTYPE html>")
    assert "Session Replay" in html_doc
    assert "sess_abcd1234" in html_doc
    assert "<script" not in html_doc
    assert "http://" not in html_doc
    assert "https://" not in html_doc
    # Inline CSS only, no external link/stylesheet.
    assert "<link" not in html_doc
    assert "<style>" in html_doc


def test_render_html_escapes_all_dynamic_content() -> None:
    hostile = '<script>alert("x")</script>'
    session = _session(
        task=hostile,
        agent="<img src=x onerror=alert(1)>",
        outcome_notes="Fish & chips <b>bold</b>",
    )
    event = SessionEvent(
        session_id="sess_abcd1234",
        ts=1,
        tool="<b>evil</b>",
        args={"query": hostile},
        result_summary="result <script>bad()</script>",
    )
    html_doc = render_html(session, [event], _diff(missing=("a.py::<x>",)))

    assert hostile not in html_doc
    assert "<script>alert" not in html_doc
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html_doc
    assert "&lt;img src=x onerror=alert(1)&gt;" in html_doc
    assert "Fish &amp; chips &lt;b&gt;bold&lt;/b&gt;" in html_doc
    assert "&lt;b&gt;evil&lt;/b&gt;" in html_doc
    assert "result &lt;script&gt;bad()&lt;/script&gt;" in html_doc
    assert "&lt;x&gt;" in html_doc


def test_render_html_running_session_and_unknown_verdict() -> None:
    html_doc = render_html(_session(ended_at=None, outcome="unknown"), [], None)
    assert "(running)" in html_doc
    assert "⚪ unknown" in html_doc


def test_render_html_empty_events() -> None:
    html_doc = render_html(_session(event_count=0), [], None)
    assert "<em>No events recorded.</em>" in html_doc
