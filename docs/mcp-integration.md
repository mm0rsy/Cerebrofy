# MCP Integration Guide

Cerebrofy ships an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) stdio server that registers **fourteen fully operational tools** for AI assistants. Once registered, any MCP-compatible client (Claude Code, Cursor, VS Code, Copilot, etc.) can call them directly against your local index.

---

## Prerequisites

```bash
uv tool install "cerebrofy[mcp]"
```

The `mcp` package is an optional extra. The base `cerebrofy` install (without `[mcp]`) is sufficient for all CLI commands but cannot start the MCP server.

> If you installed without `[mcp]` and run `cerebrofy mcp`, you will see an import error. Re-install with `[mcp]` to fix it.

---

## Quick Setup

```bash
# 1. Install with MCP support
uv tool install "cerebrofy[mcp]"

# 2. Initialize your repo (auto-registers the MCP entry with the absolute binary path)
cd /path/to/your/repo
cerebrofy init

# 3. Build the index
cerebrofy build

# 4. Restart your AI client to pick up the new MCP entry
```

`cerebrofy init` resolves the absolute path to the `cerebrofy` binary at registration time and writes it directly into the MCP config. This avoids PATH-lookup failures when the AI client launches with a minimal environment.

If the binary moves (e.g. after reinstalling), re-run with `--force`:

```bash
cerebrofy init --force
```

---

## Registration Target

`cerebrofy init` writes to `.mcp.json` in the current directory by default, registering the server for that project only.

To register globally:

```bash
cerebrofy init --global    # writes to ~/.config/mcp/servers.json
```

If a config already contains a `cerebrofy` entry, `cerebrofy init` skips it. Use `--force` to overwrite.

---

## Manual Registration

```json
{
  "mcpServers": {
    "cerebrofy": {
      "command": "/absolute/path/to/cerebrofy",
      "args": ["mcp"],
      "env": {}
    }
  }
}
```

Use the full absolute path (find it with `which cerebrofy`). For Claude Desktop on macOS the config is at `~/Library/Application Support/Claude/claude_desktop_config.json`.

---

## Available Tools

| Tool | Description |
|------|-------------|
| `search_code` | Hybrid KNN + BFS semantic search — primary navigation |
| `get_neuron` | Fetch a specific function or class by name or file:line |
| `list_lobes` | List all indexed modules with summary file paths |
| `cerebrofy_context` | Build optimal context window for a task within a token budget |
| `cerebrofy_blast_radius` | Compute every caller affected by a changed neuron + risk score |
| `cerebrofy_epistemic` | Return confidence score and staleness warnings for the index |
| `cerebrofy_health` | Longitudinal codebase health metrics from the call graph |
| `cerebrofy_intent` | Return sprint goals, incidents, and architectural direction |
| `cerebrofy_remember` | Write a structured memory attached to a neuron or lobe |
| `cerebrofy_recall` | Semantic search across all memories |
| `cerebrofy_memories` | List memories for a specific neuron or lobe |
| `cerebrofy_link_memories` | Create a directed causal link between two memories |
| `cerebrofy_trace_history` | Trace the ancestry chain of a memory through its linked predecessors |
| `cerebrofy_onboard` | Generate a topology-derived onboarding guide: reading order, entry points, hotspots, safe zones |
| `cerebrofy_impact` | Pre-change impact prediction: callers, test coverage, lobe spread, estimated LoC, memory warnings, refactoring sequence |
| `cerebrofy_vuln` | Vulnerability blast radius: find which of your functions call a vulnerable package, score exposure by trust boundary proximity, generate remediation sequence |
| `cerebrofy_build` | Full atomic re-index of the entire repository |
| `cerebrofy_update` | Incremental re-index of changed files only |
| `cerebrofy_validate` | Drift check — zero writes |

---

### `search_code`

**Primary navigation tool.** Hybrid semantic + graph search over the Cerebrofy index. Call this before reading any source file.

**Input schema:**

```json
{
  "query": "OAuth2 token validation",
  "top_k": 10,
  "lobe": "auth"
}
```

`lobe` is optional — omit to search all modules. `top_k` defaults to 10, max 50.

**How it works:** Embeds the query using the same model as the index (BAAI/bge-small-en-v1.5, offline), runs a KNN cosine-similarity search over `vec_neurons`, then expands the results via depth-2 BFS through the call graph (skipping `RUNTIME_BOUNDARY` edges). Returns ranked neurons sorted by similarity.

**Output:** JSON with ranked results, each containing `name`, `type`, `file`, `line`, `similarity`, `summary`.

```json
{
  "results": [
    {
      "name": "validate_token",
      "type": "function",
      "file": "src/auth/validator.py",
      "line": 42,
      "similarity": 0.923,
      "summary": "Validate a JWT token and return the decoded payload."
    }
  ],
  "count": 1
}
```

---

### `get_neuron`

Fetch full details for a specific neuron by name or by file path + optional line number. Use after `search_code` to get the full signature and docstring.

**Input schema (by name):**

```json
{ "name": "validate_token" }
```

**Input schema (by file):**

```json
{ "file": "src/auth/validator.py", "line": 42 }
```

**Output:** JSON array of up to 5 matching neurons with `id`, `name`, `type`, `file`, `line_start`, `line_end`, `signature`, `docstring`.

---

### `list_lobes`

List all indexed lobes (named subsections of your codebase) with paths to their Markdown summary files.

**Input schema:** none

**Output:**

```json
{
  "lobes": [
    { "name": "auth", "summary_file": ".cerebrofy/lobes/auth_lobe.md" },
    { "name": "api",  "summary_file": ".cerebrofy/lobes/api_lobe.md" }
  ],
  "full_map": ".cerebrofy/cerebrofy_map.md"
}
```

Read the `summary_file` for a module overview before searching within it.

---

### `cerebrofy_context`

Build the optimal context window for a coding task within a token budget. Embeds the task, runs KNN + BFS, scores candidates by relevance, and greedy-packs neurons with tier degradation (`full_source → signature → lobe_summary → name_only`). Call this before starting any non-trivial coding task.

**Input schema:**

```json
{
  "task": "Add rate limiting to the payments API",
  "budget": 8000,
  "model": "auto",
  "format": "json"
}
```

`budget` defaults to 8000 tokens. `model` defaults to `"auto"` (heuristic token counting). `format` accepts `"json"`, `"markdown"`, or `"claude-xml"`.

**Output:** A packed context plan with selected neurons, their representation tier, token counts, and a full epistemic confidence payload (`overall_confidence`, `neurons_changed_since_build`, `unindexed_languages`, `dynamic_dispatch_count`, `missing_test_paths`, `caveats`, `recommendation`).

---

### `cerebrofy_blast_radius`

Compute the blast radius of a changed neuron — every caller at depth 1 and 2, test coverage gaps, lobe spread, and a risk score. Use after a PR diff to understand what a change affects before merging.

**Input schema:**

```json
{
  "target": "src/auth/validator.py::validate_token",
  "depth": 2,
  "format": "json"
}
```

`target` accepts `"file::name"`, `"file:line"`, or a plain function name. `depth` defaults to 2 (max 5). `format` accepts `"json"` or `"markdown"` (PR comment format).

**Output:**

```json
{
  "target_neuron": { "name": "validate_token", "file": "src/auth/validator.py", "line": 42 },
  "callers": [
    { "name": "authenticate_request", "file": "src/api/middleware.py", "line": 18, "depth": 1 }
  ],
  "uncovered_callers": ["authenticate_request"],
  "risk_score": 0.72,
  "risk_label": "HIGH",
  "lobe_spread": 3,
  "summary": "..."
}
```

---

### `cerebrofy_epistemic`

Return the epistemic confidence score for the current index — graph age, neurons changed since last build, unindexed languages, dynamic dispatch count, and a composite confidence score (0.5–1.0). Call this before any architectural decision to understand how much to trust the index.

All other Cerebrofy tool responses include an `"epistemic"` field automatically.

**Input schema:**

```json
{ "format": "json" }
```

`format` accepts `"json"` or `"human"`.

**Output:**

```json
{
  "overall_confidence": 0.91,
  "graph_age_hours": 2.3,
  "neurons_changed_since_build": 0,
  "unindexed_languages": [],
  "dynamic_dispatch_count": 4,
  "caveats": [],
  "recommendation": "Index is fresh — results are reliable"
}
```

---

### `cerebrofy_health`

Return longitudinal codebase health metrics derived from the call graph. Includes coupling, blast radius trend, dead code %, lobe cohesion, test surface coverage, drift velocity, and hub concentration. Use to understand whether the codebase is improving or degrading over time.

**Input schema:**

```json
{
  "since_build": 1,
  "metric": "all",
  "format": "markdown"
}
```

`since_build` compares against N builds ago. `metric` can be `"all"` or a specific metric name (e.g. `"coupling"`). `format` accepts `"markdown"` or `"json"`.

**Output (markdown):** A formatted health dashboard with delta arrows (↑/↓) vs the previous build and a trend sparkline.

---

### `cerebrofy_intent`

Return the current product intent — sprint goals, active incidents, architectural direction, and team context from `.cerebrofy/intent.yaml`. Pass `lobe` or `neuron` to get relevance scoring for a specific part of the codebase.

Call this at the start of any task to understand team priorities and known risks.

**Input schema:**

```json
{
  "lobe": "payments",
  "format": "json"
}
```

Both `lobe` and `neuron` are optional. `format` accepts `"json"` or `"human"`.

**Output:**

```json
{
  "sprint": { "name": "Payments v2", "goal": "Ship Stripe billing", "deadline": "2026-07-15", "priority_lobes": ["payments", "api"] },
  "incidents": [{ "id": "INC-001", "severity": "critical", "description": "...", "status": "patched" }],
  "architecture": { "direction": "Event-driven via Kafka", "avoid_patterns": ["direct DB from API"] },
  "team_context": { "concerns": ["payments/ test coverage is 34%"] },
  "relevance_to_query": {
    "sprint_relevance": "HIGH — payments is a priority lobe this sprint",
    "active_incidents": [],
    "architectural_guidance": ["AVOID: direct DB from API"]
  }
}
```

Returns `NO_INTENT_FILE` if `.cerebrofy/intent.yaml` does not exist — create it with `cerebrofy intent init`.

---

### `cerebrofy_remember`

Write a structured memory attached to a neuron or lobe. Call this after any important architectural decision, discovered gotcha, or completed refactor — future agents will find it via `cerebrofy_recall`.

**Input schema:**

```json
{
  "title": "Clock skew breaks token expiry",
  "body": "validate_token fails when system clock drift > 30s. Always use NTP-synced time.",
  "type": "warning",
  "neuron": "auth/tokens.py::validate_token",
  "tags": ["security", "jwt"],
  "author": "claude-sonnet-4-6"
}
```

Valid types: `decision`, `warning`, `context`, `pattern`, `agent_action`.

**Output:** `{"id": "<uuid>", "neuron_id": "<resolved-id>|null", "created_ts": 1234567890}`

If `neuron` cannot be resolved, the memory is stored without anchor and a `"warning"` field is added to the response.

---

### `cerebrofy_recall`

Semantic search across all memories. Use before starting any task to surface relevant past decisions, warnings, and agent actions.

**Input schema:**

```json
{
  "query": "JWT expiry edge cases",
  "lobe": "auth",
  "type": "warning",
  "limit": 10,
  "include_stale": false
}
```

**Output:** Ranked list with `relevance_score` and `decay_score` per memory. Returns `{"memories": [], "count": 0}` gracefully if no `memories.db` exists yet.

---

### `cerebrofy_memories`

List memories for a specific neuron or lobe without a search query. Use when you already know which neuron or lobe you are about to modify.

**Input schema:**

```json
{
  "neuron": "auth/tokens.py::validate_token",
  "include_stale": false
}
```

At least one of `neuron` or `lobe` is required.

**Output:** `{"memories": [...], "count": N}`. Also included automatically in `get_neuron` responses as a `"memories"` array.

---

### `cerebrofy_build`

Trigger a full atomic re-index of the entire repository. Use when the index is missing or a full rebuild is needed.

**Input schema:** none

**Output:** `[success]` or `[error]` followed by CLI output.

---

### `cerebrofy_update`

Trigger an incremental re-index of changed files (auto-detected via git diff).

**Input schema:**

```json
{ "path": "src/auth/validator.py" }
```

`path` is optional — omit to auto-detect all changed files.

**Output:** `[success]` or `[error]` followed by CLI output.

---

### `cerebrofy_validate`

Check for drift between source code and the index. Zero writes to any file or database.

**Input schema:** none

**Output:** `[clean]`, `[minor_drift]`, or `[structural_drift]` followed by details.

---

## CWD Routing

The MCP server uses **CWD routing**: at each tool call it reads `os.getcwd()` and walks up the directory tree to find `.cerebrofy/config.yaml`. A single registered MCP entry serves all Cerebrofy-initialized repositories on the machine — no per-repo setup needed.

If the AI client's CWD is not within a Cerebrofy-initialized repo, the tool returns:

```
No Cerebrofy index found. Run 'cerebrofy build' first.
```

---

## Error Responses

| Condition | Response |
|-----------|----------|
| No `.cerebrofy/config.yaml` found | `"No Cerebrofy index found. Run 'cerebrofy build' first."` |
| Schema version mismatch | `"Schema version mismatch. Run 'cerebrofy migrate' to update."` |
| Embedding model mismatch | `"Embedding model mismatch. Run 'cerebrofy build' to rebuild."` |

---

## Verifying the Setup

After registration and restart, ask your AI client:

> "Use the cerebrofy_validate tool to check if the index is up to date."

You should see `[clean]` or drift details. If you see `"No Cerebrofy index found"`, run `cerebrofy build` in your project directory first.

---

### `cerebrofy_vuln`

Find which of your functions are exposed to a vulnerable package, ranked by exploitability proximity to external trust boundaries.

**Input schema:**

```json
{
  "package": "requests",
  "function_pattern": "requests.get",
  "depth": 2,
  "write_memories": false
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `package` | string | ✅ | Package name to scan (e.g. `requests`, `pyyaml`) |
| `function_pattern` | string | — | Specific function to trace (e.g. `requests.get`). Omit to scan the full package. |
| `depth` | integer | — | Upstream BFS depth (default: 2, max: 5) |
| `write_memories` | boolean | — | Write `warning` memories to each directly-affected neuron (default: false) |

**Example response:**

```json
{
  "package": "requests",
  "function_pattern": null,
  "pinned_version": "requests>=2.28.0",
  "direct_callers": [
    {
      "name": "fetch_webhook_payload",
      "file": "api/integrations.py",
      "line_start": 42,
      "call_target": "external::requests.get",
      "is_trust_boundary": true,
      "is_test": false
    }
  ],
  "upstream_count": 5,
  "critical_exposure": [
    {
      "entry_point": "api/integrations.py::fetch_webhook_payload",
      "call_chain": ["fetch_webhook_payload"],
      "exposure_score": 1.0
    }
  ],
  "low_exposure": [
    { "name": "fetch_test_data", "file": "tests/fixtures.py", "is_test": true }
  ],
  "remediation_sequence": [
    {
      "step": 1,
      "description": "Patch fetch_webhook_payload (api/integrations.py) — highest exposure",
      "neuron": "api/integrations.py::fetch_webhook_payload",
      "exposure_score": 1.0
    },
    {
      "step": 2,
      "description": "Pin requests >= <safe_version> in pyproject.toml after patching call sites",
      "neuron": null,
      "exposure_score": 0.0
    }
  ],
  "memories_written": 0,
  "epistemic": { "confidence": 0.95, "age_hours": 0.5 }
}
```

**Exposure scoring:**

| `exposure_score` | Meaning |
|-----------------|---------|
| `1.0` | Direct caller is a trust boundary entry point (in_degree == 0) — external input flows directly into the vulnerable call |
| `0.6` | Direct caller is internal but has a trust boundary ancestor reachable within `depth` hops |
| `0.1` | Test file or caller with no trust boundary ancestor found |

**Workflow:**

```
# Before upgrading a dependency with a known CVE
cerebrofy_vuln(package="requests")
→ Identify critical_exposure entry points
→ Patch those call sites
→ cerebrofy_vuln(package="requests")  # verify no remaining critical exposure
→ Upgrade requests in pyproject.toml
```

---

## Troubleshooting

**`cerebrofy mcp` exits with import error**

```
Error: MCP server requires the 'mcp' package. Install with: uv tool install "cerebrofy[mcp]"
```

**Tools not appearing in the AI client**

- Restart the client after registration
- Verify the MCP config contains the `cerebrofy` entry with an absolute binary path
- Re-run `cerebrofy init --force`
- Check `ls -la $(which cerebrofy)`

**"No Cerebrofy index found" when index exists**

The AI client's CWD may not be within the repo. Check the client's working directory and ensure `cerebrofy init` + `cerebrofy build` have been run there.

**Multiple installation warning**

Ensure only one cerebrofy binary is on your PATH (don't mix pip and snap installs).
