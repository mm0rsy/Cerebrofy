# Contract: `cerebrofy build` CLI Interface

**Feature**: 002-build-engine
**Date**: 2026-04-03
**Stability**: Draft

---

## Command Signature

```
cerebrofy build [OPTIONS]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--help` | — | Print usage and exit. |

No additional options in Phase 2. Incremental (`--files`) and force-rebuild (`--force`) flags
are Phase 3 (`cerebrofy update`) concerns.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Build completed successfully. `cerebrofy.db` written and all Markdown files updated. |
| `1` | Fatal error: `.cerebrofy/config.yaml` not found; disk write failure; embedding model unavailable; another build in progress. |

Non-fatal warnings (syntax errors, skipped files, unresolvable calls) do NOT change the exit
code — the build exits `0` with warnings printed to stderr.

---

## Standard Output (stdout)

All progress messages go to stdout. Format: `Cerebrofy: <message>`.

**Required messages** (in order, one per build pipeline step):

```
Cerebrofy: Starting build...
Cerebrofy: Step 0/6 — Creating index database
Cerebrofy: Step 1/6 — Parsing source files (0 / N files)
Cerebrofy: Step 1/6 — Parsing source files (K / N files)    ← progress update per 100 files
Cerebrofy: Step 2/6 — Building local call graph
Cerebrofy: Step 3/6 — Resolving cross-module calls
Cerebrofy: Step 4/6 — Generating embeddings (0 / M neurons)
Cerebrofy: Step 4/6 — Generating embeddings (K / M neurons) ← progress per batch
Cerebrofy: Step 5/6 — Writing Markdown documentation
Cerebrofy: Step 6/6 — Committing index (state_hash: <hex>)
Cerebrofy: Build complete. Indexed N neurons across M files in X.Xs.
```

**Final line** MUST always be:
```
Cerebrofy: Build complete. Indexed {N} neurons across {M} files in {X.X}s.
```

**First-run embedding download** (local model only):
```
Cerebrofy: Downloading embedding model (nomic-embed-text, ~275 MB) — first run only...
```
This line appears before Step 4 only when the model is not cached.

---

## Standard Error (stderr)

Warnings and non-fatal errors go to stderr.

| Situation | Message format |
|-----------|----------------|
| Syntax error in source file | `Warning: Syntax error in {file} at line {N}. File partially parsed.` |
| File unreadable | `Warning: Cannot read {file} (permission denied). Skipped.` |
| Unresolvable call | `Warning: Cannot resolve call to '{callee}' in {file}:{line}. Recorded as RUNTIME_BOUNDARY.` |
| Local model first download | (Progress to stdout, not stderr) |
| Another build in progress | `Error: A build is already in progress in this repository (PID {N}).` |
| `config.yaml` not found | `Error: .cerebrofy/config.yaml not found. Run 'cerebrofy init' first.` |
| Malformed config | `Error: .cerebrofy/config.yaml is invalid: {reason}. Fix and retry.` |
| Embedding model unreachable | `Error: Embedding model '{model}' is unavailable: {reason}. Build aborted.` |
| Disk full | `Error: Disk write failed: {reason}. Build aborted. Prior index preserved.` |

---

## Filesystem Side Effects

After a successful `cerebrofy build`, the following MUST exist or be updated:

```
.cerebrofy/
└── db/
    └── cerebrofy.db                ← created (or replaced atomically)

docs/
└── cerebrofy/
    ├── cerebrofy_map.md            ← created or updated
    ├── {lobe1}_lobe.md             ← created or updated (one per configured Lobe)
    ├── {lobe2}_lobe.md
    └── ...

NOT present after a successful build:
  .cerebrofy/db/cerebrofy.db.tmp    ← cleaned up by the atomic swap
  .cerebrofy/db/cerebrofy.build.lock ← deleted on build completion
```

After a **failed** `cerebrofy build`:
- `.cerebrofy/db/cerebrofy.db` remains at its prior state (or absent if no prior build).
- `.cerebrofy/db/cerebrofy.db.tmp` is deleted on failure.
- `.cerebrofy/db/cerebrofy.build.lock` is deleted on failure (even on unhandled exception).
- `docs/cerebrofy/` files are NOT written or modified (Markdown is post-swap only).

---

## Build Pipeline Steps (Ordered)

| Step | Name | Description |
|------|------|-------------|
| 0 | Create DB | Create `.tmp`, load sqlite-vec, run DDL, insert meta |
| 1 | Parse | Run Phase 1 parser on all tracked files; emit Neurons |
| 2 | Local graph | Insert nodes; resolve intra-file call expressions; insert LOCAL_CALL edges |
| 3 | Cross-module graph | Resolve import chains; insert EXTERNAL_CALL + RUNTIME_BOUNDARY edges |
| 4 | Vectors | Batch-embed all Neurons; upsert into `vec_neurons` |
| 5 | Markdown | (Post-swap) Write `[lobe]_lobe.md` + `cerebrofy_map.md` |
| 6 | Commit | Compute state_hash; populate `file_hashes`; write to meta; swap `.tmp` → `.db` |

Steps 0–6 are strictly sequential. Step 5 (Markdown) executes **after** the Step 6 swap to
guarantee Markdown always reflects the committed index.

---

## Behavior Matrix

| Condition | Behavior |
|-----------|----------|
| `.cerebrofy/config.yaml` missing | Exit 1, error message, no files written |
| `config.yaml` present, `.git/` absent | Build proceeds (build does not require git) |
| Prior `cerebrofy.db` exists | Replaced atomically on success; preserved on failure |
| Stale `.tmp` file from prior crash | Deleted silently at build start (after lock acquired) |
| Build lock held by live process | Exit 1, "build already in progress" error |
| Build lock held by dead process | Stale lock deleted; build proceeds |
| Zero tracked files | Build completes with warning; empty index; exit 0 |
| Files with syntax errors | Warning printed; files partially parsed; build continues |
| Embedding model unavailable | Exit 1 after Step 3 (before Step 4); prior index preserved |
| Disk full during build | Exit 1; `.tmp` deleted; prior index preserved |
| `embed_dim` mismatch (model changed) | Full rebuild creates new `vec_neurons` at new dimension |
