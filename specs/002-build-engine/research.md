# Research: Phase 2 — The Build Engine

**Feature**: 002-build-engine
**Date**: 2026-04-03
**Status**: Complete — all decisions resolved

---

## Decision 1: Vector Storage — sqlite-vec

**Decision**: Use `sqlite-vec` (PyPI package) to extend SQLite with vector similarity search.
Load via `sqlite_vec.load(conn)` at connection open.

**Rationale**: sqlite-vec stores embedding vectors directly in SQLite as a virtual table
(`USING vec0`). This keeps the entire Cerebrofy index — graph tables AND vectors — in a single
`.cerebrofy/db/cerebrofy.db` file, satisfying Law III (Semantic Intent) and the Storage
Architecture invariant ("Single DB — no separate store"). Hybrid KNN + BFS search runs in one
Python function with zero network calls and zero IPC.

**sqlite-vec installation**:
- `pip install sqlite-vec` bundles `vec0.so` (Linux), `vec0.dylib` (macOS), `vec0.dll` (Windows).
- Loading: `import sqlite_vec; sqlite_vec.load(conn)` where `conn` is a `sqlite3.Connection`.
- Must call `conn.enable_load_extension(True)` before loading.
- For Nuitka `.exe` (Windows distribution): `vec0.dll` must be copied alongside the binary.
  The `sqlite-vec` package exposes `sqlite_vec.loadable_path()` to get the DLL path for bundling.

**vec_neurons DDL** (generated dynamically from `config.yaml`):
```sql
CREATE VIRTUAL TABLE vec_neurons USING vec0(
  id         TEXT PRIMARY KEY,
  embedding  FLOAT[{embed_dim}]  -- dimension injected from config at build time
);
```

**Alternatives considered**:
- ChromaDB: separate process, separate file — violates Single DB invariant.
- LanceDB: Arrow-based, separate file — violates Single DB invariant.
- pgvector: requires PostgreSQL — incompatible with offline CLI tool design.
- Hand-rolled cosine similarity in Python: O(n) scan at query time, unacceptable for 10k+ Neurons.

---

## Decision 2: Embedding Model Architecture

**Decision**: Three-provider strategy behind an `Embedder` ABC. Default: `sentence-transformers`
with `nomic-ai/nomic-embed-text-v1` (768-dim, fully offline). Optional: OpenAI
`text-embedding-3-small` (1536-dim), Cohere `embed-english-v3.0` (1024-dim).

**Rationale**: The constitution mandates `embed_dim` is read from `config.yaml` at build time.
All three models have fixed, known dimensions. An ABC with three concrete implementations makes
model switching a config change + full rebuild — no engine code changes.

**Batch processing (critical for SC-001)**:
All three providers support batch embedding. Without batching, 10,000 Neurons × ~100ms/call
(local CPU) = ~17 minutes — violating SC-001 (5-minute target). With batching:
- `sentence-transformers`: `model.encode(texts, batch_size=64)` — typical throughput ~5,000
  texts/minute on a modern CPU, ~30s for 10k Neurons. Well within SC-001.
- OpenAI: `client.embeddings.create(model=..., input=texts)` supports up to 2,048 inputs per
  request; send in chunks of 512 to stay safely within limits.
- Cohere: `co.embed(texts=texts, model=..., input_type="search_document")` supports up to 96
  texts per request; send in chunks of 96.

**Text construction per Neuron** (for embedding input):
```
"{name}: {signature or ''} {docstring or ''}"
```
Strips to 512 tokens max to stay within model context limits.

**First-run model download** (local only):
`sentence-transformers` downloads `nomic-embed-text-v1` (~275 MB) on first use to
`~/.cache/huggingface/`. Subsequent runs use the cached model. Display a progress note on
first download.

**Alternatives considered**:
- Hard-coding `text-embedding-ada-002` as default: requires API key, costs money, fails offline.
- `fastembed`: lighter but less familiar API; fewer guarantees on model output stability.
- `llama.cpp` local inference: heavier dependency, not pip-installable cleanly.

---

## Decision 3: Concurrent Build Detection — PID Lock File

**Decision**: Use a PID lock file `.cerebrofy/db/cerebrofy.build.lock` containing the running
process ID. Check on `cerebrofy build` start: if lock exists and PID is alive → error. If lock
exists but PID is dead (stale) → remove lock and proceed.

**Lock file lifecycle**:
1. On `cerebrofy build` start: write PID to `.cerebrofy/db/cerebrofy.build.lock`.
2. On build success or failure: delete the lock file.
3. On next build start: if lock exists, read PID, check `os.kill(pid, 0)` (POSIX) or
   `OpenProcess` (Windows). If process is alive → exit with error. If not alive → stale lock,
   delete and proceed.

**Windows compatibility**: On Windows, `os.kill(pid, 0)` raises `OSError` if the process does
not exist, which is equivalent to "not alive". No platform-specific branching needed in the
check logic.

**Why not check for `.cerebrofy.db.tmp` instead?**
The `.tmp` file persists after a crash (stale). Checking `.tmp` existence alone would falsely
block every build after a crash. The PID check distinguishes a live concurrent build from a
stale interrupted one.

**Alternatives considered**:
- `fcntl.flock` (POSIX file locking): Does not work across processes on some network
  filesystems; also doesn't survive process crash gracefully.
- No concurrent detection: risk of two builds corrupting the `.tmp` file simultaneously.

---

## Decision 4: Cross-Module Call Resolution — Two-Pass Name Lookup

**Decision**: Two-pass build for graph construction:
- **Pass 1**: Parse all files → build a global name registry:
  `dict[name → list[Neuron]]` (multiple files may define the same name).
- **Pass 2**: For each `call_expression` capture in each file, try to resolve the callee name:
  1. Check the same file → `LOCAL_CALL` edge.
  2. Check import statements in the current file: if `from foo import bar` and `bar` is in the
     registry → `EXTERNAL_CALL` edge from caller to the first match.
  3. Unresolvable (not in registry or ambiguous multi-match) → `RUNTIME_BOUNDARY` edge.

**Import chain tracing (Phase 2 scope)**:
Phase 2 handles one level of direct import resolution (e.g., `from auth import validate` →
look up `validate` in `auth/*.py`). Re-exports and aliased imports are marked as
`RUNTIME_BOUNDARY` if the resolution would require multi-hop tracing. Full import chain tracing
(following re-exports across N files) is deferred to Phase 3 `cerebrofy update` refinement.

**Why not a full import graph?**
Full resolution requires language-specific import semantics (e.g., Python's `__init__.py`
re-exports vs. Go's explicit package declarations). This would introduce language-specific
logic in the graph builder — a Law V violation. The two-pass name lookup is purely name-based
and language-agnostic.

**Edge types** (from Blueprint Section II):
| rel_type | Meaning |
|----------|---------|
| `LOCAL_CALL` | Caller and callee are in the same file |
| `EXTERNAL_CALL` | Caller and callee are in different files; resolved via import |
| `IMPORT` | Import statement reference (not a call, but a dependency link) |
| `RUNTIME_BOUNDARY` | Call that cannot be statically resolved to a tracked code unit |

**Alternatives considered**:
- Full AST import graph per language: language-specific engine logic → Law V violation.
- Skip cross-module edges entirely: satisfies FR-005 and FR-006 partially, but makes
  Blast Radius computation shallow (only local edges). Rejected.

---

## Decision 5: Markdown Generation Strategy

**Decision**: Generate lobe Markdown files **after** the atomic index swap (Step 6), not during
the build. This ensures Markdown always reflects the committed index state.

**Rationale**: If Markdown is generated during the build (Steps 1–5) and the build fails during
Step 6 (the swap), the Markdown would reflect a state that never became the canonical index.
Generating Markdown post-swap guarantees consistency between `cerebrofy.db` and `[lobe]_lobe.md`.

**File naming convention** (from Blueprint Section II, directory layout):
- Per-lobe: `docs/cerebrofy/{lobe_name}_lobe.md`
- Master: `docs/cerebrofy/cerebrofy_map.md`

**Per-lobe Markdown structure**:
```markdown
# {lobe_name} Lobe

**Path**: `{lobe_path}`
**Last indexed**: {ISO-8601 timestamp}

## Neurons

| Name | Type | Signature | Docstring | Lines |
|------|------|-----------|-----------|-------|
| ... | ... | ... | ... | L{start}–L{end} |

## Synaptic Projections

| Neuron | Inbound Calls | Outbound Calls |
|--------|--------------|----------------|
| ... | N | N |
```

**cerebrofy_map.md structure**:
```markdown
# Cerebrofy Map

**State Hash**: `{state_hash}`
**Last Build**: {ISO-8601 timestamp}
**Lobes**: {N}

## Lobes

| Lobe | Path | Neurons | File |
|------|------|---------|------|
| auth | src/auth/ | 42 | [auth_lobe.md](auth_lobe.md) |
```

**Alternatives considered**:
- Markdown during build (pre-swap): creates Markdown/index inconsistency on failure.
- Markdown as a separate command: requires two commands after a build; violates FR-010.

---

## Decision 6: Atomic Swap Implementation

**Decision**: Write index to `.cerebrofy/db/cerebrofy.db.tmp` throughout the build. On success,
use `os.replace(tmp_path, final_path)` — an atomic rename on both POSIX and Windows (same
filesystem). On failure, delete `.tmp` file and exit with error.

**Why `os.replace` is atomic**:
- POSIX: `rename(2)` syscall is atomic — the `dst` path switches from old to new in a single
  kernel operation.
- Windows: `os.replace` uses `MoveFileExW` with `MOVEFILE_REPLACE_EXISTING`, which is atomic
  on the same volume.
- Both guarantee: no moment where `cerebrofy.db` is partially written.

**Constraint**: Both `.tmp` and `.db` must be on the same filesystem for atomic rename.
Since both are in `.cerebrofy/db/`, this is guaranteed.

**`.tmp` cleanup on next run**:
If a build was killed after writing `.tmp` but before the swap, the `.tmp` file remains.
On the next `cerebrofy build` start, detect and delete any existing `.tmp` file before
starting the new build (after acquiring the lock).

**Alternatives considered**:
- Copy then delete: two-step operation, not atomic — a crash between copy and delete
  leaves both old and new files.
- WAL mode only: SQLite WAL helps with concurrent reads, not with interrupted bulk writes.
