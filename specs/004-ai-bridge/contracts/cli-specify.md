# CLI Contract: `cerebrofy specify`

**Feature**: 004-ai-bridge
**Date**: 2026-04-04

---

## Synopsis

```
cerebrofy specify [OPTIONS] DESCRIPTION
```

Runs hybrid search on the local index, constructs a codebase-grounded LLM prompt, streams
the LLM response to stdout, and writes the complete response to a timestamped Markdown file.

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

---

## Pre-flight Checks (in order, before hybrid search)

1. `DESCRIPTION` is non-empty → else exit 1: `"Description must not be empty."`
2. `cerebrofy.db` exists → else exit 1: `"No index found. Run 'cerebrofy build' first."`
3. Schema version matches current → else exit 1: `"Schema version mismatch. Run 'cerebrofy migrate' to upgrade."`
4. `embed_model` in meta matches `embedding_model` in config → else exit 1: `"Embedding model mismatch: index was built with {meta_model}, config says {config_model}. Run 'cerebrofy build' to rebuild."`
5. `llm_endpoint` present in config → else exit 1 naming missing key
6. `llm_model` present in config → else exit 1 naming missing key
7. LLM API key present in environment → else exit 1 naming missing variable
8. `system_prompt_template` path (if configured) exists on disk → else exit 1: `"Error: system_prompt_template file not found: {path}."`
9. `state_hash` mismatch → emit to stderr (non-blocking): `"Warning: Index may be out of sync. Run 'cerebrofy update' for current results."`

---

## Execution Flow

```
1. Embed DESCRIPTION using the configured embedding model
2. Open cerebrofy.db (read-only: ?mode=ro)
3. KNN query on vec_neurons → top_k MatchedNeurons (ordered by similarity desc)
4. BFS depth=2 on edges from each MatchedNeuron (exclude RUNTIME_BOUNDARY)
5. Collect HybridSearchResult
6. If KNN returns 0 results → print "Cerebrofy: No relevant code units found for this description." → exit 0 (no LLM call, no file write)
7. Close DB connection
8. Print hybrid search summary to stderr:
     "Cerebrofy: Hybrid search — {N} neurons matched, {M} lobes affected"
     "  · {name} ({file}) — score {similarity:.2f}"  (one line per matched neuron)
     "Cerebrofy: Affected lobes: {lobe1}, {lobe2}, ..."
     "Cerebrofy: Calling LLM ({model})..."
9. Build LLMContextPayload (load lobe .md files, substitute $lobe_context in template)
10. Call LLM via openai SDK (stream=True); wrap in wall-clock timeout (llm_timeout seconds)
11. Stream response tokens to stdout as they arrive
    If endpoint returns non-streaming response → emit to stderr:
      "Note: streaming not supported by endpoint, buffering response."
    then print full response to stdout
12. On LLM failure: retry once (5xx / network error only)
    Emit to stderr: "Cerebrofy: LLM request failed ({reason}), retrying..."
    On retry failure → exit 1, no file write
    On 429 → exit 1: "Error: LLM rate limit exceeded (HTTP 429). Wait and retry."
    On 4xx → exit 1 with error details
13. On timeout → exit 1: "Error: LLM request timed out after {N}s. Increase llm_timeout in config.yaml or retry."
14. Collect full LLM response in memory
15. Resolve output path: docs/cerebrofy/specs/YYYY-MM-DDTHH-MM-SS_spec.md
    If file exists at same timestamp → append _2, _3, ... suffix
    Create docs/cerebrofy/specs/ directory if absent
16. Write response to file
17. Print output file path as final stdout line (after LLM response)
18. Exit 0
```

---

## stdout / stderr Contract

| Stream | Content |
|--------|---------|
| stdout | LLM response tokens (streamed or buffered) + final line: absolute output file path |
| stderr | Hybrid search summary (steps 8), streaming fallback notice (step 11), retry notice (step 12), state_hash warning (step 9 pre-flight), error messages on exit 1 |

**Invariant**: stdout is always clean for piping. No progress messages, no decorative text, no search summary on stdout.

---

## Exit Codes

| Code | Condition |
|------|-----------|
| 0 | Success (spec written) OR zero KNN results |
| 1 | Any error: missing index, schema mismatch, model mismatch, missing config, missing API key, missing template file, empty description, LLM timeout, LLM error (after retry), permission error |

---

## Output File

- Location: `docs/cerebrofy/specs/<YYYY-MM-DDTHH-MM-SS>_spec.md`
- Collision: `<YYYY-MM-DDTHH-MM-SS>_2_spec.md`, `_3_spec.md`, ...
- Content: Raw LLM response (Markdown); no Cerebrofy metadata added to file
- Committed to git (not .gitignored)

---

## Environment Variables

| Variable | Derived from | Description |
|----------|--------------|-------------|
| `OPENAI_API_KEY` | `llm_endpoint: openai` | API key for OpenAI |
| *(provider-specific)* | `llm_endpoint` value | Variable name is inferred from the endpoint provider |

---

## Config Keys Read

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `llm_endpoint` | Yes | — | Base URL for OpenAI-compatible endpoint |
| `llm_model` | Yes | — | Model identifier |
| `llm_timeout` | No | 60 | Max seconds to wait for full LLM response |
| `system_prompt_template` | No | built-in | Path to custom system prompt template file |
| `top_k` | No | 10 | Default KNN top-k |
| `embedding_model` | Yes | — | Must match `embed_model` in DB meta |
