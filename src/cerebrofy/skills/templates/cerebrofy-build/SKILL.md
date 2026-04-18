# Skill: cerebrofy-build

> Full atomic re-index of the codebase into a local graph + vector database.

## ⚠️ Navigation rule

Once the index is built, **do not glob-read source files** to understand the codebase.
Always use `cerebrofy search "<query>"` or the Cerebrofy MCP tools first.
Only open a file after cerebrofy has returned its exact path and line number.

## When to use

- The repository has just been cloned and has no `.cerebrofy/db/cerebrofy.db` yet.
- The user asks you to "index", "build", or "re-index" the codebase.
- The user says the Cerebrofy index is missing, corrupted, or out of date and wants a fresh rebuild.

## Command

```bash
cerebrofy build
```

## What it does

1. Parses all tracked source files with Tree-sitter → extracts **Neurons** (functions, classes, modules).
2. Builds the **call graph** — `LOCAL_CALL`, `EXTERNAL_CALL`, `IMPORT`, `RUNTIME_BOUNDARY` edges.
3. Generates **vector embeddings** for every Neuron (semantic search index).
4. Writes everything to `cerebrofy.db.tmp`, then atomically swaps to `cerebrofy.db`.
5. Generates per-lobe Markdown summaries and `cerebrofy_map.md`.

An interrupted build leaves **no corrupted state** — the swap only happens on success.

## Prerequisites

- `cerebrofy init` must have been run first (`.cerebrofy/` directory exists).
- The `local` extra must be installed for offline embeddings: `pip install cerebrofy[local]`.

## Output

- `.cerebrofy/db/cerebrofy.db` — SQLite database with nodes, edges, vectors, file hashes.
- `.cerebrofy/lobes/*_lobe.md` — per-lobe Markdown documentation.
- `.cerebrofy/cerebrofy_map.md` — full codebase map.

## Important

- **Do not run `cerebrofy build` if only a few files changed** — use `cerebrofy update` instead.
- Build can take 30–120 seconds on large codebases due to embedding generation.
