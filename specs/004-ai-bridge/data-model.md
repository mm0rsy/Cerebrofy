# Data Model: Phase 4 — AI Bridge

**Feature**: 004-ai-bridge
**Date**: 2026-04-04

---

## Overview

Phase 4 does not create new persistent tables. All commands are strictly read-only with respect
to `cerebrofy.db`. The only permitted write is the spec output file in `docs/cerebrofy/specs/`
(by `cerebrofy specify`). This document defines the in-memory data structures produced and
consumed by the three Phase 4 commands.

---

## Existing Schema (Phase 2 — consumed read-only)

```sql
-- All Phase 4 queries are read-only (open_db() called with ?mode=ro URI)
nodes        (id, name, file, type, line_start, line_end, signature, docstring, hash)
edges        (src_id, dst_id, rel_type, file)
meta         (key, value)   -- schema_version, state_hash, embed_model, embed_dim, last_build
vec_neurons  (id, embedding) -- sqlite-vec KNN virtual table
```

---

## In-Memory Data Structures

### MatchedNeuron

A single KNN result from the `vec_neurons` cosine similarity query. Produced by
`search/hybrid.py` as part of the KNN phase.

```python
@dataclass(frozen=True)
class MatchedNeuron:
    id: str           # "{file}::{name}" — matches nodes.id
    name: str         # function/class/method name
    file: str         # relative path (forward slashes, no leading ./)
    line_start: int   # line number in file
    similarity: float # cosine similarity in [0.0, 1.0]
```

**Invariants**:
- `id` matches a row in `nodes` table (verified at query time)
- `similarity` is in [0.0, 1.0]; values from `sqlite-vec` KNN are non-negative cosine similarity
- `file` uses forward slashes, no leading `./`
- `name` is the exact value from `nodes.name` — zero post-processing

---

### BlastRadiusNeuron

A BFS-discovered neighbor at depth ≤ 2 from any `MatchedNeuron`. Produced by the BFS phase
in `search/hybrid.py`. `RUNTIME_BOUNDARY` edges are excluded from BFS traversal and reported
separately.

```python
@dataclass(frozen=True)
class BlastRadiusNeuron:
    id: str        # "{file}::{name}"
    name: str      # function/class/method name
    file: str      # relative path (forward slashes, no leading ./)
    line_start: int
```

**Invariants**:
- All fields sourced directly from `nodes` table rows — never inferred
- `id` is not in `MatchedNeuron` set (BFS result is deduplicated against KNN set; KNN nodes
  are not double-counted in blast radius — they are reported only in `matched_neurons`)
- RUNTIME_BOUNDARY edges are excluded from BFS but tracked in `runtime_boundary_warnings`
  on `HybridSearchResult`

---

### RuntimeBoundaryWarning

A `RUNTIME_BOUNDARY` edge encountered during BFS. Surfaced as a warning, not counted in
blast radius.

```python
@dataclass(frozen=True)
class RuntimeBoundaryWarning:
    src_id: str    # source Neuron ID
    src_name: str  # source Neuron name
    src_file: str  # source file path
    dst_id: str    # destination Neuron ID (may be unresolvable — kept for tracing)
    lobe_name: str # lobe name for the source Neuron
```

---

### HybridSearchResult

The merged output of the KNN + BFS phases for a given description and `top_k`. This is the
central data structure shared across all three Phase 4 commands. Produced by `search/hybrid.py`.

```python
@dataclass(frozen=True)
class HybridSearchResult:
    query: str                                         # original feature description
    top_k: int                                         # actual top_k used
    matched_neurons: tuple[MatchedNeuron, ...]         # KNN results, ordered by descending similarity
    blast_radius: tuple[BlastRadiusNeuron, ...]        # BFS depth-2 neighbors (excl. KNN set)
    affected_lobes: frozenset[str]                     # lobe names containing any matched or BFS neuron
    affected_lobe_files: dict[str, str]                # lobe_name → absolute path to lobe .md file
    runtime_boundary_warnings: tuple[RuntimeBoundaryWarning, ...]  # RUNTIME_BOUNDARY edges encountered
    reindex_scope: int                                 # count of unique Neurons in matched + blast_radius
    search_duration_ms: float                          # wall-clock ms for combined KNN + BFS
```

**Invariants**:
- `matched_neurons` is ordered by descending `similarity`
- `blast_radius` contains no ID that appears in `matched_neurons`
- `affected_lobes` is the union of lobe names from both `matched_neurons` and `blast_radius`
- `reindex_scope = len(matched_neurons) + len(blast_radius)` (unique node count)
- `search_duration_ms` is measured from KNN query start to BFS completion (connection open
  time excluded from this measurement)
- If KNN returns zero results: `matched_neurons` is empty tuple; all other collection fields
  are empty; `reindex_scope = 0`

---

### LLMContextPayload

The structured prompt sent to the LLM in `cerebrofy specify`. Constructed by
`llm/prompt_builder.py` from a `HybridSearchResult`.

```python
@dataclass(frozen=True)
class LLMContextPayload:
    system_message: str   # resolved system prompt template with $lobe_context substituted
    user_message: str     # the developer's feature description verbatim
    lobe_names: tuple[str, ...]  # ordered list of lobe names injected into context
    token_estimate: int   # rough character-based token estimate (len(system_message) // 4)
```

**Construction**:
1. Load the system prompt template (file override if `system_prompt_template` in config, else built-in)
2. For each lobe in `affected_lobe_files`, read the lobe `.md` file content
3. Build `lobe_context` by concatenating: `"## {lobe_name}\n\n{file_content}\n\n"` for each lobe
4. Substitute `$lobe_context` in the template via `string.Template.safe_substitute()`
5. `user_message` is the original description string — never modified

**Invariants**:
- `system_message` contains no unresolved `$variable` placeholders after substitution
- `user_message` equals `HybridSearchResult.query` exactly
- `lobe_names` matches the sorted order used in context concatenation (alphabetical by lobe name)
- If `affected_lobe_files` is empty: `lobe_context` is empty string; system message contains
  only the template structure without lobe content (valid edge case)

---

### SpecOutputFile

Metadata about the spec file written by `cerebrofy specify`.

```python
@dataclass(frozen=True)
class SpecOutputFile:
    path: str        # absolute path to the written file
    timestamp: str   # "YYYY-MM-DDTHH-MM-SS" (hyphens replace colons in time component)
    suffix: int      # 1 for first file at that timestamp; 2, 3, ... for collisions
    byte_count: int  # total bytes written to file
```

**Filename construction**:
```python
base = f"{timestamp}_spec.md"                # e.g. "2026-04-04T14-32-07_spec.md"
if suffix > 1:
    base = f"{timestamp}_{suffix}_spec.md"   # e.g. "2026-04-04T14-32-07_2_spec.md"
path = docs_dir / base
```

**Invariants**:
- `timestamp` uses `T` separator between date and time; colons replaced by hyphens
- `suffix` starts at 1 (not 0) — collision counter starts at 2
- Directory `docs/cerebrofy/specs/` is created if absent before file open
- File is written atomically: LLM response collected fully before disk write (for non-streaming);
  for streaming, content is collected in-memory and flushed on stream completion or error
- If LLM times out or fails: no file is written, `SpecOutputFile` is never constructed

---

### PlanReport

The structured output of `cerebrofy plan`. Rendered either as Markdown (default) or JSON
(`--json` flag). Constructed from `HybridSearchResult` in `commands/plan.py`.

```python
@dataclass(frozen=True)
class PlanReport:
    result: HybridSearchResult  # source data
    format: str                 # "markdown" | "json"
    schema_version: int         # always 1 for current version
```

**JSON schema** (stable, schema_version: 1):
```json
{
  "schema_version": 1,
  "matched_neurons": [
    {"id": "auth/validator.py::validate_token", "name": "validate_token",
     "file": "auth/validator.py", "line_start": 42, "similarity": 0.91}
  ],
  "blast_radius": [
    {"id": "auth/session.py::create_session", "name": "create_session",
     "file": "auth/session.py", "line_start": 18}
  ],
  "affected_lobes": ["auth", "api"],
  "reindex_scope": 7
}
```

**Invariants**:
- All four top-level arrays are always present (empty array `[]` if no results)
- `schema_version` field always present for forward compatibility
- When `--json` is active: no non-JSON text on stdout; all warnings/progress go to stderr
- `similarity` is rounded to 2 decimal places in both Markdown and JSON output

---

### TaskList

The structured output of `cerebrofy tasks`. Always Markdown. Constructed from
`HybridSearchResult` in `commands/tasks.py`.

```python
@dataclass(frozen=True)
class TaskList:
    result: HybridSearchResult     # source data
    items: tuple[TaskItem, ...]    # ordered task items (descending similarity)
    runtime_notes: tuple[str, ...] # formatted RUNTIME_BOUNDARY note strings
```

```python
@dataclass(frozen=True)
class TaskItem:
    index: int          # 1-based task number
    neuron: MatchedNeuron
    lobe_name: str      # lobe name (or "(unassigned)" if none)
    blast_count: int    # number of BFS neighbors reachable from this Neuron
```

**Markdown output format** (per task item):
```
N. Modify {neuron_name} in [[{lobe_name}]] ({file}:{line_start}) — blast radius: {count} nodes
```

**RUNTIME_BOUNDARY note format**:
```
Note: {src_name} has unresolvable cross-language calls — see RUNTIME_BOUNDARY entries in [[{lobe_name}]].
```

**Invariants**:
- Items ordered by descending `MatchedNeuron.similarity`
- `index` is 1-based and sequential from 1 to `len(items)`
- `lobe_name` is `"(unassigned)"` when the Neuron has no matching lobe in `affected_lobe_files`
- `blast_count` counts only direct BFS neighbors of this specific Neuron (not total blast radius)
- RUNTIME_BOUNDARY notes appear after the numbered task list, separated by a blank line

---

## Config Extensions

Phase 4 adds new optional keys to the existing `CerebrофyConfig` dataclass and `config.yaml`:

```yaml
# config.yaml additions for Phase 4
llm_endpoint: "https://api.openai.com/v1"  # base URL for OpenAI-compatible endpoint
llm_model: "gpt-4o"                         # model identifier
llm_timeout: 60                             # seconds; default 60 if absent
system_prompt_template: ""                  # optional path to .txt/.md file; built-in used if absent
top_k: 10                                   # KNN top-k; default 10 if absent
```

**Invariants**:
- `llm_endpoint` and `llm_model` are required for `cerebrofy specify`; optional for `plan`/`tasks`
- `llm_timeout` defaults to 60 if absent; must be positive integer
- `system_prompt_template` path is resolved relative to repo root; exit 1 if configured but absent
- `top_k` defaults to 10 if absent; `--top-k N` CLI flag overrides for a single invocation
