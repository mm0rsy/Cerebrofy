"""Unit tests for context package: token_counter, scorer, optimizer, exporter."""

from __future__ import annotations


from cerebrofy.context.token_counter import count_tokens, tokens_for_source
from cerebrofy.context.scorer import compute_relevance
from cerebrofy.context.optimizer import (
    ContextNeuron,
    ContextPlan,
    EpistemicInfo,
    _compute_epistemic,
    _lobe_from_file,
    _read_lobe_summary,
    _signature_text,
)
from cerebrofy.context.exporter import to_json, to_markdown, to_claude_xml


# ---------------------------------------------------------------------------
# token_counter
# ---------------------------------------------------------------------------

def test_count_tokens_empty():
    assert count_tokens("") == 0


def test_count_tokens_heuristic():
    text = "a" * 400
    assert count_tokens(text) == 100  # 400 // 4


def test_count_tokens_minimum_one():
    assert count_tokens("x") == 1


def test_tokens_for_source_reads_lines(tmp_path):
    f = tmp_path / "auth.py"
    f.write_text("line1\nline2\nline3\nline4\nline5\n")
    source, tokens = tokens_for_source("auth.py", 2, 4, str(tmp_path))
    assert "line2" in source
    assert "line4" in source
    assert "line1" not in source
    assert tokens > 0


def test_tokens_for_source_missing_file(tmp_path):
    source, tokens = tokens_for_source("missing.py", 1, 10, str(tmp_path))
    assert source == ""
    assert tokens == 0


# ---------------------------------------------------------------------------
# scorer
# ---------------------------------------------------------------------------

def test_relevance_seed_high():
    score = compute_relevance(1.0, is_seed=True)
    assert score == 1.0  # 1.0*0.6 + 1.0*0.4


def test_relevance_neighbor():
    score = compute_relevance(0.0, is_seed=False)
    assert score == 0.2  # 0.0*0.6 + 0.5*0.4


def test_relevance_seed_beats_neighbor():
    seed = compute_relevance(0.5, is_seed=True)
    neighbor = compute_relevance(0.5, is_seed=False)
    assert seed > neighbor


# ---------------------------------------------------------------------------
# optimizer helpers
# ---------------------------------------------------------------------------

def test_lobe_from_nested_file():
    assert _lobe_from_file("auth/tokens.py") == "auth"


def test_lobe_from_root_file():
    assert _lobe_from_file("main.py") == ""


def test_signature_text_with_sig_and_doc():
    result = _signature_text("my_fn", "def my_fn(x: int) -> bool:", "Does something.")
    assert "def my_fn" in result
    assert "Does something" in result


def test_signature_text_fallback():
    result = _signature_text("my_fn", None, None)
    assert "my_fn" in result


def test_read_lobe_summary_missing(tmp_path):
    text, tokens = _read_lobe_summary("nonexistent", tmp_path)
    assert text == ""
    assert tokens == 0


def test_read_lobe_summary_found(tmp_path):
    lobes_dir = tmp_path / ".cerebrofy" / "lobes"
    lobes_dir.mkdir(parents=True)
    (lobes_dir / "auth_lobe.md").write_text("# Auth module\nHandles tokens.")
    text, tokens = _read_lobe_summary("auth", tmp_path)
    assert "Auth module" in text
    assert tokens > 0


def test_compute_epistemic_fresh(tmp_path):
    db = tmp_path / "cerebrofy.db"
    db.write_bytes(b"")
    info = _compute_epistemic(db)
    assert info.confidence == 1.0
    assert info.graph_age_hours < 1.0
    assert info.caveats == []


def test_compute_epistemic_missing_db(tmp_path):
    info = _compute_epistemic(tmp_path / "missing.db")
    assert info.confidence == 1.0
    assert info.graph_age_hours == 0.0


# ---------------------------------------------------------------------------
# exporter
# ---------------------------------------------------------------------------

def _make_plan() -> ContextPlan:
    n = ContextNeuron(
        id="auth/tokens.py::validate_token",
        name="validate_token",
        file="auth/tokens.py",
        line_start=42,
        line_end=60,
        relevance_score=0.94,
        inclusion_tier="full_source",
        source="semantic",
        content="def validate_token(token: str) -> bool:\n    ...",
        tokens=40,
    )
    epistemic = EpistemicInfo(
        confidence=1.0,
        graph_age_hours=0.5,
        caveats=[],
        recommendation="Index is fresh.",
    )
    return ContextPlan(
        task="fix the JWT validation bug",
        token_budget=8000,
        tokens_used=40,
        neurons=[n],
        lobe_summaries_included=[],
        truncated_count=0,
        epistemic=epistemic,
    )


def test_to_json_structure():
    import json
    plan = _make_plan()
    out = json.loads(to_json(plan))
    assert out["task"] == "fix the JWT validation bug"
    assert out["tokens_used"] == 40
    assert len(out["neurons"]) == 1
    assert out["neurons"][0]["name"] == "validate_token"
    assert "epistemic" in out


def test_to_markdown_contains_neuron():
    plan = _make_plan()
    md = to_markdown(plan)
    assert "validate_token" in md
    assert "full_source" in md
    assert "fix the JWT validation bug" in md


def test_to_claude_xml_structure():
    plan = _make_plan()
    xml = to_claude_xml(plan)
    assert "<documents>" in xml
    assert "<document index=" in xml
    assert "validate_token" in xml
    assert "fix the JWT validation bug" in xml


def test_to_claude_xml_escapes_special_chars():
    plan = _make_plan()
    plan.task = "handle <tags> & 'quotes'"
    xml = to_claude_xml(plan)
    assert "<tags>" not in xml
    assert "&lt;tags&gt;" in xml
    assert "&amp;" in xml


def test_to_json_no_epistemic():
    import json
    plan = _make_plan()
    plan.epistemic = None
    out = json.loads(to_json(plan))
    assert "epistemic" not in out
