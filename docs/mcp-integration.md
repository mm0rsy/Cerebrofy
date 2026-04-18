# MCP Integration Guide

Cerebrofy ships an [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) stdio server that registers eight tools for AI assistants. **Three tools are fully operational** (`cerebrofy_build`, `cerebrofy_update`, `cerebrofy_validate`). Five tools (`search_code`, `get_neuron`, `list_lobes`, `plan`, `tasks`) are **registered stubs** — they are advertised to the client but raise runtime errors pending implementation of `search/hybrid.py` and related modules.

Once registered, any MCP-compatible client (Claude Desktop, Cursor, VS Code, etc.) can call the operational tools directly against your local index.

---

## Prerequisites

```bash
uv tool install "cerebrofy[mcp]"
```

The `mcp` package is an optional extra. The base `cerebrofy` install (without `[mcp]`) is sufficient for the CLI commands but cannot start the MCP server.

> **Note:** If you installed cerebrofy without `[mcp]` and try to run `cerebrofy mcp`, you will get an import error. Re-install with `[mcp]` to fix it.

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

If the binary moves (e.g. after reinstalling cerebrofy), re-run with `--force`:

```bash
cerebrofy init --force    # overwrites the existing MCP entry with the current binary path
```

---

## Registration Target

`cerebrofy init` writes to a local `.mcp.json` in the current directory by default. This registers the server for that project only.

To register globally (all projects, all MCP clients that read the global config):

```bash
cerebrofy init --global    # writes to ~/.config/mcp/servers.json
```

If a config file already contains a `cerebrofy` entry, `cerebrofy init` skips it. Use `--force` to overwrite.

---

## Manual Registration

If you prefer to register manually, add this to your AI client's MCP config:

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

Use the full absolute path to the binary (find it with `which cerebrofy`). Using a bare `"command": "cerebrofy"` without an absolute path may fail if the AI client launches with a minimal PATH.

For Claude Desktop on macOS, the config file is at:
`~/Library/Application Support/Claude/claude_desktop_config.json`

For VS Code / Cursor, the MCP config is in `.mcp.json` at the project root or in the user settings.

---

## Available Tools

> **⚠️ Implementation Status**
>
> | Tool | Status | Notes |
> |------|--------|-------|
> | `cerebrofy_build` | ✅ Operational | Shells out to `cerebrofy build` |
> | `cerebrofy_update` | ✅ Operational | Shells out to `cerebrofy update` |
> | `cerebrofy_validate` | ✅ Operational | Shells out to `cerebrofy validate` |
> | `search_code` | 🚧 WIP stub | Requires `cerebrofy.search.hybrid` (not implemented) |
> | `get_neuron` | 🚧 WIP stub | Queries wrong table name (`neurons` vs actual `nodes`) |
> | `list_lobes` | 🚧 WIP stub | Queries wrong table name (`neurons` vs actual `nodes`) |
> | `plan` | 🚧 WIP stub | Requires `cerebrofy.search.hybrid` + `cerebrofy.commands.plan` |
> | `tasks` | 🚧 WIP stub | Requires `cerebrofy.search.hybrid` + `cerebrofy.commands.tasks` |

---

### `search_code`

> ⚠️ **WIP stub — not operational.** Raises `ModuleNotFoundError` at call time. Requires `cerebrofy/search/hybrid.py` to be implemented.

**Primary navigation tool.** Hybrid semantic + keyword search over the Cerebrofy index. Call this before reading any source file.

**Input schema:**

```json
{
  "query": "OAuth2 token validation",
  "top_k": 10,
  "lobe": "auth"
}
```

`lobe` is optional — omit to search all modules. `top_k` defaults to 10, max 50.

**Output:** JSON with ranked Neurons, each containing `name`, `type`, `file`, `line`, `lobe`, `similarity`, `summary`.

---

### `get_neuron`

> ⚠️ **WIP stub — not operational.** Queries a table named `neurons` but the actual DB table is `nodes`. Also references columns `node_type`, `start_line`, `lobe` which do not exist in `nodes` (`type`, `line_start`, and no `lobe` column).

Fetch a single node by name or file path. Use after `search_code` to get the full signature and docstring.

**Input schema:**

```json
{
  "name": "validate_token"
}
```

Or by file + optional line:

```json
{
  "file": "auth/validator.py",
  "line": 42
}
```

**Output:** JSON array of up to 5 matching Neurons.

---

### `list_lobes`

> ⚠️ **WIP stub — not operational.** Same table name bug as `get_neuron` — queries `FROM neurons` instead of `FROM nodes`.

List all indexed lobes (modules/packages) with node counts and summary file paths. Good for orientation before searching.

**Input schema:** none

**Output:** JSON with `lobes` (array of `{name, neuron_count, summary_file}`) and `full_map` path.

---

### `plan`

> ⚠️ **WIP stub — not operational.** Raises `ModuleNotFoundError` at call time. Requires `cerebrofy/search/hybrid.py` and `cerebrofy/commands/plan.py` to be implemented.

Analyze which parts of the codebase would be affected by a feature description. Returns matched nodes, blast radius, affected lobes, and re-index scope.

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

> ⚠️ **WIP stub — not operational.** Raises `ModuleNotFoundError` at call time. Requires `cerebrofy/search/hybrid.py` and `cerebrofy/commands/tasks.py` to be implemented.

Generate a numbered implementation task list for a feature description. Each task names the exact code unit, lobe, location, and structural blast radius.

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
      "line": 42,
      "lobe": "api",
      "blast_count": 3,
      "similarity": 0.912
    }
  ]
}
```

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
{
  "path": "src/auth/validator.py"
}
```

`path` is optional — omit to auto-detect changed files.

**Output:** `[success]` or `[error]` followed by CLI output.

---

### `cerebrofy_validate`

Check for drift between source code and the index. Zero writes to any file.

**Input schema:** none

**Output:** `[clean]`, `[minor_drift]`, or `[structural_drift]` followed by drift details.

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

> "Use the cerebrofy_validate tool to check if the index is up to date."

If the tool is available and the index is built, you should see `[clean]` or drift details. If you see `"No Cerebrofy index found"`, run `cerebrofy build` in your project directory.

> **Note:** The `plan`, `tasks`, and `search_code` tools are listed in the tool manifest but are not yet operational. Do not use them to verify the setup.

---

## Troubleshooting

**`cerebrofy mcp` exits with import error**

```
Error: MCP server requires the 'mcp' package. Install with: uv tool install "cerebrofy[mcp]"
```

Run `uv tool install "cerebrofy[mcp]"`. If you installed cerebrofy via pip or pipx, use `pip install "cerebrofy[mcp]"` or `pipx install "cerebrofy[mcp]"` instead.

**Tools not appearing in the AI client**

- Restart the client after registration
- Verify the MCP config contains the `cerebrofy` entry with an absolute binary path
- Re-run `cerebrofy init --force` to rewrite the entry with the current binary path
- Check that the binary path exists: `ls -la $(which cerebrofy)`

**Connection closed immediately**

The MCP server process exited before the client could connect. Most common cause: `mcp` extra not installed. Run `cerebrofy mcp` manually in a terminal to see the error. If you see an import error, install with `uv tool install "cerebrofy[mcp]"`.

**"No Cerebrofy index found" when index exists**

The AI client's CWD may not be within the repo. Check the client's working directory setting and ensure `cerebrofy init` + `cerebrofy build` have been run in that directory.

**Multiple installation warning**

If `cerebrofy init` prints a warning about multiple installations, ensure only one cerebrofy binary is on your PATH (e.g. don't mix pip and snap installs).
