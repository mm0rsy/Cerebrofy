-- Migration 004: AI Agent Memory Layer (Feature #05)
-- Applied to: memories.db (separate from cerebrofy.db)
-- Note: schema is applied idempotently via db/schema.py:create_memory_schema()

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

-- Phase 2: causal memory graph
CREATE TABLE IF NOT EXISTS memory_edges (
    from_memory_id  TEXT NOT NULL REFERENCES memories(id),
    to_memory_id    TEXT NOT NULL REFERENCES memories(id),
    rel_type        TEXT NOT NULL,
    created_ts      INTEGER NOT NULL,
    author          TEXT,
    PRIMARY KEY (from_memory_id, to_memory_id, rel_type)
);

-- Requires sqlite-vec extension (loaded before this runs)
CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories
    USING vec0(rowid integer primary key, embedding float[384]);
