# Memory Model

Cerebrofy lets you write and query structured memories attached to neurons and lobes. Memories persist across full rebuilds in a separate `memories.db` and decay over time using a configurable half-life (default 70 days). Stale memories are surfaced in the epistemic confidence score.

## What Memories Are For

Memories capture institutional knowledge that cannot be inferred from code alone:

- **Warnings** — gotchas, edge cases, production incidents
- **Decisions** — architectural choices and their rationale
- **Context** — background information about why code exists in its current form
- **Patterns** — synthesized patterns from the Cross-Session Synthesizer (Idea #24)
- **Agent actions** — actions taken by AI agents during sessions

## CLI Reference

```bash
# Write a memory
cerebrofy memory add "Clock skew breaks token expiry" \
    --type warning --neuron auth/tokens.py::validate_token --tags "security,jwt"

# Search memories semantically
cerebrofy memory search "JWT expiry edge cases" --lobe auth

# List memories for a lobe
cerebrofy memory list --lobe auth --type warning

# Link two memories causally
cerebrofy memory link <from-id> <to-id> --rel motivated

# Export all memories
cerebrofy memory export --format markdown > DECISIONS.md
```

## MCP Tools

| Tool | Description |
|------|-------------|
| `cerebrofy_remember` | Write a structured memory attached to a neuron or lobe |
| `cerebrofy_recall` | Semantic search across all memories |
| `cerebrofy_memories` | List memories for a specific neuron or lobe |
| `cerebrofy_link_memories` | Create a directed causal link between two memories |
| `cerebrofy_trace_history` | Trace the ancestry chain of a memory through its linked predecessors |

### `cerebrofy_remember`

**Input schema:**

```json
{
  "title": "Clock skew breaks token expiry",
  "body": "validate_token fails when system clock drift > 30s. Always use NTP-synced time.",
  "type": "warning",
  "neuron": "auth/tokens.py::validate_token",
  "tags": ["security", "jwt"],
  "author": "claude-sonnet-4-6",
  "agent_id": "claude-sess-001"
}
```

Valid types: `decision`, `warning`, `context`, `pattern`, `agent_action`.

`agent_id` is optional and refreshes the caller's coordination heartbeat (falling back to `CEREBROFY_AGENT_ID`); it also keeps the caller's own claims out of the conflict notices attached to the response.

**Output:** `{"id": "<uuid>", "neuron_id": "<resolved-id>\|null", "created_ts": 1234567890}`

If `neuron` cannot be resolved, the memory is stored without anchor and a `"warning"` field is added to the response.

### `cerebrofy_recall`

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

### `cerebrofy_memories`

**Input schema:**

```json
{
  "neuron": "auth/tokens.py::validate_token",
  "include_stale": false
}
```

At least one of `neuron` or `lobe` is required.

**Output:** `{"memories": [...], "count": N}`. Also included automatically in `get_neuron` responses as a `"memories"` array.

## Memory Persistence

- Memories live in `.cerebrofy/db/memories.db`, separate from `cerebrofy.db`
- `memories.db` survives `cerebrofy build` (which only recreates `cerebrofy.db`)
- Memories decay over time using a configurable half-life (default 70 days)
- Stale memories are surfaced in the epistemic confidence score
- Pattern memories from the synthesizer carry tags `synthesized,<type>,confidence=…,sessions=…,sample=…`

## Related

- [Synthesizer](../features/synthesizer.md) — how synthesized patterns become `type=pattern` memories
- [Epistemic](../reference/cli.md#cerebrofy-epistemic) — how stale memories affect confidence
- [Coordination](../features/coordination.md) — how memory conflicts are detected and resolved