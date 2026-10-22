---
agent: agent
description: Coordinate concurrent AI agents — see who is active, claim neurons, check conflicts, and resolve contradicting memories
---

Coordinate concurrent AI agents on this codebase before touching shared code.

Arguments (optional):

$ARGUMENTS

If the arguments name a subcommand (`who`, `claim`, `conflicts`, `release`, or
`resolve`), perform that step with the supplied arguments. Otherwise run the full
protocol below.

## Protocol

1. **Check peers first.** Call `cerebrofy_who`:
   ```
   Use cerebrofy_who with arguments: {}
   ```
   Summarise active agents, their intents, and claimed neurons. If a neuron you
   intend to edit is claimed by another agent, do not edit it.

2. **Claim before editing.** Call `cerebrofy_claim` with every neuron or file you
   will touch, a concrete intent, and a stable agent id:
   ```
   Use cerebrofy_claim with arguments: {"neurons": ["auth/tokens.py::validate_token"], "intent": "Adding strict mode parameter", "agent_id": "claude-sess-001"}
   ```
   Optional arguments: `agent_type` (default `claude`), `ttl_minutes` (1–1440,
   default `60`), `session_id`:
   ```
   Use cerebrofy_claim with arguments: {"neurons": ["auth/tokens.py"], "intent": "Refactoring token rotation", "agent_id": "cursor-sess-042", "agent_type": "cursor", "ttl_minutes": 30, "session_id": "sess_abc123"}
   ```
   Already-claimed neurons are skipped and returned as conflicts. If nothing could
   be claimed, the tool returns `NEURON_ALREADY_CLAIMED` — stop and coordinate.

3. **Check conflicts.** Call `cerebrofy_conflicts`, optionally scoped to one neuron:
   ```
   Use cerebrofy_conflicts with arguments: {"neuron": "auth/tokens.py::validate_token"}
   ```
   For memory conflicts, pick a strategy: `keep_newest`, `keep_by_author`,
   `human_review`, or `merge`. Detected contradictions carry
   `type: "keyword_opposition"`.

4. **Resolve memory conflicts.**
   ```
   Use cerebrofy_resolve with arguments: {"memory_a": "mem_001", "memory_b": "mem_002", "strategy": "keep_newest"}
   Use cerebrofy_resolve with arguments: {"memory_a": "mem_001", "memory_b": "mem_002", "strategy": "merge", "merged_body": "<merged text>", "neuron": "auth/tokens.py::validate_token"}
   ```
   `memory_a`, `memory_b`, and `strategy` are required; `author`, `merged_body`,
   and `neuron` are optional. `human_review` mutates nothing.

5. **Release when done.**
   ```
   Use cerebrofy_release with arguments: {"agent_id": "claude-sess-001", "neurons": ["auth/tokens.py::validate_token"]}
   Use cerebrofy_release with arguments: {"agent_id": "claude-sess-001"}
   ```
   Omit `neurons` to release all of that agent's claims.

## Error handling

- `NEURON_ALREADY_CLAIMED` — another agent holds the neurons; report the claimant
  and intent from `cerebrofy_who`, then wait or choose different work.
- `CLAIM_EXPIRED` — the TTL elapsed; re-claim with a fresh `ttl_minutes`.
- `NO_ACTIVE_AGENT` — the release agent id is not registered; verify it with
  `cerebrofy_who`.
- `NO_INDEX` — run `cerebrofy build` first; coordination reads never create the
  database.

CLI errors print as `Error: [CODE] message`; in the CLI `claim --intent` is
optional (default `claiming N neuron(s)`) and `--ttl-minutes` must be within
`1..1440`.

Claims are advisory. Any MCP call carrying `agent_id` refreshes the heartbeat
(falling back to `CEREBROFY_AGENT_ID`); an agent is stale after two 5-minute
heartbeat intervals (10 minutes) or when its TTL elapses, and stale claims are
auto-released. Coordination reads are read-only and best-effort — they never
create `cerebrofy.db` and never block tool output. All claims are lost when
`cerebrofy build` rebuilds the index.
