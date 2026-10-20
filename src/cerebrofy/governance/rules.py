"""Governance rule DSL: parsing (``governance.rules`` in arch-rules.yaml) and
evaluation against the live call graph.

The rules are *reporting only* — they never block a merge and never modify the
repository. Each rule has one ``if_*`` condition and one or more ``then_*``
requirements::

    governance:
      rules:
        - name: high-blast-requires-two-reviews
          description: Any PR touching blast_radius > 30 requires 2 approvals
          check:
            if_blast_radius: { gt: 30 }
            then_require_approvals: 2

This module is intentionally light at import time: :mod:`cerebrofy.arch.rules`
imports the parser, so heavy ownership/graph imports happen only when rules are
actually evaluated.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from cerebrofy.governance.ownership import LobeOwnership
    from cerebrofy.governance.reviewer import ChangeSet


class GovernanceRulesError(ValueError):
    """Raised when the ``governance`` block of arch-rules.yaml is malformed."""


# ---------------------------------------------------------------------------
# Rule model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IfBlastRadius:
    gt: int


@dataclass(frozen=True)
class IfBusFactor:
    eq: int


@dataclass(frozen=True)
class IfNewNeurons:
    enabled: bool = True


Condition = IfBlastRadius | IfBusFactor | IfNewNeurons


@dataclass(frozen=True)
class GovernanceRule:
    name: str
    condition: Condition
    description: str = ""
    require_approvals: int | None = None
    require_non_owner_review: bool = False
    require_test_file: bool = False


@dataclass(frozen=True)
class GovernanceRulesConfig:
    rules: tuple[GovernanceRule, ...] = ()

    @property
    def rule_names(self) -> tuple[str, ...]:
        return tuple(rule.name for rule in self.rules)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_IF_KEYS = ("if_blast_radius", "if_bus_factor", "if_new_neurons")
_THEN_KEYS = (
    "then_require_approvals",
    "then_require_non_owner_review",
    "then_require_test_file",
)


def parse_governance_config(
    raw: object,
    path: Path,
) -> GovernanceRulesConfig | None:
    """Parse the optional top-level ``governance`` mapping.

    Returns ``None`` when the section is absent. Raises
    :class:`GovernanceRulesError` for malformed content; the arch-rules loader
    wraps this into its own ``RulesError``.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise GovernanceRulesError(f"{path}: 'governance' must be a mapping")
    unknown = set(raw) - {"rules"}
    if unknown:
        raise GovernanceRulesError(
            f"{path}: governance has unknown key(s): {sorted(unknown)}"
        )
    raw_rules = raw.get("rules") or []
    if not isinstance(raw_rules, list):
        raise GovernanceRulesError(
            f"{path}: governance.rules must be a list of rule mappings"
        )

    rules: list[GovernanceRule] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_rules):
        rule = _parse_rule(index, item, path)
        if rule.name in seen:
            raise GovernanceRulesError(
                f"{path}: duplicate governance rule name '{rule.name}'"
            )
        seen.add(rule.name)
        rules.append(rule)
    return GovernanceRulesConfig(rules=tuple(rules))


def _parse_rule(index: int, raw: object, path: Path) -> GovernanceRule:
    prefix = f"{path}: governance.rules[{index}]"
    if not isinstance(raw, dict):
        raise GovernanceRulesError(f"{prefix}: each rule must be a mapping")

    name = str(raw.get("name") or "").strip()
    if not name:
        raise GovernanceRulesError(f"{prefix}: missing required field 'name'")
    description = str(raw.get("description") or "").strip()

    check = raw.get("check")
    if not isinstance(check, dict) or not check:
        raise GovernanceRulesError(f"{prefix} ({name}): 'check' mapping is required")

    unknown = set(check) - set(_IF_KEYS) - set(_THEN_KEYS)
    if unknown:
        raise GovernanceRulesError(
            f"{prefix} ({name}): unknown governance check key(s): {sorted(unknown)}"
        )
    if_keys = [key for key in _IF_KEYS if key in check]
    if len(if_keys) != 1:
        raise GovernanceRulesError(
            f"{prefix} ({name}): 'check' needs exactly one if_* condition, "
            f"got {if_keys or 'none'}"
        )
    then_keys = [key for key in _THEN_KEYS if key in check]
    if not then_keys:
        raise GovernanceRulesError(
            f"{prefix} ({name}): 'check' needs at least one then_* requirement"
        )

    condition = _parse_condition(prefix, name, if_keys[0], check[if_keys[0]])
    require_approvals: int | None = None
    require_non_owner = False
    require_test_file = False
    for key in then_keys:
        value = check[key]
        if key == "then_require_approvals":
            require_approvals = _positive_int(prefix, name, key, value)
        elif key == "then_require_non_owner_review":
            if not isinstance(value, bool):
                raise GovernanceRulesError(
                    f"{prefix} ({name}): '{key}' must be a boolean"
                )
            require_non_owner = value
        else:
            if not isinstance(value, bool):
                raise GovernanceRulesError(
                    f"{prefix} ({name}): '{key}' must be a boolean"
                )
            require_test_file = value

    return GovernanceRule(
        name=name,
        description=description,
        condition=condition,
        require_approvals=require_approvals,
        require_non_owner_review=require_non_owner,
        require_test_file=require_test_file,
    )


def _parse_condition(prefix: str, name: str, key: str, value: object) -> Condition:
    if key == "if_blast_radius":
        return IfBlastRadius(gt=_threshold(prefix, name, key, value, "gt"))
    if key == "if_bus_factor":
        return IfBusFactor(eq=_threshold(prefix, name, key, value, "eq"))
    if isinstance(value, dict):
        unknown = set(value) - {"enabled"}
        if unknown:
            raise GovernanceRulesError(
                f"{prefix} ({name}): '{key}' has unknown key(s): {sorted(unknown)}"
            )
        value = value.get("enabled", True)
    if not isinstance(value, bool):
        raise GovernanceRulesError(f"{prefix} ({name}): '{key}' must be a boolean")
    return IfNewNeurons(enabled=value)


def _threshold(prefix: str, name: str, key: str, value: object, field: str) -> int:
    if isinstance(value, dict):
        unknown = set(value) - {field}
        if unknown:
            raise GovernanceRulesError(
                f"{prefix} ({name}): '{key}' has unknown key(s): {sorted(unknown)}"
            )
        value = value.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GovernanceRulesError(
            f"{prefix} ({name}): '{key}.{field}' must be a non-negative integer"
        )
    return int(value)


def _positive_int(prefix: str, name: str, key: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise GovernanceRulesError(
            f"{prefix} ({name}): '{key}' must be a positive integer"
        )
    return int(value)


def governance_to_dict(config: GovernanceRulesConfig) -> dict[str, Any]:
    """Serialize a governance config back to its YAML shape."""
    rules: list[dict[str, Any]] = []
    for rule in config.rules:
        check: dict[str, Any] = {}
        condition = rule.condition
        if isinstance(condition, IfBlastRadius):
            check["if_blast_radius"] = {"gt": condition.gt}
        elif isinstance(condition, IfBusFactor):
            check["if_bus_factor"] = {"eq": condition.eq}
        else:
            check["if_new_neurons"] = condition.enabled
        if rule.require_approvals is not None:
            check["then_require_approvals"] = rule.require_approvals
        if rule.require_non_owner_review:
            check["then_require_non_owner_review"] = True
        if rule.require_test_file:
            check["then_require_test_file"] = True
        payload: dict[str, Any] = {"name": rule.name}
        if rule.description:
            payload["description"] = rule.description
        payload["check"] = check
        rules.append(payload)
    return {"rules": rules}


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuleEvaluation:
    """Outcome of one governance rule."""

    name: str
    description: str
    status: str  # PASS | WARN | FAIL
    reason: str
    triggered: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "status": self.status,
            "reason": self.reason,
            "triggered": self.triggered,
        }


@dataclass(frozen=True)
class GovernanceCheckResult:
    """Aggregated governance rule evaluation."""

    evaluations: tuple[RuleEvaluation, ...] = ()

    @property
    def rules_checked(self) -> int:
        return len(self.evaluations)

    @property
    def passing(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.evaluations if item.status == "PASS")

    @property
    def failing(self) -> tuple[RuleEvaluation, ...]:
        return tuple(item for item in self.evaluations if item.status == "FAIL")

    @property
    def warnings(self) -> tuple[RuleEvaluation, ...]:
        return tuple(item for item in self.evaluations if item.status == "WARN")

    @property
    def result(self) -> str:
        if self.failing:
            return "FAIL"
        if self.warnings:
            return "WARN"
        return "PASS"

    def to_dict(self) -> dict[str, object]:
        return {
            "rules_checked": self.rules_checked,
            "passing": list(self.passing),
            "failing": [item.to_dict() for item in self.failing],
            "warnings": [item.to_dict() for item in self.warnings],
            "result": self.result,
        }


def _is_test_file(path: str) -> bool:
    normalised = path.replace("\\", "/")
    name = normalised.rsplit("/", 1)[-1]
    return (
        name.startswith("test_")
        or name.endswith("_test.py")
        or normalised.startswith("tests/")
        or "/tests/" in normalised
    )


def _target_lobes(
    lobes: dict[str, str],
    changes: ChangeSet | None,
    lobe: str | None,
) -> list[str]:
    if lobe is not None:
        return [lobe]
    if changes is not None and changes.files:
        from cerebrofy.governance.ownership import lobe_for_file

        found = {lobe_for_file(path, lobes) for path in changes.files}
        found.discard("__unknown__")
        if found:
            return sorted(found)
    return sorted(lobes)


def _blast_radius(
    conn: sqlite3.Connection,
    lobes: dict[str, str],
    changes: ChangeSet | None,
    lobe: str | None,
) -> int:
    from cerebrofy.governance.ownership import max_blast_radius

    if changes is not None and changes.files:
        return max_blast_radius(
            conn, lobes, changed_files=frozenset(changes.files)
        )
    if lobe is not None:
        return max_blast_radius(conn, lobes, lobe=lobe)
    return max_blast_radius(conn, lobes)


def _normalise_identity(value: str) -> str:
    cleaned = value.strip().lstrip("@").lower()
    # GitHub reviewer logins have no domain; compare them with the local part
    # of ownership emails so "@alice" matches "alice@example.com".
    return cleaned.split("@", 1)[0]


def _requirement_outcomes(
    rule: GovernanceRule,
    changes: ChangeSet | None,
    owners: tuple[str, ...],
) -> list[tuple[str, str]]:
    outcomes: list[tuple[str, str]] = []

    if rule.require_approvals is not None:
        required = rule.require_approvals
        if changes is None or changes.approvals is None:
            outcomes.append(
                ("WARN", f"requires {required} approval(s); no PR metadata available")
            )
        elif changes.approvals < required:
            outcomes.append(
                ("FAIL", f"has {changes.approvals} approval(s); {required} required")
            )
        else:
            outcomes.append(
                ("PASS", f"has {changes.approvals} approval(s); {required} required")
            )

    if rule.require_non_owner_review:
        if changes is None or changes.reviewers is None:
            outcomes.append(
                ("WARN", "requires a non-owner reviewer; no PR review metadata available")
            )
        elif not changes.reviewers:
            outcomes.append(("FAIL", "requires a non-owner reviewer; no reviews recorded yet"))
        else:
            owner_ids = {_normalise_identity(owner) for owner in owners}
            non_owners = [
                reviewer
                for reviewer in changes.reviewers
                if _normalise_identity(reviewer) not in owner_ids
            ]
            if non_owners:
                outcomes.append(
                    ("PASS", f"non-owner reviewer present ({non_owners[0]})")
                )
            else:
                outcomes.append(("FAIL", "all reviewers are lobe owners"))

    if rule.require_test_file:
        files = list(changes.files) if changes is not None else []
        test_files = [path for path in files if _is_test_file(path)]
        if test_files:
            outcomes.append(("PASS", f"test file changed ({test_files[0]})"))
        else:
            outcomes.append(("FAIL", "new neurons require a changed test file"))

    return outcomes


def evaluate_governance_rules(
    config: GovernanceRulesConfig,
    conn: sqlite3.Connection,
    repo_root: Path,
    lobes: dict[str, str],
    *,
    changes: ChangeSet | None = None,
    lobe: str | None = None,
    strategy: str = "git-blame",
    activity_days: int = 90,
    ownership: dict[str, LobeOwnership] | None = None,
) -> GovernanceCheckResult:
    """Evaluate every governance rule in the requested scope."""
    targets = _target_lobes(lobes, changes, lobe)
    if lobe is not None and lobe not in lobes:
        raise ValueError(f"Unknown lobe '{lobe}' — not present in .cerebrofy/config.yaml")

    profiles = ownership
    if profiles is None and any(
        isinstance(rule.condition, IfBusFactor) for rule in config.rules
    ):
        from cerebrofy.governance.ownership import compute_all_lobe_ownership

        profiles = compute_all_lobe_ownership(
            conn,
            repo_root,
            lobes,
            strategy=strategy,
            activity_days=activity_days,
        )

    blast: int | None = None
    new_neurons = len(changes.new_neurons) if changes is not None else 0
    evaluations: list[RuleEvaluation] = []

    for rule in config.rules:
        condition = rule.condition
        triggered = False
        if isinstance(condition, IfBlastRadius):
            if blast is None:
                blast = _blast_radius(conn, lobes, changes, lobe)
            triggered = blast > condition.gt
            condition_text = f"blast_radius={blast} (threshold: >{condition.gt})"
        elif isinstance(condition, IfBusFactor):
            assert profiles is not None  # computed above
            hits = [
                name
                for name in targets
                if profiles.get(name) is not None
                and profiles[name].bus_factor == condition.eq
            ]
            triggered = bool(hits)
            if hits:
                condition_text = (
                    f"bus_factor={condition.eq} for lobe(s) {', '.join(hits)}"
                )
            else:
                condition_text = f"bus_factor={condition.eq} (no matching lobe)"
        else:
            triggered = condition.enabled and new_neurons > 0
            condition_text = f"new_neurons={new_neurons}"

        if not triggered:
            evaluations.append(
                RuleEvaluation(
                    name=rule.name,
                    description=rule.description,
                    status="PASS",
                    reason=f"condition not met — {condition_text}",
                    triggered=False,
                )
            )
            continue

        owners: tuple[str, ...] = ()
        if profiles is not None:
            owners = tuple(
                profile.primary
                for name in targets
                if (profile := profiles.get(name)) is not None and profile.primary
            )
        outcomes = _requirement_outcomes(rule, changes, owners)
        if not outcomes:
            outcomes = [("PASS", "no then_* requirement configured")]

        failed = [reason for status, reason in outcomes if status == "FAIL"]
        warned = [reason for status, reason in outcomes if status == "WARN"]
        if failed:
            status = "FAIL"
            reason = f"{condition_text}; " + "; ".join(failed)
        elif warned:
            status = "WARN"
            reason = f"{condition_text}; " + "; ".join(warned)
        else:
            status = "PASS"
            reason = f"{condition_text}; " + "; ".join(
                outcome for _, outcome in outcomes
            )

        evaluations.append(
            RuleEvaluation(
                name=rule.name,
                description=rule.description,
                status=status,
                reason=reason,
                triggered=True,
            )
        )

    return GovernanceCheckResult(evaluations=tuple(evaluations))
