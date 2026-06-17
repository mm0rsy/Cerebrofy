# Design: Surgical Removal of SpecKit Coupling

**Date:** 2026-06-14
**Status:** Approved
**Scope:** Remove plan/tasks/specify/parse/LLM dead code; fix broken MCP stubs; archive Phase 4 spec

---

## Background

Cerebrofy's original design included a Phase 4 "AI Bridge" that coupled it to specKit — a separate agentic workflow tool. That coupling produced four unimplemented CLI commands (`plan`, `tasks`, `specify`, `parse`) and two MCP tools (`plan`, `tasks`) that crash at runtime because their dependencies (`search/hybrid.py`, `commands/plan.py`, `commands/tasks.py`, `llm/client.py`) were never built.

The decision: specKit collaboration was the wrong design. Cerebrofy's identity is a **local codebase knowledge graph with hybrid search**, not an agentic task planner. The plan/tasks/specify/parse surface area is being removed. `search/hybrid.py` is the one open thread that remains — it is Cerebrofy's actual moat and the next thing to build.

---

## Removal Scope

### `src/cerebrofy/mcp/server.py`

**Delete:**
- `_handle_plan()` function
- `_handle_tasks()` function
- `_FEATURE_SCHEMA` dict
- `plan` + `tasks` entries in `list_tools()`
- `plan` + `tasks` dispatch branches in `call_tool()`

**Fix (table name + column name bugs):**
- `_handle_get_neuron()`: `FROM neurons` → `FROM nodes`; fix column aliases `start_line`/`end_line` → `line_start`/`line_end` to match actual schema
- `_handle_list_lobes()`: `FROM neurons WHERE lobe IS NOT NULL` → `FROM nodes WHERE lobe IS NOT NULL`

**Replace (graceful stub):**
- `_handle_search_code()`: remove import of non-existent `cerebrofy.search.hybrid`; return a `TextContent` message: `"search_code is not yet available. Run 'cerebrofy build' to index your repo, then watch for the next release."`

**Update module docstring:** 8 tools → 6 tools; mark search_code as stub.

**Resulting tool state:**

| Tool | State |
|---|---|
| `search_code` | Stub — honest "not yet available" message |
| `get_neuron` | Operational (table fix applied) |
| `list_lobes` | Operational (table fix applied) |
| `cerebrofy_build` | Operational (unchanged) |
| `cerebrofy_update` | Operational (unchanged) |
| `cerebrofy_validate` | Operational (unchanged) |
| `plan` | **Deleted** |
| `tasks` | **Deleted** |

---

### `src/cerebrofy/config/loader.py`

**Delete from `CerebrофyConfig` dataclass:**
- `llm_endpoint: str = ""`
- `llm_model: str = ""`
- `llm_timeout: int = 60`

**Delete from `build_default_config()`:**
- `"llm_endpoint": ""`
- `"llm_model": ""`

**Delete from `load_config()`:**
- `llm_endpoint=data.get("llm_endpoint", "")`
- `llm_model=data.get("llm_model", "")`
- `llm_timeout=data.get("llm_timeout", 60)`

No consumers of these fields exist anywhere in the codebase.

---

### `specs/`

**Archive (move, do not delete):**
- `specs/004-ai-bridge/` → `specs/_archive/004-ai-bridge/`

Reason: the research notes on LLM streaming, the two-connection pattern, and the hybrid search data model will be useful reference when `search/hybrid.py` is implemented.

**Delete:**
- `specs/005-distribution-release/contracts/cli-parse.md`

Note: `cli-plan.md`, `cli-specify.md`, `cli-tasks.md` live only inside `specs/004-ai-bridge/contracts/` — they are covered by the archive move above, not a separate deletion.

---

### `tests/`

**No test files deleted.** Integration tests for plan/tasks/specify/parse (`test_plan_command.py`, `test_tasks_command.py`, `test_specify_command.py`, `test_parse_command.py` in `tests/integration/`) were never created — they exist only as CLAUDE.md documentation.

**Rename:**
- `tests/unit/test_parse_command.py` → `tests/unit/test_hooks_sentinel.py`

Reason: this file tests `_get_hook_version` and `_replace_hook_block` from `hooks/installer.py` — it was mislabeled from day one and has no connection to the parse command.

---

### `CLAUDE.md`

**Remove from project structure map:**
- `commands/parse.py`
- `commands/plan.py`
- `commands/tasks.py`
- `commands/specify.py`
- `llm/client.py`
- `llm/prompt_builder.py`
- All integration test files for the above (`test_specify_command.py`, `test_plan_command.py`, `test_tasks_command.py`, `test_parse_command.py`)

**Remove from "Key Invariants" section** (all Phase 4 + parse entries):
- Hybrid search connection
- RUNTIME_BOUNDARY in BFS (keep the edge invariant, remove the search note)
- Embedding before LLM call
- Spec file atomicity
- `cerebrofy plan --json` schema
- System prompt template
- Phase 4 read-only (both duplicate entries)
- `cerebrofy parse` read-only
- `blast_count` per-Neuron
- `schema_version` in plan --json

**Keep** (still valid future work):
- `search/hybrid.py` as the one remaining `⚠️ NOT YET IMPLEMENTED` item

**Update "Recent Changes":** add a note that plan/tasks/specify/parse and LLM client were removed; `search/hybrid.py` is the next milestone.

---

## What This Unblocks

With dead code gone:
- The MCP server has zero runtime-crashing tools
- `CerebrофyConfig` is clean (no phantom LLM fields)
- The `specs/` directory reflects what actually exists
- CLAUDE.md describes the real codebase, not aspirational fiction
- One open thread remains: `search/hybrid.py` — KNN + BFS hybrid search, which is Cerebrofy's genuine competitive moat

---

## Out of Scope

- Implementing `search/hybrid.py` (separate feature)
- Adding FTS5 to the existing schema (separate feature)
- Multi-repo support (future)
- Benchmark tooling (future)
- Fixing the 97% claim in README/CLI header (separate PR)
