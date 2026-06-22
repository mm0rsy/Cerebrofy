# Idea #05 — AI Agent Memory Layer: Design Spec

**Date:** 2026-06-21
**Status:** Approved
**Scope:** All three phases in one PR (`feat/05-agent-memory-layer`)

---

## Context

Cerebrofy's semantic index is read-only. Every AI coding session starts from zero — no record of past decisions, known gotchas, or rationale for how code ended up the way it did. Feature #05 adds a writable memory store attached to neurons and lobes, enabling agents and humans to deposit structured knowledge that persists across sessions and survives full rebuilds.

This is the foundational layer that unblocks:
- `memory_stale_count` in `epistemic/state.py` (#22 D3 — currently always 0)
- Idea #21 (Insight Daemon) memory storage
- Ideas #06, #12, #17 which query memory context

---

## Approach

Flat `memory/` subpackage (Approach A). Complete final schema defined upfront — no intra-PR migrations needed. Three phases implemented in one PR. Pattern mirrors `health/`, `epistemic/`, `intent/`.

---

## Data Model

### New tables added to `db/schema.py`

**`memories`** — core store:

```sql
CREATE TABLE memories (
    id          TEXT PRIMARY KEY,        -- UUID v4
    neuron_id   TEXT,                    -- nullable FK → nodes.id
    lobe        TEXT,                    -- nullable lobe name
    type        TEXT NOT NULL,           -- decision|warning|context|pattern|agent_action|insight
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    author      TEXT,                    -- "claude-sonnet-4-6" | "human:alice@co.com"
    created_ts  INTEGER NOT NULL,        -- unix timestamp
    tags        TEXT,                    -- comma-separated
    decay_score REAL NOT NULL DEFAULT 1.0,
    status      TEXT NOT NULL DEFAULT 'active',  -- active|possibly_stale|stale
    vec_id      TEXT                     -- FK → vec_memories rowid
);
CREATE INDEX idx_memories_neuron ON memories(neuron_id);
CREATE INDEX idx_memories_lobe   ON memories(lobe);
CREATE INDEX idx_memories_type   ON memories(type);
```

**`vec_memories`** — semantic search (Law III extended: every memory MUST have a row here):

```sql
CREATE VIRTUAL TABLE vec_memories USING vec0(embedding FLOAT[384]);
```

**`memory_edges`** — causal graph (Phase 2):

```sql
CREATE TABLE memory_edges (
    from_memory_id  TEXT NOT NULL REFERENCES memories(id),
    to_memory_id    TEXT NOT NULL REFERENCES memories(id),
    rel_type        TEXT NOT NULL,  -- caused|motivated|resolved|contradicts|updated_by
    created_ts      INTEGER NOT NULL,
    author          TEXT,
    PRIMARY KEY (from_memory_id, to_memory_id, rel_type)
);
```

### Config additions (`config.yaml` + `CerebrоfyConfig`)

New optional `MemoryConfig` dataclass with defaults:

```yaml
memory:
  decay_half_life_days: 70       # time-based half-life
  stale_threshold: 0.1           # below → status='stale'
  possibly_stale_threshold: 0.3  # below → status='possibly_stale'
```

`CerebrоfyConfig` gains `memory: MemoryConfig` field. If absent from `config.yaml`, defaults apply.

---

## `memory/` Subpackage

```
src/cerebrofy/memory/
├── __init__.py
├── store.py      — Memory + MemoryEdge dataclasses; CRUD; trace_history
├── search.py     — recall_memories(): KNN on vec_memories
├── embedder.py   — embed_memory(): title+body concat → LocalEmbedder
└── decay.py      — compute_decay(); recompute_all_decay()
```

### `store.py`

```python
@dataclass(frozen=True)
class Memory:
    id: str
    neuron_id: str | None
    lobe: str | None
    type: str
    title: str
    body: str
    author: str | None
    created_ts: int
    tags: tuple[str, ...]
    decay_score: float
    status: str  # active | possibly_stale | stale

@dataclass(frozen=True)
class MemoryEdge:
    from_memory_id: str
    to_memory_id: str
    rel_type: str
    created_ts: int
    author: str | None
```

Public functions:
- `write_memory(conn, memory) -> str` — inserts into `memories` + `vec_memories`, returns UUID
- `get_memory(conn, id) -> Memory | None`
- `list_memories(conn, neuron_id?, lobe?, type?, include_stale=False) -> list[Memory]`
- `delete_memory(conn, id) -> None` — also removes `vec_memories` row
- `write_memory_edge(conn, edge) -> None`
- `trace_history(conn, memory_id, depth=5) -> list[Memory]` — BFS backward through `memory_edges`; depth cap prevents cycles

### `search.py`

```python
def recall_memories(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    limit: int = 10,
    type_filter: str | None = None,
    lobe_filter: str | None = None,
    include_stale: bool = False,
) -> list[tuple[Memory, float]]:
```

KNN on `vec_memories`, joins back to `memories`, applies filters post-KNN. Returns `(Memory, similarity_score)` pairs sorted by similarity desc.

### `embedder.py`

```python
def embed_memory(title: str, body: str) -> list[float]:
    text = f"{title} {body}"
    return LocalEmbedder().embed([text])[0]
```

Kept separate for test isolation — callers mock this, not `LocalEmbedder` directly.

### `decay.py`

Decay formula (Phase 3):

```python
import math

def compute_decay(
    memory: Memory,
    neuron_signature_changed: bool,
    current_ts: int,
    config: MemoryConfig,
) -> float:
    days_since = (current_ts - memory.created_ts) / 86400.0
    time_factor = math.exp(-math.log(2) / config.decay_half_life_days * days_since)
    stability_factor = 0.3 if neuron_signature_changed else 1.0
    return round(time_factor * stability_factor, 4)

def recompute_all_decay(
    conn: sqlite3.Connection,
    changed_neuron_ids: set[str],
    config: MemoryConfig,
) -> int:
    """Recompute decay for memories attached to changed neurons.
    Returns count of memories whose status changed."""
```

Status transitions:
- `decay_score >= possibly_stale_threshold` → `active`
- `stale_threshold <= decay_score < possibly_stale_threshold` → `possibly_stale`
- `decay_score < stale_threshold` → `stale`

---

## CLI — `commands/memory.py`

Registered in `cli.py` as `cerebrofy memory`. Five subcommands:

### `cerebrofy memory add`

```
cerebrofy memory add TITLE
    --type      TEXT   [required] decision|warning|context|pattern|agent_action
    --body      TEXT   [required] Full memory content (or read from stdin with -)
    --neuron    TEXT   Neuron name or file::name to attach to
    --lobe      TEXT   Lobe name to attach to
    --tags      TEXT   Comma-separated tags
    --author    TEXT   Defaults to git config user.email → "human:<email>";
                       falls back to "human:unknown"
```

Writes memory + embedding. Prints generated UUID.

### `cerebrofy memory search`

```
cerebrofy memory search QUERY
    --type          TEXT    Filter by type
    --lobe          TEXT    Filter by lobe
    --limit         INT     Default 10
    --include-stale FLAG    Include possibly_stale and stale memories
```

### `cerebrofy memory list`

```
cerebrofy memory list
    --neuron        TEXT    Filter by neuron
    --lobe          TEXT    Filter by lobe
    --type          TEXT    Filter by type
    --include-stale FLAG
```

At least one of `--neuron` or `--lobe` required.

### `cerebrofy memory link`

```
cerebrofy memory link FROM_ID TO_ID
    --rel   TEXT  [required] caused|motivated|resolved|contradicts|updated_by
```

### `cerebrofy memory export`

```
cerebrofy memory export
    --format    TEXT  markdown (default) | json
    --lobe      TEXT  Optional filter
    --type      TEXT  Optional filter
```

---

## MCP Tools

Three new tools added to `server.py`. All follow the existing handler pattern.

### `cerebrofy_remember`

Write a memory. `author` defaults to `"agent:<model-id>"` server-side when called via MCP.

**Input:** `title` (required), `body` (required), `type` (required), `neuron?`, `lobe?`, `tags?`, `author?`

**Output:** `{"id": "...", "neuron_id": "...|null", "created_ts": 1234567890}`

Returns directly (no cross-cutting epistemic/intent injection — same pattern as `cerebrofy_epistemic`).

If `neuron` param is unresolvable: writes memory with `neuron_id=NULL`, includes `"warning": "neuron not found — memory stored without anchor"` in response.

### `cerebrofy_recall`

Semantic search across memories.

**Input:** `query` (required), `type?`, `lobe?`, `limit?` (default 10), `include_stale?` (default false)

**Output:**
```json
{
  "memories": [{
    "id": "...", "title": "...", "body": "...", "type": "...",
    "neuron": "...|null", "lobe": "...|null", "author": "...",
    "created_ts": 1234567890, "tags": ["..."],
    "decay_score": 0.94, "status": "active",
    "relevance_score": 0.87
  }]
}
```

If embedding model unavailable: returns `{"memories": [], "error": "embedding unavailable"}`.

### `cerebrofy_memories`

List memories for a neuron or lobe (no embedding required).

**Input:** `neuron?`, `lobe?`, `type?`, `include_stale?` (default false). At least one of `neuron`/`lobe` required.

**Output:** `{"memories": [...], "count": N}`

### `get_neuron` enhancement

Existing `_handle_get_neuron` extended to join `memories` on `neuron_id`:

```json
{
  "name": "validate_token",
  "file": "auth/tokens.py",
  ...
  "memories": [
    {"type": "warning", "title": "Clock skew issue", "body": "...", "decay_score": 0.91}
  ]
}
```

Only `active` and `possibly_stale` memories included by default.

---

## Integration Points

### `commands/build.py` — Step 8 (after health snapshot)

```python
from cerebrofy.memory.decay import recompute_all_decay
all_neuron_ids = {row[0] for row in conn.execute("SELECT id FROM nodes")}
recompute_all_decay(conn, all_neuron_ids, config.memory)
```

Full recompute since all neuron signatures were re-evaluated during build.

### `commands/update.py` — post-success block

```python
recompute_all_decay(conn, scope.affected_node_ids, config.memory)
```

Only neurons in the update scope. Non-fatal: wrapped in try/except.

### `epistemic/state.py` — closes #22 D3

```python
def _memory_stale_count(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT COUNT(*) FROM memories WHERE status = 'stale'").fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return 0  # table absent on pre-#05 DBs that haven't been rebuilt
```

`memory_stale_count` no longer always returns 0. Falls back to 0 on DBs without the `memories` table (pre-#05 installs that haven't rebuilt).

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| `vec_memories` write fails | Fatal — raises exception (Law III) |
| Unresolvable `neuron` param in `cerebrofy_remember` | Writes with `neuron_id=NULL`, returns warning field |
| Embedding model unavailable in `cerebrofy_recall` | Returns empty list with `"error"` field |
| Decay recompute error on individual memory | Per-memory try/except, logs warning, continues |
| `trace_history` cycle in `memory_edges` | Depth cap (default 5) prevents infinite traversal |
| `cerebrofy memory list` called without `--neuron` or `--lobe` | CLI error, exits with message |

---

## Testing

All tests use `tmp_path` + in-memory sqlite. Embedder mocked in all unit tests.

| File | Coverage |
|------|----------|
| `tests/unit/test_memory_store.py` | CRUD, `list_memories` filter combinations, `trace_history` traversal, cycle safety via depth cap |
| `tests/unit/test_memory_search.py` | `recall_memories` with mocked embedder, filter combinations, stale exclusion/inclusion |
| `tests/unit/test_memory_decay.py` | `compute_decay` formula, threshold transitions (`active → possibly_stale → stale`), `recompute_all_decay` scope and count |
| `tests/unit/test_memory_embedder.py` | Text concatenation, delegates to mocked `LocalEmbedder` |
| `tests/integration/test_mcp_command.py` | Extended with `cerebrofy_remember`, `cerebrofy_recall`, `cerebrofy_memories` call simulations |

---

## File Checklist

**New files:**
- `src/cerebrofy/memory/__init__.py`
- `src/cerebrofy/memory/store.py`
- `src/cerebrofy/memory/search.py`
- `src/cerebrofy/memory/embedder.py`
- `src/cerebrofy/memory/decay.py`
- `src/cerebrofy/commands/memory.py`
- `tests/unit/test_memory_store.py`
- `tests/unit/test_memory_search.py`
- `tests/unit/test_memory_decay.py`
- `tests/unit/test_memory_embedder.py`

**Modified files:**
- `src/cerebrofy/db/schema.py` — add `memories`, `vec_memories`, `memory_edges` DDL
- `src/cerebrofy/config/loader.py` — add `MemoryConfig` dataclass + `memory` field
- `src/cerebrofy/mcp/server.py` — 3 new tool handlers + `get_neuron` enhancement
- `src/cerebrofy/commands/build.py` — Step 8 decay recompute
- `src/cerebrofy/commands/update.py` — post-success decay recompute
- `src/cerebrofy/epistemic/state.py` — `_memory_stale_count` implementation
- `src/cerebrofy/cli.py` — register `cerebrofy memory` command group
- `docs/mcp-integration.md` — document 3 new MCP tools
- `README.md` — document `cerebrofy memory` CLI commands
