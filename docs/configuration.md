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

# ── Session Recording (Idea #11) ─────────────────────────────────────────────
record_sessions: false       # true = record every MCP tool call as a replayable, local-only session

# ── Session limits (optional) ────────────────────────────────────────────────
session:
  max_tracked_neurons: 50    # cap on distinct neurons folded into a session
  max_refs_per_event: 3      # cap on neuron refs resolved per recorded event

# ── Database (optional) ──────────────────────────────────────────────────────
database:
  integrity_check: warn      # off | warn | fail — verify cerebrofy.db against its <db>.sha256 sidecar
```

---

## Field Reference

### `lobes`

**Type**: `dict[str, str]`
**Required**: yes
**Auto-detected by**: `cerebrofy init`

Maps a short lobe name to a directory path (relative to repo root). Each lobe gets its own Markdown summary at `docs/cerebrofy/<name>_lobe.md`.

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

### `record_sessions`

**Type**: `bool`
**Default**: `false`
**Since**: Idea #11 (Live Agent Session Recorder)

Opt-in flag that enables per-tool-call session recording. When `true`, the MCP server records every tool invocation (name, arguments, and a truncated result summary) into a replayable session stored in `.cerebrofy/db/sessions.db` — a database **separate** from `cerebrofy.db` so the audit trail survives index rebuilds and never contends with the index writer.

```yaml
record_sessions: true
```

Sessions are started and ended explicitly via the `cerebrofy_session_start` / `cerebrofy_session_end` MCP tools (or the `cerebrofy session` CLI). While a session is open, each tool call — including `search_code`, `cerebrofy_impact`, and even `cerebrofy_update` — is captured. At session end the recorder folds in the depth-2 blast-radius "before" and "after" counts of the neurons the agent touched (Idea #01), so each replay answers "what did the agent do and what did it affect?".

Privacy: recording is **local-only**. No session data, tool arguments, or result snippets are uploaded or sent to any server. Disable at any time by setting the flag back to `false` and restarting the MCP server.

---

### `database.integrity_check`

**Type**: `str` (`off` | `warn` | `fail`)
**Default**: `warn`

Controls verification of `cerebrofy.db` against the SHA256 sidecar
(`cerebrofy.db.sha256`) written by `cerebrofy build` / `cerebrofy update`.
`warn` logs a warning on mismatch and continues; `fail` raises
`IntegrityError`; `off` skips the check. A missing sidecar is always a no-op,
so databases from before this feature remain readable. See
[security.md](security.md).

```yaml
database:
  integrity_check: warn
```

---

### `session`

**Type**: `dict[str, int]`
**Default**: `{max_tracked_neurons: 50, max_refs_per_event: 3}`

Caps applied while recording sessions. `max_tracked_neurons` bounds the
distinct neurons folded into a session's blast-radius tracking;
`max_refs_per_event` bounds how many neuron references are resolved per
recorded event.

```yaml
session:
  max_tracked_neurons: 50
  max_refs_per_event: 3
```

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

record_sessions: false
```
