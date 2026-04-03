# Contract: `cerebrofy validate` CLI Interface

**Feature**: 003-autonomic-nervous-system
**Date**: 2026-04-03
**Stability**: Draft

---

## Command Signature

```
cerebrofy validate [--hook PRE_PUSH]
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--hook pre-push` | — | Invoked by the git hook. Output and exit behavior are identical to standalone; flag is reserved for future hook-specific optimizations. |
| `--help` | — | Print usage and exit. |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | No drift, OR minor drift only (whitespace/comments). Push may proceed. |
| `1` | Structural drift detected. Push MUST be blocked. |

**Special case**: Missing index (`.cerebrofy/` absent or `cerebrofy.db` absent) → exit `0` (WARN-only, never block).

---

## Standard Output (stdout)

**No drift**:
```
Cerebrofy: Index is current. No drift detected.
```

**Minor drift only**:
```
Cerebrofy: Minor drift detected in N file(s) — whitespace/comments only.
Cerebrofy: Suggestion: run 'cerebrofy update' to keep the index current.
```

**Structural drift**:
```
Cerebrofy: STRUCTURAL DRIFT DETECTED — push blocked.
Cerebrofy: The following code units are out of sync with the index:

  {file}::{function_name}  [added]
  {file}::{function_name}  [removed]
  {file}::{function_name}  [signature changed]
  {file}                   [import added/removed]

Run 'cerebrofy update' to resync, then retry your push.
```

**Missing index**:
```
Cerebrofy: No index found. Run 'cerebrofy init && cerebrofy build' to initialize.
```

---

## Standard Error (stderr)

Warnings only (non-fatal conditions that do not affect drift classification):

| Situation | Message format |
|-----------|----------------|
| Syntax error re-parsing changed file | `Warning: Syntax error in {file} at line {N} during validation. Results may be incomplete.` |

---

## Drift Classification Algorithm

1. **Hash scan**: For every tracked file, compute SHA-256(content). Compare against
   `file_hashes` table. Files with matching hashes → skip (no drift). Collect changed files.

2. **Re-parse**: For each changed file, run Phase 1 parser → get new `ParseResult`.

3. **Neuron diff**: Compare new Neurons vs. indexed Neurons for that file:
   - Use `name` + whitespace-normalized `signature` as the comparison key
   - Also compare import captures (added/removed imports = structural)
   - If all Neurons match exactly and no imports changed → **minor**
   - If any Neuron added, removed, renamed, or signature changed → **structural**

4. **Classify overall**: If ANY file is structural → overall result is structural → exit 1.
   If all changed files are minor → exit 0 with minor warning.

**Read-only**: `cerebrofy validate` NEVER writes to `cerebrofy.db` or any Markdown file.

---

## Hook Integration

The pre-push hook script (installed/upgraded by `hooks/installer.py`) calls:

```sh
cerebrofy validate --hook pre-push
exit_code=$?
if [ $exit_code -ne 0 ]; then
  exit 1
fi
```

In WARN-only mode (hook version 1), the hook always exits 0 regardless of validate's output.
In hard-block mode (hook version 2), the hook exits with validate's exit code.

**Identical behavior guarantee**: Running `cerebrofy validate` at the terminal produces
byte-identical output and the same exit code as when invoked by the hook.
