# MCP Tools Reference

Cerebrofy ships an MCP (Model Context Protocol) stdio server that registers **39 fully operational tools** and a set of URI-addressable **resources** for AI assistants. Once registered, any MCP-compatible client (Claude Code, Cursor, VS Code, Copilot, etc.) can call them directly against your local index.

## Setup

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
| `cerebrofy_arch_check` | Check architecture drift rules against the live call graph |
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
| `cerebrofy_claim` | Claim neuron ids or file targets before editing; skips and reports neurons already held by another active agent |
| `cerebrofy_release` | Release specific claims, or every claim held by an agent |
| `cerebrofy_who` | List active agents, their intents, claimed neurons, and overlapping claims |
| `cerebrofy_conflicts` | Report overlapping claims and contradicting memories (`keyword_opposition`) |
| `cerebrofy_resolve` | Resolve a pair of contradicting memories with a deterministic strategy |
| `cerebrofy_synthesize` | Cross-session synthesizer: detect failure/success patterns, lobe fragility, effort calibration, and agent blind spots from recorded sessions |
| `cerebrofy_build` | Full atomic re-index of the entire repository |
| `cerebrofy_update` | Incremental re-index of changed files only |
| `cerebrofy_validate` | Drift check — zero writes |
| `cerebrofy_session_start` | Start recording an agent session (opt-in via `record_sessions`). Returns a `session_id`. |
| `cerebrofy_session_end` | End the active session: outcome, duration, neurons touched, events, and blast-radius before/after. |
| `cerebrofy_session_show` | Full replay of a session (latest when omitted): timeline, neurons touched, graph diff, blast-radius verdict. |
| `cerebrofy_narrative` | Read or regenerate `NARRATIVE.md` — architectural eras, significant events, architectural DNA, and intent-driven trajectory |

All data-reading tools automatically include an `"epistemic"` field with the current confidence score, and an `"intent_context"` field if `.cerebrofy/intent.yaml` exists. `search_code`, `get_neuron`, and `cerebrofy_remember` also accept an optional `agent_id` that refreshes that agent's coordination heartbeat and excludes its own claims from conflict notices.

## Detailed Tool Schemas

Each tool is documented in its respective feature guide:

- [Blast Radius](../features/blast-radius.md) — `cerebrofy_blast_radius`
- [Health](../features/health.md) — `cerebrofy_health`
- [Memory](../features/memory.md) — `cerebrofy_remember`, `cerebrofy_recall`, `cerebrofy_memories`, `cerebrofy_link_memories`, `cerebrofy_trace_history`
- [Sessions](../features/sessions.md) — `cerebrofy_session_start`, `cerebrofy_session_end`, `cerebrofy_session_show`
- [Synthesizer](../features/synthesizer.md) — `cerebrofy_synthesize`
- [Narrative](../features/narrative.md) — `cerebrofy_narrative`
- [Insights](../features/insights.md) — `cerebrofy_insights`
- [Changelog](../features/changelog.md) — `cerebrofy_changelog`
- [Coordination](../features/coordination.md) — `cerebrofy_claim`, `cerebrofy_release`, `cerebrofy_who`, `cerebrofy_conflicts`, `cerebrofy_resolve`
- [Governance](../features/governance.md) — `cerebrofy_governance`
- [Silo Detection](../features/silo-detection.md) — `cerebrofy_silo`
- [Upgrade](../features/upgrade.md) — `cerebrofy_upgrade`
- [Coverage Gap](../features/coverage-gap.md) — `cerebrofy_coverage_gap`
- [Vulnerability](../features/vulnerability.md) — `cerebrofy_vuln`
- [Onboarding](../features/onboarding.md) — `cerebrofy_onboard`
- [Review](../features/review.md) — `cerebrofy_review`
- [Security](../features/security.md) — security model for MCP server

## Available Resources

In addition to tools, the server exposes URI-addressable **resources**. Clients read them via the MCP `resources/read` protocol method — no tool call required — and can subscribe to change notifications.

### Static Resources

| URI | Type | Content |
|-----|------|---------|
| `cerebrofy://graph/map` | `text/markdown` | Full codebase map (`docs/cerebrofy/cerebrofy_map.md`) |
| `cerebrofy://graph/entry-points` | `application/json` | Entry-point neurons (no non-runtime callers, with outgoing edges) |
| `cerebrofy://health/current` | `application/json` | Latest health snapshot |
| `cerebrofy://lobes/{name}` | `text/markdown` | Per-lobe summary (one resource per indexed lobe) |

### URI Templates

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

### Auto-Include

Some MCP clients can pin resources so they load into every session without an explicit read. Point them at `cerebrofy://graph/map`, `cerebrofy://graph/entry-points`, and `cerebrofy://health/current` for zero-tool-call orientation.

## CWD Routing

The MCP server uses **CWD routing**: at each tool call it reads `os.getcwd()` and walks up the directory tree looking for `.cerebrofy/config.yaml`. A single registered MCP entry serves all Cerebrofy-initialized repositories on the machine — no per-repo setup needed.

**Launch boundary.** Routing is clipped to where the server was launched: launched inside a repo, the boundary is that project root (a CWD pointing at a sibling repo is refused); launched at a non-project directory such as a workspace root, the boundary is that directory, so repos *beneath* it are served but siblings and parents are not. To pin one project explicitly — skipping the boundary logic entirely — set `CEREBROFY_ROOT` or pass `--root`.

If the AI client's CWD is not within a Cerebrofy-initialized repo, the tool returns:

```
No Cerebrofy index found. Run 'cerebrofy build' first.
```

## Error Responses

| Condition | Response |
|-----------|----------|
| No `.cerebrofy/config.yaml` found | `"No Cerebrofy index found. Run 'cerebrofy build' first."` |
| Schema version mismatch | `"Schema version mismatch. Run 'cerebrofy migrate' to update."` |
| Embedding model mismatch | `"Embedding model mismatch. Run 'cerebrofy build' to rebuild."` |

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