# AI Agent Memory Layer (#05) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a writable, queryable, decaying memory store to Cerebrofy so AI agents and humans can attach structured knowledge (decisions, warnings, patterns) to neurons and lobes, with semantic recall and causal linking.

**Architecture:** Memories live in a **separate `memories.db`** in `.cerebrofy/db/` — `cerebrofy build` atomically replaces `cerebrofy.db` via `os.replace()`, so memories must be separate or they'd be wiped on every rebuild. A flat `memory/` subpackage (store, embedder, search, decay) follows the same pattern as `health/`, `epistemic/`, `intent/`. Three new MCP tools plus `cerebrofy memory` CLI group. Decay runs on both `build` (time-based for all memories) and `update` (signature-triggered for re-indexed neurons).

**Spec deviation:** The design spec placed `memories/vec_memories/memory_edges` inside `cerebrofy.db`. Corrected here to `memories.db` for persistence across full rebuilds.

**Tech Stack:** Python 3.11+, sqlite3, sqlite-vec (`vec_f32()` / `vec0` virtual table — same pattern as `vec_neurons`), fastembed/LocalEmbedder (384-dim, already installed), rich-click, `uuid.uuid4`, `math`, `json`, `subprocess`.

---

## File Map

**New:**
- `src/cerebrofy/memory/__init__.py`
- `src/cerebrofy/memory/store.py` — `Memory` + `MemoryEdge` dataclasses; `open_memories_db()`; CRUD; `trace_history()`
- `src/cerebrofy/memory/embedder.py` — `embed_memory(title, body) -> list[float]`
- `src/cerebrofy/memory/search.py` — `recall_memories()` KNN on `vec_memories`
- `src/cerebrofy/memory/decay.py` — `compute_decay()`; `recompute_all_decay()`
- `src/cerebrofy/commands/memory.py` — `mem_group` Click group (add/search/list/link/export)
- `tests/unit/test_memory_store.py`
- `tests/unit/test_memory_search.py`
- `tests/unit/test_memory_decay.py`
- `tests/unit/test_memory_embedder.py`

**Modified:**
- `src/cerebrofy/config/loader.py` — add `MemoryConfig`; add `memory` field to `CerebrоfyConfig`
- `src/cerebrofy/db/schema.py` — add `create_memory_schema(conn)`
- `src/cerebrofy/mcp/server.py` — 3 new handlers + 3 tool registrations + `get_neuron` enhancement + dispatch cases
- `src/cerebrofy/commands/build.py` — after health snapshot: call `_recompute_memory_decay()`
- `src/cerebrofy/commands/update.py` — after health snapshot: call `_recompute_memory_decay()`
- `src/cerebrofy/epistemic/state.py` — implement `_memory_stale_count()`
- `src/cerebrofy/cli.py` — import and register `mem_group`
- `README.md` — `cerebrofy memory` CLI section
- `docs/mcp-integration.md` — 3 new MCP tools

---

## Task 1: Feature Branch + MemoryConfig

**Files:**
- Create: `feat/05-agent-memory-layer` branch
- Modify: `src/cerebrofy/config/loader.py`
- Test: `tests/unit/test_config.py` (check if it exists — if not, create minimal)

- [ ] **Step 1: Create branch**

```bash
git checkout master && git pull origin master
git checkout -b feat/05-agent-memory-layer
```

- [ ] **Step 2: Write failing test for MemoryConfig**

Find `tests/unit/test_config.py` (or create it). Add at the bottom:

```python
def test_memory_config_defaults():
    from cerebrofy.config.loader import MemoryConfig
    cfg = MemoryConfig()
    assert cfg.decay_half_life_days == 70.0
    assert cfg.stale_threshold == 0.1
    assert cfg.possibly_stale_threshold == 0.3


def test_memory_config_on_cerebrofy_config():
    from cerebrofy.config.loader import CerebrоfyConfig, MemoryConfig
    cfg = CerebrоfyConfig(lobes={}, tracked_extensions=[], embedding_model="local")
    assert isinstance(cfg.memory, MemoryConfig)
    assert cfg.memory.decay_half_life_days == 70.0
```

- [ ] **Step 3: Run test to confirm it fails**

```bash
uv run pytest tests/unit/test_config.py -k "memory_config" -v --no-cov
```

Expected: `ImportError: cannot import name 'MemoryConfig'`

- [ ] **Step 4: Add MemoryConfig to `src/cerebrofy/config/loader.py`**

After the existing imports, before `class CerebrоfyConfig`, add:

```python
from dataclasses import field
```

Add the `MemoryConfig` dataclass (insert before `CerebrоfyConfig`):

```python
@dataclass(frozen=True)
class MemoryConfig:
    """Decay parameters for the agent memory layer."""
    decay_half_life_days: float = 70.0
    possibly_stale_threshold: float = 0.3
    stale_threshold: float = 0.1
```

Add `memory` field to `CerebrоfyConfig` (after `embedding_model`):

```python
    memory: MemoryConfig = field(default_factory=MemoryConfig)
```

Update `load_config` to parse the `memory` section (inside the function, after building `config`):

```python
    raw_memory = data.get("memory", {})
    memory_cfg = MemoryConfig(
        decay_half_life_days=float(raw_memory.get("decay_half_life_days", 70.0)),
        possibly_stale_threshold=float(raw_memory.get("possibly_stale_threshold", 0.3)),
        stale_threshold=float(raw_memory.get("stale_threshold", 0.1)),
    )
    config = CerebrоfyConfig(
        lobes=data["lobes"],
        tracked_extensions=data["tracked_extensions"],
        embedding_model=data.get("embedding_model", "local"),
        memory=memory_cfg,
    )
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/unit/test_config.py -k "memory_config" -v --no-cov
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/cerebrofy/config/loader.py tests/unit/test_config.py
git commit -m "feat(#05): add MemoryConfig to CerebrоfyConfig with decay parameters"
```

---

## Task 2: Memory Schema + `open_memories_db()`

**Files:**
- Modify: `src/cerebrofy/db/schema.py`
- Create: `src/cerebrofy/memory/__init__.py`, `src/cerebrofy/memory/store.py` (schema + open function only)

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_memory_store.py`:

```python
"""Unit tests for memory/store.py."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cerebrofy.memory.store import open_memories_db


def test_open_memories_db_creates_tables(tmp_path):
    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True)
    conn = open_memories_db(cerebrofy_dir)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "memories" in tables
    assert "memory_edges" in tables
    conn.close()


def test_open_memories_db_idempotent(tmp_path):
    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True)
    conn1 = open_memories_db(cerebrofy_dir)
    conn1.close()
    # Second open must not raise
    conn2 = open_memories_db(cerebrofy_dir)
    conn2.close()
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_memory_store.py::test_open_memories_db_creates_tables -v --no-cov
```

Expected: `ModuleNotFoundError: No module named 'cerebrofy.memory'`

- [ ] **Step 3: Add `create_memory_schema()` to `src/cerebrofy/db/schema.py`**

At the bottom of `schema.py` add:

```python
def create_memory_schema(conn: sqlite3.Connection) -> None:
    """Create memories, vec_memories, and memory_edges tables (idempotent)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id          TEXT PRIMARY KEY,
            neuron_id   TEXT,
            lobe        TEXT,
            type        TEXT NOT NULL,
            title       TEXT NOT NULL,
            body        TEXT NOT NULL,
            author      TEXT,
            created_ts  INTEGER NOT NULL,
            tags        TEXT,
            decay_score REAL NOT NULL DEFAULT 1.0,
            status      TEXT NOT NULL DEFAULT 'active'
        );
        CREATE INDEX IF NOT EXISTS idx_memories_neuron ON memories(neuron_id);
        CREATE INDEX IF NOT EXISTS idx_memories_lobe   ON memories(lobe);
        CREATE INDEX IF NOT EXISTS idx_memories_type   ON memories(type);
        CREATE TABLE IF NOT EXISTS memory_edges (
            from_memory_id  TEXT NOT NULL REFERENCES memories(id),
            to_memory_id    TEXT NOT NULL REFERENCES memories(id),
            rel_type        TEXT NOT NULL,
            created_ts      INTEGER NOT NULL,
            author          TEXT,
            PRIMARY KEY (from_memory_id, to_memory_id, rel_type)
        );
    """)
    conn.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories "
        "USING vec0(rowid integer primary key, embedding float[384])"
    )
    conn.commit()
```

- [ ] **Step 4: Create `src/cerebrofy/memory/__init__.py`**

```python
```
(empty)

- [ ] **Step 5: Create `src/cerebrofy/memory/store.py`** with just `open_memories_db`:

```python
"""Writable memory store for Cerebrofy. Uses a separate memories.db file."""
from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VALID_TYPES = frozenset({"decision", "warning", "context", "pattern", "agent_action", "insight"})
VALID_REL_TYPES = frozenset({"caused", "motivated", "resolved", "contradicts", "updated_by"})


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


def open_memories_db(cerebrofy_dir: Path) -> sqlite3.Connection:
    """Open (or create) memories.db, load sqlite-vec, create schema idempotently."""
    import sqlite_vec  # type: ignore[import-untyped]
    db_path = cerebrofy_dir / "db" / "memories.db"
    conn = sqlite3.connect(str(db_path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA journal_mode=WAL")
    from cerebrofy.db.schema import create_memory_schema
    create_memory_schema(conn)
    return conn


def row_to_memory(row: tuple[Any, ...]) -> Memory:
    id_, neuron_id, lobe, type_, title, body, author, created_ts, tags_str, decay_score, status = row
    tags: tuple[str, ...] = tuple(
        t.strip() for t in tags_str.split(",") if t.strip()
    ) if tags_str else ()
    return Memory(
        id=id_, neuron_id=neuron_id, lobe=lobe, type=type_,
        title=title, body=body, author=author, created_ts=int(created_ts),
        tags=tags, decay_score=float(decay_score), status=status,
    )
```

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/unit/test_memory_store.py::test_open_memories_db_creates_tables tests/unit/test_memory_store.py::test_open_memories_db_idempotent -v --no-cov
```

Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add src/cerebrofy/db/schema.py src/cerebrofy/memory/__init__.py src/cerebrofy/memory/store.py tests/unit/test_memory_store.py
git commit -m "feat(#05): add memory schema and open_memories_db()"
```

---

## Task 3: memory/store.py — CRUD + trace_history

**Files:**
- Modify: `src/cerebrofy/memory/store.py`
- Modify: `tests/unit/test_memory_store.py`

- [ ] **Step 1: Write failing tests — append to `tests/unit/test_memory_store.py`**

```python
from cerebrofy.memory.store import (
    Memory, MemoryEdge, open_memories_db, row_to_memory,
    write_memory, get_memory, list_memories, delete_memory,
    write_memory_edge, trace_history,
)


def _make_conn(tmp_path: Path):
    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True)
    return open_memories_db(cerebrofy_dir)


def _mem(id: str = "m1", **kwargs) -> Memory:
    defaults = dict(
        neuron_id=None, lobe="auth", type="warning",
        title="Test memory", body="Body text",
        author="human:test@co.com", created_ts=1_000_000,
        tags=("security",), decay_score=1.0, status="active",
    )
    defaults.update(kwargs)
    return Memory(id=id, **defaults)


def test_write_and_get_memory(tmp_path):
    conn = _make_conn(tmp_path)
    m = _mem("abc", title="Clock skew", tags=("security", "jwt"))
    write_memory(conn, m, [0.1] * 384)
    conn.commit()
    result = get_memory(conn, "abc")
    assert result is not None
    assert result.title == "Clock skew"
    assert result.tags == ("security", "jwt")
    assert result.lobe == "auth"


def test_get_memory_missing_returns_none(tmp_path):
    conn = _make_conn(tmp_path)
    assert get_memory(conn, "nonexistent") is None


def test_list_memories_filter_lobe(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1", lobe="auth"), [0.1] * 384)
    write_memory(conn, _mem("m2", lobe="db"), [0.1] * 384)
    conn.commit()
    results = list_memories(conn, lobe="auth")
    assert len(results) == 1
    assert results[0].id == "m1"


def test_list_memories_excludes_stale_by_default(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1", status="active"), [0.1] * 384)
    write_memory(conn, _mem("m2", status="stale"), [0.1] * 384)
    conn.commit()
    assert len(list_memories(conn)) == 1
    assert len(list_memories(conn, include_stale=True)) == 2


def test_delete_memory(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1"), [0.1] * 384)
    conn.commit()
    delete_memory(conn, "m1")
    conn.commit()
    assert get_memory(conn, "m1") is None


def test_write_memory_edge_and_trace_history(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1", title="Root"), [0.1] * 384)
    write_memory(conn, _mem("m2", title="Child"), [0.1] * 384)
    write_memory(conn, _mem("m3", title="Grandchild"), [0.1] * 384)
    conn.commit()
    write_memory_edge(conn, MemoryEdge("m1", "m2", "motivated", 1_000_000, None))
    write_memory_edge(conn, MemoryEdge("m2", "m3", "caused", 1_000_001, None))
    conn.commit()
    # trace_history from m3 walks backward: m3 ← m2 ← m1
    chain = trace_history(conn, "m3", depth=5)
    ids = [m.id for m in chain]
    assert "m3" in ids
    assert "m2" in ids
    assert "m1" in ids


def test_trace_history_depth_cap(tmp_path):
    conn = _make_conn(tmp_path)
    for i in range(10):
        write_memory(conn, _mem(f"m{i}"), [0.1] * 384)
    conn.commit()
    for i in range(9):
        write_memory_edge(conn, MemoryEdge(f"m{i}", f"m{i+1}", "caused", 1_000_000, None))
    conn.commit()
    # depth=3 should return at most 3 memories from m9
    chain = trace_history(conn, "m9", depth=3)
    assert len(chain) <= 3
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_memory_store.py -k "write_and_get" -v --no-cov
```

Expected: `ImportError: cannot import name 'write_memory'`

- [ ] **Step 3: Implement CRUD in `src/cerebrofy/memory/store.py`** — add after `row_to_memory`:

```python
_SELECT_COLS = (
    "id, neuron_id, lobe, type, title, body, author, "
    "created_ts, tags, decay_score, status"
)


def write_memory(
    conn: sqlite3.Connection, memory: Memory, embedding: list[float]
) -> None:
    """Insert memory into memories + vec_memories. Caller must commit."""
    import json
    tags_str = ",".join(memory.tags) if memory.tags else ""
    cursor = conn.execute(
        f"INSERT INTO memories({_SELECT_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (memory.id, memory.neuron_id, memory.lobe, memory.type, memory.title,
         memory.body, memory.author, memory.created_ts, tags_str,
         memory.decay_score, memory.status),
    )
    rowid = cursor.lastrowid
    conn.execute(
        "INSERT INTO vec_memories(rowid, embedding) VALUES (?, vec_f32(?))",
        (rowid, json.dumps(embedding)),
    )


def get_memory(conn: sqlite3.Connection, memory_id: str) -> Memory | None:
    row = conn.execute(
        f"SELECT {_SELECT_COLS} FROM memories WHERE id = ?", (memory_id,)
    ).fetchone()
    return row_to_memory(row) if row else None


def list_memories(
    conn: sqlite3.Connection,
    neuron_id: str | None = None,
    lobe: str | None = None,
    type_filter: str | None = None,
    include_stale: bool = False,
) -> list[Memory]:
    q = f"SELECT {_SELECT_COLS} FROM memories WHERE 1=1"
    params: list[Any] = []
    if neuron_id is not None:
        q += " AND neuron_id = ?"
        params.append(neuron_id)
    if lobe is not None:
        q += " AND lobe = ?"
        params.append(lobe)
    if type_filter is not None:
        q += " AND type = ?"
        params.append(type_filter)
    if not include_stale:
        q += " AND status != 'stale'"
    q += " ORDER BY created_ts DESC"
    return [row_to_memory(r) for r in conn.execute(q, params).fetchall()]


def delete_memory(conn: sqlite3.Connection, memory_id: str) -> None:
    """Delete memory and its vec_memories entry. Caller must commit."""
    row = conn.execute("SELECT rowid FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if row:
        conn.execute("DELETE FROM vec_memories WHERE rowid = ?", (row[0],))
    conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))


def write_memory_edge(conn: sqlite3.Connection, edge: MemoryEdge) -> None:
    """Insert a causal edge between two memories. Caller must commit."""
    conn.execute(
        "INSERT OR REPLACE INTO memory_edges"
        "(from_memory_id, to_memory_id, rel_type, created_ts, author) VALUES (?,?,?,?,?)",
        (edge.from_memory_id, edge.to_memory_id, edge.rel_type,
         edge.created_ts, edge.author),
    )


def trace_history(
    conn: sqlite3.Connection, memory_id: str, depth: int = 5
) -> list[Memory]:
    """Walk memory_edges backward from memory_id up to depth hops."""
    visited: set[str] = set()
    result: list[Memory] = []
    frontier = [memory_id]
    for _ in range(depth):
        if not frontier:
            break
        next_frontier: list[str] = []
        for mid in frontier:
            if mid in visited:
                continue
            visited.add(mid)
            m = get_memory(conn, mid)
            if m:
                result.append(m)
            rows = conn.execute(
                "SELECT from_memory_id FROM memory_edges WHERE to_memory_id = ?",
                (mid,),
            ).fetchall()
            next_frontier.extend(r[0] for r in rows if r[0] not in visited)
        frontier = next_frontier
    return result
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_memory_store.py -v --no-cov
```

Expected: all store tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/cerebrofy/memory/store.py tests/unit/test_memory_store.py
git commit -m "feat(#05): implement Memory CRUD and trace_history in store.py"
```

---

## Task 4: memory/embedder.py

**Files:**
- Create: `src/cerebrofy/memory/embedder.py`
- Create: `tests/unit/test_memory_embedder.py`

- [ ] **Step 1: Write failing test**

Create `tests/unit/test_memory_embedder.py`:

```python
"""Unit tests for memory/embedder.py."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_embed_memory_concatenates_title_and_body():
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.5] * 384]
    with patch("cerebrofy.memory.embedder.LocalEmbedder", return_value=mock_embedder):
        from cerebrofy.memory.embedder import embed_memory
        result = embed_memory("Clock skew", "Token expiry breaks with drift > 30s")
    mock_embedder.embed.assert_called_once()
    call_text = mock_embedder.embed.call_args[0][0][0]
    assert "Clock skew" in call_text
    assert "Token expiry" in call_text
    assert result == [0.5] * 384


def test_embed_memory_returns_384_floats():
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1] * 384]
    with patch("cerebrofy.memory.embedder.LocalEmbedder", return_value=mock_embedder):
        from cerebrofy.memory.embedder import embed_memory
        result = embed_memory("title", "body")
    assert len(result) == 384
    assert all(isinstance(x, float) for x in result)
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_memory_embedder.py -v --no-cov
```

Expected: `ModuleNotFoundError: No module named 'cerebrofy.memory.embedder'`

- [ ] **Step 3: Create `src/cerebrofy/memory/embedder.py`**

```python
"""Embedding helper for memory bodies."""
from __future__ import annotations

from cerebrofy.embedder.local import LocalEmbedder


def embed_memory(title: str, body: str) -> list[float]:
    """Embed a memory's title + body into a 384-dim vector."""
    text = f"{title} {body}"
    embedder = LocalEmbedder()
    return embedder.embed([text])[0]
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_memory_embedder.py -v --no-cov
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cerebrofy/memory/embedder.py tests/unit/test_memory_embedder.py
git commit -m "feat(#05): add embed_memory() in memory/embedder.py"
```

---

## Task 5: memory/search.py — KNN recall

**Files:**
- Create: `src/cerebrofy/memory/search.py`
- Create: `tests/unit/test_memory_search.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_memory_search.py`:

```python
"""Unit tests for memory/search.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from cerebrofy.memory.store import Memory, open_memories_db, write_memory
from cerebrofy.memory.search import recall_memories


def _make_conn(tmp_path: Path):
    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True)
    return open_memories_db(cerebrofy_dir)


def _mem(id: str, title: str = "T", body: str = "B", status: str = "active", lobe: str | None = None, type_: str = "warning") -> Memory:
    return Memory(
        id=id, neuron_id=None, lobe=lobe, type=type_,
        title=title, body=body, author="human:test",
        created_ts=1_000_000, tags=(), decay_score=1.0, status=status,
    )


def test_recall_returns_memories_by_similarity(tmp_path):
    conn = _make_conn(tmp_path)
    # Write two memories with distinct embeddings
    write_memory(conn, _mem("m1", title="JWT clock skew"), [1.0] + [0.0] * 383)
    write_memory(conn, _mem("m2", title="Database connection pool"), [0.0] + [1.0] + [0.0] * 382)
    conn.commit()
    # Query near m1's embedding
    results = recall_memories(conn, [1.0] + [0.0] * 383, limit=2)
    assert len(results) >= 1
    assert results[0][0].id == "m1"


def test_recall_excludes_stale_by_default(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1", status="active"), [0.5] * 384)
    write_memory(conn, _mem("m2", status="stale"), [0.5] * 384)
    conn.commit()
    results = recall_memories(conn, [0.5] * 384, limit=10)
    ids = [r[0].id for r in results]
    assert "m1" in ids
    assert "m2" not in ids


def test_recall_includes_stale_when_flag_set(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1", status="stale"), [0.5] * 384)
    conn.commit()
    results = recall_memories(conn, [0.5] * 384, limit=10, include_stale=True)
    assert any(r[0].id == "m1" for r in results)


def test_recall_filters_by_lobe(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1", lobe="auth"), [0.5] * 384)
    write_memory(conn, _mem("m2", lobe="db"), [0.5] * 384)
    conn.commit()
    results = recall_memories(conn, [0.5] * 384, limit=10, lobe_filter="auth")
    ids = [r[0].id for r in results]
    assert "m1" in ids
    assert "m2" not in ids


def test_recall_returns_similarity_scores(tmp_path):
    conn = _make_conn(tmp_path)
    write_memory(conn, _mem("m1"), [1.0] + [0.0] * 383)
    conn.commit()
    results = recall_memories(conn, [1.0] + [0.0] * 383, limit=5)
    assert len(results) == 1
    mem, score = results[0]
    assert 0.0 <= score <= 1.0
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_memory_search.py -v --no-cov
```

Expected: `ModuleNotFoundError: No module named 'cerebrofy.memory.search'`

- [ ] **Step 3: Create `src/cerebrofy/memory/search.py`**

```python
"""KNN semantic search over memories using sqlite-vec."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from cerebrofy.memory.store import Memory, row_to_memory

_SELECT_COLS = (
    "id, neuron_id, lobe, type, title, body, author, "
    "created_ts, tags, decay_score, status"
)


def recall_memories(
    conn: sqlite3.Connection,
    query_embedding: list[float],
    limit: int = 10,
    type_filter: str | None = None,
    lobe_filter: str | None = None,
    include_stale: bool = False,
) -> list[tuple[Memory, float]]:
    """KNN search on vec_memories. Returns (Memory, similarity_score) pairs desc."""
    where_clauses: list[str] = []
    extra_params: list[Any] = []

    if type_filter is not None:
        where_clauses.append("m.type = ?")
        extra_params.append(type_filter)
    if lobe_filter is not None:
        where_clauses.append("m.lobe = ?")
        extra_params.append(lobe_filter)
    if not include_stale:
        where_clauses.append("m.status != 'stale'")

    where_sql = (" AND " + " AND ".join(where_clauses)) if where_clauses else ""

    sql = (
        f"SELECT m.{_SELECT_COLS.replace(', ', ', m.')}, v.distance "
        f"FROM vec_memories v "
        f"JOIN memories m ON m.rowid = v.rowid "
        f"WHERE v.embedding MATCH vec_f32(?) AND k = ?{where_sql} "
        f"ORDER BY v.distance"
    )
    # Fix: build proper column select with alias
    sql = (
        "SELECT m.id, m.neuron_id, m.lobe, m.type, m.title, m.body, m.author, "
        "m.created_ts, m.tags, m.decay_score, m.status, v.distance "
        "FROM vec_memories v "
        "JOIN memories m ON m.rowid = v.rowid "
        f"WHERE v.embedding MATCH vec_f32(?) AND k = ?{where_sql} "
        "ORDER BY v.distance"
    )

    params: list[Any] = [json.dumps(query_embedding), limit] + extra_params
    rows = conn.execute(sql, params).fetchall()

    results: list[tuple[Memory, float]] = []
    for row in rows:
        mem = row_to_memory(row[:11])
        similarity = max(0.0, 1.0 - float(row[11]))
        results.append((mem, round(similarity, 4)))
    return results
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_memory_search.py -v --no-cov
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/cerebrofy/memory/search.py tests/unit/test_memory_search.py
git commit -m "feat(#05): add recall_memories() KNN search over vec_memories"
```

---

## Task 6: memory/decay.py

**Files:**
- Create: `src/cerebrofy/memory/decay.py`
- Create: `tests/unit/test_memory_decay.py`

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_memory_decay.py`:

```python
"""Unit tests for memory/decay.py."""
from __future__ import annotations

import time
from pathlib import Path

from cerebrofy.config.loader import MemoryConfig
from cerebrofy.memory.decay import compute_decay, recompute_all_decay
from cerebrofy.memory.store import Memory, open_memories_db, write_memory, get_memory


def _cfg(**kw) -> MemoryConfig:
    defaults = dict(decay_half_life_days=70.0, possibly_stale_threshold=0.3, stale_threshold=0.1)
    defaults.update(kw)
    return MemoryConfig(**defaults)


def _mem(id: str, created_ts: int, neuron_id: str | None = None) -> Memory:
    return Memory(
        id=id, neuron_id=neuron_id, lobe=None, type="warning",
        title="T", body="B", author=None,
        created_ts=created_ts, tags=(), decay_score=1.0, status="active",
    )


def test_compute_decay_fresh_memory():
    now = int(time.time())
    m = _mem("m1", created_ts=now)
    score = compute_decay(m, neuron_signature_changed=False, current_ts=now, config=_cfg())
    assert 0.99 <= score <= 1.0


def test_compute_decay_old_memory_time_decay():
    now = int(time.time())
    old_ts = now - 70 * 86400  # exactly one half-life ago
    m = _mem("m1", created_ts=old_ts)
    score = compute_decay(m, neuron_signature_changed=False, current_ts=now, config=_cfg())
    assert 0.48 <= score <= 0.52  # ~0.5 after one half-life


def test_compute_decay_signature_changed_penalty():
    now = int(time.time())
    m = _mem("m1", created_ts=now)
    score_stable = compute_decay(m, neuron_signature_changed=False, current_ts=now, config=_cfg())
    score_changed = compute_decay(m, neuron_signature_changed=True, current_ts=now, config=_cfg())
    assert score_changed < score_stable
    assert score_changed <= 0.3  # 1.0 * 0.3


def test_decay_status_transitions():
    from cerebrofy.memory.decay import _decay_status
    cfg = _cfg(possibly_stale_threshold=0.3, stale_threshold=0.1)
    assert _decay_status(1.0, cfg) == "active"
    assert _decay_status(0.5, cfg) == "active"
    assert _decay_status(0.29, cfg) == "possibly_stale"
    assert _decay_status(0.09, cfg) == "stale"
    assert _decay_status(0.0, cfg) == "stale"


def test_recompute_all_decay_updates_status(tmp_path):
    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True)
    conn = open_memories_db(cerebrofy_dir)

    # Memory created 200 days ago, attached to a neuron that changed
    old_ts = int(time.time()) - 200 * 86400
    m = _mem("m1", created_ts=old_ts, neuron_id="node-abc")
    write_memory(conn, m, [0.1] * 384)
    conn.commit()

    cfg = _cfg(decay_half_life_days=70.0, possibly_stale_threshold=0.3, stale_threshold=0.1)
    changed = recompute_all_decay(conn, {"node-abc"}, cfg)
    conn.commit()

    updated = get_memory(conn, "m1")
    assert updated is not None
    assert updated.decay_score < 0.3  # 200 days ≈ 2.8 half-lives → ~0.143 * 0.3 ≈ 0.043
    assert updated.status in ("possibly_stale", "stale")
    assert changed >= 1


def test_recompute_all_decay_ignores_unattached_neurons(tmp_path):
    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True)
    conn = open_memories_db(cerebrofy_dir)

    now = int(time.time())
    m = _mem("m1", created_ts=now, neuron_id=None)  # no neuron attached
    write_memory(conn, m, [0.1] * 384)
    conn.commit()

    cfg = _cfg()
    # Pass a changed_node_ids set — memory with no neuron should still get time-based decay
    recompute_all_decay(conn, {"some-other-node"}, cfg)
    conn.commit()

    updated = get_memory(conn, "m1")
    # Fresh memory, no signature change → decay close to 1.0
    assert updated is not None
    assert updated.decay_score > 0.99
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/unit/test_memory_decay.py -v --no-cov
```

Expected: `ModuleNotFoundError: No module named 'cerebrofy.memory.decay'`

- [ ] **Step 3: Create `src/cerebrofy/memory/decay.py`**

```python
"""Memory decay scoring for the agent memory layer."""
from __future__ import annotations

import math
import sqlite3
import time as _time
from typing import Any

from cerebrofy.config.loader import MemoryConfig
from cerebrofy.memory.store import Memory, row_to_memory

_SELECT_COLS = (
    "id, neuron_id, lobe, type, title, body, author, "
    "created_ts, tags, decay_score, status"
)


def compute_decay(
    memory: Memory,
    neuron_signature_changed: bool,
    current_ts: int,
    config: MemoryConfig,
) -> float:
    """Compute decay score (0.0–1.0) for a memory.

    Time-based: exponential with the configured half-life.
    Signature penalty: multiply by 0.3 if the attached neuron changed.
    """
    days_since = max(0.0, (current_ts - memory.created_ts) / 86400.0)
    time_factor = math.exp(-math.log(2) / config.decay_half_life_days * days_since)
    stability_factor = 0.3 if neuron_signature_changed else 1.0
    score = round(time_factor * stability_factor, 4)
    return max(0.0, min(1.0, score))


def _decay_status(score: float, config: MemoryConfig) -> str:
    if score < config.stale_threshold:
        return "stale"
    if score < config.possibly_stale_threshold:
        return "possibly_stale"
    return "active"


def recompute_all_decay(
    conn: sqlite3.Connection,
    changed_neuron_ids: set[str],
    config: MemoryConfig,
) -> int:
    """Recompute decay for all memories; returns count of rows whose status changed.

    For cerebrofy build: pass an empty set (time-based decay only for all memories).
    For cerebrofy update: pass scope.affected_node_ids (signature penalty for those neurons).
    """
    current_ts = int(_time.time())
    rows = conn.execute(
        f"SELECT {_SELECT_COLS} FROM memories"
    ).fetchall()

    changed_count = 0
    for row in rows:
        memory = row_to_memory(row)
        neuron_changed = (
            memory.neuron_id is not None and memory.neuron_id in changed_neuron_ids
        )
        new_score = compute_decay(memory, neuron_changed, current_ts, config)
        new_status = _decay_status(new_score, config)
        if new_score != memory.decay_score or new_status != memory.status:
            conn.execute(
                "UPDATE memories SET decay_score = ?, status = ? WHERE id = ?",
                (new_score, new_status, memory.id),
            )
            changed_count += 1
    return changed_count
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_memory_decay.py -v --no-cov
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/cerebrofy/memory/decay.py tests/unit/test_memory_decay.py
git commit -m "feat(#05): add memory decay scoring with half-life and signature penalty"
```

---

## Task 7: `commands/memory.py` CLI + `cli.py` registration

**Files:**
- Create: `src/cerebrofy/commands/memory.py`
- Modify: `src/cerebrofy/cli.py`

- [ ] **Step 1: Create `src/cerebrofy/commands/memory.py`**

```python
"""cerebrofy memory — writable agent memory store CLI."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

import rich_click as click
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()


def _get_author(override: str | None) -> str:
    if override:
        return override
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True, text=True, timeout=3,
        )
        email = result.stdout.strip()
        if email:
            return f"human:{email}"
    except Exception:
        pass
    return "human:unknown"


def _open(root: Path):
    from cerebrofy.memory.store import open_memories_db
    cerebrofy_dir = root / ".cerebrofy"
    if not (cerebrofy_dir / "db").exists():
        click.echo("Error: No index found. Run 'cerebrofy init && cerebrofy build' first.", err=True)
        sys.exit(1)
    return open_memories_db(cerebrofy_dir)


@click.group("memory")
def mem_group() -> None:
    """Read and write structured memories attached to your codebase."""


@mem_group.command("add")
@click.argument("title")
@click.option("--type", "mem_type", required=True,
              type=click.Choice(["decision", "warning", "context", "pattern", "agent_action"]),
              help="Memory type.")
@click.option("--body", required=True, help="Full memory content.")
@click.option("--neuron", default=None, help="Neuron to attach to (file::name or name).")
@click.option("--lobe", default=None, help="Lobe name to attach to.")
@click.option("--tags", default=None, help="Comma-separated tags.")
@click.option("--author", default=None, help="Author string. Defaults to git config user.email.")
def memory_add(title: str, mem_type: str, body: str, neuron: str | None,
               lobe: str | None, tags: str | None, author: str | None) -> None:
    """Add a structured memory to the codebase index."""
    from cerebrofy.memory.embedder import embed_memory
    from cerebrofy.memory.store import Memory, write_memory

    root = Path.cwd()
    conn = _open(root)

    neuron_id: str | None = None
    if neuron:
        db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
        try:
            from cerebrofy.db.connection import open_db
            idx = open_db(db_path)
            row = idx.execute(
                "SELECT id FROM nodes WHERE name = ? OR id LIKE ?",
                (neuron, f"%::{neuron}"),
            ).fetchone()
            idx.close()
            if row:
                neuron_id = row[0]
            else:
                click.echo(f"Warning: neuron '{neuron}' not found — memory stored without anchor.", err=True)
        except Exception:
            pass

    tag_tuple = tuple(t.strip() for t in tags.split(",") if t.strip()) if tags else ()
    mem = Memory(
        id=str(uuid.uuid4()),
        neuron_id=neuron_id,
        lobe=lobe,
        type=mem_type,
        title=title,
        body=body,
        author=_get_author(author),
        created_ts=int(time.time()),
        tags=tag_tuple,
        decay_score=1.0,
        status="active",
    )
    embedding = embed_memory(title, body)
    write_memory(conn, mem, embedding)
    conn.commit()
    conn.close()
    click.echo(mem.id)


@mem_group.command("search")
@click.argument("query")
@click.option("--type", "mem_type", default=None, help="Filter by type.")
@click.option("--lobe", default=None, help="Filter by lobe.")
@click.option("--limit", default=10, show_default=True, help="Max results.")
@click.option("--include-stale", is_flag=True, default=False, help="Include stale memories.")
def memory_search(query: str, mem_type: str | None, lobe: str | None,
                  limit: int, include_stale: bool) -> None:
    """Semantic search across memories."""
    from cerebrofy.memory.embedder import embed_memory
    from cerebrofy.memory.search import recall_memories

    root = Path.cwd()
    conn = _open(root)
    embedding = embed_memory(query, "")
    results = recall_memories(conn, embedding, limit=limit, type_filter=mem_type,
                              lobe_filter=lobe, include_stale=include_stale)
    conn.close()

    if not results:
        click.echo("No memories found.")
        return

    t = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
    t.add_column("Score", justify="right")
    t.add_column("Type")
    t.add_column("Title")
    t.add_column("Lobe")
    t.add_column("Status")
    t.add_column("ID")
    for mem, score in results:
        t.add_row(f"{score:.3f}", mem.type, mem.title, mem.lobe or "", mem.status, mem.id[:8])
    console.print(t)


@mem_group.command("list")
@click.option("--neuron", default=None, help="Filter by neuron.")
@click.option("--lobe", default=None, help="Filter by lobe.")
@click.option("--type", "mem_type", default=None, help="Filter by type.")
@click.option("--include-stale", is_flag=True, default=False)
def memory_list(neuron: str | None, lobe: str | None, mem_type: str | None,
                include_stale: bool) -> None:
    """List memories for a neuron or lobe."""
    if not neuron and not lobe:
        click.echo("Error: provide --neuron or --lobe.", err=True)
        sys.exit(1)

    from cerebrofy.memory.store import list_memories

    root = Path.cwd()
    conn = _open(root)
    neuron_id: str | None = None
    if neuron:
        db_path = root / ".cerebrofy" / "db" / "cerebrofy.db"
        try:
            from cerebrofy.db.connection import open_db
            idx = open_db(db_path)
            row = idx.execute(
                "SELECT id FROM nodes WHERE name = ? OR id LIKE ?",
                (neuron, f"%::{neuron}"),
            ).fetchone()
            idx.close()
            neuron_id = row[0] if row else None
        except Exception:
            pass
    memories = list_memories(conn, neuron_id=neuron_id, lobe=lobe,
                             type_filter=mem_type, include_stale=include_stale)
    conn.close()

    if not memories:
        click.echo("No memories found.")
        return

    t = Table(box=box.SIMPLE_HEAVY, show_header=True, padding=(0, 1))
    t.add_column("ID")
    t.add_column("Type")
    t.add_column("Title")
    t.add_column("Author")
    t.add_column("Status")
    t.add_column("Score", justify="right")
    for m in memories:
        t.add_row(m.id[:8], m.type, m.title, m.author or "", m.status, f"{m.decay_score:.2f}")
    console.print(t)


@mem_group.command("link")
@click.argument("from_id")
@click.argument("to_id")
@click.option("--rel", required=True,
              type=click.Choice(["caused", "motivated", "resolved", "contradicts", "updated_by"]),
              help="Relationship type.")
def memory_link(from_id: str, to_id: str, rel: str) -> None:
    """Create a causal link between two memories."""
    from cerebrofy.memory.store import MemoryEdge, write_memory_edge

    root = Path.cwd()
    conn = _open(root)
    edge = MemoryEdge(from_id, to_id, rel, int(time.time()), _get_author(None))
    write_memory_edge(conn, edge)
    conn.commit()
    conn.close()
    click.echo(f"Linked {from_id[:8]} --[{rel}]--> {to_id[:8]}")


@mem_group.command("export")
@click.option("--format", "fmt", default="markdown",
              type=click.Choice(["markdown", "json"]), show_default=True)
@click.option("--lobe", default=None, help="Filter by lobe.")
@click.option("--type", "mem_type", default=None, help="Filter by type.")
def memory_export(fmt: str, lobe: str | None, mem_type: str | None) -> None:
    """Export memories as markdown or JSON."""
    import datetime
    from cerebrofy.memory.store import list_memories

    root = Path.cwd()
    conn = _open(root)
    memories = list_memories(conn, lobe=lobe, type_filter=mem_type, include_stale=True)
    conn.close()

    if fmt == "json":
        out = [
            {
                "id": m.id, "type": m.type, "title": m.title, "body": m.body,
                "neuron_id": m.neuron_id, "lobe": m.lobe, "author": m.author,
                "created_ts": m.created_ts, "tags": list(m.tags),
                "decay_score": m.decay_score, "status": m.status,
            }
            for m in memories
        ]
        click.echo(json.dumps(out, indent=2))
    else:
        lines = ["# Cerebrofy Memory Export\n"]
        for m in memories:
            dt = datetime.datetime.fromtimestamp(m.created_ts).strftime("%Y-%m-%d")
            lines.append(f"## [{m.type}] {m.title}\n")
            lines.append(f"*by {m.author or 'unknown'} on {dt}*  ")
            if m.lobe:
                lines.append(f"*lobe: {m.lobe}*  ")
            if m.tags:
                lines.append(f"*tags: {', '.join(m.tags)}*  ")
            lines.append(f"*status: {m.status} (decay: {m.decay_score:.2f})*\n")
            lines.append(m.body + "\n")
        click.echo("\n".join(lines))
```

- [ ] **Step 2: Register in `src/cerebrofy/cli.py`**

Add import (alphabetically with other imports):
```python
from cerebrofy.commands.memory import mem_group
```

Add command registration (alphabetically):
```python
main.add_command(mem_group)
```

- [ ] **Step 3: Smoke test the CLI**

```bash
uv run cerebrofy memory --help
uv run cerebrofy memory add --help
uv run cerebrofy memory search --help
```

Expected: help text prints without errors.

- [ ] **Step 4: Commit**

```bash
git add src/cerebrofy/commands/memory.py src/cerebrofy/cli.py
git commit -m "feat(#05): add cerebrofy memory CLI (add/search/list/link/export)"
```

---

## Task 8: MCP — `cerebrofy_remember` + `cerebrofy_recall` + `cerebrofy_memories`

**Files:**
- Modify: `src/cerebrofy/mcp/server.py`

- [ ] **Step 1: Add three handler functions to `server.py`**

Add after `_handle_intent` (around line 510 area — before `_handle_build`):

```python
def _handle_remember(arguments: dict[str, Any]) -> list[Any]:
    import json as _json
    import time as _time
    import uuid as _uuid

    title = arguments.get("title", "").strip()
    body = arguments.get("body", "").strip()
    mem_type = arguments.get("type", "").strip()

    if not title or not body or not mem_type:
        return _make_error_content("cerebrofy_remember: 'title', 'body', and 'type' are required")

    from cerebrofy.memory.store import VALID_TYPES
    if mem_type not in VALID_TYPES:
        return _make_error_content(
            f"cerebrofy_remember: invalid type '{mem_type}'. "
            f"Valid: {', '.join(sorted(VALID_TYPES))}"
        )

    root = _find_repo_root(Path.cwd())
    cerebrofy_dir = root / ".cerebrofy"
    memories_db = cerebrofy_dir / "db" / "memories.db"
    if not (cerebrofy_dir / "db").exists():
        return _make_error_content("NO_INDEX: run cerebrofy build first")

    try:
        from cerebrofy.memory.embedder import embed_memory
        from cerebrofy.memory.store import Memory, open_memories_db, write_memory

        neuron_param = arguments.get("neuron")
        neuron_id: str | None = None
        warning_msg: str | None = None
        if neuron_param:
            db_path = cerebrofy_dir / "db" / "cerebrofy.db"
            try:
                from cerebrofy.db.connection import open_db
                idx = open_db(db_path)
                row = idx.execute(
                    "SELECT id FROM nodes WHERE name = ? OR id LIKE ?",
                    (neuron_param, f"%::{neuron_param}"),
                ).fetchone()
                idx.close()
                if row:
                    neuron_id = row[0]
                else:
                    warning_msg = f"neuron '{neuron_param}' not found — memory stored without anchor"
            except Exception:
                warning_msg = "could not resolve neuron — memory stored without anchor"

        tags_raw = arguments.get("tags", [])
        if isinstance(tags_raw, str):
            tags = tuple(t.strip() for t in tags_raw.split(",") if t.strip())
        else:
            tags = tuple(str(t) for t in tags_raw)

        author = arguments.get("author") or "agent:unknown"
        mem_id = str(_uuid.uuid4())
        mem = Memory(
            id=mem_id, neuron_id=neuron_id, lobe=arguments.get("lobe"),
            type=mem_type, title=title, body=body, author=author,
            created_ts=int(_time.time()), tags=tags,
            decay_score=1.0, status="active",
        )
        embedding = embed_memory(title, body)
        conn = open_memories_db(cerebrofy_dir)
        write_memory(conn, mem, embedding)
        conn.commit()
        conn.close()

        result: dict[str, Any] = {"id": mem_id, "neuron_id": neuron_id, "created_ts": mem.created_ts}
        if warning_msg:
            result["warning"] = warning_msg
        return [TextContent(type="text", text=_json.dumps(result, indent=2))]
    except Exception as exc:
        return _make_error_content(f"cerebrofy_remember failed: {exc}")


def _handle_recall(arguments: dict[str, Any]) -> list[Any]:
    import json as _json

    query = arguments.get("query", "").strip()
    if not query:
        return _make_error_content("cerebrofy_recall: 'query' is required")

    root = _find_repo_root(Path.cwd())
    cerebrofy_dir = root / ".cerebrofy"
    if not (cerebrofy_dir / "db" / "memories.db").exists():
        return [TextContent(type="text", text=_json.dumps({"memories": [], "count": 0}))]

    try:
        from cerebrofy.memory.embedder import embed_memory
        from cerebrofy.memory.search import recall_memories
        from cerebrofy.memory.store import open_memories_db

        conn = open_memories_db(cerebrofy_dir)
        embedding = embed_memory(query, "")
        results = recall_memories(
            conn, embedding,
            limit=int(arguments.get("limit", 10)),
            type_filter=arguments.get("type"),
            lobe_filter=arguments.get("lobe"),
            include_stale=bool(arguments.get("include_stale", False)),
        )
        conn.close()

        out = {
            "memories": [
                {
                    "id": m.id, "type": m.type, "title": m.title, "body": m.body,
                    "neuron": m.neuron_id, "lobe": m.lobe, "author": m.author,
                    "created_ts": m.created_ts, "tags": list(m.tags),
                    "decay_score": m.decay_score, "status": m.status,
                    "relevance_score": score,
                }
                for m, score in results
            ]
        }
        return [TextContent(type="text", text=_json.dumps(out, indent=2))]
    except Exception as exc:
        return [TextContent(type="text", text=_json.dumps({"memories": [], "error": str(exc)}))]


def _handle_memories(arguments: dict[str, Any]) -> list[Any]:
    import json as _json

    neuron = arguments.get("neuron")
    lobe = arguments.get("lobe")
    if not neuron and not lobe:
        return _make_error_content("cerebrofy_memories: provide 'neuron' or 'lobe'")

    root = _find_repo_root(Path.cwd())
    cerebrofy_dir = root / ".cerebrofy"
    if not (cerebrofy_dir / "db" / "memories.db").exists():
        return [TextContent(type="text", text=_json.dumps({"memories": [], "count": 0}))]

    try:
        from cerebrofy.memory.store import list_memories, open_memories_db

        conn = open_memories_db(cerebrofy_dir)
        neuron_id: str | None = None
        if neuron:
            db_path = cerebrofy_dir / "db" / "cerebrofy.db"
            from cerebrofy.db.connection import open_db
            idx = open_db(db_path)
            row = idx.execute(
                "SELECT id FROM nodes WHERE name = ? OR id LIKE ?",
                (neuron, f"%::{neuron}"),
            ).fetchone()
            idx.close()
            neuron_id = row[0] if row else None

        memories = list_memories(
            conn, neuron_id=neuron_id, lobe=lobe,
            type_filter=arguments.get("type"),
            include_stale=bool(arguments.get("include_stale", False)),
        )
        conn.close()

        out = {
            "memories": [
                {
                    "id": m.id, "type": m.type, "title": m.title, "body": m.body,
                    "neuron": m.neuron_id, "lobe": m.lobe, "author": m.author,
                    "created_ts": m.created_ts, "tags": list(m.tags),
                    "decay_score": m.decay_score, "status": m.status,
                }
                for m in memories
            ],
            "count": len(memories),
        }
        return [TextContent(type="text", text=_json.dumps(out, indent=2))]
    except Exception as exc:
        return _make_error_content(f"cerebrofy_memories failed: {exc}")
```

- [ ] **Step 2: Add dispatch cases to `call_tool`**

In `call_tool`, add before the `else` clause:

```python
            elif name == "cerebrofy_remember":
                return _handle_remember(args)
            elif name == "cerebrofy_recall":
                return _handle_recall(args)
            elif name == "cerebrofy_memories":
                return _handle_memories(args)
```

Note: all three return directly (no epistemic/intent injection — memory tools return their own structured payload).

- [ ] **Step 3: Register tools in `list_tools`**

Add to the `tools` list returned by `list_tools`:

```python
            Tool(name="cerebrofy_remember", description=(
                "Write a structured memory (decision, warning, context, pattern, agent_action) "
                "attached to a neuron or lobe. Call this after any important decision, discovered "
                "gotcha, or completed refactor so future agents have context."
            ), inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Short memory title"},
                    "body": {"type": "string", "description": "Full memory content"},
                    "type": {"type": "string", "enum": ["decision", "warning", "context", "pattern", "agent_action"]},
                    "neuron": {"type": "string", "description": "Neuron name or file::name to attach to"},
                    "lobe": {"type": "string", "description": "Lobe name to attach to"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "author": {"type": "string"},
                },
                "required": ["title", "body", "type"],
            }),
            Tool(name="cerebrofy_recall", description=(
                "Semantic search across all memories. Use before starting a task to surface "
                "relevant decisions, warnings, and past agent actions."
            ), inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "type": {"type": "string", "enum": ["decision", "warning", "context", "pattern", "agent_action", "insight"]},
                    "lobe": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                    "include_stale": {"type": "boolean", "default": False},
                },
                "required": ["query"],
            }),
            Tool(name="cerebrofy_memories", description=(
                "List memories for a specific neuron or lobe without a search query. "
                "Use when you already know which neuron/lobe you're working with."
            ), inputSchema={
                "type": "object",
                "properties": {
                    "neuron": {"type": "string"},
                    "lobe": {"type": "string"},
                    "type": {"type": "string"},
                    "include_stale": {"type": "boolean", "default": False},
                },
            }),
```

- [ ] **Step 4: Smoke test**

```bash
uv run pytest tests/integration/test_mcp_command.py -v --no-cov 2>&1 | tail -10
uv run ruff check src/ tests/
uv run mypy src/cerebrofy/mcp/server.py 2>&1 | grep -v "^pyproject"
```

Fix any type or lint errors.

- [ ] **Step 5: Commit**

```bash
git add src/cerebrofy/mcp/server.py
git commit -m "feat(#05): add cerebrofy_remember, cerebrofy_recall, cerebrofy_memories MCP tools"
```

---

## Task 9: MCP — `get_neuron` Enhancement

**Files:**
- Modify: `src/cerebrofy/mcp/server.py` (`_handle_get_neuron`)

- [ ] **Step 1: Read current `_handle_get_neuron` implementation**

```bash
sed -n '126,168p' src/cerebrofy/mcp/server.py
```

Note the JSON structure it currently returns.

- [ ] **Step 2: Add memories join at the end of `_handle_get_neuron`**

Find the line in `_handle_get_neuron` where `result` dict is built and `json.dumps` is called. Before `return`, inject attached memories:

```python
    # Attach memories (if memories.db exists)
    try:
        from cerebrofy.memory.store import list_memories, open_memories_db
        cerebrofy_dir = root / ".cerebrofy"
        if (cerebrofy_dir / "db" / "memories.db").exists():
            mem_conn = open_memories_db(cerebrofy_dir)
            attached = list_memories(mem_conn, neuron_id=result.get("id"), include_stale=False)
            mem_conn.close()
            result["memories"] = [
                {
                    "id": m.id, "type": m.type, "title": m.title,
                    "body": m.body, "decay_score": m.decay_score, "status": m.status,
                    "tags": list(m.tags),
                }
                for m in attached
            ]
        else:
            result["memories"] = []
    except Exception:
        result["memories"] = []
```

The exact location depends on how `_handle_get_neuron` builds its result. The pattern is: after all other fields are set on `result`, add `memories` before serializing to JSON.

- [ ] **Step 3: Smoke test**

```bash
uv run ruff check src/cerebrofy/mcp/server.py
uv run mypy src/cerebrofy/mcp/server.py 2>&1 | grep -v "^pyproject"
```

- [ ] **Step 4: Commit**

```bash
git add src/cerebrofy/mcp/server.py
git commit -m "feat(#05): enhance get_neuron to include attached memories"
```

---

## Task 10: `build.py` + `update.py` Integration

**Files:**
- Modify: `src/cerebrofy/commands/build.py`
- Modify: `src/cerebrofy/commands/update.py`

- [ ] **Step 1: Add decay helper to `build.py`**

At the top of `build.py`, note that `config` and `root` are already available in the main function. Add a helper function near `_record_health_snapshot`:

```python
def _recompute_memory_decay_build(root: Path, config) -> None:  # type: ignore[type-arg]
    """Time-based decay recompute for all memories after a full build."""
    memories_db = root / ".cerebrofy" / "db" / "memories.db"
    if not memories_db.exists():
        return
    try:
        from cerebrofy.memory.decay import recompute_all_decay
        from cerebrofy.memory.store import open_memories_db
        conn = open_memories_db(root / ".cerebrofy")
        recompute_all_decay(conn, set(), config.memory)  # empty set = time-decay only
        conn.commit()
        conn.close()
    except Exception as exc:
        click.echo(f"Warning: memory decay recompute failed: {exc}", err=True)
```

- [ ] **Step 2: Call it in `build.py` after `_record_health_snapshot`**

Find this line in `build.py`:
```python
        _record_health_snapshot(db_path, config.lobes, str(root))
```

Add immediately after:
```python
        _recompute_memory_decay_build(root, config)
```

- [ ] **Step 3: Add decay helper to `update.py`**

Add a similar helper near `_record_health_snapshot_update`:

```python
def _recompute_memory_decay_update(root: Path, config, affected_node_ids: set[str]) -> None:  # type: ignore[type-arg]
    """Signature-aware decay recompute for memories attached to re-indexed neurons."""
    memories_db = root / ".cerebrofy" / "db" / "memories.db"
    if not memories_db.exists():
        return
    try:
        from cerebrofy.memory.decay import recompute_all_decay
        from cerebrofy.memory.store import open_memories_db
        conn = open_memories_db(root / ".cerebrofy")
        recompute_all_decay(conn, affected_node_ids, config.memory)
        conn.commit()
        conn.close()
    except Exception as exc:
        click.echo(f"Warning: memory decay recompute failed: {exc}", err=True)
```

- [ ] **Step 4: Call it in `update.py` after `_record_health_snapshot_update`**

Find:
```python
        _record_health_snapshot_update(conn, config.lobes, str(root))
```

Add immediately after:
```python
        _recompute_memory_decay_update(root, config, scope.affected_node_ids)
```

- [ ] **Step 5: Lint and type check**

```bash
uv run ruff check src/cerebrofy/commands/build.py src/cerebrofy/commands/update.py
uv run mypy src/cerebrofy/commands/build.py src/cerebrofy/commands/update.py 2>&1 | grep -v "^pyproject"
```

Fix any errors.

- [ ] **Step 6: Commit**

```bash
git add src/cerebrofy/commands/build.py src/cerebrofy/commands/update.py
git commit -m "feat(#05): trigger memory decay recompute on build and update"
```

---

## Task 11: `epistemic/state.py` — Implement `_memory_stale_count`

**Files:**
- Modify: `src/cerebrofy/epistemic/state.py`

- [ ] **Step 1: Find current `_memory_stale_count`**

```bash
grep -n "memory_stale_count\|_memory_stale" src/cerebrofy/epistemic/state.py
```

The current implementation always returns 0. Find it.

- [ ] **Step 2: Replace the stub**

Find the stub (currently `memory_stale_count=0` in `compute_epistemic_state`) and extract it as a real function. Add `_memory_stale_count` before `compute_epistemic_state`:

```python
def _memory_stale_count(repo_root: Path) -> int:
    """Count memories with status='stale' in memories.db. Returns 0 if no memories.db."""
    memories_db = repo_root / ".cerebrofy" / "db" / "memories.db"
    if not memories_db.exists():
        return 0
    try:
        import sqlite3
        conn = sqlite3.connect(str(memories_db))
        row = conn.execute("SELECT COUNT(*) FROM memories WHERE status = 'stale'").fetchone()
        conn.close()
        return int(row[0]) if row else 0
    except Exception:
        return 0
```

Update `compute_epistemic_state` to call it:

```python
    memory_stale = _memory_stale_count(repo_root)
```

And use it in the `EpistemicState` construction:
```python
        memory_stale_count=memory_stale,
```

- [ ] **Step 3: Write a test for `_memory_stale_count`** — append to `tests/unit/test_epistemic.py`:

```python
def test_memory_stale_count_no_db(tmp_path):
    from cerebrofy.epistemic.state import _memory_stale_count
    # No memories.db → returns 0 gracefully
    assert _memory_stale_count(tmp_path) == 0


def test_memory_stale_count_with_stale_memories(tmp_path):
    from cerebrofy.epistemic.state import _memory_stale_count
    from cerebrofy.memory.store import Memory, open_memories_db, write_memory

    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True)
    conn = open_memories_db(cerebrofy_dir)
    stale = Memory(
        id="s1", neuron_id=None, lobe=None, type="warning",
        title="Stale", body="Old", author=None,
        created_ts=1_000_000, tags=(), decay_score=0.05, status="stale",
    )
    write_memory(conn, stale, [0.1] * 384)
    conn.commit()
    conn.close()

    assert _memory_stale_count(tmp_path) == 1
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/test_epistemic.py -k "memory_stale" -v --no-cov
```

Expected: 2 passed.

- [ ] **Step 5: Run full epistemic test suite**

```bash
uv run pytest tests/unit/test_epistemic.py -v --no-cov
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/cerebrofy/epistemic/state.py tests/unit/test_epistemic.py
git commit -m "fix(#22): implement _memory_stale_count — closes deviation #22 D3"
```

---

## Task 12: Full Test Run + Lint + Docs

**Files:**
- Modify: `README.md`
- Modify: `docs/mcp-integration.md`

- [ ] **Step 1: Run the full test suite**

```bash
uv run pytest tests/unit/ -v --no-cov 2>&1 | tail -20
```

Fix any failures before proceeding.

- [ ] **Step 2: Run lint and type check**

```bash
uv run ruff check src/ tests/
uv run mypy src/ 2>&1 | grep -v "^pyproject" | grep -v "^Found"
```

Fix all errors.

- [ ] **Step 3: Add `cerebrofy memory` section to README.md**

Find the `### \`cerebrofy intent\`` section in `README.md` and add before it:

```markdown
### `cerebrofy memory`

Write and query structured memories attached to neurons and lobes. Memories persist across full rebuilds and decay over time (configurable half-life).

```bash
cerebrofy memory add "Clock skew breaks token expiry" --type warning --neuron auth/tokens.py::validate_token --tags "security,jwt"
cerebrofy memory search "JWT expiry edge cases"
cerebrofy memory list --lobe auth --type warning
cerebrofy memory link <from-id> <to-id> --rel motivated
cerebrofy memory export --format markdown > DECISIONS.md
```

---
```

- [ ] **Step 4: Add 3 new MCP tools to `docs/mcp-integration.md`**

Find the `### \`cerebrofy_intent\`` section and add before it:

```markdown
### `cerebrofy_remember`

Write a structured memory (decision, warning, context, pattern, or agent_action) attached to a neuron or lobe. Call this after any important architectural decision, discovered bug pattern, or completed refactor.

**Input schema:**

```json
{
  "title": "Clock skew breaks token expiry",
  "body": "validate_token fails when system clock drift > 30s. Always use NTP-synced time.",
  "type": "warning",
  "neuron": "auth/tokens.py::validate_token",
  "tags": ["security", "jwt"],
  "author": "claude-sonnet-4-6"
}
```

**Output:** `{"id": "<uuid>", "neuron_id": "<resolved-id>|null", "created_ts": 1234567890}`

---

### `cerebrofy_recall`

Semantic search across all memories. Use before starting any task to surface relevant past decisions, warnings, and agent actions.

**Input schema:**

```json
{
  "query": "JWT expiry edge cases",
  "lobe": "auth",
  "type": "warning",
  "limit": 10,
  "include_stale": false
}
```

**Output:** Ranked list with `relevance_score` and `decay_score` per memory.

---

### `cerebrofy_memories`

List memories for a specific neuron or lobe without a search query. Use when you already know which neuron or lobe you're about to modify.

**Input schema:**

```json
{
  "neuron": "auth/tokens.py::validate_token",
  "lobe": "auth",
  "type": "warning",
  "include_stale": false
}
```

**Output:** `{"memories": [...], "count": N}`

---
```

Also update the tool count in `docs/mcp-integration.md` from eleven to fourteen (search for "eleven" and update).

- [ ] **Step 5: Commit docs**

```bash
git add README.md docs/mcp-integration.md
git commit -m "docs: document cerebrofy memory CLI and 3 new MCP tools (#05)"
```

- [ ] **Step 6: Push and open PR**

```bash
git push -u origin feat/05-agent-memory-layer
gh pr create \
  --title "feat(#05): AI Agent Memory Layer — writable memory store with decay and causal graph" \
  --body "$(cat docs/superpowers/specs/2026-06-21-memory-layer-design.md | head -60)"
```

---

## Self-Review Checklist

- [x] **MemoryConfig** — Task 1 ✓
- [x] **`memories` + `vec_memories` + `memory_edges` schema** — Task 2 ✓
- [x] **`open_memories_db()`** — Task 2 ✓
- [x] **`Memory` + `MemoryEdge` dataclasses** — Task 3 ✓
- [x] **`write_memory`, `get_memory`, `list_memories`, `delete_memory`** — Task 3 ✓
- [x] **`write_memory_edge`, `trace_history`** — Task 3 ✓
- [x] **`embed_memory()`** — Task 4 ✓
- [x] **`recall_memories()` KNN** — Task 5 ✓
- [x] **`compute_decay()`, `_decay_status()`, `recompute_all_decay()`** — Task 6 ✓
- [x] **CLI: add/search/list/link/export** — Task 7 ✓
- [x] **Author auto-detect from git config** — Task 7 ✓
- [x] **`cerebrofy_remember` MCP** — Task 8 ✓
- [x] **`cerebrofy_recall` MCP** — Task 8 ✓
- [x] **`cerebrofy_memories` MCP** — Task 8 ✓
- [x] **`get_neuron` memories join** — Task 9 ✓
- [x] **`build.py` decay integration** — Task 10 ✓
- [x] **`update.py` decay integration** — Task 10 ✓
- [x] **`_memory_stale_count()` closes #22 D3** — Task 11 ✓
- [x] **All test files created** — Tasks 2, 3, 4, 5, 6, 11 ✓
- [x] **Docs updated** — Task 12 ✓

**Type consistency verified:**
- `Memory.id: str`, `Memory.tags: tuple[str, ...]`, `Memory.decay_score: float`, `Memory.status: str` — consistent across store, search, decay, CLI, MCP handlers
- `open_memories_db(cerebrofy_dir: Path)` — called with `root / ".cerebrofy"` everywhere
- `recompute_all_decay(conn, changed_node_ids: set[str], config: MemoryConfig)` — consistent across build and update callers
- `embed_memory(title: str, body: str) -> list[float]` — consistent across CLI and MCP handlers
