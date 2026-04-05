# Quickstart: Phase 3 — Autonomic Nervous System

**Feature**: 003-autonomic-nervous-system
**Date**: 2026-04-03

This guide validates that the Phase 3 implementation is working correctly end to end.
It assumes Phase 2 (`cerebrofy build`) has been completed: `cerebrofy.db` and `docs/cerebrofy/`
exist in the target repository.

---

## Prerequisites

- Phase 2 complete: `cerebrofy.db` exists; `docs/cerebrofy/cerebrofy_map.md` exists.
- Cerebrofy on `PATH`.
- A git repository with tracked source files.

---

## Step 1: Verify Incremental Update (SC-001, SC-002)

```sh
# Record baseline state_hash
HASH_BEFORE=$(grep "state_hash" docs/cerebrofy/cerebrofy_map.md | head -1)

# Edit one tracked source file (add a comment)
echo "# cerebrofy update test" >> src/some_file.py

# Run update and time it
time cerebrofy update

# Expected output:
# Cerebrofy: Starting update...
# Cerebrofy: Detected 1 changed file(s) via git
# Cerebrofy: Update complete. Re-indexed N neurons in X.Xs. New state_hash: <hex>...
# real  0m0.XXs   ← MUST be < 2s for SC-001
```

**Verify state_hash changed** (file content changed → new hash):
```sh
HASH_AFTER=$(grep "state_hash" docs/cerebrofy/cerebrofy_map.md | head -1)
[ "$HASH_BEFORE" != "$HASH_AFTER" ] && echo "PASS: state_hash updated" || echo "FAIL"
```

**Verify second update with no changes produces identical hash**:
```sh
cerebrofy update
HASH_AGAIN=$(grep "state_hash" docs/cerebrofy/cerebrofy_map.md | head -1)
[ "$HASH_AFTER" = "$HASH_AGAIN" ] && echo "PASS: deterministic" || echo "FAIL"
```

---

## Step 2: Verify Structural Drift Detection (SC-003)

```sh
# Add a new function to a tracked file
cat >> src/some_file.py << 'EOF'

def new_function_for_drift_test(x: int) -> int:
    return x * 2
EOF

# Run validate (WITHOUT running update first)
cerebrofy validate
echo "Exit code: $?"
# Expected: exit code 1
# Expected output includes: "new_function_for_drift_test  [added]"
```

**Verify validate blocks git push**:
```sh
git add src/some_file.py
git commit -m "test: add function for drift test"
git push  # should be BLOCKED by pre-push hook
# Expected: "STRUCTURAL DRIFT DETECTED — push blocked."
# Expected: push does NOT proceed
```

---

## Step 3: Verify Minor Drift Does NOT Block (SC-003)

```sh
# Revert to comment-only change (no structural change)
git checkout src/some_file.py
echo "# just a comment change" >> src/some_file.py

cerebrofy validate
echo "Exit code: $?"
# Expected: exit code 0
# Expected output: "Minor drift detected" or "Index is current"
```

---

## Step 4: Verify Update Resolves Structural Drift (SC-004)

```sh
# Add function back
cat >> src/some_file.py << 'EOF'

def another_function():
    pass
EOF

# Update the index
cerebrofy update

# Now validate — should be clean
cerebrofy validate
echo "Exit code: $?"
# Expected: exit code 0

# Push should succeed
git add src/some_file.py && git commit -m "test: add another_function"
git push  # Expected: push proceeds
```

---

## Step 5: Verify Atomic Safety (SC-002)

```sh
# Start update in background and kill it mid-run
cerebrofy update &
UPDATE_PID=$!
sleep 0.5 && kill -9 $UPDATE_PID

# Verify index is still queryable
python3 - << 'EOF'
import sqlite3, sqlite_vec
c = sqlite3.connect('.cerebrofy/db/cerebrofy.db')
c.enable_load_extension(True); sqlite_vec.load(c); c.enable_load_extension(False)
print('Index OK, neurons:', c.execute('SELECT COUNT(*) FROM nodes').fetchone()[0])
EOF

# Run a clean update to completion
cerebrofy update
echo "Update after kill: exit $?"
```

---

## Step 6: Verify Missing Index Behavior (SC-003 edge case)

```sh
mkdir /tmp/no-index-test && cd /tmp/no-index-test && git init
cerebrofy validate
echo "Exit code: $?"
# Expected: exit code 0 (WARN-only, no block)
# Expected output: "No index found. Run 'cerebrofy init && cerebrofy build' to initialize."

cerebrofy update
echo "Exit code: $?"
# Expected: exit code 1
# Expected output: "Error: No index found. Run 'cerebrofy build' first."
```

---

## Step 7: Verify Post-Merge Hook (SC-005)

```sh
# Simulate a remote state_hash change
ORIG=$(grep state_hash docs/cerebrofy/cerebrofy_map.md)
sed -i 's/state_hash.*/state_hash: 0000000000000000000000000000000000000000000000000000000000000000/' \
  docs/cerebrofy/cerebrofy_map.md

# Trigger post-merge hook manually
.git/hooks/post-merge 2>&1
# Expected: "Remote index state differs. Run 'cerebrofy build' to resync."

# Restore
sed -i "s/state_hash.*/$ORIG/" docs/cerebrofy/cerebrofy_map.md
```

---

## Step 8: Verify Hard-Block Activation

```sh
# Confirm hook is in WARN-only mode before activation (Phase 1 state)
grep "cerebrofy-hook-version" .git/hooks/pre-push
# Expected: "# cerebrofy-hook-version: 1"

# After cerebrofy update passes SC-001 verification, activate hard-block
# (This would be done via a cerebrofy command in the final implementation)
grep "cerebrofy-hook-version" .git/hooks/pre-push
# Expected post-activation: "# cerebrofy-hook-version: 2"
```

---

## Step 9: Verify Schema Migration (SC-006)

```sh
# Simulate older schema
python3 - << 'EOF'
import sqlite3, sqlite_vec
c = sqlite3.connect('.cerebrofy/db/cerebrofy.db')
c.enable_load_extension(True); sqlite_vec.load(c); c.enable_load_extension(False)
c.execute("UPDATE meta SET value='0' WHERE key='schema_version'")
c.commit()
print("Schema downgraded to version 0 for test")
EOF

cerebrofy migrate
echo "Exit code: $?"
# Expected: exit code 0 if migration script exists for v0→v1
# Expected output: "Applying migration v0_to_v1... done."

# Verify version restored
python3 -c "
import sqlite3, sqlite_vec
c = sqlite3.connect('.cerebrofy/db/cerebrofy.db')
c.enable_load_extension(True); sqlite_vec.load(c); c.enable_load_extension(False)
v = c.execute(\"SELECT value FROM meta WHERE key='schema_version'\").fetchone()[0]
print('Schema version:', v)
assert v == '1', 'FAIL: expected version 1'
print('PASS')
"
```

---

## Phase 3 Complete

If all steps above pass, Phase 3 is complete. The Cerebrofy index is now autonomic:
- Incremental updates keep the index current in < 2 seconds
- Structural drift is detected and blocked at push time
- Post-merge hooks prevent stale-index silent failures
- Schema migrations support future Cerebrofy upgrades

Proceed to Phase 4 (`cerebrofy specify`, `cerebrofy plan`, `cerebrofy tasks`) to enable
AI-assisted code intelligence.
