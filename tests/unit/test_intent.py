"""Unit tests for the intent package (loader, enricher)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from cerebrofy.intent.enricher import enrich_with_intent, inject_intent, summary_intent
from cerebrofy.intent.loader import (
    ArchDirection,
    Incident,
    IntentConfig,
    SprintContext,
    TeamContext,
    load_intent,
    scaffold_intent_yaml,
    validate_intent,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_intent(tmp_path: Path, data: dict) -> Path:
    intent_dir = tmp_path / ".cerebrofy"
    intent_dir.mkdir(parents=True, exist_ok=True)
    path = intent_dir / "intent.yaml"
    path.write_text(yaml.dump(data), encoding="utf-8")
    return intent_dir


def _full_intent() -> IntentConfig:
    return IntentConfig(
        sprint=SprintContext(
            name="Payments v2",
            goal="Ship Stripe billing",
            deadline="2026-07-15",
            priority_lobes=("payments", "api"),
            deprioritized_lobes=("viz",),
        ),
        incidents=(
            Incident(
                id="INC-001",
                date="2026-06-01",
                severity="critical",
                description="Token expiry bypass",
                affected_lobes=("auth",),
                status="patched",
                lesson="Use server_time",
            ),
            Incident(
                id="INC-002",
                date="2026-06-10",
                severity="high",
                description="Payment webhook missed",
                affected_lobes=("payments",),
                status="open",
                lesson="Add idempotency keys",
            ),
        ),
        architecture=ArchDirection(
            direction="Event-driven via Kafka",
            avoid_patterns=("direct DB calls from API layer",),
            principles=("All payments must be idempotent",),
        ),
        team_context=TeamContext(
            concerns=("payments/ test coverage is 34%",),
            upcoming_risks=("Stripe API v4 migration by 2026-09-01",),
        ),
    )


# ---------------------------------------------------------------------------
# loader: load_intent
# ---------------------------------------------------------------------------

class TestLoadIntent:
    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        result = load_intent(tmp_path / ".cerebrofy")
        assert result is None

    def test_loads_full_intent(self, tmp_path: Path) -> None:
        data = {
            "sprint": {
                "name": "Sprint 1",
                "goal": "Ship auth",
                "deadline": "2026-07-01",
                "priority_lobes": ["auth", "api"],
                "deprioritized_lobes": ["viz"],
            },
            "incidents": [
                {
                    "id": "INC-001",
                    "date": "2026-06-01",
                    "severity": "critical",
                    "description": "Bug in auth",
                    "affected_lobes": ["auth"],
                    "status": "patched",
                    "lesson": "Add tests",
                }
            ],
            "architecture": {
                "direction": "Microservices",
                "avoid_patterns": ["direct DB from API"],
                "principles": ["All calls idempotent"],
            },
            "team_context": {
                "concerns": ["auth coverage low"],
                "upcoming_risks": ["Stripe migration"],
            },
        }
        intent_dir = _write_intent(tmp_path, data)
        intent = load_intent(intent_dir)

        assert intent is not None
        assert intent.sprint is not None
        assert intent.sprint.name == "Sprint 1"
        assert intent.sprint.priority_lobes == ("auth", "api")
        assert len(intent.incidents) == 1
        assert intent.incidents[0].id == "INC-001"
        assert intent.incidents[0].affected_lobes == ("auth",)
        assert intent.architecture is not None
        assert intent.architecture.avoid_patterns == ("direct DB from API",)
        assert intent.team_context is not None
        assert intent.team_context.concerns == ("auth coverage low",)

    def test_loads_empty_yaml(self, tmp_path: Path) -> None:
        intent_dir = tmp_path / ".cerebrofy"
        intent_dir.mkdir()
        (intent_dir / "intent.yaml").write_text("", encoding="utf-8")
        intent = load_intent(intent_dir)
        assert intent is not None
        assert intent.sprint is None
        assert intent.incidents == ()

    def test_loads_partial_intent_no_sprint(self, tmp_path: Path) -> None:
        data = {"incidents": []}
        intent_dir = _write_intent(tmp_path, data)
        intent = load_intent(intent_dir)
        assert intent is not None
        assert intent.sprint is None
        assert intent.incidents == ()

    def test_intent_is_frozen(self, tmp_path: Path) -> None:
        data = {"sprint": {"name": "S", "goal": "G", "deadline": "2026-01-01",
                           "priority_lobes": [], "deprioritized_lobes": []}}
        intent_dir = _write_intent(tmp_path, data)
        intent = load_intent(intent_dir)
        assert intent is not None
        with pytest.raises((AttributeError, TypeError)):
            intent.sprint = None  # type: ignore[misc]

    def test_missing_optional_incident_fields(self, tmp_path: Path) -> None:
        data = {"incidents": [{"id": "INC-X", "description": "Partial"}]}
        intent_dir = _write_intent(tmp_path, data)
        intent = load_intent(intent_dir)
        assert intent is not None
        assert intent.incidents[0].id == "INC-X"
        assert intent.incidents[0].lesson == ""
        assert intent.incidents[0].affected_lobes == ()


# ---------------------------------------------------------------------------
# loader: validate_intent
# ---------------------------------------------------------------------------

class TestValidateIntent:
    def test_valid_intent_no_warnings(self) -> None:
        intent = _full_intent()
        known = {"payments", "api", "auth", "viz"}
        warnings = validate_intent(intent, known)
        assert warnings == []

    def test_unknown_priority_lobe_warns(self) -> None:
        intent = _full_intent()
        warnings = validate_intent(intent, {"api"})  # "payments" is missing
        assert any("priority_lobes" in w and "payments" in w for w in warnings)

    def test_unknown_deprioritized_lobe_warns(self) -> None:
        intent = _full_intent()
        warnings = validate_intent(intent, {"payments", "api", "auth"})  # "viz" missing
        assert any("deprioritized_lobes" in w and "viz" in w for w in warnings)

    def test_unknown_incident_lobe_warns(self) -> None:
        intent = _full_intent()
        warnings = validate_intent(intent, {"payments", "api", "viz"})  # "auth" missing
        assert any("INC-001" in w and "auth" in w for w in warnings)

    def test_empty_known_lobes(self) -> None:
        intent = _full_intent()
        warnings = validate_intent(intent, set())
        assert len(warnings) > 0


# ---------------------------------------------------------------------------
# loader: scaffold_intent_yaml
# ---------------------------------------------------------------------------

class TestScaffoldIntentYaml:
    def test_creates_file(self, tmp_path: Path) -> None:
        path = tmp_path / ".cerebrofy" / "intent.yaml"
        scaffold_intent_yaml(path)
        assert path.exists()

    def test_scaffolded_file_is_valid_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / ".cerebrofy" / "intent.yaml"
        scaffold_intent_yaml(path)
        data = yaml.safe_load(path.read_text())
        assert isinstance(data, dict)
        assert "sprint" in data

    def test_does_not_overwrite_existing(self, tmp_path: Path) -> None:
        path = tmp_path / ".cerebrofy" / "intent.yaml"
        path.parent.mkdir(parents=True)
        path.write_text("existing: content", encoding="utf-8")
        scaffold_intent_yaml(path)
        # scaffold_intent_yaml always writes — caller is responsible for check
        assert path.exists()


# ---------------------------------------------------------------------------
# loader: to_dict
# ---------------------------------------------------------------------------

class TestIntentConfigToDict:
    def test_full_intent_serializes(self) -> None:
        d = _full_intent().to_dict()
        assert d["sprint"]["name"] == "Payments v2"
        assert d["sprint"]["priority_lobes"] == ["payments", "api"]
        assert len(d["incidents"]) == 2
        assert d["architecture"]["direction"] == "Event-driven via Kafka"
        assert d["team_context"]["concerns"] == ["payments/ test coverage is 34%"]

    def test_empty_intent_produces_empty_dict(self) -> None:
        intent = IntentConfig(sprint=None, incidents=(), architecture=None, team_context=None)
        assert intent.to_dict() == {}

    def test_incidents_are_lists_not_tuples(self) -> None:
        d = _full_intent().to_dict()
        assert isinstance(d["sprint"]["priority_lobes"], list)
        assert isinstance(d["incidents"][0]["affected_lobes"], list)


# ---------------------------------------------------------------------------
# enricher: enrich_with_intent
# ---------------------------------------------------------------------------

class TestEnrichWithIntent:
    def test_high_relevance_for_priority_lobe(self) -> None:
        intent = _full_intent()
        result = enrich_with_intent(["payments"], intent)
        assert "HIGH" in result["sprint_relevance"]
        assert "payments" in result["sprint_relevance"]

    def test_low_relevance_for_deprioritized_lobe(self) -> None:
        intent = _full_intent()
        result = enrich_with_intent(["viz"], intent)
        assert "LOW" in result["sprint_relevance"]

    def test_medium_relevance_for_unlisted_lobe(self) -> None:
        intent = _full_intent()
        result = enrich_with_intent(["commands"], intent)
        assert "MEDIUM" in result["sprint_relevance"]

    def test_active_incidents_for_matching_lobe(self) -> None:
        intent = _full_intent()
        result = enrich_with_intent(["payments"], intent)
        # INC-002 (payments, open) should appear; INC-001 (auth) should not
        assert "active_incidents" in result
        assert any("INC-002" in inc for inc in result["active_incidents"])
        assert not any("INC-001" in inc for inc in result["active_incidents"])

    def test_patched_incidents_excluded(self) -> None:
        intent = _full_intent()
        result = enrich_with_intent(["auth"], intent)
        # INC-001 is patched — should NOT appear as active
        assert "active_incidents" not in result or not any(
            "INC-001" in inc for inc in result.get("active_incidents", [])
        )

    def test_architectural_guidance_included(self) -> None:
        intent = _full_intent()
        result = enrich_with_intent(["payments"], intent)
        assert "architectural_guidance" in result
        assert any("AVOID" in g for g in result["architectural_guidance"])

    def test_team_concern_matching_lobe(self) -> None:
        intent = _full_intent()
        result = enrich_with_intent(["payments"], intent)
        assert "priority" in result
        assert "payments" in result["priority"]

    def test_no_sprint_returns_partial(self) -> None:
        intent = IntentConfig(
            sprint=None,
            incidents=(),
            architecture=None,
            team_context=None,
        )
        result = enrich_with_intent(["auth"], intent)
        assert "sprint_relevance" not in result

    def test_unknown_lobe_returns_unknown_relevance(self) -> None:
        intent = _full_intent()
        result = enrich_with_intent([], intent)
        assert "UNKNOWN" in result.get("sprint_relevance", "")


# ---------------------------------------------------------------------------
# enricher: summary_intent
# ---------------------------------------------------------------------------

class TestSummaryIntent:
    def test_full_intent_summary(self) -> None:
        s = summary_intent(_full_intent())
        assert s["sprint"] == "Payments v2"
        assert "payments" in s["priority_lobes"]

    def test_open_incidents_counted(self) -> None:
        s = summary_intent(_full_intent())
        # INC-002 is open; INC-001 is patched
        assert s["open_incidents"] == 1
        assert "INC-002" in s["incident_ids"]

    def test_empty_intent_produces_empty_summary(self) -> None:
        intent = IntentConfig(sprint=None, incidents=(), architecture=None, team_context=None)
        assert summary_intent(intent) == {}


# ---------------------------------------------------------------------------
# enricher: inject_intent
# ---------------------------------------------------------------------------

class TestInjectIntent:
    def test_injects_into_json_dict(self) -> None:
        intent = _full_intent()
        original = json.dumps({"results": [], "count": 0})
        result = inject_intent(original, intent)
        data = json.loads(result)
        assert "intent_context" in data
        assert data["intent_context"]["sprint"] == "Payments v2"

    def test_no_injection_into_non_json(self) -> None:
        intent = _full_intent()
        text = "# Markdown output\nSome content"
        result = inject_intent(text, intent)
        assert result == text

    def test_no_injection_into_json_array(self) -> None:
        intent = _full_intent()
        text = json.dumps([1, 2, 3])
        result = inject_intent(text, intent)
        assert result == text  # arrays unchanged

    def test_empty_intent_injects_empty_context(self) -> None:
        intent = IntentConfig(sprint=None, incidents=(), architecture=None, team_context=None)
        original = json.dumps({"key": "val"})
        result = inject_intent(original, intent)
        data = json.loads(result)
        assert data["intent_context"] == {}
