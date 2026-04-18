---
agent: agent
description: Search the Cerebrofy index — find functions, classes, and modules by meaning
---

Search the Cerebrofy semantic index for code relevant to your question:

```bash
cerebrofy search "${input:query:What are you looking for? (e.g. 'auth token validation', 'database connection pool')}"
```

Cerebrofy performs a hybrid semantic + keyword search over the indexed codebase and returns
ranked Neurons (functions, classes, modules) with file paths and line numbers.

**After cerebrofy responds:**
- Navigate to the exact file:line it returned.
- Do **not** read surrounding files or glob the directory.
- If you need to search within a specific module, add `--lobe <name>`.

**Quick reference:**

| What you want | Command |
|---------------|---------|
| Semantic search | `cerebrofy search "login handler"` |
| Find callers | `cerebrofy search "calls:validate_token"` |
| Limit to a module | `cerebrofy search "..." --lobe auth` |
| Module overview | Read `.cerebrofy/lobes/<name>_lobe.md` |
| Full map | Read `.cerebrofy/cerebrofy_map.md` |
