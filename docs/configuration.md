# Cerebrofy Configuration Reference

Cerebrofy is configured through `.cerebrofy/config.yaml`, created automatically by `cerebrofy init` and editable by hand.

---

## Full Schema

```yaml
# ── Lobes ─────────────────────────────────────────────────────────────────────
lobes:
  auth: src/auth/
  api: src/api/
  db: src/db/

# ── Parser ────────────────────────────────────────────────────────────────────
tracked_extensions:
  - .py
  - .ts
  - .tsx
  - .js
  - .go

# ── Embedding ─────────────────────────────────────────────────────────────────
embedding_model: local       # local | none
```

---

## Field Reference

### `lobes`

**Type**: `dict[str, str]`
**Required**: yes
**Auto-detected by**: `cerebrofy init`

Maps a short lobe name to a directory path (relative to repo root). Each lobe gets its own Markdown summary at `.cerebrofy/lobes/<name>_lobe.md`.

```yaml
lobes:
  auth: src/auth/
  api: src/api/
  root: .            # single-lobe fallback for flat repos
```

Lobe names appear in `search_code` MCP tool results and in the blast-radius analysis. A neuron whose file path starts with `src/auth/` belongs to the `auth` lobe.

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

Controls which embedding model is used at `cerebrofy build` time. The model name and vector dimension are stored in the database — **changing this field requires a full `cerebrofy build`** to rebuild the index with the new model.

| Value | Model | Dimensions | Notes |
|-------|-------|------------|-------|
| `local` | `BAAI/bge-small-en-v1.5` | 384 | Offline ONNX via `fastembed` — bundled, no extra install, ~130MB cached after first build |
| `none` | — | — | Disables embeddings and KNN search; `search_code` will return an error |

The `local` model downloads ~130MB of ONNX weights on first use and caches them. All subsequent builds are fully offline with no API key or network access needed.

---

## Ignore Files

Cerebrofy reads two ignore files (gitignore syntax):

| File | Scope |
|------|-------|
| `.gitignore` | Standard git ignores — applied to both indexing and git hook checks |
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

## Minimal Example

```yaml
lobes:
  src: src/

tracked_extensions:
  - .py

embedding_model: local
```
