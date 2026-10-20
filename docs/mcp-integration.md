# MCP Integration Guide

Cerebrofy ships an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) stdio server that registers **31 fully operational tools** and a set of URI-addressable **resources** for AI assistants. Once registered, any MCP-compatible client (Claude Code, Cursor, VS Code, Copilot, etc.) can call them directly against your local index.

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
| `cerebrofy_arch_check` | Check architecture drift rules against the live call graph (index confidence + sprint escalations included) |
| `cerebrofy_remember` | Write a structured memory attached to a neuron or lobe |
| `cerebrofy_recall` | Semantic search across all memories |
| `cerebrofy_memories` | List memories for a specific neuron or lobe |
| `cerebrofy_link_memories` | Create a directed causal link between two memories |
| `cerebrofy_trace_history` | Trace the ancestry chain of a memory through its linked predecessors |
| `cerebrofy_onboard` | Generate a topology-derived onboarding guide: reading order, entry points, hotspots, safe zones |
| `cerebrofy_impact` | Pre-change impact prediction: callers, test coverage, lobe spread, estimated LoC, memory warnings, refactoring sequence |
| `cerebrofy_plan` | Generate a graph-aware, step-by-step refactoring plan from a plain-English description — which neurons to extract, where they move, which callers to update, and in what safe order. Markdown + optional JSON. Never modifies files. |
| `cerebrofy_vuln` | Vulnerability blast radius: find which of your functions call a vulnerable package, score exposure by trust boundary proximity, generate remediation sequence |
| `cerebrofy_upgrade` | Dependency upgrade navigator: affected neurons, effort/risk, ordered steps, optional AST auto-fix and post-upgrade validation. Offline manifests. |
| `cerebrofy_silo` | Knowledge silo detector: git-blame overlay on the call graph — bus factor risk per neuron, filterable by lobe, author, or risk level |
| `cerebrofy_coverage_gap` | Test coverage gap predictor: ranks uncovered neurons by blast radius × change velocity |
| `cerebrofy_list_resources` | Discover every MCP resource URI (static resources + URI templates), optionally filtered by type |
| `cerebrofy_changelog` | Generate a semantic changelog for a git range — classified from the call graph, drift records, and memories |
| `cerebrofy_governance` | Lobe ownership and review governance: generate CODEOWNERS, suggest reviewers for a PR/diff, check reporting-only governance rules |
| `cerebrofy_review` | Graph-aware AI review copilot: reviews a local diff or GitHub PR with blast radius, memories, arch rules, coverage gaps, coupling, and suggested reviewers; posting is opt-in |
| `cerebrofy_build` | Full atomic re-index of the entire repository |
| `cerebrofy_update` | Incremental re-index of changed files only |
| `cerebrofy_validate` | Drift check — zero writes |
| `cerebrofy_session_start` | Start recording an agent session (opt-in via `record_sessions`). Returns a `session_id`. |
| `cerebrofy_session_end` | End the active session: outcome, duration, neurons touched, events, and blast-radius before/after. |
| `cerebrofy_session_show` | Full replay of a session (latest when omitted): timeline, neurons touched, graph diff, blast-radius verdict. |

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
    { "name": "auth", "summary_file": "docs/cerebrofy/auth_lobe.md" },
    { "name": "api",  "summary_file": "docs/cerebrofy/api_lobe.md" }
  ],
  "full_map": "docs/cerebrofy/cerebrofy_map.md"
}
```

Read the `summary_file` for a module overview before searching within it.

---

### `cerebrofy_list_resources`

Discover every MCP resource URI this server exposes — static resources (codebase map, entry points, health) and URI templates (neurons, files, search, memories, blast radius). Use it to discover ambient context, then read a URI via the MCP `resources/read` protocol method (resources are not tool calls).

**Input schema:**

```json
{
  "filter": "all"
}
```

`filter` accepts `graph`, `lobes`, `neurons`, `health`, `memories`, `blast-radius`, or `all` (default).

**Output:** JSON catalog with `uri`, `name`, `description`, `mime_type`, `category`, and `template` fields per entry, plus `count`. See [Available Resources](#available-resources).

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

### `cerebrofy_arch_check`

Check `.cerebrofy/arch-rules.yaml` architecture drift rules against the live call graph: forbidden lobe-to-lobe edges, circular lobe dependencies, allowed-callers isolation, and max blast radius. Call it after making changes to catch architectural drift before merge.

**Input schema:**

```json
{
  "rule": "all",
  "format": "markdown",
  "since": "HEAD~1"
}
```

`rule` accepts a rule name or `"all"` (default). `format` accepts `"markdown"`, `"json"`, or `"github-annotations"`. `since` restricts the check to neurons changed since a git ref (e.g. `"HEAD~1"`, `"main"`).

**Output:** a per-rule report ending in `RESULT: PASS | WARN | FAIL`. The result also carries the current index confidence and marks warning rules that were escalated by the active sprint's priority lobes (`.cerebrofy/intent.yaml`) — treat escalated rules as failures, since they block commits for the sprint's duration.

Returns `NO_RULES_FILE` (offer `cerebrofy arch init`), `NO_INDEX` (offer `cerebrofy build` first), or `RULE_NOT_FOUND` when prerequisites are missing.

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

### `cerebrofy_session_start`

Start recording an agent session. Every MCP tool call made while the session is open is recorded locally into a replayable session. **Opt-in** — see `record_sessions` in [docs/configuration.md](configuration.md).
### `cerebrofy_plan`

Generate a step-by-step, graph-aware refactoring plan from a plain-English description — which neurons to extract, where they move, which callers to update, and in what safe order. The plan is a human-in-the-loop pre-flight checklist; it **never modifies files**. `dry_run` defaults to true — set it to false to also prepare an execution-handoff context window for the agent that will implement the plan.
### `cerebrofy_changelog`

Generate a semantic changelog for a git range — classified from the call graph, drift records, and memories, never from commit messages. Entry types: `feat`, `fix`, `refactor`, `security`, `breaking`, `perf`, `internal`, `intent_update`.

**Input schema:**

```json
{
  "task": "Add rate limiting to login endpoint",
  "agent": "claude-sonnet-4-6"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `task` | string | yes | Human-readable description of the coding task |
| `agent` | string | no | Agent identifier (e.g. `claude-sonnet-4-6`, `human:alice`) |

**Output:** `{"session_id": "sess_abc123", "task": "...", "agent": "...", "started_at": 1718..., "recording": true}`. When other sessions are still open, a `warning` field lists them.

**Error codes:** `[NO_INDEX]` when no `.cerebrofy` directory is found; `[RECORDING_DISABLED]` when `record_sessions` is false.

---

### `cerebrofy_session_end`

Close the active session and fold in the outcome, blast-radius "after" metric (Idea #01), and event count.

**Input schema:**

```json
{
  "session_id": "sess_abc123",
  "outcome": "success",
  "summary": "Added a token-bucket rate limiter and wired it into the login route."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | yes | ID returned by `cerebrofy_session_start` |
| `outcome` | string | no | `success` · `partial` · `failed` · `unknown` (default `unknown`) |
| `summary` | string | no | Free-text summary written to `outcome_notes` |

**Output:** `{"session_id": "...", "duration_seconds": 120, "neurons_touched": 3, "events_recorded": 9, "outcome": "success", "blast_radius_before": 14, "blast_radius_after": 14}`.

**Error codes:** `[SESSION_NOT_FOUND]` when the session id does not exist; `[NO_ACTIVE_SESSION]` when the session is already ended.

---

### `cerebrofy_session_show`

Return a full replay of a session (default: the most recent). The `cerebrofy_session_show` tool and the `cerebrofy session show` / `diff` / `export` CLI commands all derive from this replay.

**Input schema:**

```json
{
  "session_id": "sess_abc123",
  "since": "v1.2.0",
  "audience": "developer",
  "format": "markdown"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | string | no | Session to retrieve; omit for the most recent session |
| `format` | string | no | `markdown` (default) · `json` |

**Output (JSON):** the session record plus its events and graph diff — `session_id`, `task`, `agent`, `started_at`, `ended_at`, `outcome`, `outcome_notes`, `duration_seconds`, `neurons_touched[]`, `blast_radius_before`, `blast_radius_after`, `events[]` (`ts`, `tool`, `args`, `result_summary`), and a `diff` object (`present`, `missing`, `appeared`, `graph_refreshed`, `risk_verdict`).

**Error codes:** `[SESSION_NOT_FOUND]` when no session (or the requested id) exists.

  "description": "extract the payment logic into a payments service",
  "format": "markdown",
  "dry_run": true
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `description` | string | ✅ | Natural language description of the desired refactoring. |
| `format` | string | — | `markdown` (default) or `json` (machine-readable for CI/CD). |
| `dry_run` | boolean | — | If true, generate the plan only — do not modify any files (default: true). |

**How it works:** Embeds the description → KNN search over `vec_neurons` → cohesive-cluster expansion (neighbors with >50% internal edges join) → reverse-topological sequencing (callees before callers) → per-step impact prediction and blast-radius containment. Integrations with blast radius (#01), agent memory (#05), refactor impact (#07), and product intent (#23) all degrade gracefully when their data is absent.

**Output (`format: json`):** exact spec schema —

```json
{
  "cluster": [{ "name": "charge", "file": "src/pay/charge.py", "relevance_score": 0.98 }],
  "proposed_structure": { "new_module": "payments", "files": ["payments/charge.py"] },
  "callers_to_update": [{ "name": "route", "file": "src/api/routes.py", "line": 8 }],
  "steps": [{
    "step_number": 1,
    "description": "Create skeleton for 'payments/' — 1 new file(s): charge.py",
    "neurons_affected": [],
    "callers_break": false
  }],
  "estimated_hours": 1.1,
  "files_affected": 3
}
```

**Error codes:** `NO_INDEX` (run `cerebrofy build` first), `CLUSTER_TOO_SMALL` (fewer than 2 neurons matched — refine the query), `CLUSTER_TOO_LARGE` (more than 200 neurons matched — scope the description more narrowly).

**Example:**

```
cerebrofy_plan(description="extract the payment logic into a payments service", dry_run=true)
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `since` | string | ✅ | Start point: git tag, commit hash, `last-build` (commit of the newest health snapshot), or `project-start`. |
| `audience` | string | — | Target prose audience: `developer` (default), `pm`, or `user`. |
| `format` | string | — | Output format for `full_text`: `markdown` (default), `github`, or `slack`. |

**Output schema** (exact keys):

```json
{
  "since": "v1.2.0",
  "until": "a1b2c3d4e5f6...",
  "entries": [
    {
      "type": "feat",
      "title": "Added new_feature",
      "description": "src/api/views.py::new_feature (added). Callers: 0 direct...",
      "neurons": ["src/api/views.py::new_feature"],
      "blast_radius": 0,
      "audience_text": "**new_feature** (src/api/views.py): Added new_feature."
    }
  ],
  "breaking_changes": [
    {
      "title": "BREAKING: validate_token changed",
      "description": "src/auth/tokens.py::validate_token (signature_changed)...",
      "neurons": ["src/auth/tokens.py::validate_token"]
    }
  ],
  "health_delta": { "coupling": 0.3, "avg_blast": 2.0 },
  "full_text": "## Changelog v1.2.0 → a1b2c3d\n..."
}
```

**Entry types and triggers:**

| Type | Trigger |
|------|---------|
| `feat` | New neuron with no predecessor in the index |
| `fix` | Structural change to an existing neuron with a warning memory |
| `refactor` | Neuron moved across lobes (same name, different file lobe) |
| `security` | Neuron with security/CVE-tagged memories changed |
| `breaking` | >3 cross-lobe callers, signature change on a public surface, or removal with callers |
| `perf` | Neuron with performance-tagged memories changed |
| `internal` | Everything else — no user-visible impact |
| `intent_update` | `.cerebrofy/intent.yaml` changed in the range |

**Error codes:** `NO_INDEX` (run `cerebrofy build` first), `REF_NOT_FOUND` (unknown git ref).

Breaking changes are listed separately in `breaking_changes[]` so release notes never miss them. Use `--narrative` from the CLI to also persist every entry into the `narrative_events` table (idempotent per range — feeds the Codebase Narrative Engine, Idea #26).

---

## Available Resources

In addition to tools, the server exposes URI-addressable **resources**. Clients read them via the MCP `resources/read` protocol method — no tool call required — and can subscribe to change notifications.

### Static resources

| URI | Type | Content |
|-----|------|---------|
| `cerebrofy://graph/map` | `text/markdown` | Full codebase map (`docs/cerebrofy/cerebrofy_map.md`) |
| `cerebrofy://graph/entry-points` | `application/json` | Entry-point neurons (no non-runtime callers, with outgoing edges) |
| `cerebrofy://health/current` | `application/json` | Latest health snapshot |
| `cerebrofy://lobes/{name}` | `text/markdown` | Per-lobe summary (one resource per indexed lobe) |

### URI templates

| Template | Type | Content |
|----------|------|---------|
| `cerebrofy://neurons/{neuron_id}` | `application/json` | Single neuron details — source, signature, direct callers (`file::name` format) |
| `cerebrofy://neurons/file/{file_path}` | `application/json` | All neurons defined in a source file |
| `cerebrofy://neurons/search?q={query}` | `application/json` | Hybrid semantic search results |
| `cerebrofy://memories/{neuron_id}` | `application/json` | Memories attached to a neuron |
| `cerebrofy://blast-radius/{neuron_id}` | `application/json` | Callers, risk score, and PR-comment summary |

Discover the exact list at runtime with the [`cerebrofy_list_resources`](#cerebrofy_list_resources) tool (the lobe list depends on what has been indexed).

Example reads:

```
resources/read  cerebrofy://graph/map
resources/read  cerebrofy://lobes/auth
resources/read  cerebrofy://neurons/auth/tokens.py::validate_token
resources/read  cerebrofy://neurons/file/src/auth/tokens.py
resources/read  cerebrofy://neurons/search?q=token+expiry
resources/read  cerebrofy://blast-radius/validate_token
```

### Subscriptions

The server advertises `resources.subscribe = true` and watches the index while a client is connected:

| Event | Notification |
|-------|--------------|
| `cerebrofy build` / `cerebrofy update` rewrites `cerebrofy.db` or `memories.db` | `notifications/resources/updated` for every subscribed URI |
| Lobe Markdown files change (lobes added/removed) | `notifications/resources/list_changed` |

```
resources/subscribe  cerebrofy://graph/map
# ...cerebrofy update runs via the pre-commit hook → client is notified
resources/unsubscribe  cerebrofy://graph/map
```

### Auto-include

Some MCP clients can pin resources so they load into every session without an explicit read. Point them at `cerebrofy://graph/map`, `cerebrofy://graph/entry-points`, and `cerebrofy://health/current` for zero-tool-call orientation.

---

## CWD Routing

The MCP server uses **CWD routing**: at each tool call it reads `os.getcwd()` and walks up the directory tree to find `.cerebrofy/config.yaml`. A single registered MCP entry serves all Cerebrofy-initialized repositories on the machine — no per-repo setup needed.

**Launch boundary.** Routing is clipped to where the server was launched: launched inside a repo, the boundary is that project root (a CWD pointing at a sibling repo is refused); launched at a non-project directory such as a workspace root, the boundary is that directory, so repos beneath it are served but siblings and parents are not. To pin one project explicitly — skipping the boundary logic entirely — set `CEREBROFY_ROOT` or pass `--root`.

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

### `cerebrofy_governance`

Lobe ownership and review governance over the live index. Three actions:

- `generate-codeowners` — build a GitHub CODEOWNERS file from git blame, `.cerebrofy/team.yaml`, and cross-lobe call edges.
- `suggest-reviewers` — rank primary, secondary, and backup reviewers for a change set (GitHub PR or local diff).
- `check-rules` — evaluate the reporting-only `governance.rules` block in `.cerebrofy/arch-rules.yaml`.

**Input schema:**

```json
{
  "action": "suggest-reviewers",
  "pr": 42,
  "lobe": "auth",
  "format": "markdown"
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | string | ✅ | `generate-codeowners` · `suggest-reviewers` · `check-rules` |
| `pr` | integer | — | GitHub PR number — used by `suggest-reviewers` and `check-rules` (requires an authenticated `gh`) |
| `lobe` | string | — | Restrict output to a specific lobe |
| `format` | string | — | `markdown` (default) or `json` |

**Output:** for `generate-codeowners`, the CODEOWNERS file content (plain text, or `{"codeowners_content": "..."}` in JSON); for `suggest-reviewers`, a reviewer table (or `{"reviewers": [...]}`); for `check-rules`, a PASS/WARN/FAIL summary with per-rule reasons (or the full result object in JSON).

**Error codes:** `[NO_INDEX]` when no index exists; `[NO_GIT_HISTORY]` when ownership is requested from a repository with no commits; `[CONFIG_ERROR]` when `.cerebrofy/config.yaml` or `.cerebrofy/team.yaml` is malformed; `[GH_NOT_AUTHENTICATED]` when `gh` is unavailable; `[NO_GOVERNANCE_RULES]` when no `governance.rules` block is configured.

---

### `cerebrofy_upgrade`

Plan (and optionally apply/validate) a dependency upgrade from a curated breaking-change manifest. Fully offline.

**Input schema:**

```json
{
  "package": "pydantic",
  "from_version": "1.10.0",
  "to_version": "2.0.0",
  "breaking_only": true,
  "auto_fix": false,
  "step": [1, 2],
  "validate": false,
  "format": "markdown"
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `package` | string | ✅ | Package name (e.g. `pydantic`, `requests`) |
| `from_version` | string | — | Current version (used to select a manifest range) |
| `to_version` | string | — | Target version |
| `breaking_only` | boolean | — | Only report `breaking` changes (default: true) |
| `auto_fix` | boolean | — | Apply AST auto-fixes (default: false) |
| `step` | integer[] | — | Steps to auto-fix; omit for every auto-fixable step |
| `validate` | boolean | — | Rescan for remaining old patterns (default: false) |
| `format` | string | — | `markdown` (default) or `json` |

**Example:**

```
cerebrofy_upgrade(package="pydantic", from_version="1.10", to_version="2.0", format="json")
→ { "breaking_changes": [...], "steps": [...], "total_effort_hours": 0.4, "risk": "LOW" }

cerebrofy_upgrade(package="pydantic", validate=true, format="json")
→ { "passed": false, "remaining": [{ "file": "models.py", "line": 12, ... }] }
```

Errors use `[CODE] message`: `NO_INDEX`, `PACKAGE_NOT_USED`, `MANIFEST_NOT_FOUND`, `VERSION_NOT_FOUND`. Custom API diffs are CLI-only (`--manifest` / `--diff`).

---

### `cerebrofy_review`

Graph-aware review of a local diff or GitHub PR. Combines blast radius, warning
memories and past decisions, architecture rules, test coverage gaps, missing
caller updates, cross-lobe coupling, and knowledge-silo ownership into one
severity-sorted report, plus suggested reviewers and a PR-ready summary.

**Input schema:**

```json
{
  "diff": "HEAD~1",
  "pr": 142,
  "severity": "all",
  "post_comments": false,
  "format": "markdown"
}
```

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `diff` | string | — | Git ref to diff against (e.g. `HEAD~1`, `main`) |
| `pr` | integer | — | GitHub PR number to review (requires `gh` auth) |
| `severity` | string | — | Minimum severity: `error`, `warning`, or `all` (default: `all`) |
| `post_comments` | boolean | — | Post findings as inline PR comments plus a summary (requires `pr` and `gh` auth; default: false — local dry-run) |
| `format` | string | — | `markdown` (default) or `json` |

**Output:** findings sorted by `severity_score` descending, with `skipped_checks`
for degraded integrations, `suggested_reviewers`, health delta, and a PR-ready
markdown summary (or the full report object in JSON).

**Error codes:** `[NO_INDEX]` when no index exists; `[NO_DIFF_PROVIDED]` when
neither `diff` nor `pr` is supplied; `[GH_NOT_AUTHENTICATED]` when `gh` is
unavailable or unauthenticated.

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
