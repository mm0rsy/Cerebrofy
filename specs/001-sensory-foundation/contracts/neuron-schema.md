# Contract: Neuron Schema

**Feature**: 001-sensory-foundation
**Date**: 2026-04-03
**Stability**: Draft — consumed by Phase 2 (cerebrofy build) to populate cerebrofy.db

---

## Overview

A Neuron is the normalized output record produced by the Universal Parser for each named code
unit in a tracked source file. All Neurons share the same schema regardless of the source
language. This schema is the contract between Phase 1 (parser) and Phase 2 (graph builder).

---

## Schema Definition

```
Neuron {
  id          : string   -- REQUIRED. "{relative_file_path}::{name}"
  name        : string   -- REQUIRED. Name as it appears in source.
  type        : enum     -- REQUIRED. "function" | "class" | "module"
  file        : string   -- REQUIRED. Relative path from repo root.
  line_start  : integer  -- REQUIRED. 1-based, inclusive.
  line_end    : integer  -- REQUIRED. 1-based, inclusive.
  signature   : string?  -- OPTIONAL. null if not available or type is "module".
  docstring   : string?  -- OPTIONAL. null if no docstring present.
}
```

---

## Field Specifications

### `id`

Format: `"{file}::{name}"`

- `file` — the same value as the `file` field (relative path, forward slashes on all platforms).
- `name` — the same value as the `name` field.
- Separator — double colon `::` (chosen to avoid conflicts with single-colon paths on Windows).

**Examples**:
```
src/auth/login.py::authenticate
src/utils/helpers.js::formatDate
pkg/api/handler.go::HandleRequest
```

**Uniqueness**: IDs are unique within the Cerebrofy index. Within a file, if two code units
share the same `name`, only the first occurrence (lowest `line_start`) is kept; subsequent
duplicates are silently dropped.

**Cross-file**: IDs from different files are always distinct because `file` differs.

---

### `name`

The literal name of the code unit as declared in source. No transformation or normalization.

| Source construct | `name` value |
|-----------------|--------------|
| `def authenticate(...)` | `"authenticate"` |
| `class UserProfile` (no methods) | `"UserProfile"` |
| `function handleRequest() {}` | `"handleRequest"` |
| Module-level code | Filename stem without extension (e.g., `"login"` for `login.py`) |

---

### `type`

| Value | When assigned |
|-------|--------------|
| `"function"` | Named function definition at any nesting level; named method inside a class with methods. |
| `"class"` | Class definition that has **no** methods. |
| `"module"` | Synthetic record for module-level code outside all functions and classes. At most one per file. |

**Not produced**:
- Anonymous functions / lambda expressions → skipped entirely.
- Classes **with** methods → only the methods produce Neurons; no class-level Neuron is created.

---

### `file`

Relative path from repository root to the source file. Always uses forward slashes (`/`),
even on Windows. No leading `./`.

**Examples**: `"src/auth/login.py"`, `"api/handlers/user.go"`, `"main.rs"`

---

### `line_start` / `line_end`

1-based line numbers. Both are inclusive.

- For `"function"` and `"class"` types: the full extent of the declaration including body.
- For `"module"` type: line 1 through the last line of the file.

---

### `signature`

The full declaration line of a function or method, including parameter list and return type
annotation if present in source.

| Language | Example signature |
|----------|------------------|
| Python | `"def authenticate(user: str, password: str) -> bool"` |
| TypeScript | `"function handleRequest(req: Request, res: Response): void"` |
| Go | `"func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request)"` |

`null` for `"class"` and `"module"` types.

---

### `docstring`

The first contiguous docstring or documentation comment block immediately following the
definition header. Whitespace-trimmed. Language-specific comment styles are normalized to
plain text.

`null` if no docstring is present or if `type` is `"module"`.

---

## Parser Output: ParseResult

The parser returns one `ParseResult` per file:

```
ParseResult {
  file     : string          -- Relative path of the processed file.
  neurons  : list[Neuron]    -- All extracted Neurons, ordered by line_start ascending.
  warnings : list[string]    -- Non-empty only when syntax errors or skipped duplicates occurred.
}
```

**Warning message formats**:
- Syntax error: `"Syntax error in {file} at line {N}: {description}. File partially parsed."`
- Duplicate skipped: `"Duplicate name '{name}' in {file} at line {N}: skipped (kept line {M})."`

---

## Invariants

The following invariants MUST hold for every Neuron produced by the parser:

1. `id == f"{file}::{name}"`
2. `line_start >= 1` and `line_end >= line_start`
3. `type` is exactly one of `"function"`, `"class"`, `"module"`
4. `signature` is `null` iff `type != "function"`
5. No two Neurons in the same ParseResult share the same `id`
6. For `type == "module"`, `name` equals the filename stem (no extension)

---

## Example: Python File

**Source** (`src/auth/login.py`, 10 lines):
```python
"""Authentication module."""

def authenticate(user: str, password: str) -> bool:
    """Validates credentials."""
    return check_db(user, password)

TIMEOUT = 30   # module-level constant
```

**ParseResult**:
```json
{
  "file": "src/auth/login.py",
  "neurons": [
    {
      "id": "src/auth/login.py::authenticate",
      "name": "authenticate",
      "type": "function",
      "file": "src/auth/login.py",
      "line_start": 3,
      "line_end": 5,
      "signature": "def authenticate(user: str, password: str) -> bool",
      "docstring": "Validates credentials."
    },
    {
      "id": "src/auth/login.py::login",
      "name": "login",
      "type": "module",
      "file": "src/auth/login.py",
      "line_start": 1,
      "line_end": 10,
      "signature": null,
      "docstring": null
    }
  ],
  "warnings": []
}
```
