````markdown
# Skill: cerebrofy-search

> Semantic + keyword hybrid search over the Cerebrofy index.

## ⚠️ Default navigation rule — READ THIS FIRST

**Do NOT open or glob-read source files to understand the codebase.**

This repo has a pre-built Cerebrofy index. Always query it first via the MCP tools.
Only open a specific source file *after* cerebrofy has returned its exact file path and line number.

## How to search

Use the `search_code` MCP tool — pass a plain-language question:

- `search_code(query="authentication token validation")`
- `search_code(query="database connection pool", top_k=5)`
- `search_code(query="payment retry logic", lobe="billing")`

After getting results, use `get_neuron` to fetch full details on specific hits.
Navigate only to the exact file:line returned.

## When to use

- Any time you need to find a function, class, or module by meaning
- Before answering "how does X work?" or "where is Y implemented?"
- Before making changes — find all call sites first to know the blast radius

## Quick reference

| Goal | MCP call |
|------|---------|
| Find by meaning | `search_code(query="...")` |
| Fetch specific symbol | `get_neuron(name="MyClass")` |
| Fetch by location | `get_neuron(file="auth.py", line=42)` |
| List all modules | `list_lobes()` |
| Module overview | Read `.cerebrofy/lobes/<name>_lobe.md` |
| Full map | Read `.cerebrofy/cerebrofy_map.md` |
````
