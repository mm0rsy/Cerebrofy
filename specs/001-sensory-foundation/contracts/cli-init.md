# Contract: `cerebrofy init` CLI Interface

**Feature**: 001-sensory-foundation
**Date**: 2026-04-03
**Stability**: Draft

---

## Command Signature

```
cerebrofy init [OPTIONS]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--global` | off | Register MCP entry globally (`~/.config/mcp/servers.json`) instead of the first detected tool-specific path. |
| `--no-mcp` | off | Skip MCP registration entirely. Useful for CI/CD environments. |
| `--force` | off | Re-run init on an already-initialized repo (overwrites scaffold files; re-appends hooks only if marker absent). |
| `--help` | — | Print usage and exit. |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Init completed successfully (MCP may or may not have registered — both are exit 0). |
| `1` | Fatal error: `.git/` directory not found, or unable to write `.cerebrofy/` scaffold to disk. |

---

## Standard Output (stdout)

All progress and status messages go to stdout. Format: plain text, one message per line.
No ANSI color codes are required (but permitted for enhanced terminals).

**Required messages** (in order):

```
Cerebrofy: Scanning project structure...
Cerebrofy: Detected lobes: auth, api, utils     ← list of lobe names
Cerebrofy: Writing .cerebrofy/config.yaml
Cerebrofy: Writing .cerebrofy-ignore
Cerebrofy: Installing git hooks (warn-only mode)
Cerebrofy: MCP server registered → ~/Library/Application Support/Claude/claude_desktop_config.json
Cerebrofy initialized. Run `cerebrofy build` to index your codebase.
```

**Final line** MUST always be:
```
Cerebrofy initialized. Run `cerebrofy build` to index your codebase.
```
(This is the next-step instruction required by FR-007.)

**Flat repo variant** (when no subdirectories detected):
```
Cerebrofy: No subdirectories found — creating single root Lobe.
Cerebrofy: Detected lobes: root
```

---

## Standard Error (stderr)

Warnings and non-fatal errors go to stderr.

| Situation | Message |
|-----------|---------|
| Pre-existing hook found | `Warning: Pre-existing hook at .git/hooks/pre-push — appending Cerebrofy call.` |
| All MCP paths unwritable | `Warning: Could not write MCP config (permission denied). Add this entry manually:` followed by the full JSON snippet (see below). |
| Already initialized (without --force) | `Warning: .cerebrofy/ already exists. Use --force to re-initialize.` Init exits 0 without changes. |

**MCP fallback snippet** (printed to stderr when all paths unwritable):
```json
{
  "mcpServers": {
    "cerebrofy": {
      "command": "cerebrofy",
      "args": ["mcp"],
      "env": {}
    }
  }
}
```

---

## Filesystem Side Effects

After a successful `cerebrofy init`, the following MUST exist:

```
.cerebrofy/
├── config.yaml                   (written)
├── db/                           (empty directory)
├── queries/
│   ├── python.scm                (copied from bundled defaults)
│   ├── javascript.scm
│   ├── typescript.scm
│   ├── go.scm
│   ├── rust.scm
│   ├── java.scm
│   ├── ruby.scm
│   ├── c.scm
│   ├── cpp.scm
│   └── ...                       (one file per default language)
└── scripts/
    └── migrations/               (empty directory)
.cerebrofy-ignore                 (written)
.git/hooks/pre-push               (created or appended)
.git/hooks/post-merge             (created or appended)
```

**NOT created by `cerebrofy init`**:
- `.cerebrofy/db/cerebrofy.db` — created exclusively by `cerebrofy build` (Phase 2).
- `docs/cerebrofy/` — created exclusively by `cerebrofy build` (Phase 2).

---

## Hook Script Format

When creating a new hook file:
```sh
#!/bin/sh
# cerebrofy-hook-start
cerebrofy validate --hook pre-push
# cerebrofy-hook-end
```

When appending to an existing hook file:
```sh
[...existing content...]
# cerebrofy-hook-start
cerebrofy validate --hook pre-push
# cerebrofy-hook-end
```

**Idempotency marker**: The `# cerebrofy-hook-start` / `# cerebrofy-hook-end` block. If found
in the existing file, the append step is skipped entirely.

New hook files MUST be set executable (`chmod 755` equivalent on POSIX; appropriate ACL on Windows).

---

## Behavior Matrix

| Condition | Behavior |
|-----------|----------|
| `.cerebrofy/` missing, `.git/` present | Normal init |
| `.cerebrofy/` exists, `--force` absent | Warn + exit 0, no changes |
| `.cerebrofy/` exists, `--force` present | Overwrite scaffold files, re-check hooks |
| `.git/hooks/pre-push` exists | Append (unless marker present) |
| All MCP paths unwritable | Warn + print snippet + exit 0 |
| MCP entry already exists | Report + skip + exit 0 |
| Flat repo (no subdirs) | Single `root` Lobe + exit 0 |
| No `.git/` directory | Exit 1 |
