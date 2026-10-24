# Sessions

`cerebrofy session` records, replays, and audits AI agent sessions — closing the "what did the agent actually do?" gap. Recording is **opt-in** (`record_sessions: true` in `.cerebrofy/config.yaml`) and **local-only**: every MCP tool call is stored in `.cerebrofy/db/sessions.db`, which is separate from the index database so it survives rebuilds.

## What It Is

Session recording captures every MCP tool call made by an AI agent during a coding task, creating a replayable audit trail. Each replay shows which neurons were touched, what changed in the call graph, and how the blast radius moved before and after the session.

## CLI Reference

```bash
cerebrofy session list                                   # list recorded sessions
cerebrofy session show sess_abc123                       # full replay (latest when omitted)
cerebrofy session diff sess_abc123                       # graph changes the session made
cerebrofy session search "rate limiting"                 # semantic search across session tasks
cerebrofy session export sess_abc123 --format html       # shareable self-contained HTML report
cerebrofy session export --format html --output report.html
```

| Command | Purpose |
|---------|---------|
| `list` | Sessions newest-first with outcome and event count |
| `show` | Full Markdown timeline + graph diff + risk assessment (JSON with `--format json`) |
| `diff` | Graph delta (touched / missing / appeared / refreshed) and blast-radius verdict |
| `search` | Semantic KNN over task text (fallback: task-text match when embeddings are unavailable) |
| `export` | Self-contained HTML / Markdown / JSON report |

## Enabling Session Recording

Add to `.cerebrofy/config.yaml`:

```yaml
record_sessions: true

session:
  max_tracked_neurons: 50    # cap on distinct neurons folded into a session
  max_refs_per_event: 3      # cap on neuron refs resolved per recorded event
```

A session is started and ended via the MCP tools `cerebrofy_session_start` / `cerebrofy_session_end`; every tool call in between is recorded automatically by the `SessionMiddleware` woven into the MCP dispatcher.

## MCP Tools

| Tool | Description |
|------|-------------|
| `cerebrofy_session_start` | Start recording an agent session (opt-in via `record_sessions`). Returns a `session_id`. |
| `cerebrofy_session_end` | End the active session: outcome, duration, neurons touched, events, and blast-radius before/after. |
| `cerebrofy_session_show` | Full replay of a session (latest when omitted): timeline, neurons touched, graph diff, blast-radius verdict. |

### `cerebrofy_session_start`

**Input schema:**

```json
{
  "task": "Add rate limiting to login endpoint",
  "agent": "claude-sonnet-4-6"
}
```

**Output:** `{"session_id": "sess_abc123", "task": "...", "agent": "...", "started_at": 1718..., "recording": true}`

Error codes: `[NO_INDEX]` when no `.cerebrofy` directory is found; `[RECORDING_DISABLED]` when `record_sessions` is false.

### `cerebrofy_session_end`

**Input schema:**

```json
{
  "session_id": "sess_abc123",
  "outcome": "success",
  "summary": "Added a token-bucket rate limiter and wired it into the login route."
}
```

**Output:** `{"session_id": "...", "duration_seconds": 120, "neurons_touched": 3, "events_recorded": 9, "outcome": "success", "blast_radius_before": 14, "blast_radius_after": 14}`

Error codes: `[SESSION_NOT_FOUND]` when the session id does not exist; `[NO_ACTIVE_SESSION]` when the session is already ended.

### `cerebrofy_session_show`

**Input schema:**

```json
{
  "session_id": "sess_abc123",
  "format": "markdown"
}
```

**Output (JSON):** the session record plus its events and graph diff — `session_id`, `task`, `agent`, `started_at`, `ended_at`, `outcome`, `outcome_notes`, `duration_seconds`, `neurons_touched[]`, `blast_radius_before`, `blast_radius_after`, `events[]` (`ts`, `tool`, `args`, `result_summary`), and a `diff` object (`present`, `missing`, `appeared`, `graph_refreshed`, `risk_verdict`).

## Data Flow

```
AI agent starts task
    │
    ▼
cerebrofy_session_start(task, agent)
    │  INSERT sessions row → sess_id
    ▼
MCP dispatcher wraps every tool call
    call_tool → SessionMiddleware.record
    │
    ▼
record_event(sessions.db)  ← args/result truncated < 1KB
    │
    ▼
resolve_neuron_refs() + depth-2 blast-radius lookup
    (captured once per neuron, capped at MAX_TRACKED_NEURONS=50)
    │
    ▼
cerebrofy_session_end(outcome, summary)
    │  ends session + blast_radius_after + outcome
    ▼
sessions.db: closed session
```

## Privacy

Recording is **local-only**. No session data, tool arguments, or result snippets are uploaded or sent to any server. Disable at any time by setting `record_sessions: false` and restarting the MCP server.

## Integration Points

- **Synthesizer** — closed sessions feed the Cross-Session Synthesizer (Idea #24) which detects failure patterns, lobe fragility, and agent blind spots
- **Narrative Engine** — session end can trigger narrative regeneration
- **Coordination** — `session_id` on claims traces back to the session that made them

## Related

- [Synthesizer](./synthesizer.md) — cross-session pattern detection from recorded sessions
- [Memory Model](../concepts/memory-model.md) — how session insights become persistent memories
- [Configuration](../getting-started/configuration.md) — `record_sessions` and `session` config fields