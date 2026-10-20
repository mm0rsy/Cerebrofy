---
agent: agent
description: Review a diff or PR with graph context — blast radius, memories, arch rules, coverage gaps, and suggested reviewers
---

Review the following change with Cerebrofy's graph-aware review pipeline:

$ARGUMENTS

Steps:
1. Determine the input: a git ref (use as `diff`) or a GitHub PR number (use as `pr`).
   If neither is given, ask the user which diff ref or PR to review.
2. Call `cerebrofy_review` with that input, `severity="all"`, and `format="markdown"`.
3. Lead with the highest `severity_score` findings. Explain why each matters:
   blast radius, the recorded memory/decision, the architecture rule, or the missing test.
4. List `suggested_reviewers` when a knowledge silo is reported, and say which lobe they own.
5. Surface `skipped_checks` honestly — an unavailable integration is not a pass.
6. If the user explicitly asks to post to GitHub, re-run with `post_comments=true` and the
   `pr` parameter. Never post comments without that explicit request.

Do NOT open source files to discover callers or coverage — the review pipeline already
has the full call graph and recorded decisions.
