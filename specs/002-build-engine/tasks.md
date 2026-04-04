---
description: "Task list for Phase 2 — The Build Engine"
---

# Tasks: Phase 2 — The Build Engine

**Input**: Design documents from `specs/002-build-engine/`
**Prerequisites**: plan.md ✅, spec.md ✅, data-model.md ✅, contracts/ ✅, research.md ✅

**Granularity note**: Tasks are intentionally split to one function or one file per task so
each can be executed independently by any capable LLM with only local file context.

**Tests**: Not requested — no test tasks generated.

**Organization**: Tasks grouped by user story to enable independent delivery of each story.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1–US5)
- Exact file paths included in every task description

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Extend the Phase 1 package with new dependencies and empty module stubs.
All tasks are independent.

- [x] T001 Add new dependencies to `pyproject.toml`: `sqlite-vec>=0.5`, `sentence-transformers>=2.2`, `openai>=1.0`, `cohere>=4.0`. Place them in the `[project.dependencies]` list alongside the existing Phase 1 deps.
- [x] T002 [P] Create empty `__init__.py` stubs for all new subpackages: `src/cerebrofy/db/__init__.py`, `src/cerebrofy/graph/__init__.py`, `src/cerebrofy/embedder/__init__.py`, `src/cerebrofy/markdown/__init__.py`
- [x] T003 [P] Verify `pip install -e ".[dev]"` resolves all new deps after T001; confirm `import sqlite_vec`, `import sentence_transformers`, `import openai`, `import cohere` succeed in a Python REPL. No file changes needed — this is a validation-only task.

**Checkpoint**: `pip install -e ".[dev]"` succeeds with all new packages installed.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core data types and low-level infrastructure that EVERY user story depends on.
**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Extend Phase 1 Parser Output (`src/cerebrofy/parser/neuron.py`)

The graph resolver needs raw call and import captures from the parse phase. Extend
`ParseResult` without breaking Phase 1 contracts.

- [x] T004 Add a frozen `@dataclass` named `RawCapture` to `src/cerebrofy/parser/neuron.py` with fields: `capture_name: str` (e.g., `"call"`, `"import"`), `text: str` (the literal text of the captured node), `file: str`, `line: int` (1-based). This dataclass represents a single tree-sitter capture that does not produce a Neuron.
- [x] T005 Update the `ParseResult` frozen dataclass in `src/cerebrofy/parser/neuron.py` to add field `raw_captures: tuple[RawCapture, ...] = field(default_factory=tuple)`. Use `tuple` (not `list`) to match the immutable value-object convention in CLAUDE.md (all frozen dataclass sequence fields use tuples). Preserve all existing fields (`file`, `neurons`, `warnings`). The `neurons` and `warnings` fields from Phase 1 remain as `list` unless already converted — do not change them.
- [x] T006 Update function `extract_neurons` in `src/cerebrofy/parser/engine.py` to return a `tuple[list[Neuron], tuple[RawCapture, ...]]` instead of `list[Neuron]`. For each capture returned by `query.captures(tree.root_node)`: call `map_capture_to_neuron` as before (collect non-None results into `neurons`); if the result is `None` AND `capture_name` contains `"call"` or `"import"`, create a `RawCapture(capture_name=capture_name, text=node.text.decode("utf-8"), file=file, line=node.start_point[0]+1)` and append to `raw_captures`. Return `(neurons, tuple(raw_captures))`. ALSO update `parse_file` in the same file: change the line that calls `extract_neurons` to unpack the tuple — `neurons, raw_captures = extract_neurons(...)` — and pass `raw_captures` into the returned `ParseResult`. Existing Neuron extraction behavior MUST be unchanged.

### Schema DDL (`src/cerebrofy/db/schema.py`)

- [x] T007 [P] Create `src/cerebrofy/db/schema.py` with string constants `NODES_DDL`, `EDGES_DDL`, `META_DDL`, `FILE_HASHES_DDL` containing the exact `CREATE TABLE` SQL from `contracts/db-schema.md`. Also add `NODES_INDEX_DDL` and `EDGES_INDEX_DDL` with the two `CREATE INDEX` statements.
- [x] T008 Add function `create_schema(conn: sqlite3.Connection, embed_dim: int) -> None` to `src/cerebrofy/db/schema.py`. Executes all DDL: `NODES_DDL`, `NODES_INDEX_DDL`, `EDGES_DDL`, `EDGES_INDEX_DDL`, `META_DDL`, `FILE_HASHES_DDL`, then executes the vec_neurons virtual table DDL as `f"CREATE VIRTUAL TABLE vec_neurons USING vec0(id TEXT PRIMARY KEY, embedding FLOAT[{embed_dim}])"`. Use `conn.executescript` or execute each statement individually.

### Database Connection (`src/cerebrofy/db/connection.py`)

- [x] T009 [P] Create `src/cerebrofy/db/connection.py` with function `open_db(db_path: Path) -> sqlite3.Connection`. Steps: (1) `conn = sqlite3.connect(str(db_path))`; (2) `conn.enable_load_extension(True)`; (3) `import sqlite_vec; sqlite_vec.load(conn)`; (4) `conn.enable_load_extension(False)`; (5) return `conn`. Do NOT perform a schema version check here — that is done by the caller. Enable WAL mode: `conn.execute("PRAGMA journal_mode=WAL")` before returning.
- [x] T010 Add function `check_schema_version(conn: sqlite3.Connection, expected: int = 1) -> None` to `src/cerebrofy/db/connection.py`. Executes `SELECT value FROM meta WHERE key = 'schema_version'`. If the row is missing OR the integer value does not equal `expected`, raise `ValueError(f"Schema version mismatch: expected {expected}, got {row}")`. This function is called by all commands that open an existing `cerebrofy.db`.

### Graph Edge Types (`src/cerebrofy/graph/edges.py`)

- [x] T011 [P] Create `src/cerebrofy/graph/edges.py` with: (1) string constants `LOCAL_CALL = "LOCAL_CALL"`, `EXTERNAL_CALL = "EXTERNAL_CALL"`, `IMPORT_REL = "IMPORT"`, `RUNTIME_BOUNDARY = "RUNTIME_BOUNDARY"`; (2) a frozen `@dataclass` named `Edge` with fields `src_id: str`, `dst_id: str`, `rel_type: str`, `file: str`.

### Embedder Abstract Base (`src/cerebrofy/embedder/base.py`)

- [x] T012 [P] Create `src/cerebrofy/embedder/base.py` with an abstract base class `Embedder` (inherits from `abc.ABC`). Add one abstract method: `def embed(self, texts: list[str]) -> list[list[float]]` decorated with `@abc.abstractmethod`. Add docstring: "Embed a list of text strings. Returns one float vector per input text."

**Checkpoint**: Foundation ready — `RawCapture`, updated `ParseResult`, schema DDL, `open_db`, `check_schema_version`, `Edge`, `Embedder` all importable. User story implementation can now begin.

---

## Phase 3: User Story 1 — Full Codebase Indexing (Priority: P1) 🎯 MVP

**Goal**: `cerebrofy build` parses all tracked files, writes Neurons to `nodes` table, computes
`state_hash`, stores per-file hashes, and saves an index that can be queried directly.

**Independent Test**: Run `cerebrofy build` in a `cerebrofy init`-initialized repo. Confirm:
`.cerebrofy/db/cerebrofy.db` exists; `nodes` table has rows; `file_hashes` table has rows;
all 5 meta keys present; `state_hash` is identical on a second run with unchanged files.
US1 does NOT yet include edges, vectors, or Markdown — those are US2–US4.

### DB Writer — Node and Hash Functions (`src/cerebrofy/db/writer.py`)

- [ ] T013 [P] [US1] Create `src/cerebrofy/db/writer.py` with function `insert_meta(conn: sqlite3.Connection, embed_model: str, embed_dim: int) -> None`. Executes three `INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)` statements for: `('schema_version', '1')`, `('embed_model', embed_model)`, `('embed_dim', str(embed_dim))`.
- [ ] T014 [US1] Add function `write_nodes(conn: sqlite3.Connection, neurons: list) -> None` to `src/cerebrofy/db/writer.py`. For each `Neuron n`, compute `node_hash = hashlib.sha256(f"{n.name}:{n.line_start}:{n.line_end}".encode()).hexdigest()`. This is the canonical `nodes.hash` formula (a deterministic fingerprint of the node's identity metadata, not the raw source bytes — the db-schema contract comment is updated to match). Executes `conn.executemany("INSERT OR REPLACE INTO nodes(id,name,file,type,line_start,line_end,signature,docstring,hash) VALUES (?,?,?,?,?,?,?,?,?)", rows)` where `rows` is a list of tuples built from each Neuron's fields plus `node_hash`.
- [ ] T015 [US1] Add function `compute_file_hash(file_path: Path) -> str` to `src/cerebrofy/db/writer.py`. Reads `file_path.read_bytes()` and returns `hashlib.sha256(content).hexdigest()`.
- [ ] T016 [US1] Add function `compute_state_hash(file_hash_map: dict[str, str]) -> str` to `src/cerebrofy/db/writer.py`. Implements the formula from `contracts/db-schema.md`: `SHA-256("\n".join(sorted(file_hash_map.values())).encode()).hexdigest()`.
- [ ] T017 [US1] Add function `write_file_hashes(conn: sqlite3.Connection, file_hash_map: dict[str, str]) -> None` to `src/cerebrofy/db/writer.py`. Executes `conn.executemany("INSERT OR REPLACE INTO file_hashes(file, hash) VALUES (?, ?)", file_hash_map.items())`.
- [ ] T018 [US1] Add function `write_build_meta(conn: sqlite3.Connection, state_hash: str) -> None` to `src/cerebrofy/db/writer.py`. Executes two `INSERT OR REPLACE INTO meta` statements: `('state_hash', state_hash)` and `('last_build', datetime.utcnow().isoformat() + 'Z')`.

### Build Orchestrator — Steps 0, 1, 6 (`src/cerebrofy/commands/build.py`)

- [ ] T019 [P] [US1] Create `src/cerebrofy/commands/build.py` with function `build_step0_create_db(db_path: Path, embed_model: str, embed_dim: int) -> sqlite3.Connection`. Creates parent directory if needed. Calls `open_db(db_path)`. Calls `create_schema(conn, embed_dim)`. Calls `insert_meta(conn, embed_model, embed_dim)`. Returns the open connection. (In US1, writes directly to `db_path` — the `.tmp` pattern is added in US5.)
- [ ] T020 [US1] Add function `build_step1_parse(root: Path, config, ignore_rules) -> list` to `src/cerebrofy/commands/build.py`. Calls `parse_directory(root, config, ignore_rules)` from `src/cerebrofy/parser/engine.py` which returns a complete `list[ParseResult]`. Print `"Cerebrofy: Step 1/6 — Parsing source files (0 / N files)"` before the call (using `len()` from a pre-scan of tracked files for N), then `"Cerebrofy: Step 1/6 — Parsing source files (N / N files)"` after it completes. (Two prints only — not per-100-file — because `parse_directory` is a batch function with no callback.) After calling `parse_directory`, iterate the results: for each `ParseResult pr`, for each warning in `pr.warnings`, print `f"Warning: {warning}"` to `sys.stderr`. Returns the list of `ParseResult` objects.
- [ ] T021 [US1] Add function `build_step6_commit(conn: sqlite3.Connection, root: Path, config, ignore_rules) -> str` to `src/cerebrofy/commands/build.py`. Walks all tracked files by reusing `parse_directory`'s file-selection logic: iterate files under `root`, skip if `ignore_rules.matches(rel_path)`, skip if extension not in `config.tracked_extensions`. Build `file_hash_map: dict[str, str]` using `compute_file_hash` for each matched file. Calls `write_file_hashes(conn, file_hash_map)`. Computes `state_hash = compute_state_hash(file_hash_map)`. Calls `write_build_meta(conn, state_hash)`. Calls `conn.commit()`. Returns `state_hash`. Prints `"Cerebrofy: Step 6/6 — Committing index (state_hash: {state_hash[:16]}...)"`. **Note**: `ignore_rules` parameter is required so that `file_hash_map` covers exactly the same file set as Step 1 (SC-002 determinism).
- [ ] T022 [US1] Add `@click.command("build")` function `cerebrofy_build` to `src/cerebrofy/commands/build.py`. No options. Steps: (1) check `.cerebrofy/config.yaml` exists, else `click.echo("Error: ...", err=True); sys.exit(1)`; (2) load config via `load_config`; (3) create `IgnoreRuleSet.from_directory(root)`; (4) print `"Cerebrofy: Starting build..."`; (5) call `build_step0_create_db(db_path, config.embedding_model, config.embed_dim)` where `db_path = root / ".cerebrofy/db/cerebrofy.db"`; (6) call `build_step1_parse` → get `parse_results`; (7) call `write_nodes(conn, all_neurons_from_parse_results)`; (8) call `build_step6_commit(conn, root, config, ignore_rules)`; (9) print `"Cerebrofy: Build complete. Indexed {N} neurons across {M} files in {X.X}s."`.
- [ ] T023 [US1] Import `cerebrofy_build` from `src/cerebrofy/commands/build.py` and register it in `src/cerebrofy/cli.py` using `main.add_command(cerebrofy_build)`.

**Checkpoint**: `cerebrofy build` runs end-to-end. `cerebrofy.db` has populated `nodes`, `file_hashes`, and all 5 `meta` keys. Running twice produces the same `state_hash`.

---

## Phase 4: User Story 2 — Call Graph Construction (Priority: P2)

**Goal**: `cerebrofy build` additionally resolves intra-file calls, cross-module calls, and
import links, storing them as typed edges in the `edges` table.

**Independent Test**: After `cerebrofy build` on a repo with known function calls, query
`SELECT * FROM edges LIMIT 10` — at least one `LOCAL_CALL` edge exists. Check that
`RUNTIME_BOUNDARY` edges exist for external library calls.

### Graph Resolver (`src/cerebrofy/graph/resolver.py`)

- [ ] T024 [P] [US2] Create `src/cerebrofy/graph/resolver.py` with function `build_name_registry(parse_results: list) -> dict[str, list]`. Iterates all Neurons from all `ParseResult.neurons`. Returns `dict[name → list[Neuron]]` mapping each `neuron.name` to all Neurons with that name across all files.
- [ ] T025 [US2] Add function `find_containing_neuron(neurons: list, line: int) -> str | None` to `src/cerebrofy/graph/resolver.py`. Given a list of Neurons from one file and a line number, returns the `id` of the Neuron whose `[line_start, line_end]` range contains that line. Returns `None` if no Neuron contains the line. Used to determine which Neuron is the "caller" for a given call expression.
- [ ] T026 [US2] Add function `resolve_local_edges(parse_result, name_registry: dict) -> list` to `src/cerebrofy/graph/resolver.py`. For each `RawCapture` in `parse_result.raw_captures` where `capture_name` contains `"call"`: (1) get `callee_name = capture.text.split("(")[0].strip()`; (2) call `find_containing_neuron(parse_result.neurons, capture.line)` to get `caller_id`; (3) look up `callee_name` in `name_registry`; (4) if a matching Neuron exists in the SAME file (`neuron.file == parse_result.file`) AND `caller_id` is not None → append `Edge(src_id=caller_id, dst_id=match.id, rel_type=LOCAL_CALL, file=parse_result.file)`. Return list of `Edge` objects.
- [ ] T027 [US2] Add function `resolve_cross_module_edges(parse_result, name_registry: dict) -> list` to `src/cerebrofy/graph/resolver.py`. Same iteration as T026 but for callees NOT in the same file: (1) if callee found in registry in a DIFFERENT file → `Edge(..., rel_type=EXTERNAL_CALL)`; (2) if callee NOT in registry at all → create a synthetic `dst_id = f"external::{callee_name}"` → `Edge(..., rel_type=RUNTIME_BOUNDARY)`. Return list of `Edge` objects.
- [ ] T028 [US2] Add function `resolve_import_edges(parse_result, name_registry: dict) -> list` to `src/cerebrofy/graph/resolver.py`. For each `RawCapture` in `parse_result.raw_captures` where `capture_name` contains `"import"`: extract the imported name from `capture.text` (split on `import` keyword, take the last token); look up in `name_registry`; if found in a different file → `Edge(src_id=file_module_neuron_id, dst_id=match.id, rel_type=IMPORT_REL, file=parse_result.file)`. Return list of `Edge` objects.

### DB Writer — Edge Write (`src/cerebrofy/db/writer.py`)

- [ ] T029 [US2] Add function `write_edges(conn: sqlite3.Connection, edges: list) -> None` to `src/cerebrofy/db/writer.py`. Executes `conn.executemany("INSERT OR IGNORE INTO edges(src_id, dst_id, rel_type, file) VALUES (?, ?, ?, ?)", [(e.src_id, e.dst_id, e.rel_type, e.file) for e in edges])`.

### Build Orchestrator — Steps 2 and 3 (`src/cerebrofy/commands/build.py`)

- [ ] T030 [US2] Add function `build_step2_local_graph(conn: sqlite3.Connection, parse_results: list, name_registry: dict) -> None` to `src/cerebrofy/commands/build.py`. For each `ParseResult`: calls `resolve_local_edges(pr, name_registry)`, accumulates edges. Calls `write_edges(conn, all_edges)`. Prints `"Cerebrofy: Step 2/6 — Building local call graph"`.
- [ ] T031 [US2] Add function `build_step3_cross_module_graph(conn: sqlite3.Connection, parse_results: list, name_registry: dict) -> None` to `src/cerebrofy/commands/build.py`. For each `ParseResult`: calls `resolve_cross_module_edges(pr, name_registry)` and `resolve_import_edges(pr, name_registry)`, accumulates all edges. Calls `write_edges(conn, all_edges)`. Prints `"Cerebrofy: Step 3/6 — Resolving cross-module calls"`.
- [ ] T032 [US2] Update `cerebrofy_build` in `src/cerebrofy/commands/build.py` to insert Steps 2 and 3 between the `write_nodes` call and `build_step6_commit`. After `write_nodes`: (1) call `build_name_registry(parse_results)` from `graph/resolver.py`; (2) call `build_step2_local_graph(conn, parse_results, name_registry)`; (3) call `build_step3_cross_module_graph(conn, parse_results, name_registry)`.

**Checkpoint**: `cerebrofy build` completes. `SELECT COUNT(*) FROM edges` returns > 0 for any repo with function calls.

---

## Phase 5: User Story 3 — Semantic Search Readiness (Priority: P3)

**Goal**: Every Neuron in `nodes` has a corresponding vector in `vec_neurons` after build.

**Independent Test**: After `cerebrofy build`, verify `SELECT COUNT(*) FROM nodes` equals
`SELECT COUNT(*) FROM vec_neurons`. Changing `embedding_model` in `config.yaml` and rebuilding
produces new vectors at the new dimension with no error.

### Embedder Implementations

- [ ] T033 [P] [US3] Create `src/cerebrofy/embedder/local.py` with class `LocalEmbedder(Embedder)`. Constructor: `self.model = SentenceTransformer("nomic-ai/nomic-embed-text-v1")` (import from `sentence_transformers`). Method `embed(self, texts: list[str]) -> list[list[float]]`: calls `self.model.encode(texts, batch_size=64, show_progress_bar=False)` and returns `[vec.tolist() for vec in result]`.
- [ ] T034 [P] [US3] Create `src/cerebrofy/embedder/openai_emb.py` with class `OpenAIEmbedder(Embedder)`. Constructor: `self.client = openai.OpenAI()` (reads `OPENAI_API_KEY` from env automatically). Method `embed(self, texts: list[str]) -> list[list[float]]`: split `texts` into chunks of 512; for each chunk call `self.client.embeddings.create(model="text-embedding-3-small", input=chunk)`; extract `.data[i].embedding` for each item; concatenate and return full list.
- [ ] T035 [P] [US3] Create `src/cerebrofy/embedder/cohere_emb.py` with class `CohereEmbedder(Embedder)`. Constructor: `self.co = cohere.Client(os.environ["COHERE_API_KEY"])`. Method `embed(self, texts: list[str]) -> list[list[float]]`: split `texts` into chunks of 96; for each chunk call `self.co.embed(texts=chunk, model="embed-english-v3.0", input_type="search_document")`; extract `.embeddings`; concatenate and return full list.
- [ ] T036 [US3] Add function `get_embedder(embedding_model: str) -> Embedder` to `src/cerebrofy/embedder/__init__.py`. Returns `LocalEmbedder()` if `embedding_model == "local"`, `OpenAIEmbedder()` if `"openai"`, `CohereEmbedder()` if `"cohere"`. Raises `ValueError(f"Unknown embedding model: {embedding_model}")` for any other value.

### DB Writer — Vector Upsert (`src/cerebrofy/db/writer.py`)

- [ ] T037 [US3] Add function `build_neuron_text(neuron) -> str` to `src/cerebrofy/db/writer.py`. Returns `f"{neuron.name}: {neuron.signature or ''} {neuron.docstring or ''}".strip()` truncated to 512 characters. This is the text sent to the embedding model for each Neuron.
- [ ] T038 [US3] Add function `upsert_vectors(conn: sqlite3.Connection, neuron_ids: list[str], embeddings: list[list[float]]) -> None` to `src/cerebrofy/db/writer.py`. Executes `conn.executemany("INSERT OR REPLACE INTO vec_neurons(id, embedding) VALUES (?, vec_f32(?))", [(nid, json.dumps(emb)) for nid, emb in zip(neuron_ids, embeddings)])`. Note: sqlite-vec accepts the embedding as a JSON array string or bytes; use `json.dumps(emb)` to serialize.

### Build Orchestrator — Step 4 (`src/cerebrofy/commands/build.py`)

- [ ] T039 [US3] Add function `build_step4_vectors(conn: sqlite3.Connection, neurons: list, embedder) -> None` to `src/cerebrofy/commands/build.py`. Builds texts via `[build_neuron_text(n) for n in neurons]` and ids via `[n.id for n in neurons]`. Processes in batches of 256: calls `embedder.embed(texts_batch)`, then `upsert_vectors(conn, ids_batch, embeddings_batch)`. Prints `"Cerebrofy: Step 4/6 — Generating embeddings ({K} / {M} neurons)"` at the start of each batch.
- [ ] T040 [US3] Update `cerebrofy_build` in `src/cerebrofy/commands/build.py` to insert Step 4 after Step 3 and before Step 6: (1) call `get_embedder(config.embedding_model)` — wrap in try/except and exit 1 with error message if model unavailable; (2) collect all neurons from `parse_results`; (3) call `build_step4_vectors(conn, all_neurons, embedder)`.

**Checkpoint**: `SELECT COUNT(*) FROM nodes` == `SELECT COUNT(*) FROM vec_neurons`. Hybrid KNN search pattern from `contracts/db-schema.md` executes without error.

---

## Phase 6: User Story 4 — Human-Readable Lobe Documentation (Priority: P4)

**Goal**: After `cerebrofy build`, `docs/cerebrofy/[lobe]_lobe.md` and
`docs/cerebrofy/cerebrofy_map.md` exist and are human-readable.

**Independent Test**: Open `docs/cerebrofy/` — one `.md` file per configured Lobe plus
`cerebrofy_map.md`. Each lobe file contains a Neurons table and a Synaptic Projections table.
`cerebrofy_map.md` contains the `state_hash`.

### Markdown Writers (`src/cerebrofy/markdown/`)

- [ ] T041 [P] [US4] Create `src/cerebrofy/markdown/lobe.py` with function `write_lobe_md(conn: sqlite3.Connection, lobe_name: str, lobe_path: str, out_dir: Path) -> None`. (1) Query `SELECT id,name,type,signature,docstring,line_start,line_end FROM nodes WHERE file LIKE ? ORDER BY file, line_start` with `lobe_path.rstrip('/') + '%'` as param. (2) Query inbound counts: `SELECT dst_id, COUNT(*) FROM edges WHERE rel_type != 'RUNTIME_BOUNDARY' GROUP BY dst_id`. (3) Query outbound counts: `SELECT src_id, COUNT(*) FROM edges WHERE rel_type != 'RUNTIME_BOUNDARY' GROUP BY src_id`. (4) Write `out_dir / f"{lobe_name}_lobe.md"` with the Markdown structure from `contracts/cli-build.md` Decision 5 in `research.md`: `# {lobe_name} Lobe`, path, last_indexed, Neurons table, Synaptic Projections table.
- [ ] T042 [P] [US4] Create `src/cerebrofy/markdown/map.py` with function `write_map_md(conn: sqlite3.Connection, lobes: dict, state_hash: str, out_dir: Path) -> None`. (1) For each lobe, query `SELECT COUNT(*) FROM nodes WHERE file LIKE ?` to get neuron count. (2) Read `last_build` from `SELECT value FROM meta WHERE key='last_build'`. (3) Write `out_dir / "cerebrofy_map.md"` with: title, `state_hash`, `last_build`, number of lobes, and a Lobes table (`| Lobe | Path | Neurons | File |`) with one row per lobe linking to `{lobe_name}_lobe.md`.

### Build Orchestrator — Step 5 (`src/cerebrofy/commands/build.py`)

- [ ] T043 [US4] Add function `build_step5_markdown(conn: sqlite3.Connection, config, state_hash: str, docs_dir: Path) -> None` to `src/cerebrofy/commands/build.py`. Creates `docs_dir` if it does not exist (`docs_dir.mkdir(parents=True, exist_ok=True)`). Calls `write_lobe_md(conn, name, path, docs_dir)` for each `(name, path)` in `config.lobes.items()`. Calls `write_map_md(conn, config.lobes, state_hash, docs_dir)`. Prints `"Cerebrofy: Step 5/6 — Writing Markdown documentation"`.
- [ ] T044 [US4] Update `cerebrofy_build` in `src/cerebrofy/commands/build.py` to call `build_step5_markdown` as the FINAL step, AFTER `build_step6_commit` returns `state_hash`. Pass `docs_dir = root / "docs" / "cerebrofy"`. This ordering ensures Markdown always reflects the committed index.

**Checkpoint**: `docs/cerebrofy/` directory exists with all lobe files and `cerebrofy_map.md`. File contents are human-readable without Cerebrofy knowledge.

---

## Phase 7: User Story 5 — Atomic Build Safety (Priority: P5)

**Goal**: A forcefully killed build leaves the prior index intact. The next build run succeeds.
No `.tmp` files or stale lock files remain after any successful or failed build.

**Independent Test**: Run `cerebrofy build &`, kill it mid-run, query prior index — it is
unchanged. Run `cerebrofy build` again to completion — succeeds. Run two simultaneous builds —
second exits immediately with "build already in progress" error.

### Build Lock (`src/cerebrofy/db/lock.py`)

- [ ] T045 [P] [US5] Create `src/cerebrofy/db/lock.py` with frozen `@dataclass` `BuildLock`: fields `lock_path: Path`, `pid: int`. Add function `acquire(lock_path: Path) -> BuildLock`: writes `str(os.getpid())` to `lock_path` (text mode), returns `BuildLock(lock_path=lock_path, pid=os.getpid())`.
- [ ] T046 [US5] Add function `release(lock: BuildLock) -> None` to `src/cerebrofy/db/lock.py`. Deletes `lock.lock_path` if it exists. Catches `FileNotFoundError` and continues silently (idempotent release).
- [ ] T047 [US5] Add function `is_stale(lock_path: Path) -> bool` to `src/cerebrofy/db/lock.py`. If `lock_path` does not exist, returns `False`. Reads the PID from the file. Calls `os.kill(pid, 0)`: if `OSError` is raised → process is dead → return `True` (stale). If no error → process is alive → return `False`. On Windows, use `os.kill(pid, 0)` — it raises `OSError` if process is absent.

### Atomic Swap and Error Recovery (`src/cerebrofy/commands/build.py`)

- [ ] T048 [US5] Add function `get_tmp_path(db_path: Path) -> Path` to `src/cerebrofy/commands/build.py`. Returns `db_path.parent / (db_path.name + ".tmp")`.
- [ ] T049 [US5] Add function `cleanup_stale_tmp(tmp_path: Path) -> None` to `src/cerebrofy/commands/build.py`. Deletes `tmp_path` if it exists. Catches `FileNotFoundError` silently.
- [ ] T050 [US5] Update `build_step0_create_db` in `src/cerebrofy/commands/build.py` to accept a `db_path` parameter and always open the connection at `get_tmp_path(db_path)` (the `.tmp` location) instead of `db_path` directly. The final path is only created by the atomic swap in `cerebrofy_build`.
- [ ] T051 [US5] Update `cerebrofy_build` in `src/cerebrofy/commands/build.py` to add the full safety wrapper: (1) check for existing lock: if `is_stale(lock_path)` → call `release` on the stale lock, else if lock exists → `click.echo("Error: A build is already in progress...", err=True); sys.exit(1)`; (2) call `acquire(lock_path)` to get `lock`; (3) call `cleanup_stale_tmp(tmp_path)`; (4) wrap the entire build pipeline (Steps 0–6) in a `try` block; (5) in the `finally` block: call `release(lock)` — always; (6) in the `except` block (failure): call `cleanup_stale_tmp(tmp_path)`; `click.echo("Error: ...", err=True)`; `sys.exit(1)`; (7) on success: call `os.replace(str(tmp_path), str(db_path))` — atomic swap — BEFORE calling `build_step5_markdown`. Pass the new `db_path` (not `.tmp`) to `build_step5_markdown`.
- [ ] T052 [US5] Update `build_step5_markdown` in `src/cerebrofy/commands/build.py` to open a FRESH read-only connection to the final `db_path` (using `open_db(db_path)`) rather than reusing the `.tmp` connection. Close this fresh connection after Markdown writing completes.

**Checkpoint**: `cerebrofy build` is fully atomic. Prior index survives any mid-run kill. Lock file is always cleaned up. Two concurrent builds reject the second.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T053 [P] Add `cerebrofy build` to the `## Commands` section in `CLAUDE.md` under the existing CLI examples
- [ ] T054 [P] Add `--version` flag to the Click group in `src/cerebrofy/cli.py` using `@click.version_option(version=__version__, prog_name="cerebrofy")` if not already present from Phase 1
- [ ] T055 [P] Run `quickstart.md` Steps 1–7 manually; fix any issues discovered in `src/cerebrofy/commands/build.py` or any Phase 2 module
- [ ] T056 Run `ruff check src/ tests/` and `mypy src/` — fix all reported issues in Phase 2 source files

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — blocks ALL user stories
- **US1 (Phase 3)**: Depends on Foundational
- **US2 (Phase 4)**: Depends on Foundational (T004–T006 specifically for `RawCapture` + `Edge`)
- **US3 (Phase 5)**: Depends on Foundational (T007 `Embedder` ABC)
- **US4 (Phase 6)**: Depends on US1 (`cerebrofy.db` must exist for Markdown queries)
- **US5 (Phase 7)**: Depends on US1 (refactors `cerebrofy_build`); can run after US1 alone
- **Polish (Phase 8)**: Depends on all user stories complete

### User Story Cross-Dependencies

- **US1 → US2**: US2 adds Steps 2+3 by updating `cerebrofy_build` (T032). US1 must be complete first.
- **US1 → US3**: US3 adds Step 4 by updating `cerebrofy_build` (T040). US1 must be complete first.
- **US1 → US4**: US4 adds Step 5 by updating `cerebrofy_build` (T044). US1 must be complete first.
- **US1 → US5**: US5 wraps `cerebrofy_build` with atomic safety (T051). US1 must be complete first.
- **US2 and US3**: Fully independent — can proceed in parallel after US1.
- **US4 and US5**: Fully independent — can proceed in parallel after US1.

### Within Phase 3 (US1)

- T013–T018 (writer functions): all [P] with each other
- T019 (`build_step0_create_db`): depends on T007 (`schema.py`), T009 (`open_db`), T013 (`insert_meta`), T008 (`create_schema`)
- T020 (`build_step1_parse`): depends on Phase 1 parser (already built)
- T021 (`build_step6_commit`): depends on T015–T018
- T022 (`cerebrofy_build`): depends on T019–T021
- T023 (CLI registration): depends on T022

### Within Phase 4 (US2)

- T024 (`build_name_registry`): depends on updated `ParseResult` from T005
- T025–T028 (resolver functions): sequential within `resolver.py`
- T029 (`write_edges`): [P] with resolver work
- T030–T031 (Steps 2+3): depend on T024–T029
- T032 (update `cerebrofy_build`): depends on T030–T031

### Within Phase 5 (US3)

- T033–T035 (embedder implementations): all [P]
- T036 (`get_embedder`): depends on T033–T035
- T037–T038 (writer functions): [P]
- T039 (`build_step4_vectors`): depends on T036–T038
- T040 (update `cerebrofy_build`): depends on T039

---

## Parallel Execution Examples

### Phase 2 Foundational — All Parallel

```
T004 db/schema.py DDL constants
T005 (after T004) db/schema.py create_schema()
T007 db/connection.py open_db() + check_schema_version()
T009 graph/edges.py Edge dataclass + constants
T010 embedder/base.py Embedder ABC
```

### Phase 3 (US1) — Writer Functions Wave

```
T013 insert_meta()         T015 compute_file_hash()
T014 write_nodes()         T016 compute_state_hash()
                           T017 write_file_hashes()
                           T018 write_build_meta()
```

### Phase 5 (US3) — Embedder Implementations

```
T033 LocalEmbedder    T034 OpenAIEmbedder    T035 CohereEmbedder
```

### Phase 6 (US4) — Markdown Writers

```
T041 write_lobe_md()     T042 write_map_md()
```

### Phase 7 (US5) — Lock File Primitives

```
T045 BuildLock + acquire()    T046 release()    T047 is_stale()
```

---

## Implementation Strategy

### MVP First (US1 Only — Steps 0, 1, 6)

1. Complete Phase 1 (Setup) + Phase 2 (Foundational)
2. Complete Phase 3 (US1): `cerebrofy build` creates `cerebrofy.db` with Neurons indexed
3. **STOP and VALIDATE**: query `nodes`, verify `state_hash` determinism
4. This is the minimum viable index — `cerebrofy validate` (Phase 3 feature) can already
   diff against it

### Incremental Delivery

1. US1 complete → basic indexing working
2. US2 added → call graph available (enables Blast Radius in Phase 3 feature)
3. US3 added → vectors available (enables Phase 4 AI search)
4. US4 added → Markdown docs generated
5. US5 added → build is production-safe (atomic, interrupt-resilient)

### Parallel Team Strategy

After Foundational (Phase 2) is complete:
- Developer A: US1 (build orchestrator core)
- Developer B: US2 (graph resolver) — needs T004/T005/T006 from Foundational
- Developer C: US3 (embedder pipeline) — needs T007/T012 from Foundational
- US4 and US5 require US1 complete; can be parallelized after US1

---

## Notes

- [P] tasks = different files, no shared state dependencies
- Each user story is independently testable using `quickstart.md` steps
- `cerebrofy_build` is updated incrementally (T022 → T032 → T040 → T044 → T051)
- The `.tmp` pattern is introduced in US5 (T050); US1–US4 write directly to `cerebrofy.db`
- `build_step5_markdown` is always the FINAL step — called after the atomic swap in US5
- `RUNTIME_BOUNDARY` edges are stored but never traversed in BFS (Law II invariant)
