# Quickstart: Phase 2 — The Build Engine

**Feature**: 002-build-engine
**Date**: 2026-04-03

This guide validates that the Phase 2 implementation is working correctly from end to end.
It assumes Phase 1 (`cerebrofy init`) has already been completed on the target repository.

---

## Prerequisites

- Phase 1 complete: `cerebrofy init` has been run; `.cerebrofy/config.yaml` exists.
- Cerebrofy available on `PATH`.
- A git repository with at least some tracked source files.

---

## Step 1: Run `cerebrofy build`

```sh
cd /path/to/any-initialized-git-repo
cerebrofy build
```

**Expected output** (stdout):
```
Cerebrofy: Starting build...
Cerebrofy: Step 0/6 — Creating index database
Cerebrofy: Step 1/6 — Parsing source files (0 / N files)
Cerebrofy: Step 1/6 — Parsing source files (N / N files)
Cerebrofy: Step 2/6 — Building local call graph
Cerebrofy: Step 3/6 — Resolving cross-module calls
Cerebrofy: Step 4/6 — Generating embeddings (0 / M neurons)
Cerebrofy: Step 4/6 — Generating embeddings (M / M neurons)
Cerebrofy: Step 5/6 — Writing Markdown documentation
Cerebrofy: Step 6/6 — Committing index (state_hash: <64-char hex>)
Cerebrofy: Build complete. Indexed M neurons across N files in X.Xs.
```

**Verify the index was created**:
```sh
ls -lh .cerebrofy/db/
# Expected: cerebrofy.db  (no .tmp file)
```

**Verify NO lock file remains**:
```sh
ls .cerebrofy/db/
# Expected: cerebrofy.db only — no cerebrofy.build.lock
```

---

## Step 2: Verify Markdown Documentation

```sh
ls docs/cerebrofy/
# Expected: cerebrofy_map.md  plus one <lobe>_lobe.md per configured Lobe

cat docs/cerebrofy/cerebrofy_map.md
# Expected: state_hash present, list of lobes, last_build timestamp
```

Open a lobe Markdown file:
```sh
cat docs/cerebrofy/<lobe_name>_lobe.md
# Expected: Neurons table (name, type, signature, docstring, lines)
#           Synaptic Projections table (inbound/outbound counts)
```

---

## Step 3: Verify Determinism (SC-002)

Run `cerebrofy build` a second time without changing any files:
```sh
cerebrofy build
```

**Verify identical state_hash**:
```sh
# Compare state_hash from first and second build
grep "state_hash" docs/cerebrofy/cerebrofy_map.md
# Expected: same 64-char hex value both times
```

---

## Step 4: Verify Index Contents (SC-004)

Query the index directly:
```sh
python3 - <<'EOF'
import sqlite3, sqlite_vec
conn = sqlite3.connect(".cerebrofy/db/cerebrofy.db")
conn.enable_load_extension(True)
sqlite_vec.load(conn)
conn.enable_load_extension(False)

# Check schema version
version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
print(f"Schema version: {version[0]}")

# Count neurons
n_nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
print(f"Neurons indexed: {n_nodes}")

# Count edges by type
for rel_type in ("LOCAL_CALL", "EXTERNAL_CALL", "IMPORT", "RUNTIME_BOUNDARY"):
    n = conn.execute("SELECT COUNT(*) FROM edges WHERE rel_type=?", (rel_type,)).fetchone()[0]
    print(f"  {rel_type}: {n}")

# Verify all neurons have embeddings
n_vecs = conn.execute("SELECT COUNT(*) FROM vec_neurons").fetchone()[0]
print(f"Embedding vectors: {n_vecs}")
print(f"Neurons == vectors: {n_nodes == n_vecs}")

# Check meta keys
for key in ("state_hash","last_build","schema_version","embed_model","embed_dim"):
    val = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    print(f"  meta[{key}] = {val[0] if val else 'MISSING'}")
EOF
```

**Expected**:
- `Schema version: 1`
- `Neurons indexed: N` (≥ 1 for any non-empty tracked repo)
- `Embedding vectors: N` (must equal Neurons indexed)
- All 5 meta keys present

---

## Step 5: Verify Call Graph

Find a file with known function calls (e.g., `src/cerebrofy/commands/build.py`):
```sh
python3 - <<'EOF'
import sqlite3, sqlite_vec
conn = sqlite3.connect(".cerebrofy/db/cerebrofy.db")
conn.enable_load_extension(True)
sqlite_vec.load(conn)
conn.enable_load_extension(False)

# Sample: show first 10 LOCAL_CALL edges
rows = conn.execute("""
  SELECT src_id, dst_id FROM edges
  WHERE rel_type = 'LOCAL_CALL' LIMIT 10
""").fetchall()
for src, dst in rows:
    print(f"  {src} → {dst}")
EOF
```

**Expected**: At least one `LOCAL_CALL` edge is present for any repo with function calls.

---

## Step 6: Verify Atomic Safety (SC-003)

Test forced-kill recovery:
```sh
# 1. Start a build in the background
cerebrofy build &
BUILD_PID=$!

# 2. Kill it mid-run (after ~2 seconds)
sleep 2 && kill -9 $BUILD_PID

# 3. Check: prior index is unchanged (run a quick query)
python3 -c "
import sqlite3, sqlite_vec
c = sqlite3.connect('.cerebrofy/db/cerebrofy.db')
c.enable_load_extension(True); sqlite_vec.load(c); c.enable_load_extension(False)
print('Index OK, neurons:', c.execute('SELECT COUNT(*) FROM nodes').fetchone()[0])
"

# 4. Check: no .tmp file remains (may have been cleaned up or still there is OK)
ls .cerebrofy/db/

# 5. Run a clean build to completion
cerebrofy build
# Expected: succeeds; lock file is gone; .tmp is gone
```

---

## Step 7: Verify Error Handling

**Test: run build before init**:
```sh
mkdir /tmp/no-init && cd /tmp/no-init && git init
cerebrofy build
# Expected: "Error: .cerebrofy/config.yaml not found. Run 'cerebrofy init' first."
# Expected: exit code 1
```

**Test: syntax error in source file**:
```sh
echo "def broken(" > /tmp/bad.py
cp /tmp/bad.py .  # add to tracked directory
cerebrofy build
# Expected: warning on stderr mentioning bad.py
# Expected: build still completes with exit 0
```

**Test: concurrent build detection**:
```sh
cerebrofy build &
cerebrofy build   # immediately try a second build
# Expected: "Error: A build is already in progress in this repository (PID N)."
# Expected: second invocation exits 1
```

---

## Edge Case Tests

| Scenario | Command | Expected Outcome |
|----------|---------|-----------------|
| Empty repo (no source files) | `cerebrofy build` in a repo with only `.md` files | Warning "no code units indexed"; empty DB; exit 0 |
| Model switch | Change `embedding_model` in `config.yaml`, re-run build | New `embed_dim`-dimension vectors; no mismatch error |
| Stale `.tmp` file | Copy any file to `.cerebrofy/db/cerebrofy.db.tmp`, run build | Build detects and deletes stale `.tmp`; completes normally |
| Zero lobes configured | Edit `config.yaml` to have empty `lobes:`, run build | Config validation error before parsing; exit 1 |

---

## Phase 2 Complete

If all steps above pass, Phase 2 is complete. The Cerebrofy index is fully operational.

Proceed to Phase 3 (`cerebrofy update` + `cerebrofy validate`) to enable incremental indexing
and tiered git hook enforcement.
