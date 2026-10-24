# Quick Start

**Three commands, then git handles everything automatically:**

```bash
# Step 1 — one time per repo
cerebrofy init

# Step 2 — one time after init (takes ~30s on a typical codebase)
cerebrofy build

# Step 3 — optional: wire your AI client so it uses the index instead of reading files
cerebrofy init --ai claude      # writes navigation rules to CLAUDE.md
cerebrofy init --ai copilot     # writes rules to .github/copilot-instructions.md
cerebrofy init --ai vscode      # same as --ai copilot
cerebrofy init --ai opencode    # writes rules to .opencode/instructions.md
```

**That's it.** From here, `cerebrofy update` runs automatically on every `git commit` (via the installed pre-commit hook) and the index is validated before every `git push`. You never need to run `cerebrofy update` manually.

```
your workflow:
  code → git commit  →  index auto-updated  ✓
                ↓
           git push   →  index validated     ✓
```

> **First time on a new machine?** After cloning a repo that already has cerebrofy:
> ```bash
> cerebrofy init   # re-installs hooks
> cerebrofy build  # builds your local index from scratch
> ```

Once the index is built, AI assistants with MCP configured can call all 39 tools and read MCP resources directly — see [MCP Tools](../reference/mcp-tools.md).

---

## How Cerebrofy Works

Cerebrofy builds a **structural + semantic index** of your code in one SQLite file (`.cerebrofy/db/cerebrofy.db`):

1. **Parse** — Tree-sitter extracts named functions, classes, and modules as *Neurons*
2. **Graph** — Call relationships become typed edges (`LOCAL_CALL`, `EXTERNAL_CALL`, `IMPORT`, `RUNTIME_BOUNDARY`)
3. **Embed** — Each Neuron is embedded into a `sqlite-vec` vector table for semantic search
4. **Query** — Hybrid search (KNN cosine + BFS depth-2) finds affected code units for any description
5. **Expose** — An MCP stdio server lets AI clients trigger builds, run drift checks, and update the index

No cloud index. No code upload. One file, one connection.

---

## `cerebrofy init`

Scaffold `.cerebrofy/`, auto-detect Lobes, install git hooks, and register the MCP server.

```bash
cerebrofy init                           # Local MCP registration (default)
cerebrofy init --global                  # Register MCP globally (~/.config/mcp/servers.json)
cerebrofy init --no-mcp                  # Skip MCP registration
cerebrofy init --force                   # Re-initialize, overwrite MCP entry with current binary path
cerebrofy init --ai claude               # Also write AI navigation rules to CLAUDE.md
cerebrofy init --ai copilot              # Also write rules to .github/copilot-instructions.md
cerebrofy init --ai vscode               # Same as --ai copilot
cerebrofy init --ai opencode             # Also write rules to .opencode/instructions.md
```

**What it creates:**

```
.cerebrofy/
├── config.yaml          ← Lobe map, tracked extensions, embed model
├── arch-rules.yaml      ← Architecture drift rules (scaffolded sample)
├── db/                  ← cerebrofy.db lives here (gitignored)
└── queries/             ← Tree-sitter .scm files per language
.cerebrofy-ignore        ← Ignore rules (gitignore syntax)
.gitignore               ← .cerebrofy/db/ appended automatically
.git/hooks/pre-commit    ← Auto-runs cerebrofy update + arch check on every commit
.git/hooks/pre-push      ← Validates index + runs the arch check before push
.git/hooks/post-merge    ← state_hash sync check after git pull
```

The `--ai` flag appends a fenced navigation rules block to the target instructions file. The block is idempotent — re-running replaces the existing block rather than appending a second copy. It also writes `.github/workflows/cerebrofy-arch.yml` so CI runs the architecture check on every pull request (an existing workflow file is kept unless `--force`).

---

## `cerebrofy build`

Full atomic re-index of the repository.

```bash
cerebrofy build
```

Writes to `cerebrofy.db.tmp`, swaps atomically to `cerebrofy.db` only on success. An interrupted build leaves no corrupted state. Runs 6 steps:

| Step | Action |
|------|--------|
| 0 | Create `.tmp` database, apply schema |
| 1 | Parse all tracked source files → Neurons |
| 2 | Build intra-file call graph (LOCAL_CALL edges) |
| 3 | Resolve cross-module calls (EXTERNAL_CALL, IMPORT, RUNTIME_BOUNDARY edges) |
| 4 | Generate embeddings for all Neurons (`BAAI/bge-small-en-v1.5`, 384-dim, offline) |
| 5 | Commit file hashes + state_hash, atomic swap |
| 6 | Write per-lobe Markdown docs and `cerebrofy_map.md` |

---

## `cerebrofy update`

Partially re-index only changed files — target latency < 2s for a single-file change.

```bash
cerebrofy update                        # Auto-detect via git
cerebrofy update src/auth/login.py      # Explicit file list
```

Detects changes via `git diff` (falls back to file hash comparison in non-git repos). Uses depth-2 BFS to find and re-index all affected neighbors. All writes are wrapped in a single `BEGIN IMMEDIATE` transaction — on failure, full rollback.

After a successful update that completes in under 2 seconds, the pre-push git hook is automatically upgraded from warn-only (v1) to hard-block (v2).

---

## `cerebrofy validate`

Classify drift between the index and current source.

```bash
cerebrofy validate
```

Exit codes:

| Code | Meaning |
|------|---------|
| 0 | Index is clean, or minor drift (whitespace/comments only) |
| 1 | Structural drift — function added, removed, renamed, or signature changed |

This command is also invoked automatically by the pre-push git hook.

---

## Git Hooks

Cerebrofy installs three hooks at `cerebrofy init` time:

| Hook | Trigger | Behavior |
|------|---------|----------|
| `pre-commit` | After every `git commit` | **Auto-runs `cerebrofy update`** silently, then the architecture check. Index drift never blocks; **architecture violations do**. |
| `pre-push` | Before `git push` | Validates the index (auto-runs `cerebrofy update` if drift slipped through) and runs the architecture check with a full report. Blocks if the update fails or rules are violated. |
| `post-merge` | After `git pull` / merge | Compares remote `state_hash` against local index; warns if out of sync. |

All three hooks are installed by `cerebrofy init`. **You should never need to run `cerebrofy update` manually** — the pre-commit hook does it on every commit. The pre-push hook is a safety net for cases where the pre-commit hook wasn't installed or was bypassed.

The architecture gate is armed by the rules file: the check only runs while `.cerebrofy/arch-rules.yaml` exists, and when it runs its verdict is always blocking — error-severity violations, including warnings escalated by a sprint-priority lobe, refuse the commit or push. `cerebrofy update` upgrades existing hooks in place to the current version; it never downgrades them.

### Windows

Hooks are written as POSIX `sh` scripts and executed by the MSYS bash shell that ships with **Git for Windows** — no extra configuration needed. If hooks don't appear to run after `cerebrofy init`, confirm that `git` on your PATH comes from Git for Windows (not WSL or another distribution).

---

## Multi-Developer Workflow

`cerebrofy.db` is a **local artifact — it is not committed to git** (`.cerebrofy/db/` is gitignored automatically by `cerebrofy init`). Each developer builds and maintains their own index. Synchronization uses `state_hash` in `cerebrofy_map.md`, which **is** committed.

| Event | What happens |
|-------|-------------|
| First clone | `.cerebrofy/` missing → run `cerebrofy init && cerebrofy build`. Pre-push hook warns but does not block. |
| Daily development | Edit code → `cerebrofy update` syncs the index in < 2s. Pre-push hook validates automatically. |
| `git pull` / merge | Post-merge hook compares remote `state_hash` (from pulled `cerebrofy_map.md`) against local index. Warns if they differ — run `cerebrofy build` to resync. |
| Embedding model change | Change `embedding_model` in `config.yaml` → run `cerebrofy build` to rebuild the vector table at the new dimension. |

---

## Next Steps

- [Configuration](./configuration.md) — customize `.cerebrofy/config.yaml`
- [Architecture](../concepts/architecture.md) — understand the module map and data flow
- [CLI Reference](../reference/cli.md) — complete command reference
- [MCP Tools](../reference/mcp-tools.md) — use Cerebrofy from your AI assistant