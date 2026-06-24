# Skill: cerebrofy-vuln

> Map which of YOUR functions are exposed to a vulnerable package — before you patch anything.

## ⚠️ Default navigation rule — READ THIS FIRST

**Do NOT open or glob-read source files to understand the codebase.**

This repo has a pre-built Cerebrofy index. Always query it via MCP tools first.
Only open a specific source file *after* cerebrofy has returned its exact file path and line number.

## When to use

- When a Dependabot / pip-audit / Snyk alert fires for a dependency
- Before patching a vulnerable package — to know which call sites to update
- When asked "which of our functions actually call X?"
- When estimating remediation effort for a CVE
- Before a security audit — surface all external package exposure points

## How to use via MCP

```
cerebrofy_vuln(package="requests")
cerebrofy_vuln(package="requests", function_pattern="requests.get")
cerebrofy_vuln(package="pyyaml", write_memories=true)
cerebrofy_vuln(package="requests", depth=3)
```

The tool returns:
- `package` — the scanned package name
- `function_pattern` — specific function traced (if provided)
- `pinned_version` — version pinned in pyproject.toml / requirements.txt (for manual CVE comparison)
- `direct_callers` — neurons that directly call the package, with `is_trust_boundary` and `is_test` flags
- `critical_exposure` — entry points where external input can reach the vulnerable call, with `exposure_score`
- `low_exposure` — callers with no detected external input path (tests, internal utilities)
- `remediation_sequence` — ordered steps: patch highest-exposure callers first, then pin the package version
- `memories_written` — count of warning memories attached to affected neurons (when `write_memories=true`)

## How to use via CLI

```bash
cerebrofy vuln --package requests
cerebrofy vuln --package requests --function requests.get
cerebrofy vuln --package pyyaml --write-memories
cerebrofy vuln --package requests --depth 3 --output json
```

## Decision guide

| `critical_exposure` count | Recommended action |
|---------------------------|--------------------|
| 0 | Package used only in tests/internals — low real risk |
| 1–3 | Patch listed entry points before upgrading |
| 4+ | High surface area — prioritise by `exposure_score`, patch top-rated first |

| `is_trust_boundary: true` on a direct caller | Meaning |
|----------------------------------------------|---------|
| Yes | External input flows directly into the vulnerable call — highest risk |
| No | Vulnerable call is internal — still patch but lower urgency |

## Quick reference

| Goal | MCP call |
|------|---------|
| Scan full package | `cerebrofy_vuln(package="requests")` |
| Scan specific function | `cerebrofy_vuln(package="requests", function_pattern="requests.get")` |
| Write security memories | `cerebrofy_vuln(package="requests", write_memories=true)` |
| Deeper traversal | `cerebrofy_vuln(package="requests", depth=3)` |
| Check pinned version | read `pinned_version` field from any call |
