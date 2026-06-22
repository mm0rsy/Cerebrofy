````markdown
# Skill: cerebrofy-remember

> Write structured memories into Cerebrofy and traverse the causal memory graph.

## ⚠️ Default navigation rule — READ THIS FIRST

**Do NOT open or glob-read source files to understand the codebase.**

This repo has a pre-built Cerebrofy index. Always query it first via the MCP tools.
Only open a specific source file *after* cerebrofy has returned its exact file path and line number.

## When to write a memory

After **any** of these events:
- An architectural decision (use `decision`)
- A discovered footgun or edge case (use `warning`)
- Context that explains intent (use `context`)
- A repeated pattern worth naming (use `pattern`)
- An AI action you've completed (use `agent_action`)
- A synthesized insight across multiple sessions (use `insight`)

## How to write a memory

```
cerebrofy_remember(
    title="Clock skew breaks token expiry if drift > 30s",
    body="Validated JWTs can appear expired on nodes with >30s clock drift. Always add 60s leeway in strict=False mode.",
    type="warning",
    neuron="auth/tokens.py::validate_token",
    tags=["security", "jwt", "clock-skew"]
)
```

## How to recall memories

```
cerebrofy_recall(query="JWT expiry edge cases")
cerebrofy_recall(query="auth warnings", lobe="auth", type="warning")
```

## How to list memories for a neuron

```
cerebrofy_memories(neuron="auth/tokens.py::validate_token")
cerebrofy_memories(lobe="auth", type="decision")
```

## How to link memories causally (Phase 2)

```
cerebrofy_link_memories(
    from_memory="<id-of-incident>",
    to_memory="<id-of-fix-decision>",
    rel_type="motivated"
)
```

## How to trace decision history

```
cerebrofy_trace_history(memory="<memory-id>", depth=5)
```

## Quick reference

| Goal | MCP call |
|------|---------|
| Write a memory | `cerebrofy_remember(title, body, type, neuron?, lobe?, tags?)` |
| Search memories | `cerebrofy_recall(query, type?, lobe?, limit?)` |
| List for neuron/lobe | `cerebrofy_memories(neuron?, lobe?, type?)` |
| Link two memories | `cerebrofy_link_memories(from_memory, to_memory, rel_type)` |
| Trace causal chain | `cerebrofy_trace_history(memory, depth?)` |

## Memory types

| Type | Use for |
|------|---------|
| `decision` | Architectural or design decisions |
| `warning` | Known gotchas, footguns, edge cases |
| `context` | Background that explains intent |
| `pattern` | Recurring patterns worth naming |
| `agent_action` | What an AI agent did and why |
| `insight` | Synthesized observations across sessions |

## Causal edge types

| rel_type | Meaning |
|----------|---------|
| `caused` | A led directly to B |
| `motivated` | A provided the reason for B |
| `resolved` | B fixed the problem described in A |
| `contradicts` | A and B represent conflicting guidance |
| `updated_by` | B supersedes or revises A |
````
