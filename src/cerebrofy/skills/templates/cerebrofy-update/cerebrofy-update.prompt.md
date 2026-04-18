---
agent: agent
description: Incrementally re-index changed files with Cerebrofy
---

Run an incremental Cerebrofy update to re-index changed files:

```bash
# Auto-detect via git diff
cerebrofy update

# Or explicit files
cerebrofy update src/path/to/file.py
```

This detects changed files, re-parses only those, runs a depth-2 BFS to find all affected neighbors, and updates the index in a single atomic transaction. Target latency is under 2 seconds for a single-file change.

**Use this when:**
- You've edited source files and want to sync the index before querying
- The pre-push hook warns about a stale index

**Do NOT use this if** the index doesn't exist yet — run `/cerebrofy-build` first.
