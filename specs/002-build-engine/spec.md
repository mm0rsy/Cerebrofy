# Feature Specification: Phase 2 — The Build Engine

**Feature Branch**: `002-build-engine`
**Created**: 2026-04-03
**Status**: Draft
**Input**: User description: "Read @cerebrofy_blueprint_v5_0.md and specify the next feature based on phase 2"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Full Codebase Indexing (Priority: P1)

A developer has just run `cerebrofy init` on a repository and wants to build a complete,
searchable index of their codebase. They run `cerebrofy build` once, and Cerebrofy reads every
tracked source file, identifies all named code units, maps the call relationships between them,
and produces a persistent index that all subsequent Cerebrofy commands depend on.

**Why this priority**: Without a completed index, no other Cerebrofy command (`cerebrofy
validate`, `cerebrofy specify`, `cerebrofy plan`) can operate. This story is the gateway to
the entire feature set and represents the core value promise of Cerebrofy.

**Independent Test**: A developer with a `cerebrofy init`-initialized repository runs `cerebrofy
build`. On completion, the index exists, contains at least one record per tracked source file,
and the terminal reports the count of indexed code units and files processed. Running
`cerebrofy build` a second time on the same unchanged codebase produces the same result without
error.

**Acceptance Scenarios**:

1. **Given** a repository that has been initialized with `cerebrofy init`, **When** the developer
   runs `cerebrofy build`, **Then** Cerebrofy parses all source files matching
   `tracked_extensions` in `config.yaml` (excluding files matched by `.cerebrofy-ignore` and
   `.gitignore`) and produces a complete index of all named code units.

2. **Given** a previously built repository where the developer runs `cerebrofy build` again
   without making code changes, **Then** the build completes successfully and produces an
   identical `state_hash` as the prior build — confirming the index is deterministic.

3. **Given** the index already exists from a prior build, **When** the developer runs `cerebrofy
   build` again after making code changes, **Then** the prior index is replaced atomically with
   the newly built one — no manual cleanup required.

4. **Given** `cerebrofy init` has NOT been run, **When** the developer runs `cerebrofy build`,
   **Then** Cerebrofy reports a clear error explaining that `cerebrofy init` must be run first
   and exits with code 1.

5. **Given** a repository with source files in multiple configured languages, **When**
   `cerebrofy build` completes, **Then** code units from all tracked languages appear in the
   index with a consistent record structure regardless of language.

---

### User Story 2 - Call Graph Construction (Priority: P2)

A developer wants to understand how functions and modules in their codebase call each other.
After `cerebrofy build` completes, the index captures not just what code units exist, but how
they are connected — which functions call which, across files and modules. This graph is the
foundation for Blast Radius analysis in Phase 3 and AI-assisted planning in Phase 4.

**Why this priority**: The call graph is what differentiates Cerebrofy from a simple code
linter. Without edges (call relationships), `cerebrofy validate` cannot classify structural
drift, and `cerebrofy plan` cannot compute Blast Radius. However, the index is still useful
without edges for basic search — hence P2, not P1.

**Independent Test**: After `cerebrofy build`, query the index for a function known to call
another function. Confirm that a call relationship record exists between those two code units.
Confirm that unresolvable cross-module calls are recorded as boundary edges, not silently
dropped.

**Acceptance Scenarios**:

1. **Given** two functions in the same file where one calls the other, **When** `cerebrofy
   build` completes, **Then** a call relationship record exists in the index from the calling
   function to the called function.

2. **Given** a function in one module that calls a function in a different module, **When**
   `cerebrofy build` completes, **Then** a cross-module call relationship record exists in the
   index linking both code units.

3. **Given** a function that makes a call that cannot be resolved to any tracked code unit
   (e.g., an external library call or a cross-language HTTP call), **When** `cerebrofy build`
   completes, **Then** the unresolvable call is recorded as a boundary relationship — it is
   not silently ignored, and it does not cause the build to fail.

4. **Given** a circular call chain (function A calls B, B calls A), **When** `cerebrofy build`
   completes, **Then** both call relationships are recorded correctly, and the build does not
   loop indefinitely or crash.

---

### User Story 3 - Semantic Search Readiness (Priority: P3)

A developer wants AI-powered commands (`cerebrofy specify`, `cerebrofy plan`, `cerebrofy tasks`)
to find the most relevant parts of their codebase given a natural-language description. After
`cerebrofy build`, each code unit in the index is paired with a semantic embedding derived from
its name, signature, and docstring. This enables the nearest-neighbor search that Phase 4
commands rely on.

**Why this priority**: Semantic search is essential for Phase 4 AI features, but the basic
index (US1) and call graph (US2) are independently useful without vectors — `cerebrofy validate`
works entirely on the graph. Vectors are Phase 4 prep, making this P3.

**Independent Test**: After `cerebrofy build`, confirm that the index contains an embedding
record for each indexed code unit. Confirm that changing the configured embedding model in
`config.yaml` and rebuilding produces a new, complete set of embeddings at the correct
dimension.

**Acceptance Scenarios**:

1. **Given** a completed build with the default embedding model, **When** the developer inspects
   the index, **Then** every indexed code unit has an associated embedding vector at the
   dimension configured in `config.yaml`.

2. **Given** a developer changes the embedding model in `config.yaml` and re-runs
   `cerebrofy build`, **Then** the prior embeddings are replaced with a new complete set at the
   new model's dimension — no dimension mismatch errors occur.

3. **Given** a code unit with no docstring or signature (e.g., a short utility function),
   **When** `cerebrofy build` runs, **Then** an embedding is still produced (using the unit
   name alone) and the build completes without error.

---

### User Story 4 - Human-Readable Lobe Documentation (Priority: P4)

A developer or team lead wants a quick, human-readable overview of each logical module (Lobe)
in their codebase — what code units it contains, what their signatures look like, and how
heavily they interact with other modules. After `cerebrofy build`, Cerebrofy writes Markdown
documentation files alongside the index, one per Lobe, plus a master index file.

**Why this priority**: The Markdown files are a valuable output for onboarding and code review,
but they are derived entirely from the index. All other Cerebrofy commands operate on the index
directly, not on the Markdown. They are P4 because they are output artefacts, not blockers.

**Independent Test**: After `cerebrofy build`, open the `docs/cerebrofy/` directory. Confirm
that one Markdown file exists per configured Lobe plus a master `cerebrofy_map.md` file.
Confirm that each lobe file lists the code units in that lobe with their signatures and
docstrings. Confirm that the master file contains the `state_hash` and a list of all lobes.

**Acceptance Scenarios**:

1. **Given** a completed build with three configured Lobes, **When** the developer opens
   `docs/cerebrofy/`, **Then** three lobe Markdown files and one `cerebrofy_map.md` master file
   exist, each named after the corresponding Lobe.

2. **Given** a lobe Markdown file, **When** the developer reads it, **Then** it contains a
   table of all code units in that lobe (name, signature, docstring, line numbers) and a
   summary of their inbound and outbound call counts.

3. **Given** a second `cerebrofy build` run with code changes, **When** it completes, **Then**
   the lobe Markdown files are updated to reflect the current state of the codebase — stale
   documentation does not persist.

---

### User Story 5 - Atomic Build Safety (Priority: P5)

A developer wants confidence that an interrupted or failed build never leaves the repository
in a corrupted or partially-indexed state. Whether the process is killed mid-run, runs out of
disk space, or encounters an unhandled error, the previously working index (if any) must remain
intact and usable.

**Why this priority**: Build safety is a quality invariant rather than a user-visible feature.
Developers will rarely think about it until it fails — but a corrupted index is a severe trust
violation. Correctness over new features; however, a working first build (US1) must exist
before the swap mechanism has anything to protect.

**Independent Test**: Start `cerebrofy build` on a large repository and forcefully kill the
process mid-run. Confirm that the previously built index (if one existed) is unchanged and
still queryable. Confirm that no partial or temporary index file remains visible in
`.cerebrofy/db/`. Start a fresh build on a clean repo, kill it mid-run, then run it again to
completion — confirm the second run succeeds.

**Acceptance Scenarios**:

1. **Given** a repository with an existing complete index, **When** a new `cerebrofy build` is
   forcefully interrupted mid-run, **Then** the prior index is unchanged and all Cerebrofy
   commands continue to function against it.

2. **Given** a repository where a prior build was interrupted and left a partial state,
   **When** the developer runs `cerebrofy build` again, **Then** the partial state is discarded,
   the build starts fresh, and the build completes successfully.

3. **Given** a build that fails due to an unhandled error (e.g., an unreadable file that
   blocks a required step), **Then** Cerebrofy prints a clear error message identifying the
   cause, exits with a non-zero code, and leaves no partial index visible in `.cerebrofy/db/`.

---

### Edge Cases

- What happens when `cerebrofy build` is run on a repository with zero tracked source files? → The index is created but empty; a warning is printed noting no code units were indexed. The build exits 0.
- What happens when a tracked file is unreadable (permissions error)? → The file is skipped with a warning; the build continues and completes with the remaining files.
- What happens when the configured embedding model requires a network call and the network is unavailable? → The build fails at the vectorization step with a clear error. No partial index is written (atomic swap — the prior index, if any, is preserved).
- What happens when `cerebrofy build` is already running (concurrent execution in the same repo)? → The second invocation detects the in-progress temporary file and exits immediately with an informative error: "A build is already in progress in this repository."
- What happens when disk space runs out mid-build? → The write fails, the temporary index is discarded, the prior index (if any) is preserved, and Cerebrofy exits with a disk-space error.
- What if `config.yaml` is malformed or missing required fields when `cerebrofy build` is invoked? → Cerebrofy exits with a validation error before parsing any files. No index is created or modified.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `cerebrofy build` MUST be the sole creator of the Cerebrofy index (`cerebrofy.db`). No other command may create the index.
- **FR-002**: `cerebrofy build` MUST write the index to a temporary location first and swap it to the final location only on full, successful completion — a failed or interrupted build MUST NOT corrupt or overwrite the prior index.
- **FR-003**: `cerebrofy build` MUST parse all source files whose extension appears in `tracked_extensions` (from `config.yaml`) and that are not excluded by `.cerebrofy-ignore` or `.gitignore`.
- **FR-004**: `cerebrofy build` MUST index every named code unit (function, method, class without methods, module-level code block) from all tracked files, producing one record per unit following the Neuron schema defined in Phase 1.
- **FR-005**: `cerebrofy build` MUST record intra-file call relationships (where one named code unit calls another in the same file) as directed call edges in the index.
- **FR-006**: `cerebrofy build` MUST record cross-module call relationships (where a code unit in one file calls a code unit in another file) as directed cross-module edges in the index.
- **FR-007**: `cerebrofy build` MUST record unresolvable calls (external libraries, cross-language HTTP/FFI calls) as boundary edges — they MUST NOT be silently discarded.
- **FR-008**: `cerebrofy build` MUST produce a semantic embedding for every indexed code unit, using the embedding model configured in `config.yaml`. The embedding dimension MUST match the model's output dimension as specified in `config.yaml`.
- **FR-009**: `cerebrofy build` MUST compute a `state_hash` — a deterministic fingerprint of all tracked file contents — and write it to both the index metadata and to `docs/cerebrofy/cerebrofy_map.md`.
- **FR-010**: `cerebrofy build` MUST write one Markdown documentation file per Lobe (to `docs/cerebrofy/`) and update the master `cerebrofy_map.md`. Each lobe file MUST list all code units in that lobe with name, signature, docstring, line numbers, and inbound/outbound call counts.
- **FR-011**: `cerebrofy build` MUST require that `cerebrofy init` has already been run (`.cerebrofy/config.yaml` must exist). If not, it MUST exit with a clear error and code 1 before creating any files.
- **FR-012**: If a prior index exists, `cerebrofy build` MUST replace it atomically on success. The prior index MUST remain intact until the new build is fully complete.
- **FR-013**: `cerebrofy build` MUST respect the `embed_dim` value in `config.yaml` when creating the vector storage. Changing `embed_dim` and rebuilding MUST produce a new, correctly dimensioned vector store with no residual data at the old dimension.
- **FR-014**: Files with syntax errors MUST be reported as warnings (identifying file and line); the build MUST continue processing remaining files and complete successfully.
- **FR-015**: `cerebrofy build` MUST print step-by-step progress output (at minimum: which pipeline step is running and how many files have been processed) so developers can monitor long-running builds.
- **FR-016**: `cerebrofy build` MUST detect if a build is already in progress in the same repository and exit with an informative error rather than running concurrently.
- **FR-017**: `cerebrofy build` MUST store a per-file content hash for every tracked file in the index. This table is consumed by `cerebrofy validate` (Phase 3) for drift classification.

### Key Entities

- **Index** (`cerebrofy.db`): The single persistent artifact produced by `cerebrofy build`. Contains all code unit records, call relationship records, embedding vectors, per-file content hashes, and build metadata. Lives in `.cerebrofy/db/`. Not committed to version control.
- **Code Unit Record (Neuron)**: A named code unit from Phase 1. Attributes: unique ID (`{file}::{name}`), name, type (function/class/module), file path, line range, signature (optional), docstring (optional).
- **Call Relationship (Edge)**: A directed link between two code units. Types: intra-file call, cross-module call, boundary (unresolvable). Attributes: source unit ID, target unit ID, relationship type, source file.
- **Embedding Vector**: A fixed-dimension numerical representation of a code unit's semantic meaning. Dimension is determined by the configured embedding model. Enables nearest-neighbor search by Phase 4 commands.
- **State Hash**: A deterministic fingerprint of the entire tracked codebase at build time. Computed as a hash of sorted per-file content hashes over all tracked files. Written to the index metadata and to `cerebrofy_map.md`.
- **File Hash Record**: A record of a tracked file's path and content hash at the time of the last build or update. Used by Phase 3 (`cerebrofy validate`) to determine which files have changed since the index was last built.
- **Lobe Documentation** (`[lobe]_lobe.md`): A human-readable Markdown file summarizing one Lobe — code unit table and call count table. One file per configured Lobe; written to `docs/cerebrofy/`.
- **Master Index** (`cerebrofy_map.md`): A Markdown summary file listing all Lobes, the current `state_hash`, and the last-build timestamp. Committed to version control.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `cerebrofy build` completes a full index of a 10,000-file repository in under 5 minutes on a standard developer machine (8-core CPU, 16 GB RAM, local embedding model).
- **SC-002**: Two `cerebrofy build` runs on the same unchanged codebase produce byte-identical `state_hash` values — the build is fully deterministic.
- **SC-003**: A build that is forcefully killed mid-run (at any point after the first file is parsed) leaves the prior index (if any) intact and all Cerebrofy commands functional — zero corruption cases across 10 forced-kill test runs.
- **SC-004**: After `cerebrofy build`, 100% of named code units in tracked files (not excluded by ignore rules) appear in the index — no silent omissions.
- **SC-005**: Lobe Markdown files are produced for all configured Lobes within 30 seconds of the index build completing, and are comprehensible to a developer unfamiliar with Cerebrofy internals.
- **SC-006**: Changing the embedding model in `config.yaml` and running `cerebrofy build` completes without dimension mismatch errors for all three supported embedding model options (local, OpenAI, Cohere).

## Assumptions

- Phase 1 (`cerebrofy init`) has been completed on the target repository before `cerebrofy build` is invoked. `config.yaml`, `.cerebrofy-ignore`, and bundled query files are in place.
- The Universal Parser from Phase 1 is the sole mechanism for extracting code units. `cerebrofy build` consumes Phase 1 parser output directly without re-implementing parsing logic.
- The embedding model configured in `config.yaml` is available at build time — either installed locally (default) or reachable via the configured API endpoint. Network failures on remote models result in a clean, reported error, not a corrupted index.
- `cerebrofy.db` is a local artifact and is NOT committed to version control. Only `cerebrofy_map.md` (containing `state_hash`) is committed.
- `cerebrofy build` always runs a full rebuild from scratch. Incremental updates are the responsibility of `cerebrofy update` (Phase 3). There is no partial or incremental build mode in this phase.
- Cross-language runtime calls (e.g., a Python service calling a Go service via HTTP) cannot be statically resolved by the parser. These become boundary edges in the call graph.
- The `docs/cerebrofy/` directory is created by `cerebrofy build` if it does not already exist.
- Concurrent execution of multiple `cerebrofy build` processes in the same repository is not supported in Phase 2.
- `cerebrofy.db` is never opened for writes without a schema version check. If the schema version is outdated, `cerebrofy build` proceeds (it always creates the schema from scratch). Schema migration is a `cerebrofy migrate` concern (Phase 3).
