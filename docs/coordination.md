# Multi-Agent Coordination

A lightweight protocol for agents and humans working on the same codebase at the
same time: see who is active, claim the neurons you are about to edit, detect
claim collisions, and resolve contradicting memories before they mislead the next
agent.

Claims are **advisory**, not locks. Cerebrofy reports conflicts; it never blocks
an edit. The registry is local and lives beside the index, so every Cerebrofy
process on the machine sees the same claims.

## Quick start

```bash
# See who is working and what they claimed
cerebrofy who

# Claim a neuron before editing it
cerebrofy claim auth/tokens.py::validate_token \
    --intent "refactoring to add strict mode" \
    --agent-id claude-sess-001

# Check for claim and memory conflicts
cerebrofy conflicts

# Release when the edit is done
cerebrofy release auth/tokens.py::validate_token --agent-id claude-sess-001
```

## Concepts

| Term | Meaning |
|------|---------|
| **Agent** | A registered worker — an AI client (`claude`, `cursor`, `devin`), a `human`, or `ci`. Identified by `agent_id`. |
| **Claim** | An advisory hold on one or more neurons, with an intent and a TTL. |
| **Intent** | Short natural-language description of the planned work, shown to peers. Optional on the CLI; defaults to `claiming N neuron(s)`. |
| **Heartbeat** | Liveness timestamp refreshed by MCP activity. Stale agents lose their claims. |
| **Claim conflict** | Two active agents claim the same neuron. |
| **Memory conflict** | Two memories on the same neuron give contradicting guidance. |

Agents can claim neuron ids (`auth/tokens.py::validate_token`) or whole file paths
(`auth/tokens.py`, which expands to every neuron in that file). `claim` and
`release` both expand file-path tokens; tokens that are not in the index are
treated as literal ids.

## CLI reference

```bash
cerebrofy who [--format text|json]

cerebrofy claim NEURONS... [--intent TEXT] [--agent-id ID] [--agent-type TYPE]
                  [--ttl-minutes N] [--format text|json]

cerebrofy release [NEURONS...] [--agent-id ID] [--all] [--format text|json]

cerebrofy conflicts [--neuron ID] [--format text|json]

cerebrofy resolve MEMORY_A MEMORY_B --keep newest|author|human-review
                  [--format text|json]
cerebrofy resolve MEMORY_A MEMORY_B --merge --body TEXT [--author NAME]
                  [--format text|json]
```

Options:

| Option | Applies to | Description |
|--------|------------|-------------|
| `--agent-id ID` | `claim`, `release` | Acting agent id. Defaults to `CEREBROFY_AGENT_ID`, then `human-<username>`. |
| `--agent-type TYPE` | `claim` | `claude` (default), `cursor`, `devin`, `human`, `ci`. |
| `--intent TEXT` | `claim` | Optional. What you are about to do. Defaults to `claiming N neuron(s)`. |
| `--ttl-minutes N` | `claim` | Claim lifetime before auto-release. Range `1..1440`, default `60`. |
| `--neuron ID` | `conflicts`, `resolve` | Limit the scan to, or attribute the pair to, one neuron. |
| `--all` | `release` | Release every claim held by the agent (the default with no `NEURONS`). |
| `--keep STRATEGY` | `resolve` | `newest` (default), `author`, or `human-review`. |
| `--merge` / `--body TEXT` | `resolve` | Replace both memories with the text in `--body`. |
| `--author NAME` | `resolve` | Author used by the `--keep author` strategy and recorded on a merge. |
| `--format text\|json` | all | Human-readable table (default) or machine-readable JSON. |

### Behaviour

- `claim` claims every neuron it can. Neurons already held by another active agent
  are **skipped and reported** as conflicts. If none of the requested neurons could
  be claimed, the command prints the conflicts and exits `1` with
  `[NEURON_ALREADY_CLAIMED]`.
- `release` with no neuron arguments releases **all** claims held by the agent.
  File-path arguments are expanded exactly like `claim`.
- `who` shows active agents, their type, intent, claimed neurons, and active minutes.
- `conflicts` reports both claim collisions and contradicting memories.
- `resolve` applies one resolution strategy to a pair of memories and retires the
  losing memory.

All CLI errors use the form `Error: [CODE] message`.

### Machine-readable output

`--format json` emits stable payloads suitable for another agent or CI job:

```json
{
  "active_agents": [
    {
      "agent_id": "claude-sess-001",
      "agent_type": "claude",
      "intent": "Refactoring token rotation",
      "claimed_neurons": ["auth/tokens.py::validate_token"],
      "active_minutes": 12,
      "session_id": "sess_abc123"
    }
  ],
  "conflicts": [],
  "total_active": 1
}
```

## MCP tools

The same protocol is exposed to AI clients over MCP (stdio, or SSE once cloud sync
is available). There are five coordination tools in the 36-tool catalog.

| Tool | Required arguments | Optional arguments |
|------|--------------------|--------------------|
| `cerebrofy_claim` | `neurons` (array of strings), `intent`, `agent_id` | `agent_type` (default `claude`), `ttl_minutes` (1–1440, default `60`), `session_id` |
| `cerebrofy_release` | `agent_id` | `neurons` (omit to release all claims) |
| `cerebrofy_who` | — | — |
| `cerebrofy_conflicts` | — | `neuron` |
| `cerebrofy_resolve` | `memory_a`, `memory_b`, `strategy` | `author`, `merged_body`, `neuron` |

`search_code`, `get_neuron`, and `cerebrofy_remember` also accept an optional
`agent_id`. Naming the caller on those tools does two things:

1. **Self-claim exclusion** — conflict notices ignore claims held by the calling
   agent, so your own live claim is not reported back to you.
2. **Heartbeat** — any MCP call that carries an agent id refreshes that agent's
   `last_heartbeat`. When `agent_id` is omitted, the dispatcher falls back to
   `CEREBROFY_AGENT_ID` for the heartbeat; with neither set, the call simply runs
   without coordination activity.

Coordination reads (`cerebrofy_who`, `cerebrofy_conflicts`, and the heartbeat
lookup) open the registry **read-only** and never create `cerebrofy.db`. If no
index exists they report `NO_INDEX` and leave the filesystem untouched.

### Schemas

`cerebrofy_claim`

```json
{
  "neurons": ["auth/tokens.py::validate_token"],
  "intent": "Adding strict mode parameter",
  "agent_id": "claude-sess-001",
  "agent_type": "claude",
  "ttl_minutes": 60,
  "session_id": "sess_abc123"
}
```

`ttl_minutes` is clamped to `1..1440` by the handler. Response fields: `claimed`
(neuron ids claimed by this call), `conflicts` (skipped neurons with the existing
claimant, their intent, and how long they have been active), and `claim_id`.

`cerebrofy_release`

```json
{ "agent_id": "claude-sess-001", "neurons": ["auth/tokens.py::validate_token"] }
```

Omit `neurons` to release every claim for the agent. Returns `released`; when the
agent has no active registration it returns `NO_ACTIVE_AGENT`.

`cerebrofy_who`

```json
{}
```

Returns `active_agents` (agent id, type, intent, claimed neurons, active minutes,
session id), `conflicts` (neurons claimed by more than one agent), and
`total_active`.

`cerebrofy_conflicts`

```json
{ "neuron": "auth/tokens.py::validate_token" }
```

`neuron` is optional. Returns `overlapping_claims` (neurons claimed by more than one
agent), `memory_conflicts` (each carries `neuron`, `memory_a`, `memory_b`, `type`
— `keyword_opposition` for the keyword heuristic — and `resolution_options`), and
`resolution_options`.

`cerebrofy_resolve`

```json
{
  "memory_a": "mem_001",
  "memory_b": "mem_002",
  "strategy": "keep_newest",
  "neuron": "auth/tokens.py::validate_token"
}
```

`strategy` is one of `keep_newest`, `keep_by_author`, `human_review`, `merge`.
`author` is used by `keep_by_author`; `merged_body` is required by `merge`.

The resolver is **surface-neutral**: it reports `winner` / `loser` (or
`superseded` plus `merged_memory` for a merge) and never assumes `memory_a` is the
keeper. The same message text is used by the CLI and MCP paths.

### Agent invocation pattern

```
Use cerebrofy_who with arguments: {}
# Check what other agents are doing before starting work

Use cerebrofy_claim with arguments: {"neurons": ["auth/tokens.py::validate_token"], "intent": "Adding strict mode parameter", "agent_id": "claude-sess-001"}
# Claim neurons before editing them

Use search_code with arguments: {"query": "token expiry", "agent_id": "claude-sess-001"}
# Read calls carrying agent_id refresh the heartbeat and ignore your own claims

Use cerebrofy_release with arguments: {"agent_id": "claude-sess-001", "neurons": ["auth/tokens.py::validate_token"]}
# Release when finished
```

## `active_agents` schema

The registry is stored in the local index database (`.cerebrofy/db/cerebrofy.db`)
in the `active_agents` table.

| Column | Type | Notes |
|--------|------|-------|
| `agent_id` | TEXT | Primary key. Unique per agent instance. |
| `agent_type` | TEXT | `claude`, `cursor`, `devin`, `human`, `ci`. |
| `session_id` | TEXT | Nullable. Session id from the Idea #11 session recorder. **Not a foreign key yet** — the constraint is an Idea #11 TODO. |
| `intent` | TEXT | Natural-language description of the planned work. |
| `claimed_neurons` | TEXT | JSON array of claimed neuron ids. |
| `started_ts` | INTEGER | Unix timestamp when the agent registered. |
| `last_heartbeat` | INTEGER | Unix timestamp of the last heartbeat. |
| `status` | TEXT | `active` (default) or `completed`. |
| `ttl_minutes` | INTEGER | Claim lifetime, `1..1440`, default `60`. |
| `expires_ts` | INTEGER | Unix timestamp when the claim expires; refreshed by a heartbeat. |
| `created_ts` | INTEGER | Unix timestamp when the row was first created. |

Rows whose `status` is `completed` are not active and are filtered out of `who`,
`conflicts`, and conflict lookups.

## Heartbeat and TTL

- **Heartbeat interval: 5 minutes.** Any MCP tool call from the agent refreshes
  `last_heartbeat` and pushes `expires_ts` forward by the claim's TTL. The
  dispatcher reads `agent_id` from the arguments and falls back to
  `CEREBROFY_AGENT_ID`.
- **Stale threshold: 2× the interval (10 minutes) or the claim TTL, whichever
  comes first.** An agent that has not sent a heartbeat for two intervals, or
  whose `expires_ts` has passed, is considered dead; its claims are auto-released
  and the row is marked `completed`. This prevents zombie claims from crashed
  agents.
- **Claim TTL: 60 minutes by default** (`ttl_minutes` / `--ttl-minutes`, range
  `1..1440`). When the TTL elapses the claim expires and must be re-acquired with
  a fresh claim; work attempted against an expired claim reports `CLAIM_EXPIRED`.
- A live agent can extend its claim by re-claiming or by any MCP call that carries
  its `agent_id` before the TTL elapses.

## Resolution strategies

| Strategy | CLI | MCP | Use when |
|----------|-----|-----|----------|
| Keep newest | `--keep newest` | `keep_newest` | The newer guidance supersedes the older one. |
| Keep by author | `--keep author` | `keep_by_author` | One author is authoritative for this area. |
| Human review | `--keep human-review` | `human_review` | Neither memory can be trusted automatically; leave it flagged. |
| Merge | `--merge --body TEXT` | `merge` + `merged_body` | Both memories contain partial truth; write one combined statement. |

Contradictions are detected with a Phase 1 keyword heuristic — for example
"never X" versus "X is fine", "always Y" versus "Y is not required", or
"deprecated" versus "recommended". Detected pairs carry the type
`keyword_opposition`. Treat the result as a prompt to review, not a verdict.

## Error codes

| Code | Meaning | Recovery |
|------|---------|----------|
| `NEURON_ALREADY_CLAIMED` | The requested neurons are claimed by another active agent, so none could be claimed. | Run `cerebrofy who`, wait for the claimant to release or expire, or choose another neuron. |
| `CLAIM_EXPIRED` | The claim TTL elapsed before the work finished. | Re-claim with a fresh `ttl_minutes`. |
| `NO_ACTIVE_AGENT` | `release` was called for an agent id with no active registration. | Verify the id with `cerebrofy who`; omit `--agent-id` to use the local agent. |
| `NO_INDEX` | The local index / registry is missing. | Run `cerebrofy build` first; reads never create the database for you. |
| `CONFIG_ERROR` | Invalid `resolve` arguments (for example, a missing merge body, author, or unknown memory id). | Fix the arguments and retry. |

## Examples

### Two agents editing the same function

```bash
# Agent A
$ cerebrofy claim auth/tokens.py::validate_token \
    --intent "Adding strict mode parameter" --agent-id claude-a
Claimed 1 neuron(s).

# Agent B, later
$ cerebrofy claim auth/tokens.py::validate_token \
    --intent "Fixing clock-skew handling" --agent-id cursor-b
  • auth/tokens.py::validate_token — held by claude-a (Adding strict mode parameter)
1 neuron(s) skipped due to conflicts.
Claimed 0 neuron(s).
Error: [NEURON_ALREADY_CLAIMED] all requested neurons are already claimed by another active agent (cursor-b).
```

Agent B should wait for `claude-a` to release, pick a different neuron, or
coordinate with the claimant. The command exits `1` because no neuron could be
claimed.

### Resolving contradicting memories

```bash
$ cerebrofy conflicts --neuron auth/tokens.py::validate_token
auth/tokens.py::validate_token: mem_001 vs mem_002 (keyword_opposition)

$ cerebrofy resolve mem_001 mem_002 --keep newest
Kept mem_002; marked mem_001 stale.
```

## Integration notes

- **Idea #11 — Session Recorder.** `active_agents.session_id` records the session
  id supplied with a claim, so a claim can be traced back to the session that made
  it. It is **not** a foreign key; adding the constraint is an Idea #11 TODO.
- **Idea #21 — Insight Daemon.** When two agents claim overlapping neurons the
  daemon can emit a `memory_conflict` insight; overlapping claims also show up in
  `cerebrofy conflicts`.
- **Other MCP tools.** Conflict notices are additive: handlers that operate on a
  neuron can prepend a claim/memory warning without changing their normal payload.
- **Read-only, best-effort.** Coordination reads open the registry read-only,
  never create `cerebrofy.db`, and never block tool output; if the registry is
  unavailable the tool call proceeds without notices.
- **Rebuild caveat.** Coordination state lives in `cerebrofy.db`, and
  `cerebrofy build` rebuilds that database. Claims and registrations are therefore
  **ephemeral** and are lost on a full rebuild — re-claim after rebuilding.
