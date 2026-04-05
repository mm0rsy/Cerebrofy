# Cerebrofy — Architecture Guide

This document describes the internal structure, data flow, key invariants, and extension points of Cerebrofy. It is aimed at contributors and anyone who wants to understand how the system works beneath the CLI.

---

## Module Map

```
src/cerebrofy/
├── cli.py                        ← Click command group — registers all sub-commands
│
├── commands/
│   ├── init.py                   ← cerebrofy init: scaffold, hooks, MCP registration
│   ├── build.py                  ← cerebrofy build: 6-step atomic pipeline
│   ├── update.py                 ← cerebrofy update: partial atomic re-index
│   ├── validate.py               ← cerebrofy validate: drift classification
│   ├── migrate.py                ← cerebrofy migrate: sequential schema migrations
│   ├── plan.py                   ← cerebrofy plan: hybrid search → Markdown/JSON report
│   ├── tasks.py                  ← cerebrofy tasks: hybrid search → numbered task list
│   ├── specify.py                ← cerebrofy specify: hybrid search → LLM → spec file
│   ├── parse.py                  ← cerebrofy parse: read-only diagnostic parser (NDJSON)
│   └── mcp.py                    ← cerebrofy mcp: MCP stdio server entry point
│
├── parser/
│   ├── engine.py                 ← Tree-sitter runner; dispatches to .scm queries
│   └── neuron.py                 ← Neuron dataclass + ParseResult + deduplicate_neurons
│
├── graph/
│   ├── edges.py                  ← Edge dataclass + rel_type constants
│   └── resolver.py               ← Two-pass name lookup: local + cross-module edges
│
├── embedder/
│   ├── base.py                   ← Embedder ABC: embed(texts) -> list[list[float]]
│   ├── local.py                  ← LocalEmbedder (sentence-transformers, batch 64)
│   ├── openai_emb.py             ← OpenAIEmbedder (text-embedding-3-small, chunks 512)
│   └── cohere_emb.py             ← CohereEmbedder (embed-english-v3.0, chunks 96)
│
├── db/
│   ├── connection.py             ← open_db(): load sqlite-vec + WAL; check_schema_version()
│   ├── schema.py                 ← DDL constants (CREATE TABLE / INDEX / VIRTUAL TABLE)
│   ├── writer.py                 ← write_nodes(), write_edges(), upsert_vectors(), etc.
│   └── lock.py                   ← BuildLock: PID file acquire/release/stale-check
│
├── search/
│   └── hybrid.py                 ← HybridSearch: KNN + BFS, single read-only connection
│
├── llm/
│   ├── client.py                 ← LLMClient: streaming, retry on 5xx, wall-clock timeout
│   └── prompt_builder.py         ← PromptBuilder: string.Template + lobe context injection
│
├── markdown/
│   ├── lobe.py                   ← write_lobe_md(): per-lobe Markdown file
│   └── map.py                    ← write_map_md(): cerebrofy_map.md
│
├── hooks/
│   └── installer.py              ← install_hooks(), upgrade_hook(), add_gitignore_entry()
│
├── ignore/
│   └── ruleset.py                ← IgnoreRuleSet (pathspec, gitignore dialect)
│
├── mcp/
│   ├── registrar.py              ← MCP config path detection + idempotent write
│   └── server.py                 ← MCPServer: plan/tasks/specify tool handlers
│
├── config/
│   └── loader.py                 ← CerebrоfyConfig dataclass + YAML I/O
│
├── update/
│   ├── change_detector.py        ← ChangeSet via git diff or hash comparison
│   └── scope_resolver.py         ← UpdateScope via depth-2 BFS from changed nodes
│
└── validate/
    └── drift_classifier.py       ← DriftRecord: hash scan → re-parse → Neuron diff
```

---

## Data Flow

### `cerebrofy build`

```
config.yaml + .cerebrofy-ignore
        │
        ▼
   parse_directory()              ← Tree-sitter + .scm queries → list[ParseResult]
        │
        ▼
   write_nodes(conn, neurons)     ← INSERT into nodes table
        │
        ├── resolve_local_edges() → LOCAL_CALL edges
        └── resolve_cross_module_edges() + resolve_import_edges()
                                  → EXTERNAL_CALL, IMPORT, RUNTIME_BOUNDARY edges
        │
        ▼
   write_edges(conn, edges)       ← INSERT into edges table
        │
        ▼
   embedder.embed(texts)          ← list[Neuron] → list[list[float]]
        │
        ▼
   upsert_vectors(conn, ...)      ← INSERT into vec_neurons (sqlite-vec)
        │
        ▼
   build_step5_commit()           ← compute state_hash, write file_hashes, conn.commit()
        │
        ▼
   os.replace(.tmp → .db)         ← ATOMIC SWAP (only on full success)
        │
        ▼
   write_lobe_md() × N            ← per-lobe Markdown (post-swap, fresh conn)
   write_map_md()                 ← cerebrofy_map.md
```

### `cerebrofy plan` / `cerebrofy tasks`

```
DESCRIPTION (string)
        │
        ▼
   _embed_query()                 ← same embedder as build
        │
        ▼
   hybrid_search()                ← one read-only SQLite connection
        │
        ├── _run_knn_query()      ← vec_neurons KNN (cosine similarity)
        ├── _run_bfs()            ← depth-2 from matched neurons (excludes RUNTIME_BOUNDARY)
        ├── _resolve_affected_lobes()
        └── _count_bfs_neighbors() × N  ← per-neuron blast_count
        │
        ▼
   HybridSearchResult
        │
        ├── plan: _format_plan_markdown() or _format_plan_json()
        └── tasks: _build_task_items() → _format_tasks_markdown()
```

### `cerebrofy specify`

```
DESCRIPTION
        │
        ▼
   Pre-flight connection (read meta only) → check schema + embed model match → close
        │
        ▼
   _embed_query()                 ← embed before opening main DB connection
        │
        ▼
   hybrid_search()                ← same as plan/tasks
        │
        ▼
   build_llm_context()            ← load lobe .md files → LLMContextPayload
        │
        ▼
   LLMClient.call()               ← stream=True, retry once on 5xx, wall-clock timeout
        │
        ▼
   collect full response → write to docs/cerebrofy/specs/<timestamp>_spec.md
```

---

## Database Schema

Single file: `.cerebrofy/db/cerebrofy.db`

```sql
-- Named code units (functions, classes, modules)
CREATE TABLE nodes (
  id          TEXT PRIMARY KEY,   -- "{file}::{name}"
  name        TEXT NOT NULL,
  file        TEXT NOT NULL,      -- path relative to repo root
  type        TEXT,               -- "function" | "class" | "module"
  line_start  INTEGER,
  line_end    INTEGER,
  signature   TEXT,
  docstring   TEXT,
  hash        TEXT                -- SHA-256 of the source span
);
CREATE INDEX idx_nodes_file ON nodes(file);
CREATE INDEX idx_nodes_name ON nodes(name);

-- Typed call/import edges between Neurons
CREATE TABLE edges (
  src_id    TEXT REFERENCES nodes(id),
  dst_id    TEXT,
  rel_type  TEXT NOT NULL,        -- LOCAL_CALL | EXTERNAL_CALL | IMPORT | RUNTIME_BOUNDARY
  file      TEXT,
  PRIMARY KEY (src_id, dst_id, rel_type)
);
CREATE INDEX idx_edges_src ON edges(src_id);
CREATE INDEX idx_edges_dst ON edges(dst_id);

-- Key-value metadata
CREATE TABLE meta (
  key    TEXT PRIMARY KEY,
  value  TEXT
);
-- Keys: schema_version, embed_model, embed_dim, state_hash, last_build

-- Per-file content hashes (for drift detection)
CREATE TABLE file_hashes (
  file  TEXT PRIMARY KEY,
  hash  TEXT NOT NULL             -- SHA-256 of file content at last build/update
);

-- sqlite-vec virtual table for KNN search
CREATE VIRTUAL TABLE vec_neurons USING vec0(
  id          TEXT PRIMARY KEY,
  embedding   FLOAT[768]          -- dimension from embed_dim in meta
);
```

Every `nodes` row has a corresponding `vec_neurons` row after a completed build (Law III). The `vec_neurons` table cannot be updated in-place — the `cerebrofy update` command always DELETE+INSERT within the same transaction.

---

## Key Invariants

These rules are architectural constraints. No PR may violate them.

| # | Invariant |
|---|-----------|
| I | `cerebrofy init` MUST NOT create `cerebrofy.db`. The database is created exclusively by `cerebrofy build`. |
| II | All call edges are stored in the `edges` table. `RUNTIME_BOUNDARY` edges are stored but NEVER traversed in BFS. They are collected as warnings and shown separately. |
| III | Every Neuron in `nodes` MUST have a corresponding row in `vec_neurons` after a completed build. |
| IV | Git hooks start warn-only (v1). Hard-block (v2) activates only after `cerebrofy update` is verified to run in < 2s. |
| V | Zero language-specific logic in `parser/engine.py` or `graph/resolver.py`. All language rules live in `.scm` files. |
| — | `cerebrofy build` writes to `cerebrofy.db.tmp`; swaps via `os.replace()` on success only. |
| — | `cerebrofy update` wraps all DML in `BEGIN IMMEDIATE`. `vec0` does not support UPDATE — always DELETE+INSERT within same transaction. |
| — | `cerebrofy specify`, `plan`, `tasks`, `parse` MUST NOT write to `cerebrofy.db` or any tracked source file. |
| — | `cerebrofy plan` and `tasks` MUST make zero network calls even if `llm_endpoint` is configured. |
| — | Every `open_db()` call loads sqlite-vec and sets WAL mode. Read-only commands open with `?mode=ro` directly (skipping WAL) and load sqlite-vec manually. |
| — | `blast_count` per task item = depth-2 BFS neighbors reachable from **that specific Neuron** (not total across all matched Neurons). |
| — | `schema_version` in `plan --json` output is always `1`. All four top-level arrays (`matched_neurons`, `blast_radius`, `affected_lobes`, `reindex_scope`) are always present, even if empty. |

---

## The Neuron

The `Neuron` is the fundamental unit of the Cerebrofy index:

```python
@dataclass(frozen=True)
class Neuron:
    id: str           # "{file}::{name}" — globally unique
    name: str         # function/class/module name
    type: str         # "function" | "class" | "module"
    file: str         # relative path from repo root
    line_start: int   # 1-based
    line_end: int     # 1-based, inclusive
    signature: str | None
    docstring: str | None
```

Neurons are **immutable value objects** (`frozen=True`). Within a single file, if the same `id` appears more than once (e.g. duplicate function names), only the first occurrence by `line_start` is kept (`deduplicate_neurons()`). Anonymous functions (lambdas, arrow functions) are never captured.

---

## Edge Types

| Type | Meaning |
|------|---------|
| `LOCAL_CALL` | Function call resolved within the same file |
| `EXTERNAL_CALL` | Function call resolved to another file via the name registry |
| `IMPORT` | Import statement resolved to the imported module's Neurons |
| `RUNTIME_BOUNDARY` | Unresolvable cross-language or dynamic call — stored but never traversed in BFS |

`RUNTIME_BOUNDARY` edges represent calls that cross a language boundary (e.g. Python calling a C extension) or are too dynamic to resolve statically. They appear as warnings in `cerebrofy plan` and `cerebrofy tasks` output.

---

## Hybrid Search

`hybrid_search()` in `search/hybrid.py` combines two search strategies in a single read-only SQLite connection:

1. **KNN search** — `vec_neurons` cosine similarity query, returns `top_k` `MatchedNeuron` objects ordered by similarity descending
2. **BFS expansion** — depth-2 BFS from each matched Neuron's seed ID, collecting `BlastRadiusNeuron` objects (excludes `RUNTIME_BOUNDARY` edges)
3. **Lobe resolution** — derives affected lobe names from file paths, loads lobe `.md` paths
4. **Per-neuron blast count** — runs `_count_bfs_neighbors()` for each individual matched Neuron while the connection is open

```
similarity = 1.0 - (cosine_distance / 2.0)
```

The connection is opened with `?mode=ro` (read-only) to avoid any accidental writes. sqlite-vec is loaded manually (bypassing `open_db()` which sets WAL pragma, incompatible with `?mode=ro`).

---

## `plan --json` Schema

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

`schema_version` is always the first field and always `1`. All four top-level arrays are always present (never omitted, even when empty). Consumers SHOULD check `schema_version` before parsing.

---

## Git Hook Lifecycle

```
cerebrofy init
    └── install pre-push hook (version 1, warn-only)
            # BEGIN cerebrofy
            # cerebrofy-hook-version: 1
            cerebrofy validate --hook pre-push
            # END cerebrofy

cerebrofy update  (completes in < 2s)
    └── upgrade_hook() → version 2 (hard-block, idempotent)
            # BEGIN cerebrofy
            # cerebrofy-hook-version: 2
            if ! cerebrofy validate --hook pre-push; then
                echo 'Cerebrofy: Structural drift detected. Run cerebrofy update to sync.'
                exit 1
            fi
            # END cerebrofy
```

The sentinel format `# BEGIN cerebrofy` / `# cerebrofy-hook-version: N` / `# END cerebrofy` allows `upgrade_hook()` to locate and replace exactly the Cerebrofy block without disturbing any pre-existing hook logic.

---

## Adding Language Support

Cerebrofy is designed so that new language support requires zero changes to the Python engine. You only need to provide a Tree-sitter `.scm` query file.

### Steps

1. Verify the language is in `EXTENSION_TO_LANGUAGE` in `parser/engine.py`. If not, open a PR to add the extension mapping.

2. Create `.cerebrofy/queries/<lang>.scm` (or install it into `src/cerebrofy/queries/` for bundled support).

3. The query file must capture these node names:

| Capture name | Meaning |
|--------------|---------|
| `definition.name` | Name node of a function/method/class definition |
| `definition.node` | The full definition node (for extracting line range) |
| `call.name` | Name node of a function call expression |
| `import.path` | The module path being imported |

4. Add the extension to `tracked_extensions` in `.cerebrofy/config.yaml`.

5. Run `cerebrofy build` to index the new language.

### Example (Python fragment)

```scheme
; Capture function definitions
(function_definition
  name: (identifier) @definition.name) @definition.node

; Capture class definitions
(class_definition
  name: (identifier) @definition.name) @definition.node

; Capture call expressions
(call
  function: (identifier) @call.name)

; Capture imports
(import_from_statement
  module_name: (dotted_name) @import.path)
```

The engine processes only the captures listed above. Any other captures in the `.scm` file are ignored.

---

## MCP Dispatcher

The MCP server (`mcp/server.py`) uses **CWD routing**: at each tool invocation, it calls `os.getcwd()` and walks up the directory tree looking for `.cerebrofy/config.yaml`. This means a single registered MCP server entry (`mcpServers.cerebrofy`) serves all repos on the machine — no per-repo registration needed.

```
AI tool calls cerebrofy/plan with description="add rate limiting"
    │
    ▼
run_mcp_server() → call_tool("plan", {"description": "..."})
    │
    ▼
_find_repo_root(Path.cwd())   ← reads CWD at call time
    │
    ▼
load_config(root / ".cerebrofy/config.yaml")
    │
    ▼
hybrid_search(...)            ← same logic as CLI cerebrofy plan
    │
    ▼
returns TextContent(type="text", text=<json>)
```

---

## Testing

```bash
# All tests
uv run pytest

# Unit tests only (fast, no filesystem)
uv run pytest tests/unit/

# Integration tests (use tmp_path, parse real Python files)
uv run pytest tests/integration/

# Specific command
uv run pytest tests/integration/test_plan_command.py -v
```

Integration tests use `pytest`'s `tmp_path` fixture exclusively — they never touch the real filesystem outside `tmp_path`. No mocking of the database; tests build a real `cerebrofy.db` in a temporary directory.
