# Skill: cerebrofy-resources

> Discover and consume Cerebrofy's URI-addressable MCP resources — ambient codebase context without explicit tool calls.

## ⚠️ Default navigation rule — READ THIS FIRST

**Do NOT open or glob-read source files to understand the codebase.**

This repo has a pre-built Cerebrofy index. Always query it via MCP tools and resources first.
Only open a specific source file *after* cerebrofy has returned its exact file path and line number.

## When to use

- At session start, to load codebase orientation (map, entry points, health) as ambient context
- To discover which resource URIs are available before reading them
- When configuring a client that supports auto-included resources (e.g. Claude Desktop) — point it at `cerebrofy://graph/map`, `cerebrofy://graph/entry-points`, and `cerebrofy://health/current`
- To subscribe to live updates — after `cerebrofy update` (pre-commit hook) or `cerebrofy build` modifies the index, the server emits `notifications/resources/updated` for subscribed URIs, so you never work with stale graph data

## Static resources

| URI | Type | Content |
|-----|------|---------|
| `cerebrofy://graph/map` | Markdown | Full codebase map — all lobes, neurons, and edges |
| `cerebrofy://graph/entry-points` | JSON | Entry-point neurons (no non-runtime callers, with outgoing edges) |
| `cerebrofy://health/current` | JSON | Latest codebase health snapshot |
| `cerebrofy://lobes/{name}` | Markdown | Per-lobe summary (one resource per indexed lobe) |

## URI templates

| Template | Type | Content |
|----------|------|---------|
| `cerebrofy://neurons/{neuron_id}` | JSON | Single neuron details — source, signature, direct callers (`file::name` format) |
| `cerebrofy://neurons/file/{file_path}` | JSON | All neurons defined in a source file |
| `cerebrofy://neurons/search?q={query}` | JSON | Hybrid semantic search results |
| `cerebrofy://memories/{neuron_id}` | JSON | Memories attached to a neuron |
| `cerebrofy://blast-radius/{neuron_id}` | JSON | Callers, risk score, PR-comment summary |

## How to use via MCP

Discover what is available (convenience tool):

```
cerebrofy_list_resources(filter="all")
cerebrofy_list_resources(filter="lobes")     # graph | health | neurons | memories | blast-radius
```

Read a resource directly via the MCP `resources/read` protocol method — resource reads are not tool calls:

```
resources/read  cerebrofy://graph/map
resources/read  cerebrofy://lobes/auth
resources/read  cerebrofy://neurons/auth/tokens.py::validate_token
resources/read  cerebrofy://neurons/search?q=token+expiry
resources/read  cerebrofy://blast-radius/validate_token
```

Subscribe to change notifications:

```
resources/subscribe  cerebrofy://graph/map
# → notifications/resources/updated fires whenever cerebrofy build/update changes the index
resources/unsubscribe  cerebrofy://graph/map
```

## How to use via CLI

Resources are MCP-only, but the same human-readable files are generated on disk by `cerebrofy build` / `cerebrofy update`:

- `docs/cerebrofy/cerebrofy_map.md` — the codebase map
- `docs/cerebrofy/<name>_lobe.md` — per-lobe summaries

## Quick reference

| Goal | Action |
|------|--------|
| Discover all resource URIs | `cerebrofy_list_resources()` |
| Orient a fresh session | read `cerebrofy://graph/map` + `cerebrofy://graph/entry-points` |
| Check index freshness | read `cerebrofy://health/current` |
| Jump from a search hit to full details | `cerebrofy://neurons/{id}` using the `id` from search results |
| Check risk before touching a function | `cerebrofy://blast-radius/{file::name}` |
| Get past decisions for a function | `cerebrofy://memories/{file::name}` |
| Avoid stale context | subscribe to the URIs you depend on |
