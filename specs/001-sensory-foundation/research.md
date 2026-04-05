# Research: Phase 1 — Sensory Foundation

**Feature**: 001-sensory-foundation
**Date**: 2026-04-03
**Status**: Complete — all decisions resolved

---

## Decision 1: Tree-sitter Python Binding

**Decision**: Use `tree-sitter` + `tree-sitter-languages` (Python packages).

**Rationale**: `tree-sitter-languages` bundles pre-compiled parsers for 40+ languages as Python
wheels, meaning users on macOS, Linux, and Windows never need a C compiler. The `tree-sitter`
package provides the Python Query API for executing `.scm` capture files. This satisfies Law V
(Agnosticism) directly: the engine never contains language-specific logic — all parsing rules
live in `.scm` query files.

**Alternatives considered**:
- `tree-sitter` alone (without `tree-sitter-languages`): requires users to build grammars from
  source — violates the "no C compiler on user machines" requirement from Blueprint Section XI.
- `libcst` or `ast` (Python-only): language-specific, violates Law V.
- ANTLR: generates separate parsers per language, much larger dependency footprint.

---

## Decision 2: Ignore File Parsing

**Decision**: Use `pathspec` library for `.cerebrofy-ignore` and `.gitignore` pattern matching.

**Rationale**: `pathspec` implements the full gitignore spec including negation patterns, `**`
globbing, and directory-only rules (trailing `/`). It is pure Python, actively maintained, and
widely used. A single `pathspec.PathSpec.from_lines("gitwildmatch", lines)` call handles both
ignore files identically.

**Alternatives considered**:
- Manual `fnmatch`: does not cover directory-only rules or negation.
- `gitignore_parser`: less actively maintained, narrower API.
- Calling `git check-ignore`: subprocess dependency, fails on repos with no commits.

---

## Decision 3: Configuration File (config.yaml)

**Decision**: Use `PyYAML` for reading and writing `.cerebrofy/config.yaml`.

**Rationale**: PyYAML is the de-facto standard, ships with most Python environments, and handles
the config structure (nested dicts, lists) without issues. Comments are preserved on user edits
only when using `ruamel.yaml`, which is heavier. Since Cerebrofy rewrites the whole file
atomically via `init`, `PyYAML` is sufficient.

**Alternatives considered**:
- `tomllib` / `tomli`: TOML is less human-friendly for nested structures like the Lobe map.
- `ruamel.yaml`: preserves comments but adds complexity not needed in Phase 1.
- JSON: poor readability for config files.

---

## Decision 4: MCP Server Detection and Registration

**Decision**: Check MCP config paths in the priority order defined in Blueprint Section XI,
write to the first writable path, and report the result. Use a dispatcher pattern so multiple
`cerebrofy init` calls produce one entry.

**Priority order** (checked in sequence):
1. Claude Desktop (macOS): `~/Library/Application Support/Claude/claude_desktop_config.json`
2. Claude Desktop (Windows): `%APPDATA%\Claude\claude_desktop_config.json`
3. Cursor (macOS/Linux): `~/.cursor/mcp.json`
4. Cursor (Windows): `%APPDATA%\Cursor\mcp.json`
5. Opencode: `~/.config/opencode/mcp.json`
6. Generic MCP standard: `~/.config/mcp/servers.json`
7. Fallback: create `~/.config/mcp/servers.json`

**Idempotency**: Before writing, check if an entry named `"cerebrofy"` already exists under
`mcpServers`. If found, skip and report. This satisfies FR-006.

**Failure handling**: If all paths are unwritable, print the full JSON snippet for manual
copy-paste and complete init with exit 0. This satisfies FR-005 (non-fatal fallback).

**MCP entry format**:
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

**Alternatives considered**:
- Per-repo MCP entries: creates N entries for N repos, breaking the single-dispatcher design.
- Manual MCP setup docs only: violates FR-005 (no manual editing required).

---

## Decision 5: Git Hook Installation Strategy

**Decision**: Append Cerebrofy's hook call to existing hook scripts rather than overwriting.
Create the hook file if it does not exist. Ensure the script is executable (`chmod +x`).

**Append format** (added to end of existing script):
```sh
# cerebrofy-hook-start
cerebrofy validate --hook pre-push
# cerebrofy-hook-end
```

**Idempotency**: Before appending, check if the `# cerebrofy-hook-start` marker already exists.
If found, skip. This prevents duplicate entries on repeated `cerebrofy init` calls.

**Rationale**: Appending preserves prior hook workflows (linters, test runners). The marker
pattern enables idempotent re-runs. This satisfies FR-004 and the clarification from
`/speckit.clarify`.

**Alternatives considered**:
- Overwrite silently: destroys existing hook workflows, a trust-breaking action.
- Husky/lefthook delegation: adds a dependency on a JS ecosystem tool.
- Separate hooks directory: not compatible with standard `.git/hooks/` lookup.

---

## Decision 6: Lobe Auto-Detection Algorithm

**Decision**: Three-tier detection with flat-repo fallback, capped at depth 2.

**Algorithm**:
```
1. If src/ exists at repo root → use immediate subdirectories of src/ as Lobes
2. Else scan top-level directories for monorepo manifest files
   (package.json, pyproject.toml, go.mod, Cargo.toml, pom.xml)
   → each directory containing a manifest becomes a Lobe
3. Else use all top-level directories as Lobes
4. If no directories found (flat repo) → create one Lobe named "root" mapped to "."
5. Cap: include only directories at depth ≤ 2 from project root
```

**Rationale**: Covers the three common layouts (src-based, monorepo, flat) plus the edge case
of a completely flat repo (clarified in `/speckit.clarify`).

**Alternatives considered**:
- Prompt user interactively: violates FR-001 (no user input required).
- Always use root: too coarse for multi-module projects.

---

## Decision 7: Query File Bundling Strategy

**Decision**: Bundle default `.scm` query files inside the Cerebrofy Python package
(`src/cerebrofy/queries/`). During `cerebrofy init`, copy them to `.cerebrofy/queries/` in the
user's repo. This gives users a local, editable copy.

**Default languages bundled**: Python, JavaScript, TypeScript, TSX, JSX, Go, Rust, Java, Ruby,
C, C++, C headers.

**Captures required per language** (from Blueprint Section III, 1.1):
- `function_definition`
- `class_definition`
- `import_statement`
- `call_expression`

**Rationale**: Copying to the user's repo enables per-project customization and satisfies
FR-013 (new languages added without engine changes). The user can add new `.scm` files alongside
the defaults.

---

## Decision 8: Neuron Name Collision Handling

**Decision**: Keep `{file}::{name}` as the ID format. When multiple code units in the same file
share the same name, keep only the first occurrence and silently discard the rest.

**Rationale**: Clarified in `/speckit.clarify` — Option A was chosen. This keeps the ID schema
simple and avoids adding disambiguation suffixes that would make IDs non-deterministic across
runs. The trade-off (some functions invisible in the graph) is accepted for v1 simplicity.

---

## Decision 9: Named Nested Function Extraction

**Decision**: Extract named nested functions (a `def` or equivalent inside another function)
as individual Neurons. Skip anonymous functions and lambda expressions entirely.

**Rationale**: Clarified in `/speckit.clarify` — Option B. Named closures have stable,
addressable identities compatible with the `{file}::{name}` ID scheme. Anonymous lambdas do not.

**Implementation note**: Tree-sitter query captures for `function_definition` will naturally
match nested named functions. Anonymous function captures (`lambda_expression` etc.) must be
explicitly excluded in the `.scm` query files.
