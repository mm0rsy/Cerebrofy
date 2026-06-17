# MCP Integration Guide

Cerebrofy ships an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) stdio server that registers **six fully operational tools** for AI assistants. Once registered, any MCP-compatible client (Claude Code, Cursor, VS Code, Copilot, etc.) can call them directly against your local index.

---

## Prerequisites

```bash
uv tool install "cerebrofy[mcp]"
```

The `mcp` package is an optional extra. The base `cerebrofy` install (without `[mcp]`) is sufficient for all CLI commands but cannot start the MCP server.

> If you installed without `[mcp]` and run `cerebrofy mcp`, you will see an import error. Re-install with `[mcp]` to fix it.

---

## Quick Setup

```bash
# 1. Install with MCP support
uv tool install "cerebrofy[mcp]"

# 2. Initialize your repo (auto-registers the MCP entry with the absolute binary path)
cd /path/to/your/repo
cerebrofy init

# 3. Build the index
cerebrofy build

# 4. Restart your AI client to pick up the new MCP entry
```

`cerebrofy init` resolves the absolute path to the `cerebrofy` binary at registration time and writes it directly into the MCP config. This avoids PATH-lookup failures when the AI client launches with a minimal environment.

If the binary moves (e.g. after reinstalling), re-run with `--force`:

```bash
cerebrofy init --force
```

---

## Registration Target

`cerebrofy init` writes to `.mcp.json` in the current directory by default, registering the server for that project only.

To register globally:

```bash
cerebrofy init --global    # writes to ~/.config/mcp/servers.json
```

If a config already contains a `cerebrofy` entry, `cerebrofy init` skips it. Use `--force` to overwrite.

---

## Manual Registration

```json
{
  "mcpServers": {
    "cerebrofy": {
      "command": "/absolute/path/to/cerebrofy",
      "args": ["mcp"],
      "env": {}
    }
  }
}
```

Use the full absolute path (find it with `which cerebrofy`). For Claude Desktop on macOS the config is at `~/Library/Application Support/Claude/claude_desktop_config.json`.

---

## Available Tools

| Tool | Description |
|------|-------------|
| `search_code` | Hybrid KNN + BFS semantic search — primary navigation |
| `get_neuron` | Fetch a specific function or class by name or file:line |
| `list_lobes` | List all indexed modules with summary file paths |
| `cerebrofy_build` | Full atomic re-index of the entire repository |
| `cerebrofy_update` | Incremental re-index of changed files only |
| `cerebrofy_validate` | Drift check — zero writes |

---

### `search_code`

**Primary navigation tool.** Hybrid semantic + graph search over the Cerebrofy index. Call this before reading any source file.

**Input schema:**

```json
{
  "query": "OAuth2 token validation",
  "top_k": 10,
  "lobe": "auth"
}
```

`lobe` is optional — omit to search all modules. `top_k` defaults to 10, max 50.

**How it works:** Embeds the query using the same model as the index (BAAI/bge-small-en-v1.5, offline), runs a KNN cosine-similarity search over `vec_neurons`, then expands the results via depth-2 BFS through the call graph (skipping `RUNTIME_BOUNDARY` edges). Returns ranked neurons sorted by similarity.

**Output:** JSON with ranked results, each containing `name`, `type`, `file`, `line`, `similarity`, `summary`.

```json
{
  "results": [
    {
      "name": "validate_token",
      "type": "function",
      "file": "src/auth/validator.py",
      "line": 42,
      "similarity": 0.923,
      "summary": "Validate a JWT token and return the decoded payload."
    }
  ],
  "count": 1
}
```

---

### `get_neuron`

Fetch full details for a specific neuron by name or by file path + optional line number. Use after `search_code` to get the full signature and docstring.

**Input schema (by name):**

```json
{ "name": "validate_token" }
```

**Input schema (by file):**

```json
{ "file": "src/auth/validator.py", "line": 42 }
```

**Output:** JSON array of up to 5 matching neurons with `id`, `name`, `type`, `file`, `line_start`, `line_end`, `signature`, `docstring`.

---

### `list_lobes`

List all indexed lobes (named subsections of your codebase) with paths to their Markdown summary files.

**Input schema:** none

**Output:**

```json
{
  "lobes": [
    { "name": "auth", "summary_file": ".cerebrofy/lobes/auth_lobe.md" },
    { "name": "api",  "summary_file": ".cerebrofy/lobes/api_lobe.md" }
  ],
  "full_map": ".cerebrofy/cerebrofy_map.md"
}
```

Read the `summary_file` for a module overview before searching within it.

---

### `cerebrofy_build`

Trigger a full atomic re-index of the entire repository. Use when the index is missing or a full rebuild is needed.

**Input schema:** none

**Output:** `[success]` or `[error]` followed by CLI output.

---

### `cerebrofy_update`

Trigger an incremental re-index of changed files (auto-detected via git diff).

**Input schema:**

```json
{ "path": "src/auth/validator.py" }
```

`path` is optional — omit to auto-detect all changed files.

**Output:** `[success]` or `[error]` followed by CLI output.

---

### `cerebrofy_validate`

Check for drift between source code and the index. Zero writes to any file or database.

**Input schema:** none

**Output:** `[clean]`, `[minor_drift]`, or `[structural_drift]` followed by details.

---

## CWD Routing

The MCP server uses **CWD routing**: at each tool call it reads `os.getcwd()` and walks up the directory tree to find `.cerebrofy/config.yaml`. A single registered MCP entry serves all Cerebrofy-initialized repositories on the machine — no per-repo setup needed.

If the AI client's CWD is not within a Cerebrofy-initialized repo, the tool returns:

```
No Cerebrofy index found. Run 'cerebrofy build' first.
```

---

## Error Responses

| Condition | Response |
|-----------|----------|
| No `.cerebrofy/config.yaml` found | `"No Cerebrofy index found. Run 'cerebrofy build' first."` |
| Schema version mismatch | `"Schema version mismatch. Run 'cerebrofy migrate' to update."` |
| Embedding model mismatch | `"Embedding model mismatch. Run 'cerebrofy build' to rebuild."` |

---

## Verifying the Setup

After registration and restart, ask your AI client:

> "Use the cerebrofy_validate tool to check if the index is up to date."

You should see `[clean]` or drift details. If you see `"No Cerebrofy index found"`, run `cerebrofy build` in your project directory first.

---

## Troubleshooting

**`cerebrofy mcp` exits with import error**

```
Error: MCP server requires the 'mcp' package. Install with: uv tool install "cerebrofy[mcp]"
```

**Tools not appearing in the AI client**

- Restart the client after registration
- Verify the MCP config contains the `cerebrofy` entry with an absolute binary path
- Re-run `cerebrofy init --force`
- Check `ls -la $(which cerebrofy)`

**"No Cerebrofy index found" when index exists**

The AI client's CWD may not be within the repo. Check the client's working directory and ensure `cerebrofy init` + `cerebrofy build` have been run there.

**Multiple installation warning**

Ensure only one cerebrofy binary is on your PATH (don't mix pip and snap installs).
