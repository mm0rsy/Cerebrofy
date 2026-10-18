Replay and audit AI agent sessions recorded by Cerebrofy — what the agent did, in what order,
and what it changed in the graph.

Use the `cerebrofy_session_show` MCP tool to fetch the replay (omit `session_id` for the latest).
Then:

1. Summarise the session: task, agent, duration, outcome, events recorded
2. List the neurons touched and whether the graph changed during the session
3. Report the blast-radius verdict (increased / unchanged / decreased)
4. If the session outcome is missing, suggest calling `cerebrofy_session_end` with an outcome

If the user asks "what did the AI do?" or "audit the last agent session", call
`cerebrofy_session_show` with `format: "json"` and summarise the timeline.

To start recording a new session, call `cerebrofy_session_start` with the task description
**before** starting work, and `cerebrofy_session_end` when finished. Recording is opt-in —
if it is disabled, tell the user to set `record_sessions: true` in `.cerebrofy/config.yaml`.
