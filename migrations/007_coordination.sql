-- Migration 007: Multi-Agent Coordination (Feature #25)
-- Applied to: cerebrofy.db
-- This migration creates the active_agents table and index for coordinating
-- multiple AI agents working on the same codebase concurrently.

-- Table: active_agents
-- Tracks all active agents and their claimed neurons to prevent conflicts.
CREATE TABLE IF NOT EXISTS active_agents (
    agent_id          TEXT PRIMARY KEY,        -- Unique agent identifier (e.g. "claude-sess-001")
    agent_type        TEXT NOT NULL,           -- 'claude', 'cursor', 'devin', 'human', 'ci'
    session_id        TEXT,                    -- FK to sessions.id from Idea #11
    intent            TEXT,                    -- Natural language: "refactoring auth/ validate_token"
    claimed_neurons   TEXT NOT NULL DEFAULT '[]',  -- JSON array of neuron IDs being worked on
    started_ts        INTEGER NOT NULL,        -- unix epoch when agent started
    last_heartbeat    INTEGER NOT NULL,        -- unix epoch of last heartbeat
    status            TEXT DEFAULT 'active',   -- 'active', 'paused', 'completed'
    created_ts        INTEGER NOT NULL DEFAULT (unixepoch())
);

-- Index for fast status-based lookups (finding active claims)
CREATE INDEX IF NOT EXISTS idx_active_agents_status ON active_agents(status);

-- Index for fast neuron claim lookups (finding which agent claimed a neuron)
CREATE INDEX IF NOT EXISTS idx_active_agents_neuron ON active_agents(claimed_neurons);

-- Index for heartbeat-based staleness detection (cleaning stale claims)
CREATE INDEX IF NOT EXISTS idx_active_agents_heartbeat ON active_agents(last_heartbeat);

-- Sample row:
-- INSERT INTO active_agents (agent_id, agent_type, session_id, intent, claimed_neurons, started_ts, last_heartbeat)
-- VALUES ('claude-sess-001', 'claude', 'sess_abc123', 'refactoring validate_token', '["auth/tokens.py::validate_token"]', 1729400000, 1729400000);