# Tasks: Phase 4 — AI Bridge

**Input**: Design documents from `/specs/004-ai-bridge/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

**Organization**: Tasks are grouped by user story. Each task is scoped to a single function,
dataclass, or one-concern unit so that a simpler LLM can handle it without broader context.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files AND no shared write dependency)
- **[Story]**: Which user story this task belongs to
- All paths are relative to the repository root

---

## Phase 1: Setup

**Purpose**: Create directory scaffolding and extend config before any module is written.

- [x] T001 Create `src/cerebrofy/search/__init__.py` (empty file — creates search package)
- [x] T002 Create `src/cerebrofy/llm/__init__.py` (empty file — creates llm package)
- [x] T003 Add Phase 4 fields to `CerebrоfyConfig` dataclass in `src/cerebrofy/config/loader.py`:
  Add five optional fields with their defaults:
  ```python
  llm_endpoint: str = ""
  llm_model: str = ""
  llm_timeout: int = 60
  system_prompt_template: str = ""
  top_k: int = 10
  ```
  Add corresponding YAML load logic (read each key from `config.yaml`; use the default if key
  is absent). These fields MUST exist before any Phase 3–5 command references them.

**Checkpoint**: Two new Python packages exist and config supports Phase 4 keys. All later imports and config reads will work.

---

## Phase 2: Foundational — Hybrid Search Core

**Purpose**: Implement `search/hybrid.py` — the shared search kernel used by ALL three commands.
No user story work can begin until this phase is complete.

**⚠️ CRITICAL**: All of Phase 3, 4, and 5 depend on this module.

### Data structures (can all be written in parallel)

- [x] T004 [P] Add `MatchedNeuron` frozen dataclass to `src/cerebrofy/search/hybrid.py`:
  fields `id: str`, `name: str`, `file: str`, `line_start: int`, `similarity: float`.
  Use `@dataclass(frozen=True)`. No other code in this task.

- [x] T005 [P] Add `BlastRadiusNeuron` frozen dataclass to `src/cerebrofy/search/hybrid.py`:
  fields `id: str`, `name: str`, `file: str`, `line_start: int`.
  Use `@dataclass(frozen=True)`. No other code in this task.

- [x] T006 [P] Add `RuntimeBoundaryWarning` frozen dataclass to `src/cerebrofy/search/hybrid.py`:
  fields `src_id: str`, `src_name: str`, `src_file: str`, `dst_id: str`, `lobe_name: str`.
  Use `@dataclass(frozen=True)`. No other code in this task.

- [x] T007 Add `HybridSearchResult` frozen dataclass to `src/cerebrofy/search/hybrid.py`
  (depends on T004, T005, T006):
  fields `query: str`, `top_k: int`, `matched_neurons: tuple[MatchedNeuron, ...]`,
  `blast_radius: tuple[BlastRadiusNeuron, ...]`, `affected_lobes: frozenset[str]`,
  `affected_lobe_files: dict[str, str]`, `runtime_boundary_warnings: tuple[RuntimeBoundaryWarning, ...]`,
  `reindex_scope: int`, `search_duration_ms: float`.
  Use `@dataclass(frozen=True)`.

### KNN query

- [x] T008 Implement `_run_knn_query(conn: sqlite3.Connection, embedding: bytes, top_k: int) -> list[MatchedNeuron]` in `src/cerebrofy/search/hybrid.py`:
  Use a **two-step** approach required by sqlite-vec `vec0` virtual tables:

  **Step 1** — KNN search (uses required `k = ?` constraint):
  ```sql
  SELECT id, distance FROM vec_neurons WHERE embedding MATCH ? AND k = ?
  ```
  Bind `embedding` as `sqlite_vec.serialize_float32(raw_embedding_list)` and `k = top_k`.
  This returns `(id, distance)` rows where `distance` is cosine distance ∈ `[0.0, 2.0]`.

  **Step 2** — Fetch node metadata for matched IDs:
  ```sql
  SELECT id, name, file, line_start FROM nodes WHERE id IN (...)
  ```
  Build a lookup dict from the Step 2 results.

  **Construct** `MatchedNeuron(id, name, file, line_start, similarity=1.0 - distance/2.0)` for each
  KNN result. The `1 - distance/2` formula maps cosine distance `[0, 2]` → similarity `[0, 1]`.
  Return list ordered by descending similarity.

### BFS helpers

- [x] T009 Implement `_expand_bfs_one_level(conn: sqlite3.Connection, current_ids: set[str], visited_ids: set[str]) -> tuple[set[str], list[RuntimeBoundaryWarning]]` in `src/cerebrofy/search/hybrid.py`:
  Query `SELECT src_id, dst_id, rel_type FROM edges WHERE src_id IN (...)`.
  Use the `RUNTIME_BOUNDARY` constant from `src/cerebrofy/graph/edges.py`.
  For each row: if `rel_type == RUNTIME_BOUNDARY`, create a stub `RuntimeBoundaryWarning`
  (leave `src_name`/`src_file` as empty strings for now — filled by caller).
  Otherwise add `dst_id` to `next_ids` if not already in `visited_ids`.
  Return `(next_ids, warnings)`.

- [x] T010 Implement `_fetch_blast_radius_neurons(conn: sqlite3.Connection, node_ids: set[str]) -> list[BlastRadiusNeuron]` in `src/cerebrofy/search/hybrid.py`:
  Query `SELECT id, name, file, line_start FROM nodes WHERE id IN (...)` for the given IDs.
  Return list of `BlastRadiusNeuron`. If `node_ids` is empty, return `[]`.

- [x] T011 Implement `_run_bfs(conn: sqlite3.Connection, seed_ids: set[str]) -> tuple[list[BlastRadiusNeuron], list[RuntimeBoundaryWarning]]` in `src/cerebrofy/search/hybrid.py` (depends on T009, T010):
  Run exactly two levels of BFS using `_expand_bfs_one_level`:
  - Track `visited = seed_ids.copy()`.
  - Level 1: expand from `seed_ids` → `(level1_ids, warnings1)`. Add `level1_ids` to `visited`.
  - Level 2: expand from `level1_ids` → `(level2_ids, warnings2)`. Add `level2_ids` to `visited`.
  - Collect all new node IDs: `all_new_ids = (level1_ids | level2_ids) - seed_ids`.
  - Call `_fetch_blast_radius_neurons(conn, all_new_ids)` → `blast_neurons`.
  - Fill `RuntimeBoundaryWarning.src_name` and `src_file` for each warning by looking up
    `src_id` in a `SELECT id, name, file FROM nodes WHERE id IN (...)` query.
  - Return `(blast_neurons, warnings1 + warnings2)`.

### Lobe resolution

- [x] T012 Implement `_resolve_affected_lobes(conn: sqlite3.Connection, node_ids: set[str], lobe_dir: str) -> tuple[frozenset[str], dict[str, str]]` in `src/cerebrofy/search/hybrid.py`:
  Query `SELECT DISTINCT file FROM nodes WHERE id IN (...)`.
  For each file path, derive the lobe name: take the first path component before `/`
  (e.g., `"auth/validator.py"` → `"auth"`; a root-level file → `"root"`).
  Build `lobe_files = {lobe_name: os.path.join(lobe_dir, f"{lobe_name}_lobe.md")}`.
  Only include lobe entries where the `.md` file actually exists on disk.
  Return `(frozenset(lobe_names), lobe_files)`.

### Embedding helper

- [x] T013 Implement `_embed_query(description: str, config) -> bytes` in `src/cerebrofy/search/hybrid.py`:
  Load the configured embedder using the same Embedder ABC from Phase 2
  (`src/cerebrofy/embedder/base.py`). Call `embedder.embed([description])[0]` to get the
  embedding vector. Return `sqlite_vec.serialize_float32(vector)` — the serialized bytes
  required by sqlite-vec KNN (`MATCH ?` bind parameter). This function is called by all three
  commands BEFORE the DB connection is opened (per CLAUDE.md invariant:
  "Embedding before LLM call — embed the description query BEFORE opening the DB connection.").

### Orchestrator

- [x] T014 Implement `hybrid_search(query: str, db_path: str, embedding: bytes, top_k: int, config_embed_model: str, lobe_dir: str) -> HybridSearchResult` in `src/cerebrofy/search/hybrid.py` (depends on T007–T012):
  1. Open DB using `open_db()` from `src/cerebrofy/db/connection.py` with read-only mode.
     Per research Decision 1: `open_db()` supports a `?mode=ro` URI flag — use the form
     documented in Phase 2's `db/connection.py` for read-only access.
  2. Read `embed_model` from the `meta` table:
     `SELECT value FROM meta WHERE key = 'embed_model'`.
     If `embed_model` does not match `config_embed_model`, close the connection and raise:
     `ValueError(f"Embedding model mismatch: index was built with {meta_model}, config says {config_embed_model}. Run 'cerebrofy build' to rebuild.")`
     Note: `cerebrofy specify` also checks this before calling `hybrid_search` (early exit),
     but `cerebrofy plan`/`tasks` rely solely on this check inside `hybrid_search`.
  3. Record `start = time.monotonic()`.
  4. Call `_run_knn_query(conn, embedding, top_k)` → `matched_neurons`.
  5. If `matched_neurons` is empty: close connection and return empty `HybridSearchResult`
     (all collection fields empty, `reindex_scope=0`, `search_duration_ms` computed normally).
  6. Compute `seed_ids = {n.id for n in matched_neurons}`.
  7. Call `_run_bfs(conn, seed_ids)` → `(blast_radius, warnings)`.
  8. Call `_resolve_affected_lobes(conn, seed_ids | {n.id for n in blast_radius}, lobe_dir)` → `(lobes, lobe_files)`.
  9. Close connection.
  10. Return:
      ```python
      HybridSearchResult(
          query=query,
          top_k=top_k,
          matched_neurons=tuple(matched_neurons),
          blast_radius=tuple(blast_radius),
          affected_lobes=lobes,
          affected_lobe_files=lobe_files,
          runtime_boundary_warnings=tuple(warnings),
          reindex_scope=len(matched_neurons) + len(blast_radius),
          search_duration_ms=(time.monotonic() - start) * 1000,
      )
      ```

**Checkpoint**: `hybrid_search()` is functional. All three commands can now be implemented.

---

## Phase 3: User Story 1 — `cerebrofy specify` (Priority: P1) 🎯 MVP

**Goal**: LLM-grounded spec generation with streaming output, retry, timeout, and file write.

**Independent Test**: Run `cerebrofy specify "add user authentication"` with a valid index and a
mock LLM endpoint. Confirm a Markdown file appears in `docs/cerebrofy/specs/`, the file path
is the final stdout line, and the LLM response content is in the file. Exit code 0.

### Prompt builder module (can all be written in parallel)

- [x] T015 [P] [US1] Add `LLMContextPayload` frozen dataclass to `src/cerebrofy/llm/prompt_builder.py`:
  fields `system_message: str`, `user_message: str`, `lobe_names: tuple[str, ...]`, `token_estimate: int`.
  Use `@dataclass(frozen=True)`.

- [x] T016 [P] [US1] Add built-in default system prompt template constant `DEFAULT_SYSTEM_PROMPT` to `src/cerebrofy/llm/prompt_builder.py`:
  ```
  You are a senior software architect with deep knowledge of the following codebase.

  ## Codebase Context (from Cerebrofy index)

  $lobe_context

  ## Your Task

  Generate a structured feature specification for the following feature request.
  The spec must reference only real code units shown in the context above.
  Format the output as Markdown with sections: Overview, Requirements, Acceptance Criteria.
  ```
  Store as a module-level string constant. No logic in this task.

- [x] T017 [P] [US1] Implement `_load_template(template_path: str | None, repo_root: str) -> string.Template` in `src/cerebrofy/llm/prompt_builder.py`:
  If `template_path` is None or empty string: return `string.Template(DEFAULT_SYSTEM_PROMPT)`.
  Otherwise resolve the path relative to `repo_root`. If the file does not exist, raise
  `FileNotFoundError(f"system_prompt_template file not found: {resolved_path}")`.
  Read and return `string.Template(file_content)`.

- [x] T018 [P] [US1] Implement `_build_lobe_context(lobe_files: dict[str, str]) -> str` in `src/cerebrofy/llm/prompt_builder.py`:
  For each `(lobe_name, lobe_path)` sorted alphabetically by lobe_name:
    Read the file at `lobe_path`. If file does not exist, skip silently.
    Append `f"## {lobe_name}\n\n{content}\n\n"` to the result string.
  Return the concatenated string. Return `""` if `lobe_files` is empty.

- [x] T019 [US1] Implement `build_llm_context(result: HybridSearchResult, template_path: str | None, repo_root: str) -> LLMContextPayload` in `src/cerebrofy/llm/prompt_builder.py` (depends on T015–T018):
  1. Call `_load_template(template_path, repo_root)` → `tmpl`.
  2. Call `_build_lobe_context(result.affected_lobe_files)` → `lobe_context`.
  3. `system_message = tmpl.safe_substitute(lobe_context=lobe_context)`.
  4. `user_message = result.query`.
  5. `lobe_names = tuple(sorted(result.affected_lobe_files.keys()))`.
  6. `token_estimate = len(system_message) // 4`.
  7. Return `LLMContextPayload(system_message, user_message, lobe_names, token_estimate)`.

### LLM client module

- [x] T020 [P] [US1] Implement `LLMClient.__init__(self, base_url: str, api_key: str, model: str, timeout: int)` in `src/cerebrofy/llm/client.py`:
  Store `self.model = model` and `self.timeout = timeout`.
  Create `self._client = openai.OpenAI(base_url=base_url, api_key=api_key)`.
  No other logic.

- [x] T021 [US1] Implement `LLMClient._call_once(self, system_message: str, user_message: str) -> Iterator[str] | str` in `src/cerebrofy/llm/client.py` (depends on T020):
  Call `self._client.chat.completions.create(model=self.model, messages=[{"role":"system","content":system_message},{"role":"user","content":user_message}], stream=True)`.
  If the endpoint returns a non-streaming `ChatCompletion` object (detected by `isinstance`
  check), emit `"Note: streaming not supported by endpoint, buffering response."` to stderr
  and return the complete content string.
  Otherwise return the streaming iterator (a `Stream` object).

- [x] T022 [US1] Implement `LLMClient.call(self, payload: LLMContextPayload) -> str` in `src/cerebrofy/llm/client.py` (depends on T021):
  This method combines retry logic + wall-clock timeout into a single implementation.

  **Retry wrapper** (outer):
  - Call `_call_once(payload.system_message, payload.user_message)`.
  - On `openai.APIStatusError` where `status_code >= 500`, or on `openai.APIConnectionError`:
    print `f"Cerebrofy: LLM request failed ({reason}), retrying..."` to stderr.
    Retry exactly once. If retry also fails, re-raise.
  - On `openai.RateLimitError`: raise immediately (no retry).
  - On `openai.BadRequestError` (4xx): raise immediately (no retry).

  **Timeout + streaming collector** (inner — wraps the token iteration, not the call setup):
  - Create a `threading.Event` named `_timed_out`.
  - Start a `threading.Timer(self.timeout, _timed_out.set)`.
  - If `_call_once` returns a string (non-streaming): cancel timer, return string.
  - If `_call_once` returns a streaming iterator: collect tokens in a loop:
    ```python
    collected = []
    for chunk in stream:
        if _timed_out.is_set():
            timer.cancel()
            raise TimeoutError(
                f"LLM request timed out after {self.timeout}s. "
                "Increase llm_timeout in config.yaml or retry."
            )
        token = chunk.choices[0].delta.content or ""
        collected.append(token)
        print(token, end="", flush=True)  # stream to stdout
    timer.cancel()
    return "".join(collected)
    ```
  Note: the timer fires based on wall-clock time while tokens are being iterated — this covers
  the full streaming duration (from request to last token), satisfying FR-021 and research
  Decision 6.

### cerebrofy specify command

- [x] T023 [P] [US1] Implement `_resolve_output_path(specs_dir: Path, now: datetime) -> Path` in `src/cerebrofy/commands/specify.py`:
  Format timestamp as `now.strftime("%Y-%m-%dT%H-%M-%S")`.
  Build base path `specs_dir / f"{timestamp}_spec.md"`.
  If file exists, try suffix `_2`, `_3`, ... until a non-existent path is found.
  Return the resolved `Path` object. Do NOT create the file.

- [x] T024 [P] [US1] Implement `_print_search_summary(result: HybridSearchResult, model: str)` in `src/cerebrofy/commands/specify.py`:
  Write to stderr (using `click.echo(..., err=True)`):
  ```
  Cerebrofy: Hybrid search — {N} neurons matched, {M} lobes affected
    · {name} ({file}) — score {similarity:.2f}     (one line per matched neuron)
  Cerebrofy: Affected lobes: {lobe1}, {lobe2}, ...
  Cerebrofy: Calling LLM ({model})...
  ```

- [x] T025 [P] [US1] Implement `_validate_specify_prerequisites(config, db_meta: dict) -> None` in `src/cerebrofy/commands/specify.py`:
  Check in order:
  1. `config.llm_endpoint` non-empty → else raise `click.UsageError("Missing config key: llm_endpoint")`.
  2. `config.llm_model` non-empty → else raise `click.UsageError("Missing config key: llm_model")`.
  3. Derive expected env var name from endpoint URL:
     - Contains `"openai"` → `OPENAI_API_KEY`
     - Fallback for any other provider → `LLM_API_KEY`
     (Document this mapping in a code comment. Users on non-OpenAI providers must set `LLM_API_KEY`.)
     Check `os.environ` → else raise `click.UsageError(f"Missing environment variable: {var_name}")`.
  4. If `config.system_prompt_template` is non-empty and the resolved path does not exist on disk:
     raise `click.UsageError(f"Error: system_prompt_template file not found: {path}")`.
  5. Check `db_meta["embed_model"]` matches `config.embedding_model` → else raise
     `click.UsageError(f"Embedding model mismatch: index was built with {db_meta['embed_model']}, "
     f"config says {config.embedding_model}. Run 'cerebrofy build' to rebuild.")`.
     (This early exit prevents the more opaque `ValueError` from `hybrid_search` for specify.)

- [x] T026 [US1] Implement `specify` click command in `src/cerebrofy/commands/specify.py` (depends on T023–T025, T013, T014, T019, T022):
  ```python
  @click.command()
  @click.argument("description")
  @click.option("--top-k", default=None, type=int, help="Override KNN top-k for this run")
  def specify(description, top_k):
  ```
  Steps:
  1. Check `description` non-empty → else `click.echo("Description must not be empty.", err=True); sys.exit(1)`.
  2. Load config via `load_config()`.
  3. Check `cerebrofy.db` exists → else exit 1: `"No index found. Run 'cerebrofy build' first."`.
  4. Open DB (read-only), read `schema_version`, `embed_model`, `state_hash` from `meta`; close DB.
  5. Schema version check → else exit 1: `"Schema version mismatch. Run 'cerebrofy migrate' to upgrade."`.
  6. Call `_validate_specify_prerequisites(config, db_meta)` (handles embed_model, llm config, API key, template).
  7. If current `state_hash` ≠ computed SHA-256 of working tree → emit non-blocking stderr:
     `"Warning: Index may be out of sync. Run 'cerebrofy update' for current results."`
  8. `effective_top_k = top_k or config.top_k or 10`.
  9. Call `_embed_query(description, config)` → `embedding` (bytes, pre-computed BEFORE DB open).
  10. Call `hybrid_search(query=description, db_path=..., embedding=embedding, top_k=effective_top_k, config_embed_model=config.embedding_model, lobe_dir=...)` → `result`.
  11. If `len(result.matched_neurons) == 0`: print `"Cerebrofy: No relevant code units found for this description."` → exit 0 (no LLM call, no file write).
  12. Call `build_llm_context(result, config.system_prompt_template, repo_root)` → `payload`.
  13. Call `_print_search_summary(result, config.llm_model)` (to stderr).
  14. Create `LLMClient(config.llm_endpoint, api_key, config.llm_model, config.llm_timeout)`.
  15. Call `client.call(payload)` inside try/except:
      - `TimeoutError` → exit 1: `f"Error: LLM request timed out after {config.llm_timeout}s. Increase llm_timeout in config.yaml or retry."`
      - `openai.RateLimitError` → exit 1: `"Error: LLM rate limit exceeded (HTTP 429). Wait and retry."`
      - Any other error → exit 1 with error message. Never write partial file.
  16. `full_response = client.call(payload)` — already streamed to stdout by `LLMClient.call` (step 15 above).
  17. Resolve output path via `_resolve_output_path`. Create `docs/cerebrofy/specs/` if absent.
  18. Write `full_response` to file.
  19. Print output file path as final stdout line. Exit 0.

- [x] T027 [US1] Register `specify` command in `src/cerebrofy/cli.py`:
  Add `from cerebrofy.commands.specify import specify` import and `cli.add_command(specify)`.

**Checkpoint**: `cerebrofy specify "..."` runs end-to-end against a real index and LLM endpoint.

---

## Phase 4: User Story 2 — `cerebrofy plan` (Priority: P2)

**Goal**: Fully offline Markdown/JSON impact report from hybrid search. No LLM.

**Independent Test**: Run `cerebrofy plan "add user authentication"` with no network access.
Confirm Markdown output with 4 sections, exit 0. Run with `--json` and confirm valid JSON
with all required fields.

- [x] T028 [P] [US2] Implement `_format_plan_markdown(result: HybridSearchResult) -> str` in `src/cerebrofy/commands/plan.py`:
  Build a Markdown string with these sections:
  - `# Cerebrofy Plan: {result.query}`
  - `## Matched Neurons` — Markdown table: columns `#`, `Name`, `File`, `Line`, `Similarity` (2 dp). One row per `MatchedNeuron` in order.
  - `## Blast Radius (depth-2 neighbors)` — Markdown table: columns `Name`, `File`, `Line`. One row per `BlastRadiusNeuron`.
  - `## RUNTIME_BOUNDARY Warnings` (omit section entirely if no warnings) — bullet list: `- {src_name} ({src_file}) → unresolvable cross-language call`.
  - `## Affected Lobes` — Markdown table: columns `Lobe`, `File`. One row per entry in `affected_lobe_files` sorted by lobe name.
  - `## Re-index Scope` — `Estimated **{reindex_scope} nodes** would need re-indexing for changes in this area.`

- [x] T029 [P] [US2] Implement `_format_plan_json(result: HybridSearchResult) -> str` in `src/cerebrofy/commands/plan.py`:
  Build a dict:
  ```python
  {
    "schema_version": 1,
    "matched_neurons": [
      {"id": n.id, "name": n.name, "file": n.file, "line_start": n.line_start,
       "similarity": round(n.similarity, 2)}
      for n in result.matched_neurons
    ],
    "blast_radius": [
      {"id": n.id, "name": n.name, "file": n.file, "line_start": n.line_start}
      for n in result.blast_radius
    ],
    "affected_lobes": sorted(list(result.affected_lobes)),
    "reindex_scope": result.reindex_scope,
  }
  ```
  Return `json.dumps(d, indent=2)`. All four array fields MUST always be present (empty list
  `[]` if no results). `schema_version` must always be present.

- [x] T030 [US2] Implement `plan` click command in `src/cerebrofy/commands/plan.py` (depends on T028, T029, T013, T014):
  ```python
  @click.command()
  @click.argument("description")
  @click.option("--top-k", default=None, type=int, help="Override KNN top-k for this run")
  @click.option("--json", "output_json", is_flag=True, default=False, help="Output machine-readable JSON")
  def plan(description, top_k, output_json):
  ```
  Steps:
  1. Check `description` non-empty → else exit 1 `"Description must not be empty."`.
  2. Check `cerebrofy.db` exists → else exit 1 `"No index found. Run 'cerebrofy build' first."`.
  3. Open DB (read-only), check schema version; close DB. Exit 1 on mismatch.
  4. Load config. `effective_top_k = top_k or config.top_k or 10`.
  5. Call `_embed_query(description, config)` → `embedding`.
  6. Call `hybrid_search(query=description, ...)` → `result`.
  7. If `len(result.matched_neurons) == 0`: print `"Cerebrofy: No relevant code units found for this description."` → exit 0.
  8. If `output_json`: print `_format_plan_json(result)` to stdout only (no decorative text; warnings go to stderr).
     Else: print `_format_plan_markdown(result)` to stdout.
  9. Exit 0.

- [x] T031 [US2] Register `plan` command in `src/cerebrofy/cli.py`:
  Add `from cerebrofy.commands.plan import plan` import and `cli.add_command(plan)`.

**Checkpoint**: `cerebrofy plan "..."` and `cerebrofy plan --json "..."` work offline against a valid index.

---

## Phase 5: User Story 3 — `cerebrofy tasks` (Priority: P3)

**Goal**: Numbered Markdown task list from hybrid search. No LLM.

**Independent Test**: Run `cerebrofy tasks "add user authentication"` against a valid index.
Confirm output is a numbered Markdown list where each item follows the exact format
`N. Modify {name} in [[{lobe}]] ({file}:{line}) — blast radius: {count} nodes`. Exit 0.

- [x] T032 [P] [US3] Add `TaskItem` frozen dataclass to `src/cerebrofy/commands/tasks.py`:
  fields `index: int`, `neuron: MatchedNeuron`, `lobe_name: str`, `blast_count: int`.
  Use `@dataclass(frozen=True)`.
  Note: `blast_count` is the total blast radius count (i.e., `len(result.blast_radius)`) shared
  across all task items. This is consistent with spec FR-008 — "blast radius: {count} nodes"
  refers to the total structural blast, not a per-neuron sub-count.

- [x] T033 [US3] Implement `_build_task_items(result: HybridSearchResult) -> tuple[list[TaskItem], list[str]]` in `src/cerebrofy/commands/tasks.py` (depends on T032):
  - `blast_count = len(result.blast_radius)` (total blast radius, same value for all items).
  - For each `MatchedNeuron` in `result.matched_neurons` (already ordered by descending similarity):
    Derive `lobe_name` by matching `neuron.file` against `result.affected_lobe_files` keys
    (lobe name is the first path component of the file, same derivation as `_resolve_affected_lobes`).
    If no matching lobe found, use `"(unassigned)"`.
    Append `TaskItem(index=i+1, neuron=n, lobe_name=lobe_name, blast_count=blast_count)`.
  - Build RUNTIME_BOUNDARY note strings for each `w` in `result.runtime_boundary_warnings`:
    `f"Note: {w.src_name} has unresolvable cross-language calls — see RUNTIME_BOUNDARY entries in [[{w.lobe_name}]]."`
  - Return `(task_items, note_strings)`.

- [x] T034 [P] [US3] Implement `_format_tasks_markdown(items: list[TaskItem], notes: list[str], description: str) -> str` in `src/cerebrofy/commands/tasks.py`:
  Header: `f"# Cerebrofy Tasks: {description}\n\n"`.
  For each `TaskItem`:
    Append `f"{item.index}. Modify {item.neuron.name} in [[{item.lobe_name}]] ({item.neuron.file}:{item.neuron.line_start}) — blast radius: {item.blast_count} nodes\n"`.
  If `notes` is non-empty: append `"\n"` then each note on its own line.
  Return the full string.

- [x] T035 [US3] Implement `tasks` click command in `src/cerebrofy/commands/tasks.py` (depends on T032–T034, T013, T014):
  ```python
  @click.command()
  @click.argument("description")
  @click.option("--top-k", default=None, type=int, help="Override KNN top-k for this run")
  def tasks(description, top_k):
  ```
  Steps:
  1. Check `description` non-empty → else exit 1 `"Description must not be empty."`.
  2. Check `cerebrofy.db` exists → else exit 1 `"No index found. Run 'cerebrofy build' first."`.
  3. Open DB (read-only), check schema version; close DB. Exit 1 on mismatch.
  4. Load config. `effective_top_k = top_k or config.top_k or 10`.
  5. Call `_embed_query(description, config)` → `embedding`.
  6. Call `hybrid_search(query=description, ...)` → `result`.
  7. If `len(result.matched_neurons) == 0`: print `"Cerebrofy: No relevant code units found for this description."` → exit 0.
  8. Call `_build_task_items(result)` → `(items, notes)`.
  9. Print `_format_tasks_markdown(items, notes, description)` to stdout.
  10. Exit 0.

- [x] T036 [US3] Register `tasks` command in `src/cerebrofy/cli.py`:
  Add `from cerebrofy.commands.tasks import tasks` import and `cli.add_command(tasks)`.

**Checkpoint**: All three commands (`specify`, `plan`, `tasks`) are registered and functional.

---

## Phase 6: Tests

**Purpose**: Verify correctness of the hybrid search kernel and each command in isolation.

### Unit tests

- [x] T037 Write unit tests for `_run_knn_query` in `tests/unit/test_hybrid_search.py`:
  Set up an in-memory SQLite DB with a mock `vec_neurons` table (stub sqlite-vec, or skip vec_neurons
  and test with a patched `_run_knn_query` that uses a simple numeric column for distance).
  Assert `MatchedNeuron.similarity = 1 - distance/2`, fields match DB rows, ordering is descending.

- [x] T038 Write unit tests for `_run_bfs` (RUNTIME_BOUNDARY exclusion) in `tests/unit/test_hybrid_search.py`:
  Set up `edges` table with one regular edge and one `RUNTIME_BOUNDARY` edge.
  Assert: regular neighbor appears in `blast_radius`; RUNTIME_BOUNDARY edge produces a
  `RuntimeBoundaryWarning`; neighbor from RUNTIME_BOUNDARY edge is NOT in `blast_radius`.

- [x] T039 Write unit tests for `hybrid_search` (embed_model mismatch + zero results) in `tests/unit/test_hybrid_search.py`:
  - embed_model mismatch: set `meta.embed_model = "model-a"`, call with `config_embed_model = "model-b"`.
    Assert `ValueError` is raised before any query executes.
  - Zero results: mock `_run_knn_query` to return `[]`. Assert returned `HybridSearchResult` has
    empty `matched_neurons`, `reindex_scope == 0`, `blast_radius` empty.

- [x] T040 [P] Write unit tests for `_load_template` in `tests/unit/test_prompt_builder.py`:
  - Call with `template_path=None` → assert returns `string.Template` wrapping `DEFAULT_SYSTEM_PROMPT`.
  - Call with a valid file path (use `tmp_path`) → assert reads file content.
  - Call with a non-existent path → assert `FileNotFoundError` is raised.

- [x] T041 Write unit tests for `_build_lobe_context` in `tests/unit/test_prompt_builder.py`:
  - Empty dict → returns `""`.
  - Two lobe files (use `tmp_path`) → assert output contains both lobe headers in alphabetical order.
  - Missing lobe file → assert that lobe is silently skipped (no error, no content).

- [x] T042 [P] Write unit tests for `LLMClient.call` retry behavior in `tests/unit/test_llm_client.py`:
  Mock `_call_once` to raise `openai.APIStatusError` (status=500) on first call, succeed on second.
  Assert: call returns result, stderr contains "retrying..." message.
  Mock to raise `openai.RateLimitError` → assert no retry, error propagates immediately.
  Mock to raise `openai.BadRequestError` (400) → assert no retry, error propagates immediately.

- [x] T043 [P] Write unit tests for `LLMClient.call` timeout in `tests/unit/test_llm_client.py`:
  Set `timeout=1` (1 second). Mock `_call_once` to return a generator that sleeps 2 seconds
  before yielding. Assert `TimeoutError` is raised with the correct message. Assert no partial
  result is returned and no output file exists (caller catches the error).

- [x] T044 [P] Write unit tests for `_format_plan_json` in `tests/unit/test_plan_command.py`:
  Build a minimal `HybridSearchResult` (via `query="test"`, 1 matched neuron, 1 blast neuron).
  Assert JSON output: `schema_version=1`, all 4 array fields present, `similarity` rounded to 2dp.
  Call again with empty blast_radius → assert `blast_radius` key is `[]` (not absent).

- [x] T045 [P] Write unit tests for `_build_task_items` in `tests/unit/test_tasks_command.py`:
  Build a `HybridSearchResult` with 2 matched neurons (different similarities) and 1 RUNTIME_BOUNDARY warning.
  Assert: `items` has 2 entries ordered by descending similarity; `blast_count` equals
  `len(result.blast_radius)` for all items; note strings list has 1 entry with the expected format.

### Integration tests

- [x] T046 [P] Write integration test for `cerebrofy specify` (happy path + SC-002 check) in `tests/integration/test_specify_command.py`:
  Use `tmp_path` fixture to create a minimal valid `cerebrofy.db` with 2 nodes. Mock the openai
  SDK to return a streaming response `["Hello ", "world"]`. Invoke `specify` via `click.testing.CliRunner`.
  Assert: exit code 0; a `.md` file exists in `docs/cerebrofy/specs/`; file content is "Hello world";
  stdout final line is the absolute file path.
  **SC-002 check**: parse the mock LLM response for any `file::name` patterns or explicit code
  references; assert each referenced Neuron name exists in the `nodes` table. (This verifies that
  the grounding design works — only lobe context injected, no hallucinated IDs can appear from
  a mock that echoes back the input.)

- [x] T047 Write integration test for `cerebrofy specify` error cases in `tests/integration/test_specify_command.py`:
  - Missing API key → exit 1, message names the environment variable.
  - Empty description → exit 1, message `"Description must not be empty."`.
  - Zero KNN results → exit 0, no file written, message `"No relevant code units found"`.
  - LLM timeout (mock that sleeps > `llm_timeout`) → exit 1, no file written, timeout message.
  - State_hash mismatch → exit 0 (spec still written), stderr contains `"Warning: Index may be out of sync."`.

- [x] T048 [P] Write integration test for `cerebrofy plan` in `tests/integration/test_plan_command.py`:
  Use `tmp_path` + valid `cerebrofy.db`. Run via `CliRunner`.
  - Default Markdown: assert output contains `## Matched Neurons`, `## Blast Radius`, `## Affected Lobes`, `## Re-index Scope`.
  - Header: assert output starts with `# Cerebrofy Plan: add user authentication` (query propagated).
  - `--json` flag: parse output as JSON; assert all 4 fields present + `schema_version=1`; assert no non-JSON text on stdout.
  - `--top-k 1`: assert at most 1 matched neuron row in output.
  - No network calls: run with no internet access (mock embedder + use in-memory DB).

- [x] T049 [P] Write integration test for `cerebrofy tasks` in `tests/integration/test_tasks_command.py`:
  Use `tmp_path` + valid `cerebrofy.db`. Run via `CliRunner`.
  - Assert output starts with `# Cerebrofy Tasks: add user authentication`.
  - Assert each numbered item matches regex `^\d+\. Modify .+ in \[\[.+\]\] \(.+:\d+\) — blast radius: \d+ nodes$`.
  - RUNTIME_BOUNDARY edge in DB: assert a `Note:` line appears after the numbered list (not in it).
  - `--top-k 1`: assert exactly 1 task item.

- [x] T050 Write integration test for read-only invariant (FR-020) in `tests/integration/test_plan_command.py`:
  Record the file modification time of `cerebrofy.db` before running `cerebrofy plan` and
  `cerebrofy tasks`. Assert the modification time is unchanged after each command completes.
  (Guarantees no accidental writes to the index during search.)

---

## Phase 7: Polish & Cross-Cutting Concerns

- [x] T051 [P] Verify `cerebrofy plan`, `cerebrofy tasks`, `cerebrofy specify` appear in `cerebrofy --help` output. Check `cli.py` command registration. Add `help=` strings to Click decorators for all three commands if not already present.

- [x] T052 Run `ruff check src/cerebrofy/search/ src/cerebrofy/llm/ src/cerebrofy/commands/specify.py src/cerebrofy/commands/plan.py src/cerebrofy/commands/tasks.py` and fix any reported lint errors.

- [x] T053 Run `mypy src/cerebrofy/search/ src/cerebrofy/llm/ src/cerebrofy/commands/specify.py src/cerebrofy/commands/plan.py src/cerebrofy/commands/tasks.py` and fix any type errors.

- [x] T054 Validate SC-003 (plan/tasks parity): add a test to `tests/integration/test_plan_command.py` that runs `cerebrofy plan` and `cerebrofy tasks` with the same description + `--top-k` on the same index. Assert matched Neuron IDs and blast radius IDs are identical in both outputs.

- [x] T055 Validate SC-001 (hybrid search < 50ms): add a timing assertion to `tests/unit/test_hybrid_search.py` that calls `hybrid_search()` on a 1,000-node in-memory DB (no sqlite-vec KNN needed — mock `_run_knn_query` to return 10 results) and asserts `result.search_duration_ms < 50`.

- [x] T056 Validate SC-004 (first token within 3s): in `tests/integration/test_specify_command.py`, add a mock LLM that introduces a 2-second delay before returning the first token. Assert the wall-clock time from `CliRunner.invoke()` to first stdout character is < 3 seconds. Document that this test verifies streaming path only (excludes cold embedder load, per SC-004 exemption).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS Phases 3, 4, 5
- **Phase 3 (US1 — specify)**: Depends on Phase 2 — builds LLM layer on top of `hybrid_search`
- **Phase 4 (US2 — plan)**: Depends on Phase 2 only — can run in parallel with Phase 3
- **Phase 5 (US3 — tasks)**: Depends on Phase 2 only — can run in parallel with Phases 3 and 4
- **Phase 6 (Tests)**: Unit tests for Phase 2 modules can start as soon as Phase 2 is complete;
  integration tests depend on Phases 3–5
- **Phase 7 (Polish)**: Depends on Phase 6

### User Story Dependencies

- **US1 (specify)**: Requires `hybrid_search` + `_embed_query` + LLM client + prompt builder
- **US2 (plan)**: Requires `hybrid_search` + `_embed_query` only — no LLM layer
- **US3 (tasks)**: Requires `hybrid_search` + `_embed_query` only — no LLM layer

### Within Each User Story (US1)

- T015–T018 (prompt builder data structures + helpers): all parallel
- T019 (`build_llm_context`): depends on T015–T018
- T020 (`LLMClient.__init__`): parallel with T015–T018
- T021 (`_call_once`): depends on T020
- T022 (`LLMClient.call` — retry + timeout combined): depends on T021
- T023–T025 (specify helpers): all parallel
- T026 (`specify` command body): depends on T023–T025, T019, T022
- T027 (cli.py registration): depends on T026

### Within Each User Story (US2)

- T028 (`_format_plan_markdown`) and T029 (`_format_plan_json`): parallel
- T030 (`plan` command): depends on T028, T029
- T031 (cli.py registration): depends on T030

### Within Each User Story (US3)

- T032 (dataclass) and T034 (formatter): parallel
- T033 (`_build_task_items`): depends on T032
- T035 (`tasks` command): depends on T032–T034
- T036 (cli.py registration): depends on T035

### Parallel Opportunities

- Phase 2 data structures (T004–T006): all parallel
- Phase 3 prompt builder helpers (T015–T018): all parallel
- Phase 4 formatters (T028–T029): parallel
- Phase 5 dataclass + formatter (T032, T034): parallel
- Unit tests in different files: T037 (test_hybrid_search.py), T040 (test_prompt_builder.py), T042–T043 (test_llm_client, test_plan), T044–T045 (test_tasks) — all [P]
- Integration tests in different files: T046, T048, T049 — all [P]

---

## Implementation Strategy

### MVP First (User Story 1 — cerebrofy specify)

1. Phase 1: Create package dirs + config fields (T001–T003)
2. Phase 2: Build `hybrid_search()` kernel (T004–T014)
3. Phase 3: Build LLM layer + `cerebrofy specify` (T015–T027)
4. **STOP and VALIDATE**: Run against real index + LLM endpoint
5. `cerebrofy plan` and `cerebrofy tasks` add value but are not needed for MVP

### Incremental Delivery

1. Phase 1 + Phase 2 → `hybrid_search()` works ← minimal viable kernel
2. + Phase 4 (US2) → `cerebrofy plan` works ← zero LLM dependency, immediately useful offline
3. + Phase 5 (US3) → `cerebrofy tasks` works ← same offline, formatted differently
4. + Phase 3 (US1) → `cerebrofy specify` works ← requires LLM endpoint
5. + Phase 6 → full test coverage
6. + Phase 7 → production-ready

### Parallel Team Strategy

- Developer A: Phase 2 (hybrid search kernel) — blocks others, priority
- Developer B: Phase 3 LLM layer (T015–T022) — starts once Phase 2 completes
- Developer C: Phase 4 + Phase 5 (plan + tasks formatters) — starts once Phase 2 completes

---

## Notes

- Each task targets a single function, dataclass, or one-concern unit — sized for a simple LLM
- **`[P]`** tasks write to different files AND have no shared in-progress dependency
- **`[US1]`, `[US2]`, `[US3]`** labels enable per-story filtering when delegating to agents
- **`query` field**: `hybrid_search()` accepts `query: str` and populates `HybridSearchResult.query` — all output formatters use `result.query` for headers
- **sqlite-vec KNN**: use `WHERE embedding MATCH ? AND k = ?` syntax; bind embedding as `sqlite_vec.serialize_float32(list)`; `similarity = 1 - distance/2` normalises `[0,2]` → `[0,1]`
- **Timeout covers full streaming**: `LLMClient.call` (T022) wraps the token-iteration loop with a `threading.Timer`, not just the `create()` call
- **Config fields**: T003 adds all Phase 4 config keys before any Phase 3–5 task can reference them
- **RUNTIME_BOUNDARY constant**: import from `src/cerebrofy/graph/edges.py` (Phase 2)
- **Embedder**: use `Embedder` ABC from `src/cerebrofy/embedder/base.py` (Phase 2); never re-implement embedding logic in Phase 4
- **open_db()**: do not modify Phase 2's `db/connection.py` — call it with the read-only mode it already supports per research Decision 1
