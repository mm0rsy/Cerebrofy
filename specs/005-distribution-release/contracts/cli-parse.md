# Contract: `cerebrofy parse`

**Phase**: 5 (also retroactive correction to Phase 1)
**Status**: New command — authorizes creation of `commands/parse.py`
**Blueprint Review Finding**: G-H1

---

## Command Signature

```
cerebrofy parse <path>
```

| Argument | Type | Required | Description |
|----------|------|----------|-------------|
| `path` | string | Yes | File path or directory path to parse |

**No flags** — the parse command is intentionally minimal (diagnostic tool).

---

## Preconditions

| # | Condition | If Not Met |
|---|-----------|------------|
| 1 | `.cerebrofy/config.yaml` exists (repo is initialized) | Exit 1: `"No Cerebrofy config found. Run 'cerebrofy init' first."` |
| 2 | `path` exists on the filesystem | Exit 1: `"Path not found: <path>"` |

`cerebrofy.db` does NOT need to exist. `cerebrofy parse` is strictly read-only and does not
open the database.

---

## Execution Flow

1. Load `CerebrофyConfig` from `.cerebrofy/config.yaml` (walk up from CWD to find repo root)
2. Load `IgnoreRuleSet` from `.cerebrofy-ignore` and `.gitignore`
3. Determine target files:
   - If `path` is a file: single file `[path]`
   - If `path` is a directory: all files matching `tracked_extensions` under `path`, recursively
4. For each target file:
   a. Check `IgnoreRuleSet` — if excluded: print `"<path>: excluded by ignore rules"` to stdout, skip
   b. Run `parser/engine.py` on the file
   c. For each extracted `Neuron`: serialize to JSON, write to stdout (newline-terminated)
   d. On syntax error: print warning to stderr: `"Warning: <path>: parse error at line <N>"`,
      continue with successfully extracted Neurons
5. Exit 0 on success (including the case of zero Neurons extracted)
6. Exit 1 only on precondition failure (no config, path not found)

---

## Output

### stdout — NDJSON stream

One JSON object per line. Each line is a complete, valid JSON object (no trailing comma,
no array wrapper). Empty output (zero lines) is valid when the file has no extractable Neurons.

**Fields per line**:
```json
{
  "file": "src/auth/login.py",
  "name": "login_user",
  "kind": "function",
  "line_start": 42,
  "line_end": 58,
  "signature": "def login_user(username: str, password: str) -> Optional[User]",
  "lobe": "auth"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `file` | string | Path relative to repo root |
| `name` | string | Neuron name (function, class, or method name) |
| `kind` | string | One of: `"function"`, `"class"`, `"method"`, `"async_function"` |
| `line_start` | integer | 1-based start line |
| `line_end` | integer | 1-based end line (inclusive) |
| `signature` | string | Normalized signature text |
| `lobe` | string | Detected lobe name |

The field set is identical to the `Neuron` dataclass in `parser/neuron.py`. No additional
fields are added. No fields are omitted.

### stderr

Parse warnings only. Not present in normal operation:
```
Warning: src/broken.py: parse error at line 23
```

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | Success (including zero Neurons extracted) |
| 1 | Precondition failure (no config, path not found) |

---

## Key Invariants

1. **Strictly read-only**: `cerebrofy parse` MUST NOT create or modify `cerebrofy.db`,
   any `.tmp` file, any lobe `.md` file, or any file under `.cerebrofy/`. If any write
   occurs, it is a contract violation.

2. **Ignore rules apply**: Files excluded by `.cerebrofy-ignore` or `.gitignore` MUST be
   skipped. The excluded file message is printed to stdout (not stderr), so it appears
   in-stream with the Neuron output.

3. **Syntax errors are non-fatal**: A parse error in one file MUST NOT prevent output of
   Neurons from other files in a directory scan.

4. **Output is the Neuron dataclass**: The JSON schema is derived directly from
   `parser/neuron.py`. Any addition of fields to the `Neuron` dataclass is automatically
   reflected here.

5. **No config.yaml required for the parse operation itself**: `config.yaml` is needed only
   to determine `tracked_extensions` (for directory scan filtering) and ignore rules.
   The parser engine itself is language-agnostic.

---

## Behavior Matrix

| Scenario | stdin | stdout | stderr | Exit |
|----------|-------|--------|--------|------|
| Single Python file, 3 functions | — | 3 JSON lines | — | 0 |
| Directory with 5 tracked files | — | N JSON lines (all Neurons) | — | 0 |
| File excluded by `.gitignore` | — | `"<path>: excluded by ignore rules"` | — | 0 |
| File with syntax error | — | Successfully extracted Neurons | Warning line | 0 |
| Path not found | — | — | — | 1 (error message on stderr) |
| No `.cerebrofy/config.yaml` | — | — | — | 1 (error message on stderr) |
| Empty file (no Neurons) | — | *(empty)* | — | 0 |

---

## Relationship to Other Commands

- **`cerebrofy build`**: Runs the same parser internally but writes results to `cerebrofy.db`.
  `cerebrofy parse` is a diagnostic that shows what `cerebrofy build` would extract for specific
  files, without committing anything.
- **`cerebrofy validate`**: Reads from `cerebrofy.db`. `cerebrofy parse` does not.
- **`cerebrofy init`**: Must have been run first (provides `config.yaml`).

---

## Implementation Notes

- `commands/parse.py` implements the Click command
- Reuses `parser/engine.py` (no new parser logic)
- Reuses `ignore/ruleset.py` for ignore filtering
- Reuses `config/loader.py` for config loading
- The `Neuron` dataclass serializes via `dataclasses.asdict()` — no custom serializer needed
- Sort order of Neurons in output: file order (directory walk order), then `line_start` ascending
