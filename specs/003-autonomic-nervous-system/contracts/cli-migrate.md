# Contract: `cerebrofy migrate` CLI Interface

**Feature**: 003-autonomic-nervous-system
**Date**: 2026-04-03
**Stability**: Draft

---

## Command Signature

```
cerebrofy migrate
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--help` | — | Print usage and exit. |

No additional options. Migration is always automatic, sequential, and from current schema version to the installed Cerebrofy's target version.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Migration completed (or already at current version). |
| `1` | Migration failed: index not found; version gap with no script; migration script error. |

---

## Standard Output (stdout)

**Already current**:
```
Cerebrofy: Schema already at version N. Nothing to migrate.
```

**Successful migration**:
```
Cerebrofy: Migrating schema from version N to M...
Cerebrofy: Applying migration v{N}_to_v{N+1}... done.
Cerebrofy: Applying migration v{N+1}_to_v{N+2}... done.
Cerebrofy: Migration complete. Schema now at version M.
```

**Downgrade detected (schema newer than installed)**:
```
Error: Index schema version M is newer than this Cerebrofy installation (supports up to N).
Upgrade Cerebrofy to the latest version, or run 'cerebrofy build' to rebuild from source.
```

---

## Standard Error (stderr)

| Situation | Message format |
|-----------|----------------|
| No index found | `Error: No index found. Run 'cerebrofy build' first.` |
| Migration script missing | `Error: No migration script found for v{N} → v{N+1}. Run 'cerebrofy build' to rebuild.` |
| Script execution error | `Error: Migration v{N}_to_v{N+1} failed: {reason}. Schema rolled back to v{N}.` |

---

## Migration Script Location and Format

Migration scripts are stored in `.cerebrofy/scripts/migrations/` with the naming convention
`v{N}_to_v{N+1}.py`. Each script must be idempotent (safe to re-run) and MUST complete
within a single `BEGIN IMMEDIATE ... COMMIT` transaction. Scripts receive the open
`sqlite3.Connection` as their only argument and are executed by `cerebrofy migrate`.

**Example**:
```
.cerebrofy/scripts/migrations/
└── v1_to_v2.py     ← upgrades schema from version 1 to version 2
```

**Atomicity guarantee**: If a script raises any exception, the transaction is rolled back
and `schema_version` remains at N. Subsequent migration steps are aborted.
