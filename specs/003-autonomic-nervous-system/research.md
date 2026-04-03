# Research: Phase 3 — Autonomic Nervous System

**Feature**: 003-autonomic-nervous-system
**Date**: 2026-04-03

---

## Decision 1: SQLite Partial Re-index Transaction Strategy

**Decision**: Use a single `BEGIN IMMEDIATE ... COMMIT` transaction wrapping all DML for a
partial update: delete affected rows by file path from `nodes`, `edges`, `vec_neurons`, and
`file_hashes`; insert new rows; update `file_hashes` and `meta`; all in one block.

**Rationale**: WAL mode allows concurrent readers but only one writer. `BEGIN IMMEDIATE`
acquires the write lock upfront, preventing mid-transaction lock failures from concurrent
`cerebrofy validate` reads. Critical constraint: `sqlite-vec`'s `vec0` virtual table does
NOT support `UPDATE` — only `DELETE` + `INSERT`. The delete-and-reinsert pair must occur
inside the same `BEGIN IMMEDIATE` block; otherwise `vec0`'s internal shadow-table writes may
commit before the outer transaction, breaking atomicity. The full-DB `.tmp` swap from Phase 2
is not viable here — copying the entire DB for a single-file change blows the 2-second budget.

**Alternatives considered**:
- `SAVEPOINT` for nested transactions — rejected: zero benefit for this use case; one flat
  atomic unit is simpler.
- Full `.tmp` swap (Phase 2 approach) — rejected: requires copying entire DB per update, making
  the < 2-second latency target impossible on large repos.
- Separate `vec_neurons` update outside main transaction — rejected: violates atomicity
  guarantee (vec0 shadow tables commit independently).

---

## Decision 2: Git Change Detection via subprocess

**Decision**: Use `subprocess.run()` with explicit argument lists (never `shell=True`) to call
the three git commands. Do not use `gitpython` or `pygit2`.

**Rationale**: `gitpython` adds a heavy dependency with its own subprocess bugs; `pygit2`
requires `libgit2` and complicates platform packaging (Homebrew, Snap, winget). Raw
`subprocess` with `["git", "diff", "--name-status", "HEAD"]` is zero-dependency and matches
the spec exactly.

**Critical edge cases to handle**:
- **Fresh repo (no commits)**: `git diff --name-status HEAD` exits code 128 ("fatal:
  ambiguous argument 'HEAD'"). Detect via `git rev-parse --verify HEAD` returning nonzero;
  fall back to `git ls-files` only.
- **Renamed files**: `--name-status` emits `R<score>\told_path\tnew_path` (3 tab-separated
  fields). Parser must split on tab and handle the `R` prefix — treat old path as deleted
  and new path as added.
- **Binary files**: Appear identically to text files in `--name-status` output. Tree-sitter
  will produce zero Neurons for them, which is correct; no special handling needed.
- **No `.git/` directory**: Fall back to hash-comparison against `file_hashes` table
  (as per spec clarification).

**Alternatives considered**:
- `gitpython` — rejected: heavyweight, own subprocess handling bugs, packaging burden.
- `pygit2` — rejected: requires compiled `libgit2`, breaks platform bundles.
- `watchdog` (filesystem watcher) — rejected: requires long-running daemon, incompatible
  with on-demand CLI invocation.

---

## Decision 3: Drift Classification at Neuron Signature Level

**Decision**: Classify drift by comparing Neuron name+signature strings (whitespace-
normalized) between the re-parsed file and the current index. Minor drift = all existing
Neurons have identical normalized signatures and no Neurons were added or removed. Structural
drift = any Neuron added, removed, renamed, or with a changed signature.

**Rationale**: Full source-text comparison is too noisy (comments, docstrings, blank lines
all alter the hash without structural change). The `name` + `signature` fields extracted by
Phase 1's tree-sitter queries encode the public contract of each code unit. Whitespace-
normalizing with `" ".join(sig.split())` before comparison eliminates false positives from
formatting-only changes. Docstring changes produce no signature change — correctly classified
as minor drift. Import changes are classified by comparing the Neuron list for any `module`-
type Neuron's capture list; an import add/remove is structural (FR-011).

**Alternatives considered**:
- AST-hash comparison (hash the tree-sitter CST) — rejected: flags comment changes as
  structural, producing false positives.
- Token-set diff — rejected: overkill given the Neuron schema already captures relevant
  structural fields.
- Raw file diff (line count change) — rejected: too coarse, cannot distinguish structural
  from non-structural changes.

---

## Decision 4: Hook Upgrade from WARN-only to Hard-block

**Decision**: Use a versioned marker comment `# cerebrofy-hook-version: 2` inside the git
hook file itself. The upgrade logic in `hooks/installer.py` reads the existing hook, checks
for the version marker, and does a targeted in-place string replacement only within the
`# BEGIN cerebrofy` / `# END cerebrofy` sentinel block established in Phase 1.

**Rationale**: Storing the activation state in the hook file makes it self-describing and
survives config.yaml deletion or repo migration. The Phase 1 sentinel block pattern means
user customizations outside the sentinels are never touched. If sentinels are absent (user
rewrote the hook), emit `Warning: hook not managed — manual upgrade required` and skip
silently. The upgrade is triggered by `cerebrofy update` itself after verifying the index is
healthy (schema_version correct, file_hashes table non-empty, SC-001 verified by test run).

**Alternatives considered**:
- config.yaml flag (`hard_block_enabled: true`) — rejected: desynchronizes from actual hook
  state if users copy repos or restore from backup.
- Separate hook file symlinked — rejected: symlink management is fragile on Windows and
  inside Snap sandboxes.
- Hard-coding activation in Cerebrofy version upgrade — rejected: couples hook behavior to
  a release, making it impossible to pre-verify SC-001 before enabling.

---

## Decision 5: `cerebrofy update` Latency Budget

**Decision**: 2 seconds is achievable for warm embedding model invocations. The cold-start
risk (1.8–3.5 s) is mitigated by documenting first-run behavior and loading the embedding
model once at the start of `cerebrofy update` (not per-Neuron).

**Realistic budget for 1 changed file, ~10 changed Neurons, 10k-node graph**:

| Step | Budget (warm) |
|------|--------------|
| 3× git subprocess calls | 50–100 ms |
| tree-sitter re-parse of 1 file | 10–30 ms |
| depth-2 BFS on 10k-node graph | 20–60 ms |
| sentence-transformers embed 10 Neurons (warm) | 200–600 ms |
| SQLite partial transaction write | 10–30 ms |
| **Total (warm)** | **290–820 ms** |
| **Total (cold model)** | **1.8–3.5 s** |

**Mitigation**: Load the embedding model at update start, not per-Neuron. Document that the
first `cerebrofy update` invocation after install/reboot may exceed 2 seconds (cold model
warm-up); subsequent calls are fast. Re-embedding is skipped for unchanged neighbors
(content hash unchanged = skip embed), reducing the Neuron batch size in practice.

**Alternatives considered**:
- Long-running background daemon — rejected: incompatible with CLI-first architecture and
  platform bundle deployment constraints.
- OpenAI embeddings for speed — rejected: adds network dependency (~200–400 ms/call),
  breaks offline-first guarantee.
- `--no-embed` flag to skip vectors — acceptable as a future optimization; deferred to
  Phase 3 polish.
