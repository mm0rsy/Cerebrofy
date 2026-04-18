````markdown
# Skill: cerebrofy-search

> Semantic + keyword hybrid search over the Cerebrofy index.

## ⚠️ Default navigation rule — READ THIS FIRST

**Do NOT open or glob-read source files to understand the codebase.**

This repo has a pre-built Cerebrofy index at `.cerebrofy/db/cerebrofy.db` that already contains
every function, class, and module. Always query the index first.

Only open a specific source file *after* cerebrofy has pointed you to it — and only to read or
edit that exact file.

## Command

```bash
# Semantic + keyword hybrid search (default)
cerebrofy search "<query>"

# Limit to a specific lobe (module/package)
cerebrofy search "<query>" --lobe auth

# Return fewer results
cerebrofy search "<query>" --limit 5
```

## When to use

- Any time you need to find a function, class, or module
- Before answering "how does X work?" or "where is Y implemented?"
- Before making changes — find all call sites first so you know the blast radius

## Output

Returns a ranked list of Neurons (functions / classes / modules) with:

- File path + line number
- Neuron name and type
- Relevance score
- Short docstring / summary

Navigate directly to the file:line cerebrofy returns. Do not read surrounding files.

## Quick reference

| Goal | Command |
|------|---------|
| Find a function | `cerebrofy search "login handler"` |
| Find all callers of a symbol | `cerebrofy search "calls:validate_token"` |
| Find by file | `cerebrofy search "file:auth.py"` |
| Module overview | Read `.cerebrofy/lobes/auth_lobe.md` |
| Full map | Read `.cerebrofy/cerebrofy_map.md` |
````
