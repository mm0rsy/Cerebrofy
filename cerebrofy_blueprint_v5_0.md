# 🧠 Cerebrofy
## The Self-Aware Repository Engine
### Blueprint v5.0 — 39/39 Issues Resolved — Implementation Ready

---

## I. The Cerebrofy Constitution

*Five invariant laws. No implementation decision may violate them.*

| Law | Definition |
|-----|------------|
| **Law of Precedence** | The index must exist before any spec is written. No spec file may be committed against an unindexed codebase. |
| **Law of Structural Truth** | Function calls are Synapses stored in a SQLite graph (cerebrofy.db) — zero-hallucination dependency tracking with O(1) edge lookups. |
| **Law of Semantic Intent** | Code logic is vectorized via sqlite-vec into the same cerebrofy.db, letting the AI reason about module meaning without reading every line. |
| **Law of Autonomic Health** | If the index is out of sync with the code, the repo is Cerebrofy-Dead. Git hooks enforce a tiered response: warn on minor drift, hard-block on structural drift. |
| **Law of Agnosticism** | Tree-sitter is the only parser. Language support is additive — new .scm query files extend Cerebrofy to new languages without touching the core engine. |

---

## II. System Architecture

### Directory Layout

```
root/
├── .cerebrofy/
│   ├── config.yaml          ← Lobe map, language list, embed model, LLM settings
│   ├── db/
│   │   └── cerebrofy.db     ← Single SQLite file: graph tables + vec_neurons (sqlite-vec)
│   ├── queries/             ← Tree-sitter .scm query files per language
│   └── scripts/
│       ├── cerebrofy_tool.py  ← Core Python engine
│       └── migrations/        ← Schema migration scripts (v1_to_v2.py, etc.)
├── docs/cerebrofy/
│   ├── cerebrofy_map.md     ← Master index: state_hash, lobe list, global topology
│   ├── [module]_lobe.md     ← Per-lobe: neuron table, synaptic projections
│   └── specs/               ← Output of cerebrofy specify (<timestamp>_spec.md)
├── .cerebrofy-ignore        ← User-defined ignore rules (gitignore syntax)
├── .git/hooks/
│   ├── pre-push             ← Tiered drift enforcement (WARN or BLOCK)
│   └── post-merge           ← state_hash sync check after git pull
└── src/                     ← Source code
```

### Architectural Decisions (Locked)

> ✅ **DECIDED:** `cerebrofy build` absorbs `cerebrofy connect`. Local call indexing and cross-module axon tracing are one atomic operation. No two-step workflow, no half-built index.

> ✅ **DECIDED:** Single database: `cerebrofy.db`. All state — graph nodes, edges, meta, and vectors — lives in one SQLite file. No separate connectome.db. No ChromaDB. No LanceDB.

> ✅ **DECIDED:** Tiered git hook enforcement. Minor drift → WARN + suggest `cerebrofy update`. Structural drift → HARD BLOCK exit 1. First clone / missing index → WARN only.

> ✅ **DECIDED:** `cerebrofy merge` descoped for v1. On post-pull conflict (remote `state_hash` ≠ local), WARN and require manual `cerebrofy build`. No binary SQLite diff attempted.

---

## III. Implementation Plan

*`cerebrofy update` is built in Phase 3 before the hard-block hook is enabled. This guarantees developers always have a fast sync path before enforcement activates.*

---

### Phase 1 — Sensory Foundation

#### 1.1 Universal Parser

- **Dependency:** `tree-sitter-languages` (Python binding, covers 40+ languages).
- Write `.scm` query files extracting: `function_definition`, `class_definition`, `import_statement`, `call_expression` per language.
- Primary language set at `cerebrofy init` time. Additional languages added via `config.yaml` without engine changes.
- **Parser output — normalized Neuron schema:**
  ```
  { id: '{file}::{name}', type: function|class|module, name, file,
    line_start, line_end, docstring, signature }
  ```
- **Chunking rules:** functions and methods = one Neuron each. Module-level code outside any function = one `module` Neuron per file. Classes without methods = one Neuron. Config files (YAML, JSON, TOML) = skipped unless explicitly included in `config.yaml`.

#### 1.2 cerebrofy init

- Scan directory tree. Propose Lobe groupings: each top-level directory under `src/` becomes one Lobe. If no `src/` exists, top-level dirs of the repo root are used. Max Lobe depth = 2 levels. Monorepos: each package directory (detected by presence of `package.json`, `pyproject.toml`, `go.mod`) becomes its own Lobe.
- Write `.cerebrofy/config.yaml`: lobe map, tracked_extensions list, embedding_model (default: local). **Note:** ignore rules live exclusively in `.cerebrofy-ignore` — config.yaml has no `ignore_patterns` field.
- **Create directory structure only:** `.cerebrofy/db/`, `.cerebrofy/queries/`, `.cerebrofy/scripts/migrations/`. Do NOT create `cerebrofy.db` at init time — the database is created exclusively by `cerebrofy build`.
- Write `.cerebrofy-ignore` with default ignores: `node_modules/`, `__pycache__/`, `.git/`, `dist/`, `build/`, `vendor/`, `*.min.js`, `*.min.css`, `*.lock`, `*.map`.
- Install git hooks in WARN-ONLY mode. Hard-block activates in Phase 3 after `cerebrofy update` is verified.
- Print next step: *"Cerebrofy initialized. Run `cerebrofy build` to index your codebase."*

---

### Phase 2 — The Build Engine

#### 2.1 cerebrofy build *(single command — does everything)*

`cerebrofy build` is the **sole creator** of `cerebrofy.db`. It writes to `cerebrofy.db.tmp` (creating it fresh each run), then swaps to `cerebrofy.db` only on full success. An interrupted build leaves no corrupted state — the `.tmp` file is discarded on the next run. If `cerebrofy.db` already exists from a prior build, it is replaced atomically.

- **Step 0 — Create DB:** Create `.cerebrofy/db/cerebrofy.db.tmp` fresh. Load sqlite-vec extension. Run `CREATE TABLE nodes, edges, meta, file_hashes` and `CREATE VIRTUAL TABLE vec_neurons USING vec0(...FLOAT[embed_dim])` using `embed_dim` from `config.yaml`. Insert `schema_version`, `embed_model`, `embed_dim` into meta.
- **Step 1 — Parse:** Run Tree-sitter on all tracked files (respecting `.cerebrofy-ignore` and `.gitignore`). Emit Neuron records.
- **Step 2 — Graph (local):** Insert all Neurons as nodes in `cerebrofy.db.tmp`. Identify intra-file `call_expression` matches. Insert as `LOCAL_CALL` edges.
- **Step 3 — Graph (cross-module):** Resolve import/export chains across all files. Insert `EXTERNAL_CALL` edges. Insert `RUNTIME_BOUNDARY` edges for unresolvable cross-language calls.
- **Step 4 — Vectors:** Embed each Neuron using configured model. Upsert into `vec_neurons` virtual table in the same `cerebrofy.db.tmp`.
- **Step 5 — Markdown:** Write `[module]_lobe.md` files: Neuron table (name, signature, docstring, line) + Synaptic Projections table (inbound/outbound call counts).
- **Step 6 — Commit:** Compute `state_hash`: SHA-256 of all tracked file hashes. Populate `file_hashes` table: upsert one row per tracked file (file path + SHA-256 of content). Write `state_hash` to `cerebrofy_map.md` header and meta table. Swap `cerebrofy.db.tmp` → `cerebrofy.db`.

---

### Phase 3 — Autonomic Nervous System

#### 3.1 cerebrofy update ← *Build and verify this before enabling hard-block*

- Accept a list of changed files, or auto-detect via three git commands that together cover all change types:
  1. `git diff --name-status HEAD` — modified and deleted tracked files
  2. `git diff --name-status` — unstaged changes to tracked files not yet committed
  3. `git ls-files --others --exclude-standard` — new untracked files
  - Results deduplicated and tagged by status: M (modified), D (deleted), A (added).
- **Deleted files:** remove all matching rows from `nodes`, `edges`, `vec_neurons`, and `file_hashes` within the transaction. Re-index any graph neighbors (depth=2 BFS) that referenced the deleted nodes.
- **Modified/added files:** re-parse, run BFS depth=2 from each changed node to find affected neighbors. Re-index only those nodes, edges, and vectors.
- **Atomicity:** all writes wrapped in one SQLite transaction (BEGIN → all writes → COMMIT). On any failure, full rollback. `file_hashes` rows for affected files and `state_hash` only updated on COMMIT.
- Rewrite only affected `lobe.md` files. Recompute `state_hash`. Target latency: **< 2 seconds** for a single-file change.
- Uses depth=2 matching Blast Radius depth to prevent stale second-hop query results.

#### 3.2 Pre-Push Hook & cerebrofy validate

`cerebrofy validate` is a **standalone command AND** the function invoked automatically by the pre-push git hook. Both code paths are identical.

- **Step 1 — Hash scan:** compute SHA-256 of every tracked source file. Compare against `file_hashes` table in `cerebrofy.db`. Files whose hash differs are candidates for drift classification.
- **Step 2 — Drift classification** (only for changed files): re-parse each changed file with Tree-sitter. Diff the resulting Neuron list against the current `nodes` table.
  - Same function names/signatures, only comments/whitespace changed → **MINOR drift** → WARN, suggest `cerebrofy update`, allow push.
  - Any function added, removed, renamed, or signature changed; or any import added/removed → **STRUCTURAL drift** → HARD BLOCK. Exit code 1. Print list of unsynced Neurons by name and file.
  - `.cerebrofy/` missing or `cerebrofy.db` missing → **WARN only**, print `cerebrofy init` instructions. Never block.

#### 3.3 Post-Merge Hook (Sync Check)

- Runs automatically after `git pull` / `git merge`.
- Compares remote `state_hash` (from pulled `cerebrofy_map.md`) against local `state_hash` (from `cerebrofy.db` meta).
  - **Match** → no action.
  - **Differ** → WARN: *"Remote index differs from local. Run `cerebrofy build` to resync."* No automatic merge attempted in v1.

---

### Phase 4 — AI Bridge

#### 4.1 cerebrofy specify

- **CLI:** `cerebrofy specify "<feature description>"`
- Reads `.cerebrofy/config.yaml` for LLM endpoint (default: OpenAI; configurable to any OpenAI-compatible API).
- Runs hybrid search (see 4.2) with default `top_k=10`. Auto-injects matching `lobe.md` files into the system prompt.
- **Output:** Markdown spec written to `docs/cerebrofy/specs/<timestamp>_spec.md`

#### 4.2 cerebrofy plan & cerebrofy tasks

- **CLI:** `cerebrofy plan "<description>"` | `cerebrofy tasks "<description>"`
- **Hybrid search:**
  1. sqlite-vec KNN query on `vec_neurons` — returns `top_k` nearest Neurons by cosine similarity (default `top_k=10`, configurable in `config.yaml`).
  2. BFS depth=2 from each matched Neuron to compute Blast Radius.
  3. Merge + deduplicate. Both queries run in the same SQLite connection — no IPC overhead.
- **plan output:** Markdown to stdout listing: matched Neurons, Blast Radius set, affected lobe files, estimated re-index scope.
- **tasks output:** Numbered task list with direct Neuron links e.g. *"Modify validate() in [[auth_lobe]], blast radius: 7 nodes"*.

---

## IV. Storage Design — cerebrofy.db

All Cerebrofy state lives in a single file: `.cerebrofy/db/cerebrofy.db`. Graph tables and the vector virtual table share one SQLite connection. One file to back up, copy, diff, or delete. The `.tmp` swap pattern ensures it is never corrupted by an interrupted build.

### Graph Schema

```sql
CREATE TABLE nodes (
  id          TEXT PRIMARY KEY,  -- "{file}::{name}"
  name        TEXT NOT NULL,
  file        TEXT NOT NULL,
  type        TEXT,              -- function | class | module
  line_start  INTEGER,
  line_end    INTEGER,
  hash        TEXT               -- SHA-256 of source span
);

CREATE TABLE edges (
  src_id    TEXT REFERENCES nodes(id),
  dst_id    TEXT REFERENCES nodes(id),
  rel_type  TEXT,                -- LOCAL_CALL | EXTERNAL_CALL | IMPORT | RUNTIME_BOUNDARY
  file      TEXT,
  PRIMARY KEY (src_id, dst_id, rel_type)
);

CREATE TABLE meta (
  key    TEXT PRIMARY KEY,
  value  TEXT
);
-- meta keys:
--   state_hash     : SHA-256 of all tracked file hashes (defines sync state)
--   last_build     : ISO-8601 timestamp of last full cerebrofy build
--   schema_version : integer, checked on open for migration
--   embed_model    : name of configured embedding model
--   embed_dim      : integer dimension of vec_neurons vectors

-- Per-file hash index: used by cerebrofy validate for drift classification
CREATE TABLE file_hashes (
  file  TEXT PRIMARY KEY,  -- relative path from repo root
  hash  TEXT NOT NULL      -- SHA-256 of file content at last build/update
);
```

### Vector Schema (sqlite-vec)

```sql
-- Extension loaded once at connection open:
-- conn.enable_load_extension(True)
-- conn.load_extension("vec0")

-- IMPORTANT: dimension is NOT hardcoded. cerebrofy build reads embed_dim
-- from config.yaml and generates this statement dynamically, e.g.:
--   dim = config["embed_dim"]  # 768 for nomic, 1536 for OpenAI, 1024 for Cohere
--   conn.execute(f"CREATE VIRTUAL TABLE vec_neurons USING vec0(
--       id TEXT PRIMARY KEY, embedding FLOAT[{dim}])")
-- Changing the model requires DROP + recreate, handled automatically by cerebrofy build.

CREATE VIRTUAL TABLE vec_neurons USING vec0(
  id         TEXT PRIMARY KEY,
  embedding  FLOAT[{embed_dim}]  -- dimension resolved from config at build time
);

-- Hybrid search example:
SELECT n.id, n.name, n.file,
       vec_distance_cosine(v.embedding, ?) AS dist
FROM   vec_neurons v JOIN nodes n ON n.id = v.id
ORDER  BY dist LIMIT 10;
```

> 💡 **KEY BENEFIT:** `vec_neurons` and `nodes` share the same SQLite connection. A full Hybrid Search (KNN semantic + BFS graph) is one Python function with zero network calls, zero serialization, and zero IPC. Blast Radius + semantic results merge in-memory in microseconds.

### Schema Migration

- `schema_version` is read on every connection open.
- If version matches installed Cerebrofy → proceed normally.
- If version is older → `cerebrofy migrate` runs auto-migration scripts from `.cerebrofy/scripts/migrations/` (e.g. `v1_to_v2.py`). Scripts applied sequentially.
- If no migration script exists for the version gap → prompt: *"Schema incompatible. Run `cerebrofy build` to rebuild from source."*
- `cerebrofy.db` is never opened for writes without a version check.

---

## V. File Tracking & Ignore Rules

`state_hash` correctness depends on a deterministic, consistent definition of which files are tracked. These rules apply on every `cerebrofy build`, `cerebrofy update`, and `cerebrofy validate` run.

### Tracking Definition

- A file is **tracked** if: its extension matches `tracked_extensions` in `config.yaml` **AND** it is not matched by `.cerebrofy-ignore` **AND** it is not matched by `.gitignore`.
- `state_hash = SHA-256( sorted list of SHA-256(file_content) for every tracked file )`
- This definition is deterministic across machines because both ignore files are evaluated on the local working tree.

### Default .cerebrofy-ignore

```
# Cerebrofy default ignore list — edit to customize
node_modules/
__pycache__/
.git/
dist/
build/
out/
vendor/
.venv/
venv/
*.min.js
*.min.css
*.map
*.lock
*.pyc
*.egg-info/
coverage/
.nyc_output/
```

### config.yaml Structure

```yaml
# .cerebrofy/config.yaml — generated by cerebrofy init, editable by user
lobes:
  auth:    src/auth/
  api:     src/api/
  utils:   src/utils/

tracked_extensions:
  - .py
  - .js
  - .ts
  - .tsx
  - .jsx
  - .go
  - .rs
  - .java
  - .rb
  - .cpp
  - .c
  - .h

embedding_model: local        # local | openai | cohere
embed_dim: 768                # 768 (local/nomic) | 1536 (openai) | 1024 (cohere)
                              # cerebrofy build reads this to generate CREATE VIRTUAL TABLE

llm_endpoint: openai          # for cerebrofy specify/plan/tasks
llm_model: gpt-4o             # any OpenAI-compatible model name
top_k: 10                     # number of nearest Neurons returned by KNN search
                              # used by cerebrofy specify, plan, and tasks
```

---

## VI. Blast Radius — Formal Definition

Blast Radius is the set of nodes structurally at risk when a target node changes. Computed as a bounded, bidirectional BFS from the target node in `cerebrofy.db`.

```python
def blast_radius(db: sqlite3.Connection, target_id: str, depth: int = 2) -> set[str]:
    visited = set()
    queue   = [(target_id, 0)]
    while queue:
        node, d = queue.pop(0)
        if node in visited or d > depth:
            continue
        visited.add(node)
        # Traverse both directions: callers (inbound) + callees (outbound)
        rows = db.execute(
            "SELECT src_id FROM edges WHERE dst_id = ? "
            "UNION SELECT dst_id FROM edges WHERE src_id = ?",
            (node, node)
        ).fetchall()
        for (neighbor,) in rows:
            queue.append((neighbor, d + 1))
    return visited - {target_id}
```

| Property | Detail |
|----------|--------|
| **Default depth** | 2 — matches the re-index depth in `cerebrofy update` to prevent stale second-hop results. |
| **Cycle safety** | `visited` set prevents infinite loops in circular call graphs. |
| **RUNTIME_BOUNDARY edges** | Excluded from traversal. Cross-language HTTP/FFI calls surfaced as a separate warning in `cerebrofy plan` output. |
| **Performance** | BFS on a 10,000-node graph at depth=2 completes in < 10ms via indexed SQLite edge queries. Scales to 100k nodes without architectural changes. |

---

## VII. Embedding Model Strategy

The embedding model is configured in `config.yaml` at `cerebrofy init` time, but written to meta by `cerebrofy build` Step 0 — the sole creator of `cerebrofy.db`. The `vec_neurons` virtual table dimension (`FLOAT[N]`) is fixed at build time and cannot change without a full `cerebrofy build`.

| Option | Detail |
|--------|--------|
| **Default (local)** | `nomic-embed-text` via `sentence-transformers`. No API key, fully offline, 768-dim. Works on any machine with Python. Default for all new projects. |
| **Override: OpenAI** | Set `embedding_model: openai` in `config.yaml`. Uses `text-embedding-3-small` (1536-dim). Requires `OPENAI_API_KEY` env var. |
| **Override: Cohere** | Set `embedding_model: cohere` in `config.yaml`. Uses `embed-english-v3.0` (1024-dim). Requires `COHERE_API_KEY`. |
| **Model switch** | Change `embedding_model` in `config.yaml`, then run `cerebrofy build`. The old `vec_neurons` table is dropped and rebuilt at the new dimension. `cerebrofy validate` blocks queries if `embed_model` in meta mismatches `config.yaml`. |

---

## VIII. Multi-Developer Workflow

`cerebrofy.db` is a **local artifact — it is not committed to git**. Each developer builds and maintains their own index. Synchronization is handled via the `state_hash` in `cerebrofy_map.md`, which **IS committed**.

### Normal Workflow

1. Developer runs `cerebrofy build` once after cloning.
2. Developer uses `cerebrofy update` after each editing session (or pre-push hook triggers `validate` automatically).
3. `cerebrofy_map.md` is committed as part of normal code changes — it reflects the last indexed state of the codebase.

### After git pull / merge

- Post-merge hook compares remote `state_hash` (from pulled `cerebrofy_map.md`) against local `state_hash` (from `cerebrofy.db` meta).
  - **Match** → nothing to do.
  - **Differ** → WARN: *"Remote index state differs. Run `cerebrofy build` to resync."* No automatic merge. No data loss possible.

### On first clone

- `.cerebrofy/` does not exist. `cerebrofy validate` warns: *"No index found. Run `cerebrofy init && cerebrofy build` to initialize."*
- No push is blocked on first clone. Hard-block only activates once a valid `cerebrofy.db` exists and has been out of sync.

---

## IX. Command Reference

| Command | Action | Phase | Neural Equiv. |
|---------|--------|-------|---------------|
| `cerebrofy init` | Scaffold `.cerebrofy/`, `config.yaml`, `.cerebrofy-ignore`, git hooks (no DB — created by build) | Phase 1 | Gestation |
| `cerebrofy build` | Full atomic build: parse + graph + vectors + Markdown | Phase 2 | Cognition |
| `cerebrofy update [files]` | Incremental re-index of changed files + depth=2 neighbors | Phase 3 | Neuroplasticity |
| `cerebrofy validate` | Tiered sync check: drift classification + WARN or BLOCK | Phase 3 | Proprioception |
| `cerebrofy migrate` | Apply schema migration scripts after Cerebrofy version upgrade | Phase 3 | Adaptation |
| `cerebrofy specify <desc>` | LLM spec generation with lobe context injection | Phase 4 | Intentionality |
| `cerebrofy plan <desc>` | Hybrid KNN + BFS search: matched neurons + blast radius | Phase 4 | Foresight |
| `cerebrofy tasks <desc>` | Task list with Neuron links and re-index scope estimate | Phase 4 | Motor Output |

---

## X. Performance Targets (Benchmarks)

*The following are engineering targets to be validated during implementation, not guaranteed results.*

| Target | Detail |
|--------|--------|
| **Token compression** | 20,000 LOC (~600k tokens) → 10 Module Lobes (~15k tokens) — a ~97% reduction in context per query. Actual ratio depends on docstring density. |
| **Graph lookup** | O(1) indexed SQLite edge query vs. O(n) LLM guessing. No approximation. |
| **Blast Radius query** | BFS depth=2 on 10k-node graph: target < 10ms. Validated against real repos in Phase 3. |
| **Incremental update latency** | `cerebrofy update` on a single changed file: target < 2 seconds end-to-end. |
| **Per-query cost** | Estimated 90%+ reduction vs. raw file dumping by serving structured lobe Markdown + targeted vector results. To be measured post-implementation. |

---

## XI. Distribution & Installation

Cerebrofy ships as a self-contained binary on every platform. The install is one command. MCP registration is automatic on `cerebrofy init`. No manual AI tool configuration required.

### Distribution Matrix

| Platform | Package Manager | Command |
|----------|----------------|---------|
| **macOS** | Homebrew (custom tap) | `brew tap cerebrofy/tap && brew install cerebrofy` |
| **Linux (any)** | Snap | `snap install cerebrofy --classic` |
| **Windows 10/11** | winget | `winget install cerebrofy` |
| **Universal fallback** | pip | `pip install cerebrofy` |

> **Homebrew note:** Custom tap for v1 — ships immediately. Migration to `homebrew-core` deferred until adoption warrants it.

### Windows Bundle — Technical Requirements

The winget package ships a self-contained `.exe` built with Nuitka (v1 accepts 2–5 second cold start; startup optimization deferred to v2). The bundle must include:

- **sqlite-vec for Windows:** `vec0.dll` bundled alongside the `.exe`. MSVC redistributable (`VC_redist.x64.exe`) bundled and silently installed by the winget installer if not already present.
- **Tree-sitter grammars:** pre-compiled `.dll` files for all supported languages built on Windows CI runners and embedded in the bundle. No C compiler required on the user's machine.
- **Python runtime:** fully embedded via Nuitka compilation. No system Python dependency.
- **winget manifest `Commands` field** set to `cerebrofy`, ensuring the binary is added to `%PATH%` automatically post-install. No manual PATH editing required.

> ⚠️ **Known v1 limitation:** The Nuitka-compiled `.exe` has a 2–5 second cold start time on Windows. This affects the pre-push hook (`cerebrofy validate` runs on every push). Accepted for v1. v2 will address this with a persistent background daemon or a lightweight compiled launcher. Users are informed in the install documentation.

### MCP Server Auto-Registration

`cerebrofy init` automatically registers Cerebrofy as an MCP server after scaffolding. The developer never manually edits an AI tool config file.

- **Default (project-level):** A single global MCP entry points to a cerebrofy dispatcher that reads the current working directory at invocation time. Running `cerebrofy init` in multiple repos does not create duplicate entries — the dispatcher handles routing.
- **Opt-in (global):** `cerebrofy init --global` registers a machine-wide entry. Same dispatcher pattern.
- `cerebrofy init` checks MCP config paths in the following priority order, writes to the first one found, and reports exactly what it wrote:
  1. **Claude Desktop** (macOS): `~/Library/Application Support/Claude/claude_desktop_config.json`
  2. **Claude Desktop** (Windows): `%APPDATA%\Claude\claude_desktop_config.json`
  3. **Cursor** (macOS/Linux): `~/.cursor/mcp.json`
  4. **Cursor** (Windows): `%APPDATA%\Cursor\mcp.json`
  5. **Opencode:** `~/.config/opencode/mcp.json`
  6. **Generic MCP standard** (Windsurf, others): `~/.config/mcp/servers.json`
  7. **Fallback:** create `~/.config/mcp/servers.json` and print a note listing which tools will auto-detect it.
- On version mismatch (multiple Cerebrofy installations detected): warns, identifies all installed versions by path, prints specific remediation steps. Does not silently overwrite.

### CI/CD Release Pipeline

Every tagged release triggers a GitHub Actions workflow that builds all platform artifacts and publishes them automatically. The one exception is winget, which requires a human review step.

- **Step 1 — Build matrix:** parallel jobs on `ubuntu-latest` (snap + pip), `macos-latest` (Homebrew bottle), `windows-latest` (Nuitka `.exe` + winget manifest). Pre-compile Tree-sitter grammar DLLs on the Windows runner.
- **Step 2 — Artifact hashes:** SHA-256 of every binary computed and attached to the GitHub Release. winget and Homebrew manifests reference these hashes for integrity verification.
- **Step 3 — Homebrew tap:** CI auto-commits an updated Formula to the `cerebrofy/homebrew-cerebrofy` tap repository. `brew upgrade cerebrofy` picks it up immediately.
- **Step 4 — Snap Store:** CI pushes to the Snap Store via `snapcraft remote-build`. Auto-updates propagate to all snap-installed users within 24 hours.
- **Step 5 — winget PR:** CI opens a PR against `microsoft/winget-pkgs` with the updated manifest. Microsoft review is manual, typically 1–5 business days. Release notes document this so users know winget lags by a few days.
- **Step 6 — PyPI:** `pip install cerebrofy` updated via `twine publish`. Available immediately.

> ⚠️ **One-time Snap Store step:** The Snap Store requires manual review before granting `--classic` confinement (which Cerebrofy needs for unrestricted filesystem access to arbitrary repos). Submit the confinement request before the first public release. Estimated review time: 1–2 weeks. Until approved, the snap is available in strict mode with manual filesystem permissions, or via pip as a fallback.

---

## XII. Gap Resolution Log

*All 39 issues across all review cycles have been resolved. This document is implementation-ready.*

| ID | Resolution |
|----|-----------|
| GAP 1 | `cerebrofy build` and `cerebrofy connect` collapsed into a single atomic command. |
| GAP 2 | All DB references standardized to `cerebrofy.db`. `connectome.db` retired. |
| GAP 3 | `cerebrofy merge` descoped for v1. Post-merge hook WARNS + requires manual `cerebrofy build`. |
| GAP 4 | Lobe auto-proposal algorithm defined: `src/` dirs, monorepo detection, max depth 2. |
| GAP 5 | Phase 4 commands have defined CLI signatures, output formats, and LLM config path. |
| GAP 6 | `state_hash` defined as SHA-256 of sorted per-file SHA-256 hashes for all tracked files. |
| GAP 7 | Neuron chunking rules fully defined for functions, module-level code, classes, and config files. |
| GAP 8 | `cerebrofy update` depth unified to 2, matching Blast Radius depth. |
| GAP 9 | `.cerebrofy-ignore` defined with default ignore list. |
| GAP 10 | Atomic build via `.tmp` swap. Interrupted builds leave no corrupted state. |
| GAP 11 | Schema versioning and migration path defined with sequential migration scripts. |
| GAP 12 | ROI claims relabeled as engineering targets/benchmarks. |
| v4 ISSUE 1 | Duplicate `.cerebrofy/` entry removed. `specs/` and `migrations/` added to directory tree. |
| v4 ISSUE 2 | `cerebrofy validate` clarified as both standalone command and hook-invoked function. |
| v4 ISSUE 3 | `cerebrofy update` atomicity via SQLite transaction. Full rollback on failure. |
| v4 CLARIF. A | `file_hashes` table added to schema. `cerebrofy validate` reads from it for per-file drift. |
| v4 CLARIF. B | `.cerebrofy/scripts/migrations/` added to directory tree. |
| v4.1 GAP A | `cerebrofy validate` two-step drift logic: hash scan → re-parse + Neuron diff to classify. |
| v4.1 GAP B | `ignore_patterns` removed from `config.yaml`. `.cerebrofy-ignore` is the single canonical source. |
| v4.1 GAP C | `cerebrofy build` Step 6 explicitly populates `file_hashes` table. `cerebrofy update` COMMIT also updates it. |
| v4.1 GAP D | `cerebrofy update` handles deleted files: purges nodes/edges/vec_neurons/file_hashes; re-indexes depth=2 neighbors. |
| v4.1 GAP E | `vec_neurons` dimension dynamic. `cerebrofy build` Step 0 generates `CREATE VIRTUAL TABLE` from `embed_dim` in `config.yaml`. |
| v4.2 ISSUE 1 | Directory tree `config.yaml` comment corrected: "ignore rules" removed. |
| v4.2 ISSUE 2 | Change detection: three-command combination covering modified, deleted, and new untracked files. |
| v4.2 ISSUE 3 | `top_k` default defined as 10. Configurable via `top_k` in `config.yaml`. |
| v4.3 ISSUE 1 | `cerebrofy init` no longer creates `cerebrofy.db`. `cerebrofy build` Step 0 is sole DB creator. |
| v4.3 ISSUE 2 | Missing v4.1 GAP E entry restored to gap resolution log. |
| v4.4 STALE REF 1 | Section VII intro corrected: embed model configured at init, written to meta by `cerebrofy build` Step 0. |
| v4.4 STALE REF 2 | `config.yaml` `embed_dim` comment corrected: "cerebrofy build reads this" (not init). |
| DIST GAP 1 | sqlite-vec Windows DLL + MSVC redistributable bundled in the Nuitka `.exe`. No VC++ pre-install required. |
| DIST GAP 2 | Tree-sitter grammars pre-compiled as `.dll` files on Windows CI runners. No C compiler on user machines. |
| DIST GAP 3 | `cerebrofy init` checks MCP config paths in priority order, reports exact write location, falls back gracefully. |
| DIST GAP 4 | CI opens winget PR automatically. Release notes document 1–5 business day Microsoft review lag. |
| DIST GAP 5 | Snap Store `--classic` approval documented as one-time manual step (~1–2 weeks). pip is the fallback. |
| DIST GAP 6 | Global MCP registration uses dispatcher pattern. Multiple `cerebrofy init` runs create one entry, not duplicates. |
| DIST GAP 7 | Windows 2–5 second cold start accepted for v1. Documented as known limitation. v2 roadmap item. |
| DIST GAP 8 | winget manifest `Commands` field set to `cerebrofy`. Binary on `%PATH%` automatically post-install. |
| DIST GAP 9 | Homebrew ships via custom tap (`cerebrofy/tap`) for v1. Migration to `homebrew-core` deferred. |
| DIST GAP 10 | `cerebrofy init` detects all installed versions on mismatch, prints all paths, provides remediation steps. |

---

*Cerebrofy — Blueprint v5.0 · 39/39 Issues Resolved · Implementation Ready*
