# MCP Integration Guide

Cerebrofy ships an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) stdio server that exposes three tools for AI assistants: `plan`, `tasks`, and `specify`. Once registered, any MCP-compatible client (Claude Desktop, Cursor, etc.) can call these tools directly without leaving the editor.

---

## Prerequisites

```bash
pip install cerebrofy[mcp]
```

The `mcp` package is an optional extra. The base `cerebrofy` install does not require it.

---

## Quick Setup

```bash
# 1. Install with MCP support
pip install cerebrofy[mcp]

# 2. Initialize your repo (auto-registers the MCP entry)
cd /path/to/your/repo
cerebrofy init

# 3. Build the index
cerebrofy build

# 4. Restart your AI client to pick up the new MCP entry
```

`cerebrofy init` automatically detects your AI client's MCP config file and writes the registration entry. If it cannot find a writable config, it prints a manual snippet (see [Manual Registration](#manual-registration)).

---

## Auto-Detection Priority

`cerebrofy init` searches for MCP config files in this order:

| Tool | Config Path |
|------|------------|
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop (Windows) | `%APPDATA%/Claude/claude_desktop_config.json` |
| Cursor (macOS/Linux) | `~/.cursor/mcp.json` |
| Cursor (Windows) | `%USERPROFILE%/.cursor/mcp.json` |
| Opencode | `~/.config/opencode/mcp.json` |
| Generic MCP | `~/.config/mcp/servers.json` |

The first existing, writable file is used. If none exist, Cerebrofy creates `~/.config/mcp/servers.json`.

To force global registration regardless of which tools are installed:

```bash
cerebrofy init --global    # writes to ~/.config/mcp/servers.json
```

---

## Manual Registration

If auto-detection fails, add this entry to your AI client's MCP config manually:

```json
{
  "mcpServers": {
    "cerebrofy": {
      "command": "cerebrofy",
      "args": ["mcp"],
      "env": {}
    }
  }
}
```

For Claude Desktop on macOS, the config file is at:
`~/Library/Application Support/Claude/claude_desktop_config.json`

---

## Available Tools

### `plan`

Analyze which parts of the codebase would be affected by a feature description. Returns a structured JSON report with matched Neurons, blast radius, affected lobes, and re-index scope.

**Makes zero network calls** — safe to use offline and in CI.

**Input schema:**

```json
{
  "description": "add OAuth2 login",
  "top_k": 10
}
```

**Output:** JSON string (same schema as `cerebrofy plan --json`)

```json
{
  "schema_version": 1,
  "matched_neurons": [...],
  "blast_radius": [...],
  "affected_lobes": ["auth", "api"],
  "reindex_scope": 5
}
```

---

### `tasks`

Generate a numbered implementation task list for a feature description. Each task names the exact code unit to modify, its lobe, location, and structural blast radius.

**Makes zero network calls** — safe to use offline and in CI.

**Input schema:**

```json
{
  "description": "add rate limiting to the API",
  "top_k": 10
}
```

**Output:** JSON string

```json
{
  "tasks": [
    {
      "number": 1,
      "neuron_name": "handle_request",
      "neuron_file": "api/middleware.py",
      "lobe": "api",
      "blast_count": 3,
      "similarity": 0.912
    }
  ]
}
```

---

### `specify`

Generate an AI-grounded feature specification using the codebase as context. The spec is written to `docs/cerebrofy/specs/` and the full content is returned.

**Requires LLM configuration** in `.cerebrofy/config.yaml` and the appropriate API key in the environment.

**Input schema:**

```json
{
  "description": "add OAuth2 login",
  "top_k": 10
}
```

**Output:** JSON string

```json
{
  "output_file": "docs/cerebrofy/specs/2026-04-05T12-00-00_spec.md",
  "content": "# Feature Specification: Add OAuth2 Login\n..."
}
```

---

## CWD Routing

The MCP server uses **CWD (current working directory) routing**: at each tool call, it reads `os.getcwd()` and walks up the directory tree to find `.cerebrofy/config.yaml`. This means a single registered MCP entry serves all Cerebrofy-initialized repositories on the machine — no per-repo setup needed.

When you open a project in your AI client:
1. The client's CWD is typically the project root
2. Cerebrofy finds `.cerebrofy/config.yaml` by walking up from that CWD
3. The correct index and config are loaded for that specific project

If the AI client's CWD is not within a Cerebrofy-initialized repository, the tool returns:

```
No Cerebrofy index found. Run 'cerebrofy build' first.
```

---

## Error Responses

The MCP server returns structured error messages (not exceptions) so the AI client can relay them clearly:

| Condition | Response |
|-----------|----------|
| No `.cerebrofy/config.yaml` found | `"No Cerebrofy index found. Run 'cerebrofy build' first."` |
| Schema version mismatch | `"Schema version mismatch. Run 'cerebrofy migrate' to update."` |
| Embedding model mismatch | `"Embedding model mismatch. Run 'cerebrofy build' to rebuild."` |
| LLM timeout (`specify` only) | `"LLM request timed out. Increase 'llm_timeout' in config.yaml."` |
| Other errors | `"Error: <message>"` |

---

## Verifying the Setup

After registration and restart, ask your AI client:

> "Use the cerebrofy plan tool to analyze what would be affected by adding rate limiting."

If the tool is available and the index is built, you should see a structured JSON response. If you see `"No Cerebrofy index found"`, run `cerebrofy build` in your project directory.

---

## Troubleshooting

**`cerebrofy mcp` exits with import error**

```
Error: MCP server requires the 'mcp' package. Install with: pip install cerebrofy[mcp]
```

Run `pip install cerebrofy[mcp]` (or `uv pip install cerebrofy[mcp]`).

**Tools not appearing in the AI client**

- Restart the client after registration
- Verify the MCP config contains the `cerebrofy` entry: `cat ~/Library/Application\ Support/Claude/claude_desktop_config.json`
- Check that `cerebrofy` is on your PATH: `which cerebrofy`

**"No Cerebrofy index found" when index exists**

The AI client's CWD may not be within the repo. Check the client's working directory setting and ensure `cerebrofy init` + `cerebrofy build` have been run in that directory.

**Multiple installation warning**

If `cerebrofy init` prints a warning about multiple installations, ensure only one cerebrofy binary is on your PATH (e.g. don't mix pip and snap installs).
