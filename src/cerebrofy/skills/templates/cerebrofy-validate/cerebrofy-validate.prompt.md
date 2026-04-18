---
agent: agent
description: Check if the Cerebrofy index is in sync with the current source
---

Validate the Cerebrofy index against the current source:

```bash
cerebrofy validate
```

**Exit codes:**
| Code | Meaning |
|------|---------|
| 0 | Index is clean — safe to query |
| 1 | Minor drift (whitespace/comments) — index is usable, run `cerebrofy update` when convenient |
| 2 | Structural drift — run `cerebrofy update` or `cerebrofy build` before querying |

Run this before using `cerebrofy plan` or `cerebrofy tasks` to confirm the index reflects the current code.
