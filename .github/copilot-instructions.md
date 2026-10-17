

<!-- cerebrofy:start -->
## Codebase Navigation — Cerebrofy Index

This project's codebase is indexed by [Cerebrofy](https://github.com/mm0rsy/Cerebrofy).
The semantic index lives at `.cerebrofy/db/cerebrofy.db`.

**Navigation rules (enforced):**

1. **NEVER glob-read or recursively open source files** to understand the codebase.
   The index already contains every function, class, and module with embeddings.

2. **ALWAYS start with an MCP tool call** when asked about code structure or behaviour:
   - `search_code` — find code by meaning (semantic + graph search)
   - `get_neuron` — fetch a specific function or class by name or file:line
   - `list_lobes` — get the list of all modules with summary file paths
   - `cerebrofy_list_resources` — discover ambient MCP resources (map, lobes, health, neurons)

3. Use the pre-built summaries for orientation — no parsing needed:
   - `docs/cerebrofy/cerebrofy_map.md` — full codebase map
   - `docs/cerebrofy/<name>_lobe.md` — per-module summaries

4. **Only open a specific source file** after cerebrofy has returned its file path and
   line number — and only to read or edit *that exact location*.
<!-- cerebrofy:end -->
