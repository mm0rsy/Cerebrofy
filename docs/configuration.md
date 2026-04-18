# Cerebrofy Configuration Reference

Cerebrofy is configured through `.cerebrofy/config.yaml`, created automatically by `cerebrofy init` and editable by hand.

---

## Full Schema

```yaml
# ── Lobes ────────────────────────────────────────────────────────────────────
lobes:
  auth: src/auth/
  api: src/api/
  db: src/db/

# ── Parser ───────────────────────────────────────────────────────────────────
tracked_extensions:
  - .py
  - .ts
  - .tsx
  - .js
  - .go

# ── Embedding ─────────────────────────────────────────────────────────────────
embedding_model: local       # local | none

# ── Hybrid Search ───────────────────────────────────────────────────────────────
top_k: 10                    # default KNN top-k for plan / tasks (MCP tools)

# ── LLM (reserved for future cerebrofy specify) ───────────────────────────────────
# llm_endpoint: ""           # OpenAI-compatible base URL (not yet used by any command)
# llm_model: ""              # Model identifier
# llm_timeout: 60            # Max seconds to wait for full LLM response
# system_prompt_template: "" # Path to custom .txt template

---

## Field Reference

### `lobes`

**Type**: `dict[str, str]`  
**Required**: yes  
**Auto-detected by**: `cerebrofy init`

Maps a short lobe name to a directory path (relative to repo root). Each lobe gets its own Markdown documentation file at `docs/cerebrofy/<name>_lobe.md`.

```yaml
lobes:
  auth: src/auth/
  api: src/api/
  root: .            # single-lobe fallback for flat repos
```

Lobe names appear in `tasks` MCP tool output and are injected as context in `plan` and `tasks` results. A Neuron whose file path starts with `src/auth/` belongs to the `auth` lobe.

---

### `tracked_extensions`

**Type**: `list[str]`  
**Required**: yes  
**Default** (from `cerebrofy init`):

```yaml
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
```

Only files whose extension is in this list are parsed and indexed. Remove extensions you don't use to speed up builds in polyglot repos.

A Tree-sitter `.scm` query file must exist in `.cerebrofy/queries/` for each extension. If no `.scm` file is found, files with that extension are skipped with a warning.

---

### `embedding_model`

**Type**: `string`  
**Default**: `local`  
**Options**: `local` | `none`

Controls which embedding model is used at `cerebrofy build` time. The model name and vector dimension are stored in the database; **changing this field requires a full `cerebrofy build`** to rebuild the index.

| Value | Model | Dimensions | Notes |
|-------|-------|------------|-------|
| `local` | `BAAI/bge-small-en-v1.5` | 384 | Offline ONNX via `fastembed` (~130MB, cached after first build) |
| `none` | — | — | Disables all embedding and KNN search |

The `local` model downloads ~130MB of ONNX weights on first use and caches them. All subsequent builds are fully offline. No API key or extra required.

---

### `top_k`

**Type**: `integer`  
**Default**: `10`

Default number of nearest-neighbor results used by the MCP `plan` and `tasks` tools (when implemented). Overridable per-call via the tool's `top_k` input field.

---

### LLM fields (`llm_endpoint`, `llm_model`, `llm_timeout`, `system_prompt_template`)

These fields exist in the config schema and are parsed by `CerebrоfyConfig` but are **not yet consumed by any command** — the `search/hybrid.py`, `llm/client.py`, and `commands/specify.py` modules are not yet implemented. Leave them commented out for now.

Cerebrofy reads two ignore files (gitignore syntax):

| File | Scope |
|------|-------|
| `.gitignore` | Standard git ignores — applied to both indexing and `cerebrofy parse` |
| `.cerebrofy-ignore` | Cerebrofy-specific ignores — for files git tracks but you don't want indexed |

Default `.cerebrofy-ignore` created by `cerebrofy init`:

```
node_modules/
__pycache__/
.git/
dist/
build/
vendor/
*.min.js
*.min.css
*.lock
*.map
```

Add patterns to `.cerebrofy-ignore` to exclude generated files, large asset directories, or test fixtures from the index without affecting git tracking.

---

## Environment Variables

| Variable | When Used |
|----------|-----------|
| `OPENAI_API_KEY` | When `llm_endpoint` contains `openai` |
| `LLM_API_KEY` | For all other LLM endpoints |

API keys are never written to `config.yaml`. They are read exclusively from the environment at runtime.

---

## Example Configurations

### Minimal (offline, local model)

```yaml
lobes:
  src: src/

tracked_extensions:
  - .py

embedding_model: local
top_k: 10
```

### With LLM spec generation (local embeddings + Ollama)

```yaml
lobes:
  auth: src/auth/
  api: src/api/
  db: src/db/
  frontend: frontend/src/

tracked_extensions:
  - .py
  - .ts
  - .tsx

embedding_model: local
top_k: 15

llm_endpoint: http://localhost:11434/v1
llm_model: llama3.1:70b
llm_timeout: 180
```

Set the key: `export LLM_API_KEY=ollama` (Ollama ignores the key value but it must be non-empty)

### With LLM spec generation (local embeddings + OpenAI)

```yaml
lobes:
  auth: src/auth/
  api: src/api/

tracked_extensions:
  - .py
  - .ts

embedding_model: local
top_k: 15

llm_endpoint: https://api.openai.com/v1
llm_model: gpt-4o
llm_timeout: 90
```

Set the key: `export OPENAI_API_KEY=sk-...`
