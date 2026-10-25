---
name: cerebrofy-arch-check
description: "Architecture drift alerts — verify code changes against .cerebrofy/arch-rules.yaml using the live call graph."
---

# Skill: cerebrofy-arch-check

> Architecture drift alerts — verify code changes against `.cerebrofy/arch-rules.yaml` using the live call graph.

## ⚠️ Navigation rule

**Do NOT open source files or grep for imports to evaluate architecture rules.**

The Cerebrofy index already contains every real call/import edge plus lobe
membership. Use `cerebrofy_arch_check` / `cerebrofy arch check` and read only
the reported violation locations.

## When to use

- After finishing a change, before handoff: confirm no lobe boundary was crossed.
- When the user asks "is this within our architecture rules / did we introduce drift?"
- In PR review: scope the check to files changed since a git ref (`--since`).
- After editing `.cerebrofy/arch-rules.yaml`: verify the rules against the graph.
- In watch mode while refactoring: `cerebrofy arch watch` re-runs continuously.

## MCP tool

```
cerebrofy_arch_check()                                    # all rules, markdown report
cerebrofy_arch_check(rule="no-direct-db-in-api")           # one rule
cerebrofy_arch_check(since="HEAD~1")                       # only drift touching files changed since ref
cerebrofy_arch_check(format="json")                        # spec JSON: rules_checked / passing / failing / warnings / result
```

Error codes in the result:
- `[NO_RULES_FILE]` — run `cerebrofy arch init` (ask the user before creating files).
- `[NO_INDEX]` — run `cerebrofy build` first.
- `[RULE_NOT_FOUND]` — call without `rule`, or list available rules from `cerebrofy arch explain`.

## CLI commands

```bash
cerebrofy arch check                                    # exit 0 pass/warn · 1 error-severity · 2 config error
cerebrofy arch check --rule no-direct-db-in-api
cerebrofy arch check --since HEAD~1 --format github-annotations
cerebrofy arch check --write-memories                   # record violations as warning memories (opt-in)
cerebrofy arch explain no-direct-db-in-api              # rule definition + every current violation
cerebrofy arch history                                  # when each rule was FIRST violated
cerebrofy arch init                                     # scaffold rules + interactive rule builder
cerebrofy arch init --ci                                 # write .github/workflows/cerebrofy-arch.yml now
cerebrofy health                                        # includes an Architecture Drift section
cerebrofy health --trend arch_violations                # sparkline of violation counts per check
cerebrofy arch watch --interval 2                       # live monitor (Ctrl+C to stop)
```

`cerebrofy init --ai <client>` also writes `.github/workflows/cerebrofy-arch.yml`
automatically (existing files are preserved unless `--force`), so AI-assisted
projects get the CI gate from day one.

Git hooks installed by `cerebrofy init` always **block** on arch violations
(pre-commit and pre-push): error severity exits 1, and warning rules that touch
a sprint-priority lobe are escalated to errors for the sprint's duration
(`.cerebrofy/intent.yaml` → `sprint.priority_lobes`).

## Rule DSL (quick reference)

```yaml
# .cerebrofy/arch-rules.yaml
rules:
  - name: no-direct-db-in-api
    severity: error            # error = blocks (exit 1) · warning = report only
    check:
      no_edge: { from_lobe: api, to_lobe: db }
  - name: no-circular-lobe-deps
    check: { no_cycles: { scope: lobes } }
  - name: embedder-is-isolated
    check: { allowed_callers: { neuron: "*embedder/*", from_lobes: [commands, embedder] } }
  - name: tests-only-call-public-api
    check: { no_edge: { from_pattern: "tests/**", to_pattern: "*/private/**" } }
  - name: max-blast-radius
    check: { max_blast_radius: 50 }
```

Semantics: RUNTIME_BOUNDARY edges are always excluded (Law II). Lobes come from
`.cerebrofy/config.yaml`; respecting them is mandatory — a rule naming an
unknown lobe is skipped and reported as a config error (exit 2).

## Reading a result

- **Index confidence:** every interactive/CI run reports the index freshness
  (`Index confidence: 92% ✅ — 12 neurons changed since last build`). When it
  is low (⚠️/🔴), say so in your report and suggest `cerebrofy build` — a stale
  index can both hide and invent violations. JSON output carries the same data
  under a top-level `epistemic` object.
- **Escalated rules:** `Escalated: sprint priority lobe(s) X — warning rules
  block this sprint` means a warning-severity rule was treated as an error
  because it touches a sprint-priority lobe. Fix it or raise the rule severity
  question with the user; do not silence it.
- **Exit codes:** 0 = pass/warn, 1 = error-severity violations (or escalated),
  2 = configuration error (unknown lobe/check/rule).

## Workflow

1. Call the tool/CLI as configured above.
2. On FAIL: report each violation as `rule → location → introduced in`.
3. Suggest the smallest fix (intermediate layer, cycle break, split, or allowed
   caller) — the rule's `description` is the intended fix hint.
4. On WARN: surface the warnings; do not block the work (unless escalated by a
   sprint priority lobe — then treat as FAIL).
5. Re-run after the fix to confirm `RESULT: ✅ PASSED`.
