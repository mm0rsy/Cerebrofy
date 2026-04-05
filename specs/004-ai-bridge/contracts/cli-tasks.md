# CLI Contract: `cerebrofy tasks`

**Feature**: 004-ai-bridge
**Date**: 2026-04-04

---

## Synopsis

```
cerebrofy tasks [OPTIONS] DESCRIPTION
```

Runs hybrid search on the local index and outputs a numbered Markdown task list where each
item names the specific Neuron to modify, links to its lobe, and states the blast radius count.
Fully offline: zero LLM, zero network.

---

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `DESCRIPTION` | Yes | Plain-language feature description. Must be non-empty string. |

---

## Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--top-k N` | Integer | `config.yaml:top_k` (default 10) | Override KNN top-k; caps task list length |

---

## Pre-flight Checks (in order)

1. `DESCRIPTION` is non-empty → else exit 1: `"Description must not be empty."`
2. `cerebrofy.db` exists → else exit 1: `"No index found. Run 'cerebrofy build' first."`
3. Schema version matches current → else exit 1: `"Schema version mismatch. Run 'cerebrofy migrate' to upgrade."`

*Note*: No API key check — `cerebrofy tasks` is entirely offline.

---

## Execution Flow

```
1. Embed DESCRIPTION using the configured embedding model
2. Open cerebrofy.db (read-only: ?mode=ro)
3. KNN query on vec_neurons → top_k MatchedNeurons (ordered by similarity desc)
4. BFS depth=2 on edges from each MatchedNeuron (exclude RUNTIME_BOUNDARY)
5. Collect HybridSearchResult
6. If KNN returns 0 results → print "Cerebrofy: No relevant code units found for this description." → exit 0
7. Close DB connection
8. For each MatchedNeuron (ordered by descending similarity):
     - Lookup lobe name from affected_lobe_files (or "(unassigned)")
     - Count direct BFS neighbors of this Neuron (blast_count)
     - Format task item line
9. Collect RUNTIME_BOUNDARY warnings from HybridSearchResult
10. Write numbered task list + RUNTIME_BOUNDARY notes to stdout
11. Exit 0
```

---

## stdout Output Format

```markdown
# Cerebrofy Tasks: {description}

1. Modify validate_token in [[auth]] (auth/validator.py:42) — blast radius: 3 nodes
2. Modify create_session in [[auth]] (auth/session.py:18) — blast radius: 2 nodes
3. Modify UserLogin in [[api]] (api/handlers.py:77) — blast radius: 1 nodes

Note: validate_token has unresolvable cross-language calls — see RUNTIME_BOUNDARY entries in [[auth]].
```

**Per-item format**:
```
N. Modify {neuron_name} in [[{lobe_name}]] ({file}:{line_start}) — blast radius: {count} nodes
```

**RUNTIME_BOUNDARY note format** (after numbered list, separated by blank line):
```
Note: {src_name} has unresolvable cross-language calls — see RUNTIME_BOUNDARY entries in [[{lobe_name}]].
```

---

## Invariants

- Items ordered by descending `MatchedNeuron.similarity` (highest similarity = task #1)
- `--top-k N` caps the task list to N items (at most N KNN results)
- `lobe_name` is `"(unassigned)"` when the Neuron has no matching lobe
- Every Neuron name, file, and line in output MUST exist in the `nodes` table (zero hallucinations)
- `blast_count` per task item = direct BFS neighbors of that specific Neuron (not total blast radius count)
- RUNTIME_BOUNDARY notes appear AFTER the numbered list; they are NOT counted in any task's `blast_count`
- For the same DESCRIPTION and `top_k`: output is identical to `cerebrofy plan`'s Neuron set and blast radius set (FR-010 / SC-003)

---

## stdout / stderr Contract

| Stream | Content |
|--------|---------|
| stdout | Numbered Markdown task list + RUNTIME_BOUNDARY notes |
| stderr | Error messages only |

---

## Exit Codes

| Code | Condition |
|------|-----------|
| 0 | Success (task list written to stdout) OR zero KNN results |
| 1 | Missing index, schema mismatch, empty description |

---

## Config Keys Read

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `top_k` | No | 10 | Default KNN top-k; caps task list length |
| `embedding_model` | Yes | — | Model for query embedding |
