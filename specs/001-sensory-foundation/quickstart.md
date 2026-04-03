# Quickstart: Phase 1 — Sensory Foundation

**Feature**: 001-sensory-foundation
**Date**: 2026-04-03

This guide validates that the Phase 1 implementation is working correctly from end to end.

---

## Prerequisites

- Cerebrofy installed and available on `PATH` (`cerebrofy --version` prints a version number).
- A git repository to test against (can be the Cerebrofy repo itself or any other).

---

## Step 1: Run `cerebrofy init`

```sh
cd /path/to/any-git-repo
cerebrofy init
```

**Expected output**:
```
Cerebrofy: Scanning project structure...
Cerebrofy: Detected lobes: <list of lobe names>
Cerebrofy: Writing .cerebrofy/config.yaml
Cerebrofy: Writing .cerebrofy-ignore
Cerebrofy: Installing git hooks (warn-only mode)
Cerebrofy: MCP server registered → <path to config file>
Cerebrofy initialized. Run `cerebrofy build` to index your codebase.
```

**Verify scaffold**:
```sh
ls .cerebrofy/
# Expected: config.yaml  db/  queries/  scripts/
ls .cerebrofy/queries/
# Expected: python.scm  javascript.scm  typescript.scm  go.scm ... (one per language)
cat .cerebrofy-ignore
# Expected: default ignore list (node_modules/, __pycache__/, etc.)
ls .git/hooks/
# Expected: pre-push  post-merge  (and any previously existing hooks)
```

**Verify NO database created**:
```sh
ls .cerebrofy/db/
# Expected: empty (no cerebrofy.db file — that's Phase 2)
```

---

## Step 2: Verify Config

```sh
cat .cerebrofy/config.yaml
```

**Expected structure**:
```yaml
lobes:
  <lobe-name>: <directory-path>/
  ...

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

embedding_model: local
embed_dim: 768
llm_endpoint: openai
llm_model: gpt-4o
top_k: 10
```

Verify the `lobes` section reflects the actual directory structure of the test repo.

---

## Step 3: Verify Git Hooks (Warn-Only)

```sh
cat .git/hooks/pre-push
# Expected: contains "cerebrofy validate --hook pre-push"
# Expected: contains the cerebrofy-hook-start marker
# Expected: exits 0 (does NOT block push) at this stage
```

Make a test push to confirm no blocking occurs:
```sh
git add .cerebrofy .cerebrofy-ignore
git commit -m "test: add cerebrofy scaffold"
git push   # Should succeed; hook runs in warn-only mode
```

---

## Step 4: Verify MCP Registration

**Claude Desktop (macOS)**:
```sh
cat ~/Library/Application\ Support/Claude/claude_desktop_config.json | grep cerebrofy
# Expected: "cerebrofy" entry under mcpServers
```

**Cursor**:
```sh
cat ~/.cursor/mcp.json | grep cerebrofy
# Expected: "cerebrofy" entry
```

**Idempotency test** — run `cerebrofy init` a second time:
```sh
cerebrofy init
# Expected: "Warning: .cerebrofy/ already exists" OR (with --force) re-init without duplicate MCP entry
```

---

## Step 5: Verify Parser (Standalone)

Run the parser directly on a single Python file to confirm Neuron extraction:

```sh
cerebrofy parse src/cerebrofy/cli.py
# Expected: JSON output listing all functions/classes with id, name, type, file, line_start, line_end
```

Or on a directory:
```sh
cerebrofy parse src/
# Expected: Neurons for every .py file not excluded by .cerebrofy-ignore or .gitignore
```

Check that:
- Anonymous lambdas do NOT appear in output.
- Named nested functions DO appear.
- Module-level code appears as a single `"module"` type Neuron per file.

---

## Step 6: Verify Language Agnosticism

```sh
# Test with a Go file (if available)
cerebrofy parse some-file.go
# Expected: same Neuron schema as Python output (id, name, type, file, line_start, line_end, signature, docstring)
```

---

## Step 7: Add a New Language (Law V Verification)

1. Create a minimal `.scm` query file for a new language (e.g., Kotlin):
   ```sh
   echo '(function_declaration name: (simple_identifier) @name) @function_definition' \
     > .cerebrofy/queries/kotlin.scm
   ```
2. Add `.kt` to `tracked_extensions` in `.cerebrofy/config.yaml`.
3. Run `cerebrofy parse path/to/file.kt`.
4. Confirm: Neurons are produced, no changes to core engine code required.

---

## Edge Case Tests

| Scenario | Command | Expected Outcome |
|----------|---------|-----------------|
| Flat repo (no subdirs) | `mkdir /tmp/flat && cd /tmp/flat && git init && cerebrofy init` | Single `root` Lobe; init exits 0 |
| Syntax error in source file | Run parser on a file with broken syntax | Warning printed; other files parsed successfully |
| MCP unwritable | `chmod 000` all MCP config dirs, then `cerebrofy init` | Prints JSON snippet to stderr; exits 0 |
| Pre-existing hook | Create a custom `pre-push` then run `cerebrofy init` | Original content preserved; cerebrofy block appended |

---

## Phase 1 Complete

If all steps above pass, Phase 1 is complete. Proceed to `cerebrofy build` (Phase 2) to create
`cerebrofy.db` and produce the indexed graph.
