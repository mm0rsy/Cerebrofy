-- Migration 006: Semantic Changelog narrative events (Feature #14, feeds #26)
-- Applied to: cerebrofy.db (the main index database)
-- Note: schema is applied idempotently via db/schema.py:ensure_narrative_schema()
--       and is part of create_schema() for fresh builds. This file documents
--       the migration for existing indexes.

CREATE TABLE IF NOT EXISTS narrative_events (
    id                  TEXT PRIMARY KEY,
    ts                  INTEGER NOT NULL,
    commit_ref          TEXT,
    type                TEXT,   -- changelog entry type: feat | fix | refactor | security | breaking | perf | internal | intent_update
    title               TEXT,
    body                TEXT,
    lobes_affected      TEXT,   -- JSON array
    blast_radius_delta  REAL,
    health_delta        TEXT    -- JSON object
);

CREATE INDEX IF NOT EXISTS idx_narrative_ts ON narrative_events(ts DESC);
