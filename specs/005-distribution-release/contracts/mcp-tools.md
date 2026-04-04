# Contract: MCP Tool Schemas

**Phase**: 5
**Status**: New — MCP tool interface contract
**Spec Requirements**: FR-014, FR-015, FR-016, FR-017

---

## Overview

This document specifies the input/output schemas for the three MCP tools exposed by
`cerebrofy mcp`. These schemas are registered via `list_tools()` in the MCP server and
are used by AI tools to validate inputs and parse responses.

---

## Tool: `plan`

### Input Schema

```json
{
  "name": "plan",
  "description": "Analyze which parts of the codebase would be affected by a feature. Returns matched Neurons, structural neighbors (blast radius), affected modules, and re-index scope. Makes zero network calls — safe offline and in CI.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "description": {
        "type": "string",
        "description": "Natural-language description of the feature or change to plan for"
      },
      "top_k": {
        "type": "integer",
        "description": "Number of KNN search results to return. Default: 10. Range: 1–100.",
        "minimum": 1,
        "maximum": 100,
        "default": 10
      }
    },
    "required": ["description"]
  }
}
```

### Output Schema

Returns a `TextContent` item containing a JSON string with this schema:

```json
{
  "schema_version": 1,
  "matched_neurons": [
    {
      "id": 42,
      "name": "login_user",
      "file": "src/auth/login.py",
      "similarity": 0.923,
      "lobe": "auth",
      "blast_count": 5
    }
  ],
  "blast_radius": [
    {
      "id": 87,
      "name": "verify_token",
      "file": "src/auth/token.py",
      "lobe": "auth"
    }
  ],
  "affected_lobes": ["auth", "api"],
  "reindex_scope": ["src/auth/login.py", "src/auth/token.py"]
}
```

**Field invariants**:
- `schema_version` is always `1` (integer)
- All four array fields (`matched_neurons`, `blast_radius`, `affected_lobes`, `reindex_scope`) are always present; empty arrays if no results
- `similarity` is a float in [0.0, 1.0], ordered descending
- `blast_count` per `NeuronMatch` = direct BFS neighbors from **that specific Neuron** (depth-2, excluding `RUNTIME_BOUNDARY` edges)

---

## Tool: `tasks`

### Input Schema

```json
{
  "name": "tasks",
  "description": "Generate a numbered implementation task list for a feature. Each task identifies the exact code unit to modify, its module location, and the structural risk of changing it. Makes zero network calls — safe offline and in CI.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "description": {
        "type": "string",
        "description": "Natural-language description of the feature to implement"
      },
      "top_k": {
        "type": "integer",
        "description": "Number of KNN search results to return (= number of tasks generated). Default: 10. Range: 1–100.",
        "minimum": 1,
        "maximum": 100,
        "default": 10
      }
    },
    "required": ["description"]
  }
}
```

### Output Schema

```json
{
  "tasks": [
    {
      "number": 1,
      "neuron_name": "login_user",
      "neuron_file": "src/auth/login.py",
      "lobe": "auth",
      "blast_count": 5,
      "similarity": 0.923
    },
    {
      "number": 2,
      "neuron_name": "AuthService.authenticate",
      "neuron_file": "src/auth/service.py",
      "lobe": "auth",
      "blast_count": 2,
      "similarity": 0.881
    }
  ]
}
```

**Field invariants**:
- Tasks are ordered by similarity descending (highest relevance first)
- `blast_count` per task = direct BFS neighbors from **that specific Neuron**, independently computed
- `tasks` array is always present; empty array if no results

---

## Tool: `specify`

### Input Schema

```json
{
  "name": "specify",
  "description": "Generate an AI-grounded feature specification using the codebase as context. The spec is written to docs/cerebrofy/specs/ and the full content is returned. Requires an LLM endpoint configured in .cerebrofy/config.yaml.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "description": {
        "type": "string",
        "description": "Natural-language description of the feature to specify"
      },
      "top_k": {
        "type": "integer",
        "description": "Number of KNN results to include as LLM context. Default: 10. Smaller = faster and cheaper. Range: 1–100.",
        "minimum": 1,
        "maximum": 100,
        "default": 10
      }
    },
    "required": ["description"]
  }
}
```

### Output Schema

```json
{
  "output_file": "docs/cerebrofy/specs/2026-04-04T14-32-07_spec.md",
  "content": "# Feature Specification: Add OAuth2 Login\n\n..."
}
```

**Field invariants**:
- `output_file` is a path relative to the repo root
- `content` is the complete spec content as written to the file (not truncated)
- If a file already exists for the same second, a `_2` suffix is added (collision handling same as CLI)
- The spec file is committed atomically: if the LLM call fails or times out, no partial file is written

---

## RUNTIME_BOUNDARY Notes

When `blast_radius` in the `plan` tool response contains Neurons reachable via
`RUNTIME_BOUNDARY` edges (cross-language or dynamic call boundaries), they are excluded from
the `blast_radius` array. Instead, they appear as a `runtime_boundary_warnings` array (optional
field, may be absent if no such edges exist):

```json
{
  "schema_version": 1,
  "matched_neurons": [...],
  "blast_radius": [...],
  "affected_lobes": [...],
  "reindex_scope": [...],
  "runtime_boundary_warnings": [
    {
      "from": "src/api/handler.py::handle_request",
      "to": "unknown::external_service_call",
      "note": "RUNTIME_BOUNDARY: cross-language boundary, not traversed in BFS"
    }
  ]
}
```

`runtime_boundary_warnings` is never included in `blast_count` calculations.

---

## Schema Versioning

The `schema_version: 1` field in the `plan` tool output enables backward-compatible evolution:

| Version | Field Set | Breaking Change |
|---------|-----------|-----------------|
| 1 | All fields above | — (initial version) |

When a breaking schema change is required, `schema_version` increments to 2. AI tools and
tooling that parse the `plan` output should check `schema_version` before parsing.

The `tasks` and `specify` tool outputs do not currently carry `schema_version` (they are
simpler structures). If their schemas need versioning, `schema_version` will be added.
