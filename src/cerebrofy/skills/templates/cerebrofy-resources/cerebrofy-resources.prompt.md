Before reading any source file, check Cerebrofy's MCP resources for the context you need.

Discovery:
  cerebrofy_list_resources(filter="all")   # or: graph | lobes | neurons | health | memories | blast-radius

Read resources directly via MCP resources/read (not tool calls):
  cerebrofy://graph/map                        → full codebase map (Markdown)
  cerebrofy://graph/entry-points               → entry-point neurons (JSON)
  cerebrofy://health/current                   → latest health snapshot (JSON)
  cerebrofy://lobes/<name>                     → per-lobe summary (Markdown)
  cerebrofy://neurons/<file::name>             → single neuron details (JSON)
  cerebrofy://neurons/file/<path>              → all neurons in a file (JSON)
  cerebrofy://neurons/search?q=<query>         → semantic search results (JSON)
  cerebrofy://memories/<file::name>            → memories attached to a neuron (JSON)
  cerebrofy://blast-radius/<file::name>        → callers + risk score + PR summary (JSON)

Session start:
- Read cerebrofy://graph/map and cerebrofy://graph/entry-points to orient without glob-reading files.

Before modifying a function:
- Read cerebrofy://blast-radius/<file::name> and cerebrofy://memories/<file::name> first.

Keeping context fresh:
- Subscribe to the URIs you care about — the server sends notifications/resources/updated
  after every cerebrofy build/update, so your context never goes stale.
