# Sessions

Record, replay, and audit AI agent sessions — closing the "what did the agent actually do?" gap. Recording is **opt-in** (`record_sessions: true` in `.cerebrofy/config.yaml`) and **local-only**: every MCP tool call is stored in `.cerebrofy/db/sessions.db`, which is separate from the index database so it survives rebuilds.

## What Session Recording Captures

Every MCP tool call made while a session is open is recorded:

- Tool name and arguments
- Truncated result summary (< 1 KB per event)
- Depth-2 blast-radius "before" and "after" counts for each neuron the agent touched
- Session outcome, duration, and neuron touch count

## CLI Reference

```bash
cerebrofy session list                                   # list recorded sessions
cerebrofy session show sess_abc123                       # full replay (latest when omitted)
cerebrofy session diff sess_abc123                       # graph changes the session made
cerebrofy session search "rate limiting"                 # semantic search across session tasks
cerebrofy session export sess_abc123 --format html       # shareable self-contained HTML report
cerebrofy session export --format html --output report.html
```

A session is started and ended via the MCP tools `cerebrofy_session_start` / `cerebrofy_session_end`; every tool call in between is recorded automatically by the `SessionMiddleware` woven into the MCP dispatcher. `cerebrofy session diff` answers "what did this session do to the graph?" — which neurons it touched, which disappeared, and whether the blast radius (Idea #01) grew, shrank, or stayed flat.

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

Then start a session via MCP:

```json
{
  "tool": "cerebrofy_session_start",
  "arguments": {
    "task": "Add rate limiting to login endpoint",
    "agent": "claude-sonnet-4-6"
  }
}
```

And end it:

```json
{
  "tool": "cerebrofy_session_end",
  "arguments": {
    "session_id": "sess_abc123",
    "outcome": "success",
    "summary": "Added a token-bucket rate limiter and wired it into the login route."
  }
}
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `cerebrofy_session_start` | Start recording an agent session (opt-in via `record_sessions`). Returns a `session_id`. |
| `cerebrofy_session_end` | End the active session: outcome, duration, neurons touched, events, and blast-radius before/after. |
| `cerebrofy_session_show` | Full replay of a session (latest when omitted): timeline, neurons touched, graph diff, blast-radius verdict. |

## Privacy

Recording is **local-only**. No session data, tool arguments, or result snippets are uploaded or sent to any server. Disable at any time by setting `record_sessions: false` and restarting the MCP server.

## Related

- [Memory Model](./memory-model.md) — how memories from sessions persist
- [Synthesizer](../features/synthesizer.md) — how closed sessions feed pattern detection
- [Configuration](../getting-started/configuration.md) — `record_sessions` and `session` config fields