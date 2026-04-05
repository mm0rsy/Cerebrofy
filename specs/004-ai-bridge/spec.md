# Feature Specification: Phase 4 — AI Bridge

**Feature Branch**: `004-ai-bridge`
**Created**: 2026-04-04
**Status**: Draft
**Input**: User description: "Read @cerebrofy_blueprint_v5_0.md and specify the next feature based on phase 4"

## Clarifications

### Session 2026-04-04

- Q: What should the default LLM request timeout be for `cerebrofy specify`? → A: Configurable via `llm_timeout` in `config.yaml`; default 60 seconds.
- Q: Should `cerebrofy specify` retry failed LLM requests before exiting 1? → A: One automatic retry on transient errors (5xx, network failure); no retry on 429 (rate-limit) or 4xx client errors.
- Q: Should developers be able to customize the LLM system prompt template? → A: Optional `system_prompt_template` file path in `config.yaml`; built-in default is used when absent.
- Q: Should `cerebrofy specify` fall back to non-streaming mode when streaming is unavailable? → A: Auto-detect — attempt streaming; if the endpoint returns a non-streaming response, accept it and emit `"Note: streaming not supported by endpoint, buffering response."` to stderr.
- Q: Should `cerebrofy specify` output hybrid search results for observability? → A: Print a compact hybrid search summary to stderr before the LLM call — matched Neuron names, cosine similarity scores, and affected lobe names.

---

## Overview

Phase 4 delivers the AI Bridge — three commands that convert a developer's plain-language
feature description into structured, codebase-grounded output by combining local hybrid
search (semantic KNN + structural BFS) with an optional LLM reasoning layer.

`cerebrofy plan` and `cerebrofy tasks` are fully offline — they run hybrid search locally
and produce structured Markdown output with zero network calls. `cerebrofy specify` extends
this with an outbound LLM call that receives the hybrid search results as grounded context,
producing an AI-generated spec anchored to the real codebase.

Phase 4 requires a complete Phase 2 index (`cerebrofy.db`) and a functioning Phase 3
update/validate cycle before it can be used.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — AI-Grounded Spec Generation (Priority: P1)

A developer has a feature idea and wants a structured specification grounded in their actual
codebase, not a generic AI answer. They run `cerebrofy specify "add OAuth2 login"`.
Cerebrofy finds the most semantically relevant code units in the repository, computes the
structural blast radius, injects the relevant lobe documentation into an LLM prompt, and
writes a codebase-aware spec to `docs/cerebrofy/specs/<timestamp>_spec.md`. The developer
gets a spec that references real function names, real file locations, and real dependency
chains — not boilerplate.

**Why this priority**: This is the primary value proposition of Phase 4 — AI reasoning
about the developer's specific codebase rather than producing generic advice. All other Phase
4 stories contribute to this capability. P1 because without it, Phase 4 has no LLM output.

**Independent Test**: Run `cerebrofy specify "add user authentication"` against a repo with
a valid index and configured LLM credentials. Confirm a Markdown file is created in
`docs/cerebrofy/specs/`. Confirm the file references actual function names and files from
the codebase. Confirm exit code 0 and the output file path is printed to stdout.

**Acceptance Scenarios**:

1. **Given** a valid index and a configured LLM endpoint with a valid API key, **When**
   the developer runs `cerebrofy specify "add OAuth2 login"`, **Then** the command runs
   hybrid search, injects the matching lobe `.md` files into the LLM system prompt, attempts
   streaming (falling back to buffered output with a stderr notice if the endpoint does not
   support it), and writes the full response to `docs/cerebrofy/specs/<ISO-timestamp>_spec.md`.
   Exit code 0. The output file path is printed as the final line of stdout.

2. **Given** the LLM API key is missing from the environment, **When** the developer runs
   `cerebrofy specify`, **Then** the command prints a clear error identifying the missing
   environment variable and exits 1 without making any API call or writing any file.

3. **Given** `llm_endpoint` or `llm_model` is absent from `config.yaml`, **When** the
   developer runs `cerebrofy specify`, **Then** the command prints a clear error identifying
   the missing config key and exits 1.

4. **Given** the hybrid search returns zero matching Neurons, **When** the developer runs
   `cerebrofy specify`, **Then** the command prints
   `"Cerebrofy: No relevant code units found for this description."`, exits 0, and does NOT
   call the LLM or write any file.

5. **Given** the index's `state_hash` does not match the current working tree, **When** the
   developer runs `cerebrofy specify`, **Then** the command emits a non-blocking warning
   (`"Warning: Index may be out of sync. Run 'cerebrofy update' for current results."`) and
   proceeds to generate the spec. It MUST NOT block.

8. **Given** a valid index and LLM configuration, **When** `cerebrofy specify` runs hybrid
   search, **Then** before making the LLM call it prints a compact search summary to stderr
   listing each matched Neuron name, similarity score, and affected lobe names. stdout
   remains clean — only the LLM response (streamed or buffered) appears on stdout.

6. **Given** the `docs/cerebrofy/specs/` directory does not exist, **When** the developer
   runs `cerebrofy specify`, **Then** the command creates the directory and writes the file
   without error.

7. **Given** `embed_model` in `cerebrofy.db` meta does not match `embedding_model` in
   `config.yaml`, **When** the developer runs `cerebrofy specify`, **Then** the command
   exits 1 with the error:
   `"Embedding model mismatch: index was built with {meta_model}, config says {config_model}. Run 'cerebrofy build' to rebuild."`

---

### User Story 2 — Codebase Impact Analysis (Priority: P2)

Before starting a new feature, a developer wants to understand which existing code units
are most semantically relevant and how large the structural blast radius of a change in that
area would be. They run `cerebrofy plan "add OAuth2 login"`. The command runs a fully local
hybrid search — no LLM, no API key, zero network calls — and prints a structured Markdown
report: matched Neurons with similarity scores, depth-2 structural neighbors, affected lobe
files, and estimated re-index scope.

**Why this priority**: `cerebrofy plan` delivers concrete value (impact analysis, developer
orientation) with no network dependency. P2 because it is useful independently of the LLM
and its output feeds directly into `cerebrofy specify`.

**Independent Test**: Run `cerebrofy plan "add user authentication"` on a machine with no
network access. Confirm the output is Markdown containing matched Neurons, Blast Radius,
Affected Lobes, and Re-index Scope sections. Confirm exit 0 and no network calls.

**Acceptance Scenarios**:

1. **Given** a valid index and a feature description, **When** the developer runs
   `cerebrofy plan "add OAuth2 login"`, **Then** the command outputs to stdout a Markdown
   report with four labeled sections: **Matched Neurons** (name, file, line, similarity
   score), **Blast Radius** (depth-2 neighbor Neuron names and files, RUNTIME_BOUNDARY
   edges excluded from traversal), **Affected Lobes** (lobe names and `.md` file paths),
   and **Re-index Scope** (estimated count of nodes that would need re-indexing). Exit 0.

2. **Given** a valid index and `--json` flag, **When** the developer runs `cerebrofy plan
   --json "..."`, **Then** stdout is a machine-readable JSON object with stable fields
   `matched_neurons`, `blast_radius`, `affected_lobes`, `reindex_scope`. No decorative text
   is mixed into stdout.

3. **Given** `--top-k N` CLI flag, **When** the developer runs `cerebrofy plan --top-k 20
   "..."`, **Then** the KNN search uses `top_k=20` overriding `config.yaml`.

4. **Given** the hybrid search returns zero matches, **When** the developer runs
   `cerebrofy plan`, **Then** the command prints
   `"Cerebrofy: No relevant code units found for this description."` and exits 0.

5. **Given** no valid index, **When** the developer runs `cerebrofy plan`, **Then** the
   command exits 1 with a clear error directing the developer to run `cerebrofy build`.

---

### User Story 3 — Actionable Task List (Priority: P3)

After understanding the impact area, a developer wants a numbered, ordered task list they
can execute one by one. They run `cerebrofy tasks "add OAuth2 login"`. The command runs the
same local hybrid search and produces a numbered task list where each entry names the
specific code unit to modify, links to its lobe Markdown file, and states the blast radius
count — giving the developer a concrete, ordered work plan anchored to real code locations.

**Why this priority**: `cerebrofy tasks` adds task-list formatting on top of the same local
search as `cerebrofy plan`. P3 because it is an output-shape variant, not a new capability.

**Independent Test**: Run `cerebrofy tasks "add user authentication"` against a valid index.
Confirm output is a numbered Markdown list. Confirm each item contains a Neuron name, file,
lobe link, blast radius count. Confirm exit 0 and no network calls.

**Acceptance Scenarios**:

1. **Given** a valid index and a feature description, **When** the developer runs
   `cerebrofy tasks "add OAuth2 login"`, **Then** stdout is a numbered Markdown task list
   where each item follows:
   `N. Modify {neuron_name} in [[{lobe_name}]] ({file}:{line_start}) — blast radius: {count} nodes`
   Items are ordered by descending KNN similarity score. Exit 0.

2. **Given** a RUNTIME_BOUNDARY edge is encountered during BFS, **When** the developer runs
   `cerebrofy tasks`, **Then** it is listed separately as:
   `Note: {neuron_name} has unresolvable cross-language calls — see RUNTIME_BOUNDARY entries in [[{lobe_name}]].`
   It is NOT counted in the blast radius.

3. **Given** the same description passed to `cerebrofy plan`, **When** the developer runs
   `cerebrofy tasks`, **Then** the Neuron set, blast radius, and affected lobes are
   identical to `cerebrofy plan` output — both commands share the exact same hybrid search.

4. **Given** `--top-k N`, **When** the developer runs `cerebrofy tasks --top-k 5 "..."`,
   **Then** the task list has at most 5 items (one per KNN-matched Neuron).

5. **Given** a Neuron reference in the output, **When** the developer inspects the index,
   **Then** every Neuron name, file, and line in the task list MUST exist in the `nodes`
   table. Zero hallucinated references are permitted.

---

### Edge Cases

- What happens when `cerebrofy specify` is run with no index? → Exit 1: `"No index found. Run 'cerebrofy build' first."`
- What happens when the LLM response is truncated due to context length limits? → Write the partial response to the output file; emit warning: `"Warning: LLM response may be truncated. Consider reducing top_k in config.yaml."`
- What happens when `top_k` exceeds the total number of Neurons in the index? → Use all Neurons. No error.
- What happens when the `docs/cerebrofy/specs/` directory is not writable? → Exit 1 with the path and permission details.
- What happens when the LLM request times out? → Exit 1: `"Error: LLM request timed out after {N}s. Increase llm_timeout in config.yaml or retry."` No partial file is written. Timeout duration is configurable via `llm_timeout` in `config.yaml` (default 60 seconds).
- What happens when two `cerebrofy specify` calls occur at the same second? → Append counter suffix: `<timestamp>_2_spec.md`, `<timestamp>_3_spec.md`.
- What happens when the description is an empty string? → Exit 1: `"Description must not be empty."`
- What happens when `cerebrofy plan --json` is piped to another process? → Valid JSON on stdout, no decorative text intermixed.
- What happens when a Neuron has no assigned lobe (edge case in lobe mapping)? → Include the Neuron with lobe label `"(unassigned)"`. Do not skip.
- What happens when the index schema is outdated? → Exit 1: `"Schema version mismatch. Run 'cerebrofy migrate' to upgrade."`
- What happens when `cerebrofy specify` is called concurrently by two processes? → Both writes succeed to different timestamp filenames. No locking needed (write-once, distinct filenames).
- What happens when `system_prompt_template` is configured in `config.yaml` but the file does not exist? → Exit 1: `"Error: system_prompt_template file not found: {path}."` No LLM call is made.
- What happens when the LLM returns HTTP 429 (rate-limited)? → Exit 1 immediately with `"Error: LLM rate limit exceeded (HTTP 429). Wait and retry."` No automatic retry — retrying immediately would hit the limit again.
- What happens when both the initial LLM request and the automatic retry fail? → Exit 1 with both failure reasons logged to stderr. No partial file written.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `cerebrofy specify`, `cerebrofy plan`, and `cerebrofy tasks` MUST each accept a feature description as a required positional CLI argument. An empty description string MUST exit 1 with the error: `"Description must not be empty."`

- **FR-002**: All three commands MUST execute hybrid search as their first step: (1) KNN cosine similarity query on `vec_neurons` returning the top-k nearest Neurons; (2) BFS depth=2 from each KNN-matched Neuron across the `edges` table excluding `RUNTIME_BOUNDARY` edges; (3) merge and deduplicate the union of KNN results and BFS-neighbor Neuron IDs.

- **FR-003**: The hybrid search MUST execute entirely within a single read-only SQLite connection to `cerebrofy.db` — zero network calls, zero IPC, zero serialization at the search step. Both the KNN query and the BFS graph traversal MUST run within the same connection.

- **FR-004**: The `top_k` value for KNN MUST default to the `top_k` field in `config.yaml` (default 10 if the field is absent). All three commands MUST support a `--top-k N` CLI flag that overrides the config value for that invocation.

- **FR-005**: If the KNN search returns zero Neurons, all three commands MUST print `"Cerebrofy: No relevant code units found for this description."`, exit 0, and MUST NOT call the LLM, write any file, or produce any report output.

- **FR-006**: `cerebrofy plan` MUST output a Markdown report to stdout containing four labeled sections: **Matched Neurons** (name, file, line_start, cosine similarity score), **Blast Radius** (depth-2 neighbor Neuron names and files, RUNTIME_BOUNDARY edges excluded), **Affected Lobes** (lobe names and `.md` file paths), **Re-index Scope** (estimated count of nodes impacted). No LLM call is made.

- **FR-007**: `cerebrofy plan` MUST support a `--json` flag producing a machine-readable JSON object with stable top-level fields: `schema_version` (always `1`), `matched_neurons`, `blast_radius`, `affected_lobes`, `reindex_scope`. The `schema_version` field MUST always be present as the first top-level field. AI tools SHOULD check `schema_version` before parsing (FR-023). When `--json` is active, no decorative text, progress messages, or warnings are mixed into stdout (they go to stderr only).

- **FR-008**: `cerebrofy tasks` MUST output a numbered Markdown task list to stdout. Each item MUST follow: `N. Modify {neuron_name} in [[{lobe_name}]] ({file}:{line_start}) — blast radius: {count} nodes`. Items MUST be ordered by descending KNN similarity score. No LLM call is made.

- **FR-009**: `cerebrofy tasks` MUST list RUNTIME_BOUNDARY edges encountered during BFS separately (not in the numbered task list), using the format: `Note: {neuron_name} has unresolvable cross-language calls — see RUNTIME_BOUNDARY entries in [[{lobe_name}]].`

- **FR-010**: `cerebrofy tasks` and `cerebrofy plan` MUST use the identical hybrid search implementation. For the same description and `top_k`, the matched Neuron set, blast radius set, affected lobe set, and RUNTIME_BOUNDARY notes MUST be identical.

- **FR-011**: `cerebrofy specify` MUST read `llm_endpoint` and `llm_model` from `config.yaml`. If either key is absent, it MUST exit 1 with a clear error naming the missing key before making any API call.

- **FR-012**: `cerebrofy specify` MUST resolve the LLM API key from the environment. The environment variable name is derived from `llm_endpoint` (e.g., `openai` → `OPENAI_API_KEY`). If the key is absent, it MUST exit 1 naming the missing variable without making any API call.

- **FR-013**: `cerebrofy specify` MUST construct an LLM prompt where the system message is derived from a system prompt template. The template receives the affected lobe `.md` file contents (each prefixed by its lobe name) as an injectable variable. The user message is the developer's feature description verbatim. Only lobes containing KNN-matched or BFS-neighbor Neurons are included — not all lobes.

- **FR-023**: `cerebrofy specify` MUST resolve the system prompt template in this order: (1) path specified by `system_prompt_template` in `config.yaml` (resolved relative to the repo root); (2) built-in default template bundled with Cerebrofy. If a `system_prompt_template` path is configured but the file does not exist, `cerebrofy specify` MUST exit 1 with a clear error identifying the missing file path. The built-in default template produces a structured Markdown specification grounded in the injected lobe context.

- **FR-014**: `cerebrofy specify` MUST support any OpenAI-compatible LLM endpoint (Chat Completions API with `messages` array). The endpoint base URL is derived from `llm_endpoint` in `config.yaml`. It is not locked to the OpenAI API domain.

- **FR-015**: `cerebrofy specify` MUST attempt to stream the LLM response token-by-token to stdout as it arrives. If the endpoint does not support streaming and returns a complete non-streaming response, `cerebrofy specify` MUST accept it, emit `"Note: streaming not supported by endpoint, buffering response."` to stderr, then print the full response to stdout and write it to the output file. The output file content MUST be identical regardless of whether streaming or non-streaming mode was used.

- **FR-016**: `cerebrofy specify` MUST write output to `docs/cerebrofy/specs/<ISO-timestamp>_spec.md`. If the directory does not exist, it MUST create it. If a file with the same timestamp already exists, a monotonically incrementing counter suffix MUST be appended (`_2`, `_3`, etc.).

- **FR-017**: `cerebrofy specify` MUST detect when the index `state_hash` in `cerebrofy.db` meta differs from the SHA-256 of the current working tree. On mismatch, it MUST emit a non-blocking stderr warning: `"Warning: Index may be out of sync. Run 'cerebrofy update' for current results."` Spec generation proceeds regardless.

- **FR-018**: `cerebrofy specify` MUST detect when `embed_model` in `cerebrofy.db` meta does not match `embedding_model` in `config.yaml`. On mismatch, it MUST exit 1 with: `"Embedding model mismatch: index was built with {meta_model}, config says {config_model}. Run 'cerebrofy build' to rebuild."` A mismatched model produces semantically meaningless KNN results.

- **FR-019**: All three commands MUST require a valid `cerebrofy.db` at the current schema version. If the index is absent → exit 1 directing to `cerebrofy build`. If schema version is outdated → exit 1 directing to `cerebrofy migrate`. Schema version MUST be checked before any query.

- **FR-020**: All three commands MUST be strictly read-only with respect to the index and tracked source files. The ONLY permitted write operation across all three commands is `cerebrofy specify`'s output file in `docs/cerebrofy/specs/`.

- **FR-021**: `cerebrofy specify` MUST respect a `llm_timeout` value (in seconds) from `config.yaml` as the maximum wall-clock time to wait for the LLM to complete its response. If absent from `config.yaml`, the default is 60 seconds. On timeout, the command MUST exit 1 with the message `"Error: LLM request timed out after {N}s. Increase llm_timeout in config.yaml or retry."` No partial file is written.

- **FR-022**: `cerebrofy specify` MUST automatically retry the LLM request exactly once on transient failures (HTTP 5xx responses or network-level errors). The retry MUST emit `"Cerebrofy: LLM request failed ({reason}), retrying..."` to stderr before the second attempt. If the retry also fails, the command exits 1 with the error details. `cerebrofy specify` MUST NOT retry on HTTP 429 (rate-limit) or any 4xx client error — these are returned immediately with a clear error message.

- **FR-024**: Before making the LLM call, `cerebrofy specify` MUST print a compact hybrid search summary to stderr. The summary MUST include: the count of matched Neurons, each matched Neuron's name and cosine similarity score (2 decimal places), and the names of affected lobes. This output goes to stderr only — stdout remains clean for the LLM response. Example format:
  ```
  Cerebrofy: Hybrid search — 4 neurons matched, 2 lobes affected
    · validate_token (auth/validator.py) — score 0.91
    · create_session (auth/session.py)  — score 0.87
    · UserLogin (api/handlers.py)       — score 0.74
    · import auth.oauth2                — score 0.68
  Cerebrofy: Affected lobes: auth, api
  Cerebrofy: Calling LLM ({model})...
  ```

### Key Entities

- **Hybrid Search Result**: The merged, deduplicated output of KNN + BFS for a given description and `top_k`. Contains: matched Neurons with cosine similarity scores, blast radius Neuron set (depth-2 BFS neighbors), affected lobe set, RUNTIME_BOUNDARY warnings.
- **LLM Context Payload**: The constructed prompt sent to the LLM. System message = affected lobe `.md` file contents, each prefixed by lobe name. User message = the developer's feature description verbatim.
- **Spec Output File**: The LLM-generated Markdown document at `docs/cerebrofy/specs/<timestamp>_spec.md`. Content is the raw LLM response. Committed to git along with other cerebrofy Markdown artifacts.
- **Lobe Context Set**: The subset of lobe `.md` files for lobes containing any KNN-matched or BFS-neighbor Neuron. Always a subset of all lobes — never the full set.
- **Search Summary**: The compact stderr output printed before the LLM call — matched Neuron names, cosine similarity scores, and affected lobe names. Enables developers to understand what context was sent to the LLM without running a separate `cerebrofy plan`.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The hybrid search (KNN + BFS combined) completes in under 50 milliseconds on a 10,000-node index on a standard developer machine. This is entirely local — no network latency contributes to this target.

- **SC-002**: Every Neuron name, file path, and lobe name appearing in `cerebrofy specify` output exists in the current `nodes` table of the index. Zero hallucinated code references are present in any generated spec, verified across all test runs.

- **SC-003**: `cerebrofy plan` and `cerebrofy tasks` return identical Neuron sets, blast radius sets, and affected lobe sets for the same description and `top_k` on the same index. 100% consistency across all test invocations.

- **SC-004**: `cerebrofy specify` streams its first output token to stdout within 3 seconds of invocation on a standard internet connection (excluding cold embedding model load time documented in Phase 3 SC-001).

- **SC-005**: The lobe context injected into the LLM prompt contains no more than 10% of the total token count of all tracked raw source files in the same repository (target: ≥ 90% token reduction). Measured on a 20,000-LOC reference repository.

- **SC-006**: `cerebrofy specify` correctly handles all failure modes — missing API key, LLM timeout, HTTP 5xx, network unavailability — in 100% of tested cases: always exits 1 with a clear user-facing error, never writes a partial or empty spec file.

---

## Assumptions

- Phase 2 (`cerebrofy build`) and Phase 3 (`cerebrofy update`, `cerebrofy validate`) are complete and verified before Phase 4 is implemented. A valid, current-schema `cerebrofy.db` must exist before any Phase 4 command can run.
- `embed_model` in `cerebrofy.db` meta is assumed to match `embedding_model` in `config.yaml` unless `cerebrofy specify` detects a mismatch (FR-018). Mismatched models produce semantically meaningless KNN results and are treated as a hard error.
- The LLM endpoint is OpenAI-compatible (supports the Chat Completions API with `messages` array and `stream: true`). Non-compatible endpoints are out of scope for v1.
- `cerebrofy plan` and `cerebrofy tasks` are intentionally LLM-free. Their value is structured local reasoning — fast, free, offline, and hallucination-free by design.
- Lobe `.md` files written by `cerebrofy build` / `cerebrofy update` are the sole source of codebase context sent to the LLM. Raw source files are never sent.
- The default `top_k=10` balances context quality with LLM context window usage. Projects with very large lobes may need to reduce `top_k` to avoid context length truncation.
- The system prompt template is resolved from `system_prompt_template` in `config.yaml` (file path relative to repo root) or falls back to Cerebrofy's built-in default. The built-in default produces a structured Markdown spec grounded in lobe context. Teams can override it to match their own spec format, style guide, or output language.
- The `docs/cerebrofy/specs/` directory and all generated spec files are committed to git. Cerebrofy does not add them to `.gitignore`.
- Concurrent invocations of `cerebrofy specify` in the same repository are safe — each writes to a unique timestamp-based filename. No file lock is required.
- The minimum cosine similarity threshold for KNN inclusion defaults to 0.0 (all `top_k` results are included regardless of score). A configurable threshold is deferred to a future version.
- `cerebrofy plan --json` output schema is stable within a major version. Consumers may rely on the field names `matched_neurons`, `blast_radius`, `affected_lobes`, `reindex_scope`.
- `llm_timeout` in `config.yaml` controls the maximum wall-clock seconds `cerebrofy specify` waits for the LLM response. Default is 60 seconds. This covers both connection establishment and full response streaming.
