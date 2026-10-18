---
agent: agent
description: Check architecture drift rules with Cerebrofy and report violations with fixes
---

Run the Cerebrofy architecture drift check for:

$ARGUMENTS

Steps:
1. Call `cerebrofy_arch_check`. If the user named a specific rule, pass
   `rule="<name>"`; if they gave a git ref or "my last change", pass
   `since="<ref>"`.
2. On `[NO_RULES_FILE]`: offer `cerebrofy arch init` — ask before creating files.
3. On `[NO_INDEX]`: offer `cerebrofy build` first.
4. Summarize each violation: rule name, location (`file::name` pair or cycle
   path), detail, and "introduced in" commit when present.
5. Read the result honestly: if it reports low index confidence, say so and
   suggest `cerebrofy build`; treat rules escalated by a sprint-priority lobe
   as failures (they block commits for the sprint).
6. Propose the smallest fix (intermediate layer, break the cycle, split the
   function, or adjust callers); the rule description is the fix hint.
7. Do NOT open source files to hunt for call sites — the graph-based result is
   already complete. Only open a file to implement an agreed fix.
8. Offer `cerebrofy arch watch` when the user wants continuous enforcement.
