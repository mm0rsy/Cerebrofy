Plan a refactor from a plain-English description — before touching any code.

Use the `cerebrofy_plan` MCP tool with `description` set to the requested change
(e.g. "extract the payment logic into a payments service"). Then:

1. Summarise the proposed structure (new module + mapped files) for approval.
2. List every caller that needs updating — do not skip any.
3. Walk the steps in order: skeleton → moves with re-export stubs → caller
   updates → stub removal + tests. Verify each step with `cerebrofy_impact`.
4. Never modify files until the plan is approved. If no index exists, run
   `cerebrofy build` first; if the cluster is too small or too large, refine the
   description and re-run.
