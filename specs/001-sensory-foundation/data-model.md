# Data Model: Phase 1 — Sensory Foundation

**Feature**: 001-sensory-foundation
**Date**: 2026-04-03

---

## Entities

### Neuron

The fundamental unit of the Cerebrofy index. Represents one named code unit extracted from a
source file: a named function, named nested function, method, class (without methods), or a
module-level code block.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | Unique identifier: `"{file}::{name}"`. File path is relative to repo root. |
| `name` | string | yes | Name of the code unit as it appears in source. |
| `type` | enum | yes | `"function"` \| `"class"` \| `"module"` |
| `file` | string | yes | Relative path from repo root to the source file. |
| `line_start` | integer | yes | 1-based line number where the code unit begins. |
| `line_end` | integer | yes | 1-based line number where the code unit ends (inclusive). |
| `signature` | string | no | Full function/method signature including parameters and return type hint, if available. `null` for class and module types. |
| `docstring` | string | no | First docstring/comment block immediately following the definition, if present. `null` if absent. |

**ID uniqueness rule**: IDs are unique within a file. If two code units in the same file share
the same `name`, only the first occurrence (by `line_start` ascending) is retained; subsequent
duplicates are silently discarded.

**Type assignment rules**:
- `"function"` — any named function definition or named nested function definition, including
  methods inside classes that have methods.
- `"class"` — a class definition that has no methods (a class with methods produces only
  `"function"` Neurons for each method, not a separate class Neuron).
- `"module"` — all code at module level outside any function or class, collected into a single
  Neuron per file. The `name` is the filename stem (e.g., `"login"` for `login.py`).

**Excluded**:
- Anonymous functions (lambdas, arrow functions, unnamed closures).
- Classes that have methods (the class itself is not indexed; only its methods are).

**Example**:
```json
{
  "id": "src/auth/login.py::authenticate",
  "name": "authenticate",
  "type": "function",
  "file": "src/auth/login.py",
  "line_start": 42,
  "line_end": 67,
  "signature": "def authenticate(user: str, password: str) -> bool",
  "docstring": "Validates user credentials against the database."
}
```

---

### Lobe

A logical grouping of related source files, corresponding to a directory in the repository.
Defined in `config.yaml` under the `lobes` key.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Human-readable slug for the Lobe (e.g., `"auth"`, `"api"`, `"root"`). Used as the key in `config.yaml` and as the filename stem for `[name]_lobe.md`. |
| `path` | string | yes | Relative directory path from repo root (e.g., `"src/auth/"`, `"."` for root Lobe). Must end with `/`. |

**Flat-repo fallback**: When no subdirectories are found, a single Lobe named `"root"` with
`path: "."` is created.

**Depth constraint**: Lobe detection scans at most 2 directory levels from the repo root.

---

### CerebrоfyConfig

The full contents of `.cerebrofy/config.yaml`. Parsed and validated on every Cerebrofy command.

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `lobes` | map[string → string] | yes | auto-detected | Lobe name → directory path mapping. |
| `tracked_extensions` | list[string] | yes | see defaults | File extensions to include in parsing. Each entry includes the leading dot (e.g., `".py"`). |
| `embedding_model` | string | yes | `"local"` | `"local"` \| `"openai"` \| `"cohere"`. Used by Phase 2+ commands. |
| `embed_dim` | integer | yes | `768` | Vector dimension matching the embedding model. Used by Phase 2+. |
| `llm_endpoint` | string | yes | `"openai"` | LLM provider for Phase 4 commands. |
| `llm_model` | string | yes | `"gpt-4o"` | Model name for Phase 4 commands. |
| `top_k` | integer | yes | `10` | Number of nearest Neurons returned by KNN search (Phase 4). |

**Default tracked extensions** (written by `cerebrofy init`):
`.py`, `.js`, `.ts`, `.tsx`, `.jsx`, `.go`, `.rs`, `.java`, `.rb`, `.cpp`, `.c`, `.h`

**Validation rules**:
- `lobes` MUST contain at least one entry.
- `tracked_extensions` MUST contain at least one entry.
- `embed_dim` MUST match the model: 768 for `local`, 1536 for `openai`, 1024 for `cohere`.
- `top_k` MUST be a positive integer.

---

### IgnoreRuleSet

The combined set of ignore rules from `.cerebrofy-ignore` and `.gitignore`. Not persisted —
re-evaluated on every parse run from the current file contents.

| Field | Description |
|-------|-------------|
| `cerebrofy_rules` | Lines from `.cerebrofy-ignore` (gitignore syntax). |
| `git_rules` | Lines from `.gitignore` at repo root (gitignore syntax). |

**Matching semantics**: A file path is excluded if it matches ANY rule in either rule set.
Rules are evaluated using `pathspec` with the `gitwildmatch` dialect (full gitignore spec:
negation, `**` glob, directory-only `/` suffix).

**Default `.cerebrofy-ignore` content** (written by `cerebrofy init`):
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

---

### ParseResult

The output of a single parser run on one source file. Not persisted directly in Phase 1 —
consumed by Phase 2 (`cerebrofy build`) to populate the graph database.

| Field | Type | Description |
|-------|------|-------------|
| `file` | string | Relative path of the parsed source file. |
| `neurons` | list[Neuron] | All Neurons extracted from this file. Empty if the file is skipped or produces no named units. |
| `warnings` | list[string] | Human-readable warning messages (e.g., syntax error details). Empty for clean files. |

---

## State Transitions

Phase 1 produces no persistent state (no `cerebrofy.db`). The only persisted outputs are:

```
cerebrofy init → writes:
  .cerebrofy/config.yaml
  .cerebrofy/db/               (empty directory)
  .cerebrofy/queries/          (populated with default .scm files)
  .cerebrofy/scripts/          (empty directory)
  .cerebrofy/scripts/migrations/  (empty directory)
  .cerebrofy-ignore
  .git/hooks/pre-push          (created or appended)
  .git/hooks/post-merge        (created or appended)
  [MCP config file]            (written to first available path)

Parser (invoked by cerebrofy build in Phase 2) → produces:
  In-memory list[ParseResult]  → consumed by graph builder
  No files written in Phase 1
```
