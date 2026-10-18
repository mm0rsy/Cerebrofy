-- Migration 005: Live Agent Session Recorder (Feature #11)
-- Applied to: sessions.db (separate from cerebrofy.db, mirroring 004_memories.sql)
-- Note: schema is applied idempotently via db/schema.py:create_session_schema()
--
-- Why a separate database: cerebrofy.db is rebuilt atomically by `cerebrofy build`
-- (os.replace of cerebrofy.db.tmp) and held under BEGIN IMMEDIATE by `cerebrofy update`.
-- An audit trail must survive rebuilds and never contend with the index writer.

CREATE TABLE IF NOT EXISTS sessions (
    id                   TEXT PRIMARY KEY,        -- "sess_<hex>"
    started_at           INTEGER NOT NULL,        -- unix epoch seconds
    ended_at             INTEGER,
    agent                TEXT,                    -- e.g. "claude-sonnet-4-6", "human:alice"
    task                 TEXT NOT NULL,           -- human-readable task description
    outcome              TEXT NOT NULL DEFAULT 'unknown',  -- success | partial | failed | unknown
    outcome_notes        TEXT,                    -- free text written at session end
    neurons_touched      TEXT,                    -- JSON array of node ids
    blast_radius_before  INTEGER,                 -- depth-2 callers of tracked neurons at first reference
    blast_radius_after   INTEGER,                 -- depth-2 callers of tracked neurons at session end
    event_count          INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_ended ON sessions(ended_at);

CREATE TABLE IF NOT EXISTS session_events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT NOT NULL REFERENCES sessions(id),
    ts             INTEGER NOT NULL,              -- unix epoch seconds
    tool           TEXT NOT NULL,                 -- MCP tool name
    args           TEXT,                          -- JSON object (values truncated)
    result_summary TEXT                           -- truncated first line(s) of the tool result
);

CREATE INDEX IF NOT EXISTS idx_session_events_session ON session_events(session_id, id);

-- Task-text embeddings for `cerebrofy session search` (384-dim, bge-small-en-v1.5).
-- Requires the sqlite-vec extension (loaded before this runs).
CREATE VIRTUAL TABLE IF NOT EXISTS vec_sessions
    USING vec0(rowid integer primary key, embedding float[384]);
