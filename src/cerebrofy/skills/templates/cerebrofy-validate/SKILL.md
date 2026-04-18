# cerebrofy validate

Classify drift between the Cerebrofy index and the current source code.

## When to use

- To check if the index is out of date before running `plan` or `specify`
- In CI pipelines to enforce index freshness
- After pulling changes to see if a rebuild or update is needed

## Usage

```bash
cerebrofy validate
```

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | No drift — index matches source |
| 1 | Minor drift — cosmetic changes (whitespace, comments) |
| 2 | Structural drift — function signatures, new/deleted Neurons |

## How to use the output

- Exit code 0 → safe to use `cerebrofy plan` / `cerebrofy tasks` / `cerebrofy specify`
- Exit code 1 → index is slightly stale but usable; run `cerebrofy update` when convenient
- Exit code 2 → run `cerebrofy update` (or `cerebrofy build` for large changes) before querying
