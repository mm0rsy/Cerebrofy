# Configuration — Quick Reference

Cerebrofy is configured through `.cerebrofy/config.yaml`, created automatically by `cerebrofy init` and editable by hand. For the full field reference, see [Configuration Reference](../getting-started/configuration.md).

## Minimal Example

```yaml
lobes:
  auth: src/auth/
  api: src/api/

tracked_extensions:
  - .py
  - .ts
  - .go

embedding_model: local      # local | none
record_sessions: false
```

## Top-Level Keys

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `lobes` | `dict[str, str]` | (auto-detected) | Maps lobe name to directory path |
| `tracked_extensions` | `list[str]` | (auto-detected) | File extensions to parse and index |
| `embedding_model` | `string` | `local` | `local` \| `none` |
| `record_sessions` | `bool` | `false` | Enable session recording (Idea #11) |
| `session` | `dict` | `{max_tracked_neurons: 50, max_refs_per_event: 3}` | Session recording limits |
| `synthesis` | `dict` | `{every_n_sessions: 10}` | Cross-session synthesizer trigger (Idea #24) |
| `database` | `dict` | `{integrity_check: warn}` | Database integrity verification |
| `governance` | `dict` | `{strategy: git-blame, ...}` | Lobe ownership and CODEOWNERS (Idea #18) |

## Key Details

### `embedding_model`

- `local` — `BAAI/bge-small-en-v1.5`, 384 dims, offline ONNX via `fastembed` (~130MB cached)
- `none` — disables embeddings and KNN search

Changing this field requires a full `cerebrofy build` to rebuild the index.

### `database.integrity_check`

- `off` — skip the check
- `warn` (default) — log a warning on mismatch, continue
- `fail` — raise `IntegrityError`

Verifies `cerebrofy.db` against the SHA256 sidecar `cerebrofy.db.sha256`.

### `governance.strategy`

- `git-blame` — author with most blamed lines across the lobe's neurons
- `explicit` — owners declared in `.cerebrofy/team.yaml`
- `hybrid` — blame weighted by commits in the last `activity_days`

### Ignore Files

| File | Scope |
|------|-------|
| `.gitignore` | Standard git ignores — applied to indexing and hook checks |
| `.cerebrofy-ignore` | Cerebrofy-specific ignores — files git tracks but shouldn't be indexed |

Default `.cerebrofy-ignore`:

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

## Related

- [Configuration Reference](../getting-started/configuration.md) — full field-by-field reference
- [Architecture](../concepts/architecture.md) — how configuration drives the build pipeline
- [Governance](../features/governance.md) — governance config details
- [Synthesizer](../features/synthesizer.md) — `synthesis` config details
- [Sessions](../features/sessions.md) — `record_sessions` and `session` config details