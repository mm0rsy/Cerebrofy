---
agent: agent
description: Run a full atomic re-index of the codebase with Cerebrofy
---

Run a full Cerebrofy build to index this codebase:

```bash
cerebrofy build
```

This parses all tracked source files, builds the call graph, generates vector embeddings, and writes everything to `.cerebrofy/db/cerebrofy.db`. The swap is atomic — an interrupted build leaves no corrupted state.

**Use this when:**
- The repo was just cloned and has no index yet
- The index is corrupted or missing
- A full rebuild is needed after changing `tracked_extensions` or `embedding_model` in config

**After it completes**, the index is ready for `cerebrofy validate`, and the per-lobe Markdown docs in `docs/cerebrofy/` are updated.
