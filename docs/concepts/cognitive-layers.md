# Cognitive Layers

A **Lobe** is a named module group — typically one top-level directory in your repository. Cerebrofy auto-detects Lobes at `cerebrofy init` time. Each Lobe gets a Markdown summary at `docs/cerebrofy/<name>_lobe.md`.

Lobes are configured in `.cerebrofy/config.yaml`:

```yaml
lobes:
  auth: src/auth/
  api: src/api/
  db: src/db/
```

The lobe name surfaces in MCP tool output (`"lobe": "auth"`) and in lobe summary files used as AI context.

## What Lobes Are For

Lobes give Cerebrofy a structural understanding of your codebase's architecture:

- **Search scoping** — `search_code` accepts an optional `lobe` parameter to restrict results to one module
- **Blast-radius analysis** — lobe spread is a factor in risk scoring; cross-lobe calls are flagged
- **Architecture rules** — `.cerebrofy/arch-rules.yaml` can forbid edges between specific lobes
- **Governance** — ownership, CODEOWNERS, and reviewer suggestions are computed per lobe
- **Context windows** — lobe summaries are pre-written Markdown files that give AI assistants an orientation layer before diving into specifics

## Lobe Summaries

Each lobe gets a Markdown summary file written by `cerebrofy build` and `cerebrofy update`:

```
docs/cerebrofy/<name>_lobe.md
```

The summary contains a table of all neurons in the lobe, their signatures, docstrings, and line ranges. These files are committed to git (not gitignored) and serve as both a human-readable index and AI context.

A master map file aggregates all lobes:

```
docs/cerebrofy/cerebrofy_map.md
```

This file contains the `state_hash` used for cross-developer synchronization and a table listing every lobe with its neuron count and summary file path.

## Auto-Detection

At `cerebrofy init` time, Cerebrofy scans the repository for top-level directories containing source files matching `tracked_extensions`. Each directory becomes a lobe with a name derived from the directory name. You can override or extend the lobe map by editing `.cerebrofy/config.yaml`.

For flat repositories with no clear directory structure, use the `root` lobe:

```yaml
lobes:
  root: .
```

## Related

- [Architecture](./architecture.md) — module map and how lobes fit into the data flow
- [Configuration](../getting-started/configuration.md) — `lobes` field reference
- [Blast Radius](../features/blast-radius.md) — how lobe spread affects risk scoring
- [Governance](../features/governance.md) — per-lobe ownership and reviewer suggestions