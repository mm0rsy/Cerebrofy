Before refactoring any function or class, always run cerebrofy_impact first.

Usage:
  cerebrofy_impact(target="<file>::<name>")   # preferred — unambiguous
  cerebrofy_impact(target="<name>")            # by name (first match)
  cerebrofy_impact(target="<file>:<line>")     # by file and line number

Read the result before editing:
- complexity_rating HIGH or lobe_spread >= 3 → pause, share the impact report with the user
- memory_warnings non-empty → surface them to the user before proceeding
- uncovered_callers non-empty → suggest adding tests before the refactor
- refactoring_sequence → follow this order when updating callers
