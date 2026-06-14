---
agent: agent
description: Search the Cerebrofy index — find functions, classes, and modules by meaning
---

Search the Cerebrofy index for code relevant to the following query:

$ARGUMENTS

Use the `search_code` MCP tool:
- Pass the query above directly to `search_code`
- Optionally add `top_k` to control how many results to return (default: 10)
- Optionally add `lobe` to restrict to a specific module

After receiving results, use `get_neuron` to fetch full details on the top matches.
Navigate to the exact file:line returned — do **not** read surrounding files.

If `search_code` returns "not yet available", read `.cerebrofy/lobes/` summaries to orient
yourself, then use `get_neuron(name="...")` if you know the symbol name.
