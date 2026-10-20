Review the ownership and governance implications of this change.

Use the `cerebrofy_governance` MCP tool:

1. Call `cerebrofy_governance(action="suggest-reviewers", pr=<number>)` when a PR
   number is known, otherwise omit `pr` to see owners for all lobes.
2. Call `cerebrofy_governance(action="check-rules", pr=<number>, format="json")`
   to evaluate `governance.rules` from `.cerebrofy/arch-rules.yaml`.
3. Summarise the result as: result (PASS/WARN/FAIL), failing rule names with
   reasons, then the suggested primary / secondary / backup reviewers.
4. If the user wants to refresh the CODEOWNERS file, call
   `cerebrofy_governance(action="generate-codeowners", format="json")` and show
   the returned content before writing anything.

`check-rules` is reporting only — do not block a merge based on it. Surface
`[GH_NOT_AUTHENTICATED]` as "run `gh auth login`", and `[NO_INDEX]` as
"run `cerebrofy build` first".
