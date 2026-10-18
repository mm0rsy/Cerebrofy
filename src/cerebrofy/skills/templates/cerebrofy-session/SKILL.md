````markdown
# Skill: cerebrofy-session

> Live agent session recorder: every MCP tool call recorded as a replayable, auditable session.

## ⚠️ Default navigation rule — READ THIS FIRST

**Do NOT open or glob-read source files to understand the codebase.**

This repo has a pre-built Cerebrofy index. Always query it first via the MCP tools.
Only open a specific source file *after* cerebrofy has returned its exact file path and line number.

## When to use this skill

Invoke `/cerebrofy:session` when you need to:
- Start recording an AI coding session so it can be audited later
- Replay what an agent actually did — tool calls, neurons touched, graph changes
- Audit AI-assisted changes before a review or a merge
- Show the blast-radius impact of an agent session (did it grow the blast radius?)

Recording is **opt-in** and **local-only** — enable it with `record_sessions: true`
in `.cerebrofy/config.yaml`. Nothing is uploaded.

## How to run

```bash
cerebrofy session list                       # list recorded sessions
cerebrofy session show sess_abc123           # full replay (latest when omitted)
cerebrofy session diff sess_abc123           # graph changes the session made
cerebrofy session search "rate limiting"     # semantic search across session tasks
cerebrofy session export sess_abc123 --format html   # shareable HTML report
cerebrofy session export --format html --output report.html
```

Or via MCP tools:

```
cerebrofy_session_start(task="Add rate limiting to login endpoint", agent="claude-sonnet-4-6")
# ... do the work with the other cerebrofy tools ...
cerebrofy_session_end(session_id="sess_abc123", outcome="success", summary="Added token bucket")
cerebrofy_session_show(session_id="sess_abc123", format="json")
```

## Session boundary protocol

1. **Before starting any coding task**, call `cerebrofy_session_start` with a clear task description.
2. Work normally — every MCP tool call (`search_code`, `cerebrofy_impact`, `cerebrofy_update`, …)
   is recorded automatically while the session is open.
3. **After completing**, call `cerebrofy_session_end` with `outcome` (`success` | `partial` | `failed`)
   and a short `summary`.

## How to interpret a replay

| Field | Meaning |
|-------|---------|
| **Timeline** | Ordered tool calls with args and truncated result summaries |
| **Neurons touched** | Neurons referenced during the session (resolved from tool args) |
| **Graph diff** | Touched neurons still present, neurons that disappeared, neurons that appeared after an index refresh |
| **Blast radius before/after** | Depth-2 caller count of the touched set at first reference vs session end (Idea #01) |
| **Verdict** | `increased` / `unchanged` / `decreased` — did the session grow the blast radius? |

## Error codes

| Code | Meaning | Recovery |
|------|---------|----------|
| `SESSION_NOT_FOUND` | No session with that ID | `cerebrofy session list` |
| `NO_ACTIVE_SESSION` | `session_end` called for an already-ended session | Start a new session |
| `RECORDING_DISABLED` | `record_sessions` is false | Enable it and restart the MCP server |
````
