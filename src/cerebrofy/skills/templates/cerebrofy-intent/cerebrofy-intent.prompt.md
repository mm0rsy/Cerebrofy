Use the `cerebrofy_intent` MCP tool to fetch the current product intent for this codebase.

Steps:
1. Call `cerebrofy_intent` with `{}` to get the full intent context
2. If working on a specific lobe, call again with `{"lobe": "<lobe_name>"}` for relevance scoring
3. Read the sprint goal, priority lobes, active incidents, and architectural guidance
4. Let this context shape your recommendations — sprint-critical lobes deserve extra care; avoid patterns listed under `architecture.avoid_patterns`

If `cerebrofy_intent` returns `NO_INTENT_FILE`, inform the user that no `intent.yaml` exists and suggest running `cerebrofy intent init` to create one.

Present findings as:
- **Sprint**: name, goal, deadline
- **Priority lobes**: list
- **Open incidents**: any affecting the area of work
- **Architectural direction**: what to follow and what to avoid
- **Team concerns**: relevant warnings
