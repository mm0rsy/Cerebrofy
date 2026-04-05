# Quickstart: Phase 5 — Distribution, Release Engineering & Cross-Phase Corrections

**Feature**: 005-distribution-release
**Date**: 2026-04-04

---

## Overview

Phase 5 has two independent tracks:

- **Track A**: Install Cerebrofy as a native package on macOS, Linux, or Windows.
  Use `cerebrofy mcp` to expose it as an AI tool.
- **Track B**: Retroactive corrections to Phase 1–4 specs (applied before implementing those phases).

This quickstart covers the end-user experience (Track A).

---

## Installation

### macOS (Homebrew)

```bash
brew tap cerebrofy/tap
brew install cerebrofy
cerebrofy --version
```

**No Python, no compiler, no PATH configuration required.**
All dependencies are bundled in the Homebrew bottle.

Upgrade:
```bash
brew upgrade cerebrofy
```

---

### Linux (Snap)

```bash
snap install cerebrofy --classic
cerebrofy --version
```

**Classic confinement** grants Cerebrofy unrestricted filesystem access — required for
indexing arbitrary repositories.

If Snap Store `--classic` approval is still pending, use pip as fallback:
```bash
pip install cerebrofy
```

---

### Windows (winget)

```powershell
winget install cerebrofy
# Open a NEW terminal session
cerebrofy --version
```

**No Python, no PATH editing required.** The installer adds Cerebrofy to `%PATH%`
automatically. A new terminal session is required for the `%PATH%` change to take effect.

> **Note**: The first `cerebrofy validate` invocation on Windows may take 2–5 seconds
> (cold-start extraction). This is a v1 known limitation. Subsequent invocations are fast.

Upgrade:
```powershell
winget upgrade cerebrofy
```

---

### All platforms (pip — universal fallback)

```bash
pip install cerebrofy
cerebrofy --version
```

For MCP server support:
```bash
pip install cerebrofy[mcp]
```

---

## Using `cerebrofy parse` (diagnostic)

Verify parser output before running a full build:

```bash
# Parse a single file
cerebrofy parse src/auth/login.py

# Parse an entire directory
cerebrofy parse src/

# Pipe to jq for exploration
cerebrofy parse src/ | jq 'select(.lobe == "auth")'
```

Output is **newline-delimited JSON** (NDJSON): one Neuron per line.

```json
{"file": "src/auth/login.py", "name": "login_user", "kind": "function", "line_start": 42, "line_end": 58, "signature": "def login_user(username: str, password: str) -> Optional[User]", "lobe": "auth"}
{"file": "src/auth/login.py", "name": "logout_user", "kind": "function", "line_start": 60, "line_end": 71, "signature": "def logout_user(session_id: str) -> None", "lobe": "auth"}
```

`cerebrofy parse` is **strictly read-only** — no index is created or modified.

---

## Using `cerebrofy mcp` (AI tool integration)

`cerebrofy init` registers the MCP server automatically. After init:

```bash
cerebrofy init
```

Open your AI tool — `cerebrofy plan`, `cerebrofy tasks`, and `cerebrofy specify` are now
available as structured tools.

### Multi-repo usage

Run `cerebrofy init` in each repository. Only **one MCP entry** is ever written to your AI
tool's config — the dispatcher reads the working directory at invocation time to route to
the correct repo.

```bash
cd ~/projects/my-api && cerebrofy init        # writes MCP entry (first time)
cd ~/projects/my-frontend && cerebrofy init   # no-op for MCP (entry already exists)
cd ~/projects/another-service && cerebrofy init  # no-op for MCP
```

Verify: open your AI tool's MCP config — confirm exactly one `"cerebrofy"` entry.

### Global registration

```bash
cerebrofy init --global
```

Writes to `~/.config/mcp/servers.json` — compatible with any MCP-compliant AI tool.

### Manual MCP server startup (for debugging)

```bash
cerebrofy mcp
# Starts stdio server, waits for MCP protocol input
# Ctrl+C to stop
```

---

## `.gitignore` — Automatic Index Protection

After `cerebrofy init`, the local index (`cerebrofy.db`) is automatically excluded from git:

```bash
cerebrofy init
cat .gitignore  # contains: .cerebrofy/db/
git add .       # cerebrofy.db does NOT appear in staging
```

If `.gitignore` already contains `.cerebrofy/db/`, no duplicate entry is added.

---

## Hook Sentinel Format (Cross-Phase Correction)

Phase 1's `cerebrofy init` installs a pre-push hook in this exact format:

```bash
# BEGIN cerebrofy
# cerebrofy-hook-version: 1
cerebrofy validate --hook pre-push
# END cerebroels
# END cerebrofy
```

Phase 3's upgrade function detects `# cerebrofy-hook-version: 1` and replaces the block
(within the sentinels) with the hard-block version (`cerebrofy-hook-version: 2`).

**Verify your hook format**:
```bash
cat .git/hooks/pre-push
# Expected lines:
# # BEGIN cerebrofy
# # cerebrofy-hook-version: 1  (or 2 if Phase 3 is applied)
# cerebrofy validate --hook pre-push
# # END cerebrofy
```

---

## Validate Output (Cross-Phase Correction)

The clean-state message from `cerebrofy validate` is:

```
Cerebrofy: Index is clean.
```

This exact string is asserted in all integration tests across Phases 3 and 4. If you see a
different message, you may be running a pre-correction version.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `cerebrofy: command not found` (Windows after install) | PATH not yet updated | Open a NEW terminal session |
| `cerebrofy mcp` not responding | `mcp` package not installed | `pip install cerebrofy[mcp]` |
| Multiple Cerebrofy MCP entries in AI tool config | Ran older version of `cerebrofy init` | Remove duplicate entries manually |
| `cerebrofy parse` fails with "No Cerebrofy config found" | `cerebrofy init` not run | Run `cerebrofy init` first |
| `cerebrofy.db` appears in `git status` | `.gitignore` not updated | Run `cerebrofy init` again; add `.cerebrofy/db/` to `.gitignore` |
| Windows: `cerebrofy validate` takes 5+ seconds on first run | Cold-start extraction (v1 limitation) | Expected behavior — subsequent runs are fast |
| Hook version still shows `cerebrofy-hook-version: 1` after Phase 3 upgrade | Phase 3 not yet run | Run `cerebrofy migrate` or re-run Phase 3 setup |

---

## Key Invariants

- `cerebrofy parse` makes zero writes to disk — safe to run at any time
- `cerebrofy mcp` (`plan` and `tasks` tools) makes zero network calls — safe offline
- `cerebrofy init` runs in 10 repos → exactly 1 MCP entry in AI tool config
- `cerebrofy.db` is always excluded from git after `cerebrofy init`
- The hook sentinel format is `# BEGIN cerebrofy` / `# cerebrofy-hook-version: N` / ... / `# END cerebrofy`
