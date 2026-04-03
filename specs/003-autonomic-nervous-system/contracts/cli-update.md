# Contract: `cerebrofy update` CLI Interface

**Feature**: 003-autonomic-nervous-system
**Date**: 2026-04-03
**Stability**: Draft

---

## Command Signature

```
cerebrofy update [FILES...]
```

### Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `FILES...` | (none) | Optional list of file paths to re-index. If omitted, auto-detection runs. |

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--help` | — | Print usage and exit. |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Update completed successfully. Index and Markdown files updated. |
| `1` | Fatal error: no index found (`cerebrofy build` required); lock contention; embedding model unavailable; disk full. |

Non-fatal conditions (syntax errors in changed files, unresolvable calls) do NOT change the exit code — they produce stderr warnings and the update continues.

---

## Standard Output (stdout)

All progress messages use the prefix `Cerebrofy: `.

```
Cerebrofy: Starting update...
Cerebrofy: Detected N changed file(s) via git
Cerebrofy: Update scope: M node(s) across K file(s) (depth-2 BFS)
Cerebrofy: Re-parsing changed files...
Cerebrofy: Re-resolving call graph...
Cerebrofy: Generating embeddings (P / Q neurons)
Cerebrofy: Writing Markdown documentation...
Cerebrofy: Update complete. Re-indexed Q neurons in X.Xs. New state_hash: <16-char prefix>...
```

**When no changes detected**:
```
Cerebrofy: Nothing to update. Index is current.
```

**When git absent (hash-comparison fallback)**:
```
Cerebrofy: Detected N changed file(s) via hash comparison (no git repository)
```

---

## Standard Error (stderr)

| Situation | Message format |
|-----------|----------------|
| No index exists | `Error: No index found. Run 'cerebrofy build' first.` |
| Build lock held | `Error: A build or update is already in progress (PID N).` |
| Embedding unavailable | `Error: Embedding model unavailable: {reason}. Update aborted.` |
| Syntax error in changed file | `Warning: Syntax error in {file} at line {N}. File partially parsed.` |
| Unresolvable call | `Warning: Cannot resolve call to '{callee}' in {file}:{line}. Recorded as RUNTIME_BOUNDARY.` |
| Cold embedding model | `Cerebrofy: Loading embedding model (first invocation may be slow)...` |
| Hook sentinels absent | `Warning: Git hook not managed by Cerebrofy — manual upgrade to hard-block required.` |

---

## Filesystem Side Effects

After a successful `cerebrofy update`:

```
.cerebrofy/db/cerebrofy.db           ← updated in-place (partial transaction)
docs/cerebrofy/cerebrofy_map.md      ← rewritten with new state_hash
docs/cerebrofy/{lobe}_lobe.md        ← rewritten for any affected Lobe (others unchanged)

NOT created/modified:
  .cerebrofy/db/cerebrofy.db.tmp     ← not used by update (no full swap)
```

Lock file `.cerebrofy/db/cerebrofy.build.lock` is created on start and deleted on completion.

---

## Auto-Detection Behavior

When no `FILES...` are provided:

**In a git repository** (`.git/` present):
1. `git rev-parse --verify HEAD` — if nonzero (no commits), skip to step 3
2. `git diff --name-status HEAD` — modified and deleted tracked files
3. `git diff --name-status` — unstaged changes
4. `git ls-files --others --exclude-standard` — new untracked files
5. Deduplicate; classify each path as M/D/A

**Outside a git repository**:
1. Walk all tracked files (same extension filter + ignore rules as `cerebrofy build`)
2. Compare SHA-256(content) against `file_hashes` table
3. Files not in `file_hashes` = A; files with changed hash = M; files in `file_hashes` but absent = D

---

## Update Pipeline Steps (Ordered)

| Step | Name | Description |
|------|------|-------------|
| 0 | Lock | Acquire build lock |
| 1 | Detect | Auto-detect or accept explicit file list |
| 2 | Scope | Depth-2 BFS from changed nodes → UpdateScope |
| 3 | Transaction START | `BEGIN IMMEDIATE` |
| 4 | Delete | Remove stale nodes, edges, vec_neurons, file_hashes for affected files |
| 5 | Parse | Re-parse changed files → new Neurons + RawCaptures |
| 6 | Graph | Re-resolve local + cross-module edges for changed files |
| 7 | Embed | Embed changed Neurons (skip if content hash unchanged) |
| 8 | Write | INSERT new nodes, edges, vec_neurons, file_hashes |
| 9 | Commit | UPDATE meta (state_hash, last_build); `COMMIT` |
| 10 | Markdown | Rewrite affected lobe .md files + cerebrofy_map.md |
| 11 | Unlock | Release build lock |

Steps 3–9 are one atomic SQLite transaction. Failure at any step → `ROLLBACK`.
Step 10 runs after commit (same pattern as Phase 2 Markdown post-commit).
