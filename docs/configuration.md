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
embedding_model: local       # local | openai | cohere
embed_dim: 768               # auto-set from embedding_model; change only if custom

# ── Hybrid Search ─────────────────────────────────────────────────────────────
top_k: 10                    # default KNN top-k for plan / tasks / specify

# ── LLM (required only for cerebrofy specify) ─────────────────────────────────
llm_endpoint: ""             # OpenAI-compatible base URL
llm_model: ""                # Model identifier passed to the API
llm_timeout: 60              # Max seconds to wait for the full LLM response
system_prompt_template: ""   # Path to a custom .txt template (optional)
```

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

Lobe names appear in `cerebrofy tasks` output as `[[auth]]` and are injected as context into `cerebrofy specify` prompts. A Neuron whose file path starts with `src/auth/` belongs to the `auth` lobe.

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
**Options**: `local` | `openai` | `cohere`

Controls which embedding model is used at `cerebrofy build` time. The model name and vector dimension are stored in the database; **changing this field requires a full `cerebrofy build`** to rebuild the index.

| Value | Model | Dimensions | API Key Required |
|-------|-------|-----------|-----------------|
| `local` | `nomic-embed-text-v1` (sentence-transformers) | 768 | No — fully offline |
| `openai` | `text-embedding-3-small` | 1536 | `OPENAI_API_KEY` |
| `cohere` | `embed-english-v3.0` | 1024 | `COHERE_API_KEY` |

The `local` model downloads the weights on first use (~500 MB) and caches them locally. All subsequent builds are fully offline.

---

### `embed_dim`

**Type**: `integer`  
**Default**: set automatically from `embedding_model` (768 / 1536 / 1024)

You should not need to set this manually. It is automatically derived from `embedding_model` and stored in the database schema at build time. Only override if you are using a custom embedding model not in the three standard options.

---

### `top_k`

**Type**: `integer`  
**Default**: `10`

Default number of nearest-neighbor results returned by the KNN vector search in `cerebrofy plan`, `cerebrofy tasks`, and `cerebrofy specify`. Can be overridden per-invocation with `--top-k N`.

Higher values surface more potentially affected code units but increase noise and LLM context size.

---

## LLM Settings

These fields are only required for `cerebrofy specify`. The offline commands (`plan`, `tasks`, `parse`, `validate`, `update`) ignore them entirely.

### `llm_endpoint`

**Type**: `string`  
**Required for `specify`**: yes

Base URL for an OpenAI-compatible chat completions endpoint.

```yaml
llm_endpoint: https://api.openai.com/v1          # OpenAI
llm_endpoint: https://api.anthropic.com/v1       # Anthropic (via openai-compatible proxy)
llm_endpoint: http://localhost:11434/v1          # Ollama (local)
llm_endpoint: https://openrouter.ai/api/v1       # OpenRouter
```

The string `openai` (case-insensitive) in the endpoint URL causes Cerebrofy to read `OPENAI_API_KEY` from the environment. All other endpoints use `LLM_API_KEY`.

---

### `llm_model`

**Type**: `string`  
**Required for `specify`**: yes

The model identifier passed to the API.

```yaml
llm_model: gpt-4o
llm_model: gpt-4o-mini
llm_model: claude-3-5-sonnet-20241022
llm_model: llama3.1:70b                   # Ollama
```

---

### `llm_timeout`

**Type**: `integer` (seconds)  
**Default**: `60`

Maximum wall-clock time to wait for the complete LLM response. If exceeded, `cerebrofy specify` exits 1 with an error message. No partial spec file is written on timeout.

Increase this for large codebases or slow endpoints:

```yaml
llm_timeout: 120
```

---

### `system_prompt_template`

**Type**: `string` (file path, relative to repo root)  
**Default**: built-in template in `llm/prompt_builder.py`

Path to a custom system prompt template file. The template uses Python `string.Template` syntax. The variable `$lobe_context` is substituted with the content of affected lobe `.md` files.

```yaml
system_prompt_template: .cerebrofy/my_prompt.txt
```

Example template:

```
You are a senior engineer on this codebase. Use the provided module documentation
to write a detailed implementation specification for the requested feature.

Always reference specific function names and file paths from the context below.

$lobe_context
```

If the path is set but the file does not exist, `cerebrofy specify` exits 1 with an error before making any LLM call.

---

## Ignore Rules

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
| `COHERE_API_KEY` | When `embedding_model: cohere` |

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

### Full (OpenAI embeddings + GPT-4o spec generation)

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

embedding_model: openai
embed_dim: 1536
top_k: 15

llm_endpoint: https://api.openai.com/v1
llm_model: gpt-4o
llm_timeout: 90
```

Set the key: `export OPENAI_API_KEY=sk-...`

### Local LLM via Ollama

```yaml
lobes:
  src: src/

tracked_extensions:
  - .py

embedding_model: local
top_k: 10

llm_endpoint: http://localhost:11434/v1
llm_model: llama3.1:70b
llm_timeout: 180
```

Set the key: `export LLM_API_KEY=ollama` (Ollama ignores the key value but it must be non-empty)
