Generate a semantic changelog for this repository — what actually changed, classified from
the call graph and memories, not from commit messages.

Use the `cerebrofy_changelog` MCP tool to get the structured report. Then:

1. Determine the range: `since` is a git tag, commit hash, `last-build`, or `project-start`.
2. Pick the audience: `developer` (default, function names + files), `pm` (feature-level),
   or `user` (plain English, no internals).
3. Pick the format: `markdown` (default), `github` (release body), or `slack`.
4. Summarise `breaking_changes[]` FIRST — these need an upgrade note.
5. For `fix` and `security` entries, quote the "why" from the embedded memory text.

If asked for release notes, prefer `format="github"` and paste `full_text` into the release body.
If asked for a Slack post, use `format="slack"`.
If the tool returns `[NO_INDEX]`, run `cerebrofy build` first. If it returns `[REF_NOT_FOUND]`,
check whether the tag/hash exists (e.g. ask the user for the previous release tag).
