# Skill: cerebrofy-update

> Partially re-index only changed files — fast incremental update.

## When to use

- After editing source files and before running `cerebrofy plan`, `tasks`, or `specify`.
- The git pre-push hook triggers this automatically, but you can run it manually.
- The user says the index is "stale" or "out of date" for a few files.

## Command

```bash
# Auto-detect changes via git diff
cerebrofy update

# Explicit file list
cerebrofy update src/auth/login.py src/api/handler.py
```

## What it does

1. Detects changed files via `git diff` (falls back to file-hash comparison).
2. Re-parses only the changed files → updated Neurons.
3. Runs **depth-2 BFS** from changed nodes to find all affected neighbors.
4. Re-indexes the affected subgraph (nodes, edges, embeddings) in a single atomic transaction.

Target latency: **< 2 seconds** for a single-file change.

## When NOT to use

- If the index does not exist yet → use `cerebrofy build` first.
- If the schema version has changed after a Cerebrofy upgrade → run `cerebrofy migrate` then `cerebrofy build`.

## Output

Updates `.cerebrofy/db/cerebrofy.db` in place (atomic transaction — full rollback on failure).
