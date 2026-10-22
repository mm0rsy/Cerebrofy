---
name: cerebrofy-coordination
description: Coordinate multiple AI agents working on the same codebase — see who is active, claim neurons before editing, detect claim collisions, and resolve contradicting memories. Use when multiple agents work concurrently, before editing shared code, or when two memories disagree.
trigger: /cerebrofy:coordination
---

# cerebrofy-coordination

> Multi-agent coordination: see who is active, claim neurons before editing, and resolve contradicting memories — so two agents never silently undo each other's work.

## ⚠️ Navigation Rule

Always check the coordination registry **before** editing shared code:

```
Use cerebrofy_who with arguments: {}
```

If another active agent has claimed the neuron, do not edit it. Claim the neuron
first, or pick a different task. Only open source files that Cerebrofy points at.

## Use When

- Two or more AI agents (or humans) are working in the same repository at once
- You are about to edit a function or file that another agent may also touch
- `cerebrofy_who` shows a claim overlapping your intended change
- `cerebrofy conflicts` reports contradicting memories on the same neuron
- A previous agent wrote guidance that conflicts with what you are about to write

## Supported Clients

- Claude Code (`.claude/commands/cerebrofy/`)
- GitHub Copilot Chat and VS Code (`.github/prompts/`, `/cerebrofy-coordination`)
- OpenCode (`.opencode/commands/cerebrofy/`)

The same workflow is available without slash commands through the MCP tools below.

## Workflow

1. **Who** — before starting work, check who is active and what they claimed.
2. **Claim** — claim the neurons you are about to edit, with a short intent.
3. **Conflicts** — if the claim reports collisions, skip those neurons or coordinate
   with the claimant; check memory conflicts on the same neuron.
4. **Work** — make the change while your claim is live. Any MCP call that carries
   your `agent_id` refreshes the heartbeat; claims expire after their TTL or after
   two missed heartbeat intervals.
5. **Release** — release the claims when the edit is done or abandoned.
6. **Resolve** — if two memories contradict each other, resolve them with an
   explicit strategy instead of leaving both in the index.

## Slash Command

The installer ships one prompt file, so there is a single slash command. Pass a
subcommand and its arguments after it; without arguments it runs the full protocol.

| Command | What it does |
|---------|--------------|
| `/cerebrofy:coordination [subcommand] [args...]` | Run the coordination protocol, or one subcommand. |

GitHub Copilot and VS Code expose the same prompt as `/cerebrofy-coordination`.

Usage examples:

```
/cerebrofy:coordination
/cerebrofy:coordination who
/cerebrofy:coordination claim auth/tokens.py::validate_token "refactoring to add strict mode"
/cerebrofy:coordination conflicts
/cerebrofy:coordination release auth/tokens.py::validate_token
/cerebrofy:coordination resolve mem_001 mem_002 --keep newest
```

## CLI

```bash
cerebrofy who
cerebrofy claim auth/tokens.py::validate_token \
    --intent "refactoring to add strict mode" \
    --agent-id claude-sess-001 --agent-type claude --ttl-minutes 60
cerebrofy conflicts
cerebrofy conflicts --neuron auth/tokens.py::validate_token
cerebrofy release auth/tokens.py::validate_token --agent-id claude-sess-001
cerebrofy release --agent-id claude-sess-001          # all claims for that agent
cerebrofy resolve mem_001 mem_002 --keep newest
cerebrofy resolve mem_001 mem_002 --merge --body "Use datetime.now(timezone.utc)."
```

Every command accepts `--format text|json`.

`--intent` is optional on `claim`; when omitted it defaults to
`claiming N neuron(s)`. `--ttl-minutes` accepts `1..1440` (default `60`). `claim`
and `release` both expand file paths like `auth/tokens.py` into every indexed
neuron in that file.

`claim` claims every neuron it can. Neurons already held by another active agent are
skipped and reported as conflicts; when nothing could be claimed the command prints
the conflicts and exits `1` with
`Error: [NEURON_ALREADY_CLAIMED] ...`.

## MCP Tools

### `cerebrofy_claim`

Required: `neurons`, `intent`, `agent_id`. Optional: `agent_type` (default
`claude`), `ttl_minutes` (`1..1440`, default `60`), `session_id`.

```
Use cerebrofy_claim with arguments: {"neurons": ["auth/tokens.py::validate_token"], "intent": "Adding strict mode parameter", "agent_id": "claude-sess-001"}

Use cerebrofy_claim with arguments: {"neurons": ["auth/tokens.py", "auth/refresh.py"], "intent": "Refactoring token rotation", "agent_id": "cursor-sess-042", "agent_type": "cursor", "ttl_minutes": 30, "session_id": "sess_abc123"}
```

### `cerebrofy_release`

Required: `agent_id`. Optional: `neurons` (omit to release all of that agent's claims).

```
Use cerebrofy_release with arguments: {"agent_id": "claude-sess-001", "neurons": ["auth/tokens.py::validate_token"]}

Use cerebrofy_release with arguments: {"agent_id": "claude-sess-001"}
```

### `cerebrofy_who`

No required arguments.

```
Use cerebrofy_who with arguments: {}
```

### `cerebrofy_conflicts`

Optional: `neuron`.

```
Use cerebrofy_conflicts with arguments: {}

Use cerebrofy_conflicts with arguments: {"neuron": "auth/tokens.py::validate_token"}
```

### `cerebrofy_resolve`

Required: `memory_a`, `memory_b`, `strategy`. Optional: `author`, `merged_body`, `neuron`.

```
Use cerebrofy_resolve with arguments: {"memory_a": "mem_001", "memory_b": "mem_002", "strategy": "keep_newest"}

Use cerebrofy_resolve with arguments: {"memory_a": "mem_001", "memory_b": "mem_002", "strategy": "merge", "merged_body": "Use datetime.now(timezone.utc) — clock skew is fixed.", "neuron": "auth/tokens.py::validate_token"}
```

## Resolution Strategies

| Strategy | MCP `strategy` | CLI flag | Behaviour |
|----------|----------------|----------|-----------|
| Keep newest | `keep_newest` | `--keep newest` | Keep the most recently written memory, retire the other. |
| Keep by author | `keep_by_author` | `--keep author` | Keep the memory from the trusted/expected author. |
| Human review | `human_review` | `--keep human-review` | Leave the conflict flagged for a human decision. |
| Merge | `merge` | `--merge --body TEXT` | Replace both with a single merged memory (`merged_body` / `--body`). |

## Error Codes

| Code | Meaning | Recovery |
|------|---------|----------|
| `NEURON_ALREADY_CLAIMED` | Every requested neuron is held by another active agent, so none could be claimed. | Read `cerebrofy who`, wait for release, or pick another neuron. |
| `CLAIM_EXPIRED` | The claim TTL elapsed before the work finished. | Re-claim the neuron with a fresh TTL. |
| `NO_ACTIVE_AGENT` | `release` was called for an agent id with no active registration. | Check the id with `cerebrofy who`; omit `--agent-id` to use the local agent. |
| `NO_INDEX` | The local index / registry is missing. | Run `cerebrofy build`; coordination reads never create the database. |

CLI errors are printed as `Error: [CODE] message`.

## Notes

- Claims are **advisory**, not locks — Cerebrofy reports conflicts, it does not block edits.
- Coordination reads (`who`, `conflicts`, and heartbeat lookups) are **read-only
  and best-effort**: they never create `cerebrofy.db` and never block tool output.
- Any MCP call that carries an `agent_id` refreshes the heartbeat; `search_code`,
  `get_neuron`, and `cerebrofy_remember` accept it as an optional argument, and the
  dispatcher falls back to `CEREBROFY_AGENT_ID`. A named agent's own claims are
  excluded from its conflict notices.
- The heartbeat interval is 5 minutes; an agent silent for 2× that interval
  (10 minutes), or past its claim TTL, is considered stale and its claims are
  auto-released.
- Claim TTL defaults to 60 minutes and accepts `1..1440` (`ttl_minutes` / `--ttl-minutes`).
- Coordination state lives in `.cerebrofy/db/cerebrofy.db`, so `cerebrofy build`
  rebuilds the index and discards claims. Re-claim after a full rebuild.
- Always release claims when finished so peers can proceed.
