-- Migration 007: Multi-Agent Coordination (Feature #25)
-- Applied to: cerebrofy.db
-- Creates the active_agents table and indexes used to coordinate multiple AI
-- agents (and humans) working on the same codebase concurrently.
--
-- NOTE: coordination state is ephemeral by design.  Rebuilding the index
-- recreates cerebrofy.db and therefore clears claims.  Durable knowledge lives
-- in memories.db.  Keep this DDL in sync with ACTIVE_AGENTS_DDL in
-- src/cerebrofy/db/schema.py.

CREATE TABLE IF NOT EXISTS active_agents (
    agent_id        TEXT PRIMARY KEY,        -- Unique agent identifier (e.g. "claude-sess-001")
    agent_type      TEXT NOT NULL,           -- 'claude', 'cursor', 'devin', 'human', 'ci'
    session_id      TEXT,                    -- FK to sessions.id from Idea #11
    intent          TEXT,                    -- Natural language: "refactoring auth/ validate_token"
    claimed_neurons TEXT NOT NULL DEFAULT '[]',  -- JSON array of neuron IDs being worked on
    started_ts      INTEGER NOT NULL,        -- unix epoch when agent started
    last_heartbeat  INTEGER NOT NULL,        -- unix epoch of last heartbeat
    status          TEXT DEFAULT 'active',   -- 'active', 'paused', 'completed'
    ttl_minutes     INTEGER NOT NULL DEFAULT 60, -- claim lifetime before auto-release
    expires_ts      INTEGER,                 -- unix epoch when the claim expires
    created_ts      INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);

-- Index for fast status-based lookups (finding active claims)
CREATE INDEX IF NOT EXISTS idx_active_agents_status ON active_agents(status);

-- Index for heartbeat-based staleness detection (cleaning stale claims)
CREATE INDEX IF NOT EXISTS idx_active_agents_heartbeat ON active_agents(last_heartbeat);

-- Sample row:
-- INSERT INTO active_agents
--   (agent_id, agent_type, session_id, intent, claimed_neurons,
--    started_ts, last_heartbeat, ttl_minutes, expires_ts)
-- VALUES
--   ('claude-sess-001', 'claude', 'sess_abc123', 'refactoring validate_token',
--    '["auth/tokens.py::validate_token"]', 1729400000, 1729400000, 60, 1729403600);
