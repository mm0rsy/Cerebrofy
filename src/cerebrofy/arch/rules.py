"""ArchRule dataclasses, arch-rules.yaml loader, validator, and scaffold."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml

RULES_FILENAME = "arch-rules.yaml"
_MAX_FILE_SIZE = 50 * 1024  # 50KB

_SEVERITIES = ("error", "warning")

# Slack webhook wiring: YAML key, overridable through the environment.
SLACK_WEBHOOK_KEY = "slack_webhook"
SLACK_WEBHOOK_ENV = "CEREBROFY_SLACK_WEBHOOK"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NoEdgeCheck:
    """Forbid call/import edges matching the given source and target selectors.

    ``from_lobe``/``to_lobe`` reference lobe names from .cerebrofy/config.yaml;
    ``from_patterns``/``to_patterns`` are glob patterns over source file paths.
    Omitted selectors act as wildcards; at least one selector per side is required.
    """

    from_lobe: str | None = None
    to_lobe: str | None = None
    from_patterns: tuple[str, ...] = ()
    to_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class NoCyclesCheck:
    """Forbid circular dependencies. ``scope='lobes'`` detects cycles in the lobe graph."""

    scope: str = "lobes"


@dataclass(frozen=True)
class AllowedCallersCheck:
    """Restrict which lobes may call neurons matching the ``neuron`` glob pattern.

    The pattern is matched against ``file::name`` ids, plain names, and file paths.
    """

    neuron: str
    from_lobes: tuple[str, ...]


@dataclass(frozen=True)
class MaxBlastRadiusCheck:
    """Cap the reverse caller set of a neuron (callers at depth 1 + depth 2)."""

    limit: int


Check = NoEdgeCheck | NoCyclesCheck | AllowedCallersCheck | MaxBlastRadiusCheck


@dataclass(frozen=True)
class ArchRule:
    """A single architecture drift rule from arch-rules.yaml."""

    name: str
    severity: str  # "error" (blocking) | "warning" (informational)
    check: Check
    description: str = ""


@dataclass(frozen=True)
class RulesConfig:
    """Parsed contents of .cerebrofy/arch-rules.yaml."""

    rules: tuple[ArchRule, ...]
    slack_webhook: str | None = None

    @property
    def rule_names(self) -> tuple[str, ...]:
        return tuple(rule.name for rule in self.rules)


class RulesError(Exception):
    """Raised when arch-rules.yaml exists but is malformed or fails validation."""


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------

def rules_path(root: Path) -> Path:
    """Return the expected path of .cerebrofy/arch-rules.yaml under repo root."""
    return root / ".cerebrofy" / RULES_FILENAME


def rules_file_exists(root: Path) -> bool:
    """Return True when arch-rules.yaml exists under root/.cerebrofy."""
    return rules_path(root).exists()


def load_arch_rules(root: Path) -> RulesConfig | None:
    """Load .cerebrofy/arch-rules.yaml.

    Returns None when the file does not exist; raises RulesError when it exists
    but is malformed.
    """
    path = rules_path(root)
    if not path.exists():
        return None

    size = path.stat().st_size
    if size > _MAX_FILE_SIZE:
        import sys
        print(
            f"Warning: arch-rules.yaml exceeds 50KB ({size} bytes) — loading anyway.",
            file=sys.stderr,
        )

    with open(path, encoding="utf-8") as f:
        data: Any = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise RulesError(f"{path}: top-level YAML mapping expected")
    return _parse_rules_config(data, path)


def dump_arch_rules(config: RulesConfig, path: Path) -> None:
    """Serialize RulesConfig back to arch-rules.yaml (comments are not preserved)."""
    payload: dict[str, Any] = {"rules": [_rule_to_dict(rule) for rule in config.rules]}
    if config.slack_webhook:
        payload[SLACK_WEBHOOK_KEY] = config.slack_webhook
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)


def scaffold_arch_rules(path: Path) -> None:
    """Write an example arch-rules.yaml scaffold (all rule types, commented out)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_SCAFFOLD_CONTENT, encoding="utf-8")


# ---------------------------------------------------------------------------
# Private parsers
# ---------------------------------------------------------------------------

def _parse_rules_config(data: dict[str, Any], path: Path) -> RulesConfig:
    raw_rules = data.get("rules")
    if raw_rules is None:
        raw_rules = []
    if not isinstance(raw_rules, list):
        raise RulesError(f"{path}: 'rules' must be a list of rule mappings")

    rules: list[ArchRule] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_rules):
        rule = _parse_rule(index, raw, path)
        if rule.name in seen:
            raise RulesError(f"{path}: duplicate rule name '{rule.name}'")
        seen.add(rule.name)
        rules.append(rule)

    webhook = data.get(SLACK_WEBHOOK_KEY)
    if webhook is not None and not isinstance(webhook, str):
        raise RulesError(f"{path}: '{SLACK_WEBHOOK_KEY}' must be a webhook URL string")
    return RulesConfig(rules=tuple(rules), slack_webhook=webhook or None)


def _parse_rule(index: int, raw: Any, path: Path) -> ArchRule:
    prefix = f"{path}: rules[{index}]"
    if not isinstance(raw, dict):
        raise RulesError(f"{prefix}: each rule must be a mapping")

    name = str(raw.get("name") or "").strip()
    if not name:
        raise RulesError(f"{prefix}: missing required field 'name'")

    severity = str(raw.get("severity") or "warning").strip().lower()
    if severity not in _SEVERITIES:
        raise RulesError(
            f"{prefix} ({name}): severity must be one of {_SEVERITIES}, got '{severity}'"
        )

    description = str(raw.get("description") or "")
    return ArchRule(name=name, severity=severity, check=_parse_check(prefix, name, raw), description=description)


def _parse_check(prefix: str, name: str, raw: dict[str, Any]) -> Check:
    check_raw = raw.get("check")
    if not isinstance(check_raw, dict) or not check_raw:
        raise RulesError(f"{prefix} ({name}): mapping 'check' entry is required")
    if len(check_raw) != 1:
        keys = ", ".join(sorted(check_raw))
        raise RulesError(f"{prefix} ({name}): 'check' must contain exactly one entry, got: {keys}")

    key, value = next(iter(check_raw.items()))
    parser = _CHECK_PARSERS.get(key)
    if parser is None:
        raise RulesError(f"{prefix} ({name}): unknown check type '{key}'")
    try:
        return parser(value)
    except RulesError:
        raise
    except Exception as exc:
        raise RulesError(f"{prefix} ({name}): invalid '{key}' payload: {exc}") from exc


def _parse_no_edge(value: Any) -> NoEdgeCheck:
    if not isinstance(value, dict):
        raise RulesError("'no_edge' expects a mapping of selectors")
    unknown = set(value) - {"from_lobe", "to_lobe", "from_pattern", "to_pattern"}
    if unknown:
        raise RulesError(f"'no_edge' has unknown section(s): {sorted(unknown)}")
    from_lobe = _opt_str(value.get("from_lobe"), "from_lobe")
    to_lobe = _opt_str(value.get("to_lobe"), "to_lobe")
    from_patterns = _pattern_tuple(value.get("from_pattern"), "from_pattern")
    to_patterns = _pattern_tuple(value.get("to_pattern"), "to_pattern")
    if from_lobe is None and not from_patterns:
        raise RulesError("'no_edge' needs a source selector: 'from_lobe' or 'from_pattern'")
    if to_lobe is None and not to_patterns:
        raise RulesError("'no_edge' needs a target selector: 'to_lobe' or 'to_pattern'")
    return NoEdgeCheck(
        from_lobe=from_lobe,
        to_lobe=to_lobe,
        from_patterns=from_patterns,
        to_patterns=to_patterns,
    )


def _parse_no_cycles(value: Any) -> NoCyclesCheck:
    scope = value
    if isinstance(value, dict):
        unknown = set(value) - {"scope"}
        if unknown:
            raise RulesError(f"'no_cycles' has unknown key(s): {sorted(unknown)}")
        scope = value.get("scope")
    if scope is None:
        scope = "lobes"
    if not isinstance(scope, str):
        raise RulesError("'no_cycles' scope must be a string")
    scope = scope.strip()
    if scope != "lobes":
        raise RulesError(f"'no_cycles' currently supports scope='lobes', got '{scope}'")
    return NoCyclesCheck(scope=scope)


def _parse_allowed_callers(value: Any) -> AllowedCallersCheck:
    if not isinstance(value, dict):
        raise RulesError("'allowed_callers' expects a mapping")
    unknown = set(value) - {"neuron", "from_lobes"}
    if unknown:
        raise RulesError(f"'allowed_callers' has unknown key(s): {sorted(unknown)}")
    pattern = str(value.get("neuron") or "").strip()
    if not pattern:
        raise RulesError("'allowed_callers' requires a 'neuron' glob pattern")
    raw_lobes = value.get("from_lobes")
    if isinstance(raw_lobes, str):
        lobes: list[str] = [raw_lobes]
    elif isinstance(raw_lobes, list):
        lobes = [str(item) for item in raw_lobes]
    else:
        raise RulesError("'allowed_callers' requires a non-empty 'from_lobes' list")
    lobes = [lobe.strip() for lobe in lobes if lobe.strip()]
    if not lobes:
        raise RulesError("'allowed_callers' requires a non-empty 'from_lobes' list")
    return AllowedCallersCheck(neuron=pattern, from_lobes=tuple(lobes))


def _parse_max_blast_radius(value: Any) -> MaxBlastRadiusCheck:
    if isinstance(value, dict):
        value = value.get("limit")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RulesError("'max_blast_radius' expects a positive integer limit")
    return MaxBlastRadiusCheck(limit=int(value))


def _opt_str(value: Any, field: str) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        raise RulesError(f"'{field}' must not be empty")
    return text


def _pattern_tuple(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values: list[str] = [value]
    elif isinstance(value, list):
        values = [str(item) for item in value]
    else:
        raise RulesError(f"'{field}' must be a glob string or a list of glob strings")
    patterns = tuple(p for p in (v.strip() for v in values) if p)
    if not patterns:
        raise RulesError(f"'{field}' must not be empty")
    return patterns


_CHECK_PARSERS: dict[str, Callable[[Any], Check]] = {
    "no_edge": _parse_no_edge,
    "no_cycles": _parse_no_cycles,
    "allowed_callers": _parse_allowed_callers,
    "max_blast_radius": _parse_max_blast_radius,
}


def _rule_to_dict(rule: ArchRule) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": rule.name}
    if rule.description:
        payload["description"] = rule.description
    payload["severity"] = rule.severity
    check = rule.check
    if isinstance(check, NoEdgeCheck):
        body: dict[str, Any] = {}
        if check.from_lobe:
            body["from_lobe"] = check.from_lobe
        if check.from_patterns:
            body["from_pattern"] = _yaml_str_or_list(check.from_patterns)
        if check.to_lobe:
            body["to_lobe"] = check.to_lobe
        if check.to_patterns:
            body["to_pattern"] = _yaml_str_or_list(check.to_patterns)
        payload["check"] = {"no_edge": body}
    elif isinstance(check, NoCyclesCheck):
        payload["check"] = {"no_cycles": {"scope": check.scope}}
    elif isinstance(check, AllowedCallersCheck):
        payload["check"] = {
            "allowed_callers": {
                "neuron": check.neuron,
                "from_lobes": list(check.from_lobes),
            }
        }
    else:
        assert isinstance(check, MaxBlastRadiusCheck)  # narrow for mypy
        payload["check"] = {"max_blast_radius": check.limit}
    return payload


def _yaml_str_or_list(patterns: tuple[str, ...]) -> str | list[str]:
    return patterns[0] if len(patterns) == 1 else list(patterns)


# ---------------------------------------------------------------------------
# Scaffold
# ---------------------------------------------------------------------------

_SCAFFOLD_CONTENT = """\
# .cerebrofy/arch-rules.yaml — architecture drift rules for Cerebrofy
#
# Rules are evaluated against the live call graph on every
# 'cerebrofy arch check' run (CLI, git hooks, CI, and the arch_check MCP tool).
#   severity: error   -> blocks the commit / push / CI step (exit 1)
#   severity: warning -> reported, never blocks (exit 0)
# Lobes must exist in .cerebrofy/config.yaml. RUNTIME_BOUNDARY edges are
# always excluded from rule evaluation.
#
# Uncomment examples to activate them, or run 'cerebrofy arch init' to add
# a rule interactively.

# rules:
#   - name: no-direct-db-in-api
#     description: API controllers must not directly call DB writer functions
#     severity: error
#     check:
#       no_edge:
#         from_lobe: api
#         to_lobe: db
#
#   - name: tests-only-call-public-api
#     description: Test files must not import private helpers directly
#     severity: warning
#     check:
#       no_edge:
#         from_pattern: "tests/**"
#         to_pattern: "*/private/**"
#
#   - name: no-circular-lobe-deps
#     description: No circular dependencies between lobes
#     severity: error
#     check:
#       no_cycles:
#         scope: lobes
#
#   - name: embedder-is-isolated
#     description: Only the build pipeline may call the embedder
#     severity: warning
#     check:
#       allowed_callers:
#         neuron: "*embedder/*"        # glob over file::name ids, names, and file paths
#         from_lobes: [commands, embedder]
#
#   - name: max-blast-radius
#     description: No single function may have a blast radius above 50
#     severity: warning
#     check:
#       max_blast_radius: 50
#
# Slack alerts (also settable via the CEREBROFY_SLACK_WEBHOOK environment var):
# slack_webhook: "https://hooks.slack.com/services/..."
"""
