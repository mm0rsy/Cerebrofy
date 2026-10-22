"""Declarative MCP tool registry (Lane A1 — replaces the inline ``Tool(...)`` list).

This module is the single source of truth for the MCP tool catalog that the
cerebrofy stdio server advertises and dispatches:

* tool names, in the exact ``list_tools`` order the server must report them;
* human-facing descriptions and JSON schemas (copied byte-for-byte from the
  previous ``run_mcp_server`` ``list_tools`` implementation);
* the name of the handler function that implements each tool;
* whether the tool is a *data-reading* tool that receives the cross-cutting
  epistemic / intent enrichment (``inject=True``) or a self-contained /
  side-effecting tool that does not (``inject=False``).

It is intentionally dependency-free (stdlib only) so it can be imported — and
unit-tested — even when the optional ``mcp`` extra is not installed. It never
imports :mod:`cerebrofy.mcp.server` (that would create a cycle: server imports
this module, this module would import server).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Frozen tool specification
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ToolSpec:
    """Immutable description of one MCP tool in the cerebrofy catalog."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler_name: str
    inject: bool


# ---------------------------------------------------------------------------
# Input schemas (copied verbatim from the previous ``run_mcp_server`` block).
# ---------------------------------------------------------------------------
EmptySchema: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "Natural-language search query"},
        "top_k": {
            "type": "integer",
            "description": "Max results (default: 10)",
            "default": 10,
            "minimum": 1,
            "maximum": 50,
        },
        "lobe": {"type": "string", "description": "Filter to a specific lobe/module (optional)"},
        "agent_id": {
            "type": "string",
            "description": (
                "Acting agent id; enables self-claim exclusion and heartbeat (optional)."
            ),
        },
    },
    "required": ["query"],
}

_NEURON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Exact function/class name"},
        "file": {"type": "string", "description": "Source file path (partial match)"},
        "line": {"type": "integer", "description": "Line number within the file (requires 'file')"},
        "agent_id": {
            "type": "string",
            "description": (
                "Acting agent id; enables self-claim exclusion and heartbeat (optional)."
            ),
        },
    },
}

_UPDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Specific file to re-index (omit for auto-detect)"},
    },
}

_RESOURCES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "filter": {
            "type": "string",
            "description": (
                "Filter resource types: 'graph', 'lobes', 'neurons', 'health', "
                "'memories', 'blast-radius', or 'all' (default)."
            ),
            "default": "all",
        },
    },
    "required": [],
}

_CONTEXT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task": {"type": "string", "description": "Natural language coding task description."},
        "budget": {"type": "integer", "default": 8000, "description": "Token budget."},
        "model": {"type": "string", "default": "auto", "description": "Model for token counting."},
        "format": {"type": "string", "default": "json", "enum": ["json", "markdown", "claude-xml"]},
    },
    "required": ["task"],
}

_BLAST_RADIUS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "target": {
            "type": "string",
            "description": (
                "Neuron to analyse. Accepts: "
                "'file::name', 'file:line', or plain name."
            ),
        },
        "depth": {"type": "integer", "default": 2, "minimum": 1, "maximum": 5},
        "format": {"type": "string", "default": "json", "enum": ["json", "markdown"]},
    },
    "required": ["target"],
}

_EPISTEMIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "format": {"type": "string", "default": "json", "enum": ["json", "human"]},
    },
}

_HEALTH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "since_build": {"type": "integer", "default": 1, "description": "Compare against N builds ago."},
        "metric": {"type": "string", "default": "all", "description": "Specific metric name or 'all'."},
        "format": {"type": "string", "default": "markdown", "enum": ["markdown", "json"]},
    },
}

_INTENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lobe": {"type": "string", "description": "Get intent relevance for a specific lobe (optional)"},
        "neuron": {"type": "string", "description": "Get intent relevance for a specific neuron path (optional)"},
        "format": {"type": "string", "default": "json", "enum": ["json", "human"]},
    },
}

_REMEMBER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short memory title"},
        "body": {"type": "string", "description": "Full memory content"},
        "type": {
            "type": "string",
            "enum": ["decision", "warning", "context", "pattern", "agent_action"],
        },
        "neuron": {"type": "string", "description": "Neuron name or file::name"},
        "lobe": {"type": "string", "description": "Lobe name"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "author": {"type": "string"},
        "agent_id": {
            "type": "string",
            "description": (
                "Acting agent id; enables self-claim exclusion and heartbeat (optional)."
            ),
        },
    },
    "required": ["title", "body", "type"],
}

_RECALL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "type": {
            "type": "string",
            "enum": ["decision", "warning", "context", "pattern", "agent_action", "insight"],
        },
        "lobe": {"type": "string"},
        "limit": {"type": "integer", "default": 10},
        "include_stale": {"type": "boolean", "default": False},
    },
    "required": ["query"],
}

_MEMORIES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "neuron": {"type": "string"},
        "lobe": {"type": "string"},
        "type": {"type": "string"},
        "include_stale": {"type": "boolean", "default": False},
    },
}

_LINK_MEMORIES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "from_memory": {"type": "string", "description": "ID of the source memory"},
        "to_memory": {"type": "string", "description": "ID of the target memory"},
        "rel_type": {
            "type": "string",
            "enum": ["caused", "motivated", "resolved", "contradicts", "updated_by"],
        },
        "author": {"type": "string"},
    },
    "required": ["from_memory", "to_memory", "rel_type"],
}

_TRACE_HISTORY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "memory": {"type": "string", "description": "Memory ID to trace backward from"},
        "depth": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
    },
    "required": ["memory"],
}

_ONBOARD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Recipient name for the header (optional)"},
        "focus_lobe": {"type": "string", "description": "Restrict guide to this lobe (optional)"},
        "depth": {
            "type": "string",
            "enum": ["junior", "senior"],
            "default": "junior",
            "description": "Calibration hint for AI agents reading the output",
        },
    },
}

_IMPACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "target": {
            "type": "string",
            "description": (
                "Neuron to analyse. Accepts: "
                "'file::name' (e.g. auth/tokens.py::validate_token), "
                "'file:line' (e.g. auth/tokens.py:42), "
                "or plain name (e.g. validate_token)."
            ),
        },
        "depth": {
            "type": "integer",
            "description": "BFS caller traversal depth (default: 2).",
            "default": 2,
            "minimum": 1,
            "maximum": 5,
        },
        "show_tests": {
            "type": "boolean",
            "description": "Include covering test list (default: true).",
            "default": True,
        },
    },
    "required": ["target"],
}

_SILO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "depth": {
            "type": "integer",
            "description": "BFS caller traversal depth (default: 2).",
            "default": 2,
            "minimum": 1,
            "maximum": 5,
        },
        "min_callers": {
            "type": "integer",
            "description": "Minimum caller count to include a neuron (default: 1).",
            "default": 1,
        },
        "top": {
            "type": "integer",
            "description": "Number of top silos to return (default: 20).",
            "default": 20,
        },
        "lobe": {
            "type": "string",
            "description": "Filter analysis to a specific lobe (optional).",
        },
        "author": {
            "type": "string",
            "description": "Filter to silos owned by a specific author email (optional).",
        },
        "risk_level": {
            "type": "string",
            "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
            "description": "Filter by risk level (optional, default: all).",
        },
        "write_memories": {
            "type": "boolean",
            "description": "Write warning memories to HIGH/CRITICAL silo neurons (default: false).",
            "default": False,
        },
    },
}

_COVERAGE_GAP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "days": {
            "type": "integer",
            "description": "Velocity window in days — commits within this window count (default: 30).",
            "default": 30,
            "minimum": 1,
        },
        "depth": {
            "type": "integer",
            "description": "BFS caller traversal depth (default: 2).",
            "default": 2,
            "minimum": 1,
            "maximum": 5,
        },
        "min_blast": {
            "type": "number",
            "description": "Minimum weighted blast radius (d1 + 0.4×d2) to include (default: 0).",
            "default": 0.0,
        },
        "top": {
            "type": "integer",
            "description": "Number of top gaps to return (default: 20).",
            "default": 20,
        },
        "lobe": {
            "type": "string",
            "description": "Filter analysis to a specific lobe (optional).",
        },
        "risk_level": {
            "type": "string",
            "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"],
            "description": "Filter by risk level (optional, default: all).",
        },
        "write_memories": {
            "type": "boolean",
            "description": "Write warning memories to HIGH/CRITICAL gap neurons (default: false).",
            "default": False,
        },
    },
}

_VULN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "package": {
            "type": "string",
            "description": "Package name to scan (e.g. 'requests', 'pyyaml').",
        },
        "function_pattern": {
            "type": "string",
            "description": "Specific function to trace (e.g. 'requests.get'). Omit to scan the full package.",
        },
        "depth": {
            "type": "integer",
            "description": "Upstream BFS depth (default: 2).",
            "default": 2,
            "minimum": 1,
            "maximum": 5,
        },
        "write_memories": {
            "type": "boolean",
            "description": "Write warning memories to each directly-affected neuron (default: false).",
            "default": False,
        },
    },
    "required": ["package"],
}

_UPGRADE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "package": {
            "type": "string",
            "description": "Package name to plan the upgrade for (e.g. 'pydantic', 'requests').",
        },
        "from_version": {
            "type": "string",
            "description": "Current pinned version (e.g. '1.10.0').",
        },
        "to_version": {
            "type": "string",
            "description": "Target version (e.g. '2.0.0').",
        },
        "breaking_only": {
            "type": "boolean",
            "description": "Only report breaking API changes (default: true).",
            "default": True,
        },
        "auto_fix": {
            "type": "boolean",
            "description": "Apply mechanical auto-fixes using AST transforms (default: false).",
            "default": False,
        },
        "step": {
            "type": "array",
            "items": {"type": "integer"},
            "description": "Which steps to auto-fix (e.g. [1, 2]); only used when auto_fix=true.",
        },
        "validate": {
            "type": "boolean",
            "description": "Validate that no old API patterns remain (post-upgrade).",
            "default": False,
        },
        "format": {
            "type": "string",
            "description": "Output format (default: markdown).",
            "enum": ["markdown", "json"],
            "default": "markdown",
        },
    },
    "required": ["package"],
}

_ARCH_CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rule": {
            "type": "string",
            "description": "Specific rule name to check, or 'all' (default).",
            "default": "all",
        },
        "format": {
            "type": "string",
            "description": "Output format (default: markdown).",
            "enum": ["markdown", "json", "github-annotations"],
            "default": "markdown",
        },
        "since": {
            "type": "string",
            "description": (
                "Only report drift touching files changed since this git ref "
                "(e.g. 'HEAD~1'). Omit to check everything."
            ),
        },
    },
}

_SESSION_START_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "task": {
            "type": "string",
            "description": "Human-readable description of the coding task being started.",
        },
        "agent": {
            "type": "string",
            "description": "Agent identifier (e.g. 'claude-sonnet-4-6', 'human:alice').",
        },
    },
    "required": ["task"],
}

_SESSION_END_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Session ID returned by cerebrofy_session_start.",
        },
        "outcome": {
            "type": "string",
            "enum": ["success", "partial", "failed", "unknown"],
            "description": "Session outcome (default: unknown).",
        },
        "summary": {
            "type": "string",
            "description": "Optional human-readable summary of what was accomplished.",
        },
    },
    "required": ["session_id"],
}

_SESSION_SHOW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Session ID to retrieve; omit for the most recent session.",
        },
        "format": {
            "type": "string",
            "enum": ["markdown", "json"],
            "default": "markdown",
            "description": "Output format (default: markdown).",
        },
    },
}

_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": "Natural language description of the desired refactoring.",
        },
        "format": {
            "type": "string",
            "description": "Output format (default: markdown).",
            "enum": ["markdown", "json"],
            "default": "markdown",
        },
        "dry_run": {
            "type": "boolean",
            "description": "If true, generate the plan only — do not modify any files (default: true).",
            "default": True,
        },
    },
    "required": ["description"],
}

_CHANGELOG_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "since": {
            "type": "string",
            "description": (
                "Start point: git tag, commit hash, 'last-build' "
                "(commit of the newest health snapshot), or 'project-start'."
            ),
        },
        "audience": {
            "type": "string",
            "enum": ["developer", "pm", "user"],
            "default": "developer",
            "description": "Target audience for the generated prose.",
        },
        "format": {
            "type": "string",
            "enum": ["markdown", "github", "slack"],
            "default": "markdown",
            "description": "Output format for full_text.",
        },
    },
    "required": ["since"],
}

_GOVERNANCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "description": (
                "Action to perform: 'generate-codeowners', 'suggest-reviewers', "
                "or 'check-rules'"
            ),
            "enum": ["generate-codeowners", "suggest-reviewers", "check-rules"],
        },
        "pr": {
            "type": "integer",
            "description": (
                "GitHub PR number — used by suggest-reviewers and check-rules"
            ),
        },
        "lobe": {
            "type": "string",
            "description": "Restrict output to a specific lobe",
        },
        "format": {
            "type": "string",
            "description": "Output format: 'markdown' or 'json'",
            "enum": ["markdown", "json"],
            "default": "markdown",
        },
    },
    "required": ["action"],
}

_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "diff": {
            "type": "string",
            "description": "Git ref to diff against (e.g. 'HEAD~1', 'main').",
        },
        "pr": {
            "type": "integer",
            "description": "GitHub PR number to review (requires gh CLI auth).",
        },
        "severity": {
            "type": "string",
            "description": "Minimum severity to report.",
            "enum": ["error", "warning", "all"],
            "default": "all",
        },
        "post_comments": {
            "type": "boolean",
            "description": (
                "Post findings as inline GitHub PR comments plus a summary "
                "(requires pr and gh auth). Default is a local dry-run."
            ),
            "default": False,
        },
        "format": {
            "type": "string",
            "description": "Output format.",
            "enum": ["markdown", "json"],
            "default": "markdown",
        },
    },
}

_CLAIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "agent_id": {
            "type": "string",
            "description": "Stable identifier for the acting agent (e.g. 'claude-sess-001').",
        },
        "neurons": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Neuron ids or file paths to claim before editing. File paths "
                "expand to every neuron indexed for that file."
            ),
        },
        "intent": {
            "type": "string",
            "description": "What the agent is about to do — shown to other agents.",
        },
        "agent_type": {
            "type": "string",
            "description": "Agent kind (default: 'claude').",
            "default": "claude",
        },
        "ttl_minutes": {
            "type": "integer",
            "description": "Claim lifetime in minutes (default: 60, max: 1440).",
            "default": 60,
            "minimum": 1,
            "maximum": 1440,
        },
        "session_id": {
            "type": "string",
            "description": "Optional Idea #11 session id to associate with the claim.",
        },
    },
    "required": ["agent_id", "neurons", "intent"],
}

_RELEASE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "agent_id": {
            "type": "string",
            "description": "Agent whose claims should be released.",
        },
        "neurons": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Neuron ids or file paths to release; omit to release every claim."
            ),
        },
    },
    "required": ["agent_id"],
}

_WHO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

_CONFLICTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "neuron": {
            "type": "string",
            "description": "Limit memory-conflict detection to one neuron (optional).",
        },
    },
    "required": [],
}

_RESOLVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "memory_a": {"type": "string", "description": "First memory id in the conflict."},
        "memory_b": {"type": "string", "description": "Second memory id in the conflict."},
        "strategy": {
            "type": "string",
            "description": "Resolution strategy. 'human_review' never mutates memories.",
            "enum": ["keep_newest", "keep_by_author", "human_review", "merge"],
        },
        "author": {
            "type": "string",
            "description": "Author to prefer for keep_by_author (optional).",
        },
        "merged_body": {
            "type": "string",
            "description": (
                "Content for the resolved memory when strategy is 'merge' "
                "(required for that strategy)."
            ),
        },
        "neuron": {
            "type": "string",
            "description": "Neuron the conflicting memories belong to (optional).",
        },
    },
    "required": ["memory_a", "memory_b", "strategy"],
}


# ---------------------------------------------------------------------------
# The tool catalog
# ---------------------------------------------------------------------------
# Order is significant: it is the exact order ``list_tools`` advertises and the
# order the previous server registered them. ``handler_name`` must be the
# ``__name__`` of a module-level ``_handle_*`` callable in
# :mod:`cerebrofy.mcp.server` (the dispatch table is built there from
# ``TOOL_SPECS``, so a renamed handler fails loudly at import instead of
# producing a silent "Unknown tool" error at call time).
#
# ``inject=True`` marks data-reading tools whose results are enriched with the
# epistemic confidence score and the compact product-intent summary by
# ``dispatch_tool``. Subprocess / mutation / self-contained tools are
# ``inject=False`` — they return their own payload verbatim.
TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="search_code",
        description=(
            "Hybrid semantic + keyword search over the Cerebrofy index. "
            "ALWAYS call this first when asked about code structure or behaviour. "
            "Returns ranked Neurons with file path and line number. "
            "Never glob-read source files — use this instead."
        ),
        input_schema=_SEARCH_SCHEMA,
        handler_name="_handle_search_code",
        inject=True,
    ),
    ToolSpec(
        name="get_neuron",
        description=(
            "Fetch details for a specific Neuron by name or file path. "
            "Use after search_code to get the full signature, docstring, and location."
        ),
        input_schema=_NEURON_SCHEMA,
        handler_name="_handle_get_neuron",
        inject=True,
    ),
    ToolSpec(
        name="list_lobes",
        description=(
            "List all indexed lobes (modules/packages) with summary file paths. "
            "Use for high-level orientation before searching."
        ),
        input_schema=EmptySchema,
        handler_name="_handle_list_lobes",
        inject=True,
    ),
    ToolSpec(
        name="cerebrofy_list_resources",
        description=(
            "List every MCP resource URI this server exposes — static resources "
            "(codebase map, entry points, health) and URI templates (neurons, files, "
            "search, memories, blast radius). Use this to discover ambient context, "
            "then read a URI directly via the MCP resources/read protocol method. "
            "Supports subscribing to resources/updated notifications."
        ),
        input_schema=_RESOURCES_SCHEMA,
        handler_name="_handle_list_resources",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_context",
        description=(
            "Build the optimal context window for a coding task within a token budget. "
            "Embeds the task, runs KNN + BFS, scores candidates by relevance, and "
            "greedy-packs neurons with tier degradation (full_source → signature → "
            "lobe_summary → name_only). Call this before starting any non-trivial coding task."
        ),
        input_schema=_CONTEXT_SCHEMA,
        handler_name="_handle_context",
        inject=True,
    ),
    ToolSpec(
        name="cerebrofy_blast_radius",
        description=(
            "Compute the blast radius of a changed neuron — every caller at depth 1 and 2, "
            "test coverage, lobe spread, and a risk score. "
            "Use after a PR diff to understand what a change affects before merging."
        ),
        input_schema=_BLAST_RADIUS_SCHEMA,
        handler_name="_handle_blast_radius",
        inject=True,
    ),
    ToolSpec(
        name="cerebrofy_epistemic",
        description=(
            "Return the epistemic confidence score for the current index — "
            "graph age, neurons changed since last build, unindexed languages, "
            "dynamic dispatch count, and a composite confidence score (0.5–1.0). "
            "Call this before any architectural decision to understand how much to "
            "trust the index. All other Cerebrofy tool responses include an "
            "'epistemic' field automatically."
        ),
        input_schema=_EPISTEMIC_SCHEMA,
        handler_name="_handle_epistemic",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_health",
        description=(
            "Return longitudinal codebase health metrics derived from the call graph. "
            "Includes coupling, blast radius trend, dead code %, lobe cohesion, "
            "test surface coverage, drift velocity, and hub concentration. "
            "Use to understand whether the codebase is improving or degrading over time."
        ),
        input_schema=_HEALTH_SCHEMA,
        handler_name="_handle_health",
        inject=True,
    ),
    ToolSpec(
        name="cerebrofy_intent",
        description=(
            "Return the current product intent — sprint goals, active incidents, "
            "architectural direction, and team context. Pass 'lobe' or 'neuron' to "
            "get relevance scoring for a specific part of the codebase. "
            "Call this at the start of any task to understand team priorities and known risks."
        ),
        input_schema=_INTENT_SCHEMA,
        handler_name="_handle_intent",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_build",
        description=(
            "Full atomic re-index of the entire repository. "
            "Use when the index is missing or a full rebuild is needed."
        ),
        input_schema=EmptySchema,
        handler_name="_handle_build",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_update",
        description=(
            "Incremental re-index of changed files (auto-detected via git diff). "
            "Pass 'path' to limit to a specific file."
        ),
        input_schema=_UPDATE_SCHEMA,
        handler_name="_handle_update",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_validate",
        description=(
            "Check for drift between source code and the index. "
            "Returns 'clean', 'minor_drift', or 'structural_drift'. Zero writes."
        ),
        input_schema=EmptySchema,
        handler_name="_handle_validate",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_remember",
        description=(
            "Write a structured memory (decision, warning, context, pattern, agent_action) "
            "attached to a neuron or lobe. Call this after any important decision, gotcha, "
            "or completed refactor so future agents have context."
        ),
        input_schema=_REMEMBER_SCHEMA,
        handler_name="_handle_remember",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_recall",
        description=(
            "Semantic search across all memories. Use before starting a task to surface "
            "relevant decisions, warnings, and past agent actions."
        ),
        input_schema=_RECALL_SCHEMA,
        handler_name="_handle_recall",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_memories",
        description=(
            "List memories for a specific neuron or lobe without a search query. "
            "Use when you already know which neuron/lobe you are working with."
        ),
        input_schema=_MEMORIES_SCHEMA,
        handler_name="_handle_memories",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_link_memories",
        description=(
            "Create a typed causal edge between two memories (Phase 2 causal graph). "
            "Use to record why a decision was made, what an action resolved, or how "
            "two memories relate. rel_type: caused | motivated | resolved | contradicts | updated_by."
        ),
        input_schema=_LINK_MEMORIES_SCHEMA,
        handler_name="_handle_link_memories",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_trace_history",
        description=(
            "Walk the causal memory graph backward from a memory to explain why a neuron "
            "is the way it is. Returns the full causal chain up to 'depth' hops. "
            "Use when you need to understand the decision history behind a piece of code."
        ),
        input_schema=_TRACE_HISTORY_SCHEMA,
        handler_name="_handle_trace_history",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_onboard",
        description=(
            "Generate a structured onboarding guide from the cerebrofy index. "
            "Returns full Markdown and a structured JSON summary of reading order, "
            "entry points, complexity hotspots, safe zones, and architectural warnings. "
            "Call this at the start of any onboarding session or when joining a new repo."
        ),
        input_schema=_ONBOARD_SCHEMA,
        handler_name="_handle_onboard",
        inject=True,
    ),
    ToolSpec(
        name="cerebrofy_impact",
        description=(
            "Pre-change impact prediction. Run before any refactor to see every caller, "
            "test coverage, lobe spread, estimated LoC, and a recommended refactoring sequence. "
            "Standard pre-flight check before touching any function or class."
        ),
        input_schema=_IMPACT_SCHEMA,
        handler_name="_handle_impact",
        inject=True,
    ),
    ToolSpec(
        name="cerebrofy_silo",
        description=(
            "Detect knowledge silos: functions with high blast radius owned by few contributors. "
            "Overlays git blame authorship on the call graph to compute bus factor risk per neuron. "
            "silo_score = caller_count / unique_authors — high score means one person owns "
            "widely-called code. Use before team changes or major refactors to surface key-person risk. "
            "Pass 'author' to answer 'if this person left, what breaks?'"
        ),
        input_schema=_SILO_SCHEMA,
        handler_name="_handle_silo",
        inject=True,
    ),
    ToolSpec(
        name="cerebrofy_coverage_gap",
        description=(
            "Rank uncovered neurons by blast radius × change velocity to find the functions "
            "most likely to cause production bugs. A function that is widely-called, "
            "actively changing, and has no tests is the highest risk. "
            "Coverage is read from coverage.xml if present (pytest-cov output), "
            "otherwise derived from the call graph. "
            "Use before a sprint or release to identify the most dangerous untested code."
        ),
        input_schema=_COVERAGE_GAP_SCHEMA,
        handler_name="_handle_coverage_gap",
        inject=True,
    ),
    ToolSpec(
        name="cerebrofy_vuln",
        description=(
            "Map which of YOUR functions are exposed to a vulnerable package. "
            "Finds all call sites of the package via the graph, traces backward to "
            "trust boundary entry points, scores exposure, and generates a remediation sequence. "
            "Run this before patching a dependency to know exactly what to update."
        ),
        input_schema=_VULN_SCHEMA,
        handler_name="_handle_vuln",
        inject=True,
    ),
    ToolSpec(
        name="cerebrofy_upgrade",
        description=(
            "Plan a dependency upgrade from a curated breaking-change manifest: "
            "find every indexed neuron that uses the changing API, score migration "
            "effort, order the steps, and optionally apply precise AST auto-fixes. "
            "Run with validate=true after upgrading to confirm no old patterns remain. "
            "Offline — use --manifest/--diff on the CLI for custom API diffs. "
            "Error codes: NO_INDEX, PACKAGE_NOT_USED, MANIFEST_NOT_FOUND, VERSION_NOT_FOUND."
        ),
        input_schema=_UPGRADE_SCHEMA,
        handler_name="_handle_upgrade",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_arch_check",
        description=(
            "Check .cerebrofy/arch-rules.yaml architecture drift rules against the "
            "live call graph: forbidden lobe-to-lobe edges, circular lobe dependencies, "
            "allowed-callers isolation, and max blast radius. Use after making changes "
            "to catch architectural drift before merge. Results include the index "
            "confidence score and flag warning rules escalated by the active sprint's "
            "priority lobes (treat escalated rules as failures). Returns NO_INDEX / "
            "NO_RULES_FILE / RULE_NOT_FOUND guidance when prerequisites are missing."
        ),
        input_schema=_ARCH_CHECK_SCHEMA,
        handler_name="_handle_arch_check",
        inject=True,
    ),
    ToolSpec(
        name="cerebrofy_session_start",
        description=(
            "Start recording an agent session. Call this BEFORE a coding task, then "
            "cerebrofy_session_end when done. Every MCP tool call in between is "
            "recorded locally into a replayable session (opt-in: record_sessions: true)."
        ),
        input_schema=_SESSION_START_SCHEMA,
        handler_name="_handle_session_start",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_session_end",
        description=(
            "End the current agent session: records the outcome and returns the "
            "session's duration, neurons touched, events recorded, and blast-radius "
            "before/after (Idea #01)."
        ),
        input_schema=_SESSION_END_SCHEMA,
        handler_name="_handle_session_end",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_session_show",
        description=(
            "Return a recorded session as a full replay — timeline of tool calls, "
            "neurons touched, graph diff, and blast-radius risk verdict. Omit "
            "session_id for the most recent session. Use before reviewing "
            "AI-authored changes to see what the agent actually did."
        ),
        input_schema=_SESSION_SHOW_SCHEMA,
        handler_name="_handle_session_show",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_plan",
        description=(
            "Generate a step-by-step, graph-aware refactoring plan from a "
            "plain-English description — which neurons to extract, where they "
            "move, which callers to update, and in what safe order. "
            "The plan is a human-in-the-loop pre-flight checklist; it never "
            "modifies files. Pass dry_run=false to also prepare an execution "
            "handoff for the agent that will implement the plan."
        ),
        input_schema=_PLAN_SCHEMA,
        handler_name="_handle_plan",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_changelog",
        description=(
            "Generate a semantic changelog for a git range — classified from the "
            "call graph, drift records, and memories, never from commit messages. "
            "Entry types: feat, fix, refactor, security, breaking, perf, internal. "
            "Audiences: developer (default), pm, user. Formats: markdown (default), "
            "github, slack. 'since' accepts a tag, commit hash, 'last-build', or "
            "'project-start'. Returns structured entries, breaking_changes, "
            "health_delta, and the formatted full_text. "
            "Error codes: NO_INDEX, REF_NOT_FOUND."
        ),
        input_schema=_CHANGELOG_SCHEMA,
        handler_name="_handle_changelog",
        inject=True,
    ),
    ToolSpec(
        name="cerebrofy_governance",
        description=(
            "Lobe ownership and review governance. Generates a GitHub CODEOWNERS "
            "file from git blame + call-graph topology ('generate-codeowners'), "
            "suggests primary/secondary/backup reviewers for a PR "
            "('suggest-reviewers'), and evaluates reporting-only governance rules "
            "from governance.rules in .cerebrofy/arch-rules.yaml ('check-rules'). "
            "Use this before merging or when deciding who must review a change. "
            "Returns NO_INDEX / NO_GIT_HISTORY / GH_NOT_AUTHENTICATED / "
            "NO_GOVERNANCE_RULES guidance when prerequisites are missing."
        ),
        input_schema=_GOVERNANCE_SCHEMA,
        handler_name="_handle_governance",
        inject=True,
    ),
    ToolSpec(
        name="cerebrofy_review",
        description=(
            "Graph-aware AI review copilot. Reviews a local diff or GitHub PR with "
            "blast radius, past warning memories/decisions, architecture rules, test "
            "coverage gaps, missing caller updates, cross-lobe coupling, and knowledge "
            "silo experts. Returns sorted findings (severity_score descending), "
            "suggested reviewers, health delta, and a PR-ready markdown summary. "
            "Posting is opt-in via post_comments=true and requires an authenticated "
            "gh CLI; the default is a local dry-run. "
            "Error codes: NO_INDEX, NO_DIFF_PROVIDED, GH_NOT_AUTHENTICATED."
        ),
        input_schema=_REVIEW_SCHEMA,
        handler_name="_handle_review",
        inject=True,
    ),
        ToolSpec(
        name="cerebrofy_claim",
        description=(
            "Claim neurons before editing them so concurrent agents do not "
            "silently undo each other's work. Claims are local to this project, "
            "expire after ttl_minutes (default 60, max 1440), and conflicting "
            "neurons are skipped and reported with the existing claimant."
        ),
        input_schema=_CLAIM_SCHEMA,
        handler_name="_handle_claim",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_release",
        description=(
            "Release neurons claimed by this agent. Pass specific neuron ids or "
            "omit 'neurons' to release every claim. Use this when finished with "
            "a task so other agents can take over."
        ),
        input_schema=_RELEASE_SCHEMA,
        handler_name="_handle_release",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_who",
        description=(
            "List all active agents, what each one has claimed, how long they "
            "have been active, and any overlapping claims. Call this before "
            "starting work on shared code to see who else is editing it."
        ),
        input_schema=_WHO_SCHEMA,
        handler_name="_handle_who",
        inject=True,
    ),
    ToolSpec(
        name="cerebrofy_conflicts",
        description=(
            "Report overlapping neuron claims and contradicting memories. Pass "
            "'neuron' to scope memory-contradiction detection to one neuron. "
            "The response includes the available resolution strategies."
        ),
        input_schema=_CONFLICTS_SCHEMA,
        handler_name="_handle_conflicts",
        inject=True,
    ),
    ToolSpec(
        name="cerebrofy_resolve",
        description=(
            "Resolve a pair of contradicting memories with a deterministic "
            "strategy: keep_newest, keep_by_author, human_review, or merge. "
            "human_review never mutates memories — it flags the conflict for a "
            "human (requires_review=true)."
        ),
        input_schema=_RESOLVE_SCHEMA,
        handler_name="_handle_resolve",
        inject=False,
    ),
    ToolSpec(
        name="cerebrofy_insights",
        description=(
            "Query or run the Cerebrofy Insight Daemon — proactive analysis across "
            "graph, health, memories, sessions, and arch rules. Returns insights "
            "like trend alerts, session failure patterns, silo risks, architectural "
            "predictions, memory conflicts, and coverage regressions. Use at session "
            "start to understand codebase health, or run_now=true to force a fresh "
            "daemon execution. Error codes: NO_INDEX, DAEMON_RUNNING."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "Filter by insight type (e.g., 'trend_alert', 'silo_risk')"},
                "since": {"type": "string", "description": "Time window e.g. '7d', '24h'"},
                "min_confidence": {"type": "number", "description": "Minimum confidence 0-1", "default": 0.7},
                "run_now": {"type": "boolean", "description": "Force daemon run before returning results", "default": False},
                "show_all": {"type": "boolean", "description": "Include all insights regardless of confidence", "default": False},
            },
            "required": [],
        },
        handler_name="_handle_insights",
        inject=True,
    ),
)>>>>>> 807d514 (feat(insight): wire Insight Daemon into CLI, MCP, and build/update hooks)
)

# Name -> ToolSpec lookup. Fails loudly on duplicate names so a copy/paste
# cannot register two tools under the same name.
SPEC_BY_NAME: dict[str, ToolSpec] = {}
for spec in TOOL_SPECS:
    if spec.name in SPEC_BY_NAME:
        raise ValueError(f"Duplicate tool name in TOOL_SPECS: {spec.name}")
    SPEC_BY_NAME[spec.name] = spec
