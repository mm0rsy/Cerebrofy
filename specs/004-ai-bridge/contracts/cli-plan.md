# CLI Contract: `cerebrofy plan`

**Feature**: 004-ai-bridge
**Date**: 2026-04-04

---

## Synopsis

```
cerebrofy plan [OPTIONS] DESCRIPTION
```

Runs hybrid search on the local index and outputs a structured impact report — Matched Neurons,
Blast Radius, Affected Lobes, Re-index Scope — to stdout. Fully offline: zero LLM, zero network.

---

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `DESCRIPTION` | Yes | Plain-language feature description. Must be non-empty string. |

---

## Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--top-k N` | Integer | `config.yaml:top_k` (default 10) | Override KNN top-k for this invocation |
| `--json` | Flag | false | Output machine-readable JSON instead of Markdown |

---

## Pre-flight Checks (in order)

1. `DESCRIPTION` is non-empty → else exit 1: `"Description must not be empty."`
2. `cerebrofy.db` exists → else exit 1: `"No index found. Run 'cerebrofy build' first."`
3. Schema version matches current → else exit 1: `"Schema version mismatch. Run 'cerebrofy migrate' to upgrade."`

*Note*: No API key check, no LLM config check — `cerebrofy plan` is entirely offline.

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
8. Render output:
   - Default (Markdown): write structured report to stdout
   - --json: write JSON object to stdout
9. Exit 0
```

---

## Markdown Output Format (default)

```markdown
# Cerebrofy Plan: {description}

## Matched Neurons

| # | Name | File | Line | Similarity |
|---|------|------|------|------------|
| 1 | validate_token | auth/validator.py | 42 | 0.91 |
| 2 | create_session | auth/session.py | 18 | 0.87 |

## Blast Radius (depth-2 neighbors)

| Name | File | Line |
|------|------|------|
| hash_password | auth/utils.py | 31 |

## RUNTIME_BOUNDARY Warnings

- {src_name} ({src_file}) → unresolvable cross-language call

## Affected Lobes

| Lobe | File |
|------|------|
| auth | docs/cerebrofy/lobes/auth_lobe.md |
| api  | docs/cerebrofy/lobes/api_lobe.md |

## Re-index Scope

Estimated **{N} nodes** would need re-indexing for changes in this area.
```

*If no RUNTIME_BOUNDARY warnings: omit that section entirely.*

---

## JSON Output Format (`--json`)

```json
{
  "schema_version": 1,
  "matched_neurons": [
    {
      "id": "auth/validator.py::validate_token",
      "name": "validate_token",
      "file": "auth/validator.py",
      "line_start": 42,
      "similarity": 0.91
    }
  ],
  "blast_radius": [
    {
      "id": "auth/utils.py::hash_password",
      "name": "hash_password",
      "file": "auth/utils.py",
      "line_start": 31
    }
  ],
  "affected_lobes": ["auth", "api"],
  "reindex_scope": 3
}
```

**Invariants**:
- All four top-level array fields always present (empty `[]` if no results)
- `schema_version: 1` always present as the first top-level field; AI tools SHOULD check it before parsing (FR-023)
- `similarity` rounded to 2 decimal places
- No decorative text on stdout when `--json` is active; warnings go to stderr only
- `cerebrofy plan` MUST silently ignore `llm_endpoint`, `llm_model`, `llm_timeout`, and `system_prompt_template` config keys — their presence MUST NOT trigger any network call (FR-027)

---

## stdout / stderr Contract

| Mode | stdout | stderr |
|------|--------|--------|
| Default | Markdown report | Error messages only |
| `--json` | JSON object (no decorative text) | Warnings + error messages |

---

## Exit Codes

| Code | Condition |
|------|-----------|
| 0 | Success (report written to stdout) OR zero KNN results |
| 1 | Missing index, schema mismatch, empty description |

---

## Config Keys Read

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `top_k` | No | 10 | Default KNN top-k |
| `embedding_model` | Yes | — | Model for query embedding |
