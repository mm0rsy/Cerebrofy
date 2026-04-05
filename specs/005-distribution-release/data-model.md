# Data Model: Phase 5 — Distribution, Release Engineering & Cross-Phase Corrections

**Feature**: 005-distribution-release
**Date**: 2026-04-04

---

## Overview

Phase 5 introduces no new database tables. All runtime data continues to live in the existing
`cerebrofy.db` schema (Phase 2). Phase 5 data entities are either:

1. **Configuration artifacts** (files on disk — MCP config, CI manifests, Homebrew formula, winget manifest)
2. **Protocol contracts** (MCP tool input/output schemas)
3. **Corrections to existing entities** (blast_count, PlanReport schema_version — from Track B)

---

## New Runtime Entities

### MCPToolCall (input schema — per tool)

The input schema for each MCP tool exposed by `cerebrofy mcp`.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `description` | string | Yes | Feature description or query (same as CLI positional arg) |
| `top_k` | integer | No | KNN result count (default: config.yaml `top_k`, or 10) |

All three tools (`plan`, `tasks`, `specify`) share the same input schema.

**Validation rules**:
- `description`: non-empty string, ≤ 4000 characters
- `top_k`: integer, 1 ≤ top_k ≤ 100 (clamped, not rejected)

---

### MCPToolResult (output schema — `plan` tool)

The structured output returned when the AI tool calls the `plan` MCP tool.

| Field | Type | Always Present | Description |
|-------|------|----------------|-------------|
| `schema_version` | integer | Yes | Always `1` |
| `matched_neurons` | array[NeuronMatch] | Yes | KNN matched Neurons (empty array if none) |
| `blast_radius` | array[NeuronRef] | Yes | BFS structural neighbors (empty array if none) |
| `affected_lobes` | array[string] | Yes | Lobe names (empty array if none) |
| `reindex_scope` | array[string] | Yes | File paths needing re-index (empty array if none) |

This schema is identical to the `cerebrofy plan --json` output (FR-015). `schema_version: 1`
is required at the top level (FR-023 — retroactive correction to Phase 4).

**NeuronMatch**:
| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Node ID from `nodes` table |
| `name` | string | Function/class name |
| `file` | string | Relative file path |
| `similarity` | float | KNN cosine similarity score (0.0–1.0) |
| `lobe` | string | Lobe name |
| `blast_count` | integer | BFS neighbor count for this Neuron specifically |

**Correction (FR-022)**: `blast_count` is the count of BFS neighbors directly reachable from
**this specific Neuron** — not the total across all matched Neurons. Each `NeuronMatch` entry
independently reflects the structural risk of changing that specific Neuron.

**NeuronRef**:
| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Node ID |
| `name` | string | Function/class name |
| `file` | string | Relative file path |
| `lobe` | string | Lobe name |

---

### MCPToolResult (output schema — `tasks` tool)

| Field | Type | Always Present | Description |
|-------|------|----------------|-------------|
| `tasks` | array[TaskItem] | Yes | Numbered task list (empty array if none) |

**TaskItem** (correction to Phase 4 data model, FR-022):
| Field | Type | Description |
|-------|------|-------------|
| `number` | integer | Task number (1-based) |
| `neuron_name` | string | Neuron name |
| `neuron_file` | string | Relative file path |
| `lobe` | string | Lobe name |
| `blast_count` | integer | BFS neighbor count for **this Neuron specifically** |
| `similarity` | float | KNN cosine similarity (0.0–1.0) |

**blast_count invariant**: `blast_count` for TaskItem at index `i` equals
`len(blast_radius_bfs(matched_neurons[i].id))` — computed per-Neuron, independently.

---

### MCPToolResult (output schema — `specify` tool)

| Field | Type | Always Present | Description |
|-------|------|----------------|-------------|
| `output_file` | string | Yes | Path to written spec file (relative to repo root) |
| `content` | string | Yes | Full spec content as written to the file |

---

### MCPErrorResult

Returned by any MCP tool when a fatal error occurs (no index, schema mismatch, etc.).

| Field | Type | Description |
|-------|------|-------------|
| `content` | array[TextContent] | Always one item: `{"type": "text", "text": "<message>"}` |
| `isError` | boolean | Always `true` |

**Error messages**:
- No index: `"No Cerebrofy index found. Run 'cerebrofy build' first."`
- Schema mismatch: `"Schema version mismatch. Run 'cerebrofy migrate' to update."`
- Embed model mismatch: `"Embedding model mismatch. Run 'cerebrofy build' to rebuild."`

---

### ParseResult (output entity — `cerebrofy parse`)

The NDJSON output entity for `cerebrofy parse`. One JSON object per line on stdout.

| Field | Type | Description |
|-------|------|-------------|
| `file` | string | File path (relative to repo root) |
| `name` | string | Neuron name (function/class/method) |
| `kind` | string | `"function"`, `"class"`, `"method"`, `"async_function"` |
| `line_start` | integer | 1-based start line |
| `line_end` | integer | 1-based end line (inclusive) |
| `signature` | string | Normalized signature text |
| `lobe` | string | Detected lobe name |

**Relationship to Neuron**: This is the `Neuron` dataclass (from `parser/neuron.py`)
serialized as JSON. The `parse` command uses the same `Neuron` dataclass — no new schema.
`lobe` is determined by the same lobe detection algorithm used in `cerebrofy build`.

**NDJSON format**: One JSON object per line, no trailing comma, no array wrapper:
```
{"file": "src/auth/login.py", "name": "login_user", "kind": "function", ...}
{"file": "src/auth/login.py", "name": "logout_user", "kind": "function", ...}
```

---

## Configuration Artifacts (Files on Disk)

### MCP Config Entry

Written to the first writable path from the FR-012 priority list by `cerebrofy init`.

**JSON structure** (merged into existing config file):
```json
{
  "mcpServers": {
    "cerebrofy": {
      "command": "cerebrofy",
      "args": ["mcp"]
    }
  }
}
```

**Idempotency**: If the `"cerebrofy"` key already exists in `mcpServers`, `cerebrofy init`
does NOT overwrite it. The existing entry is preserved.

**Multi-installation warning**: If `cerebrofy` resolves to a different binary path than the
existing MCP entry's `command`, `cerebrofy init` prints a warning with all detected paths
and provides remediation steps (FR-018).

---

### Hook Version Block

The versioned pre-push hook block (correction from FR-020). Delimited by sentinels.

**Version 1 (warn-only, installed by Phase 1)**:
```bash
# BEGIN cerebrofy
# cerebrofy-hook-version: 1
cerebrofy validate --hook pre-push
# END cerebrofy
```

**Version 2 (hard-block, upgraded by Phase 3)**:
```bash
# BEGIN cerebrofy
# cerebrofy-hook-version: 2
if ! cerebrofy validate --hook pre-push; then
    echo "Cerebrofy: Structural drift detected. Run 'cerebrofy update' to sync."
    exit 1
fi
# END cerebrofy
```

**Sentinel invariants**:
- `# BEGIN cerebrofy` and `# END cerebrofy` are the outermost delimiters — never nested
- `# cerebrofy-hook-version: N` is always the second line within the block
- Non-Cerebrofy hook content outside the sentinels is NEVER modified
- Idempotency: if `# cerebrofy-hook-version: 2` already present, no changes made on re-upgrade

---

### .gitignore Entry (FR-019)

`cerebrofy init` appends to the repository's `.gitignore`:

```
# cerebrofy — local index (not committed)
.cerebrofy/db/
```

**Rules**:
- If `.cerebrofy/db/` already present: no duplicate added (check before append)
- If `.gitignore` does not exist: created with this entry
- Append-only: existing `.gitignore` content is preserved

---

## Corrections to Existing Phase 4 Entities

### PlanReport (Phase 4 data-model.md — correction FR-023)

**Current Phase 4 definition** (missing `schema_version`):
```python
@dataclass(frozen=True)
class PlanReport:
    matched_neurons: list[NeuronMatch]
    blast_radius: list[NeuronRef]
    affected_lobes: list[str]
    reindex_scope: list[str]
```

**Corrected definition** (adds `schema_version`):
```python
@dataclass(frozen=True)
class PlanReport:
    schema_version: int  # Always 1; incremented only on breaking JSON schema changes
    matched_neurons: list[NeuronMatch]
    blast_radius: list[NeuronRef]
    affected_lobes: list[str]
    reindex_scope: list[str]
```

**JSON output change**: The `--json` flag output now includes `"schema_version": 1` as the
first top-level field. Field ordering: `schema_version`, `matched_neurons`, `blast_radius`,
`affected_lobes`, `reindex_scope`.

### TaskItem.blast_count (Phase 4 data-model.md — correction FR-022)

**Current Phase 4 definition** (ambiguous):
> `blast_count`: total count of BFS neighbors across all matched Neurons

**Corrected definition**:
> `blast_count`: count of BFS neighbors **reachable from this specific Neuron** (depth-2).
> Computed as `len(bfs_neighbors(neuron_id, depth=2, exclude_runtime_boundary=True))`.
> Each TaskItem has an independent blast_count. The same Neuron appearing in different queries
> will always produce the same blast_count regardless of what other Neurons are in the result.

---

## Entity Relationship Summary

```
MCP Config File (disk)
    └── MCPServerEntry ("cerebrofy": {command, args})

cerebrofy mcp (stdio server)
    ├── tool: plan  → MCPToolResult (PlanReport JSON)
    ├── tool: tasks → MCPToolResult (TaskItem[] JSON)
    └── tool: specify → MCPToolResult (output_file, content)

cerebrofy parse (CLI command)
    └── stdout: ParseResult (NDJSON stream of Neuron objects)

.git/hooks/pre-push (disk)
    └── HookVersionBlock (versioned sentinel block)

.gitignore (disk)
    └── GitignoreEntry (".cerebrofy/db/")
```
