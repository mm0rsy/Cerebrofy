# Contract: `cerebrofy mcp`

**Phase**: 5
**Status**: New command — authorizes creation of `commands/mcp.py` and `mcp/server.py`
**Spec Requirements**: FR-014, FR-015, FR-016, FR-017, FR-011

---

## Command Signature

```
cerebrofy mcp
```

No arguments. No flags. The command starts an MCP stdio server and blocks until the AI tool
closes the connection.

---

## Preconditions

| # | Condition | If Not Met |
|---|-----------|------------|
| 1 | Python `mcp` package installed (`pip install cerebrofy[mcp]`) | Exit 1: `"MCP server requires the 'mcp' package. Install with: pip install cerebrofy[mcp]"` |

`cerebrofy.db` does NOT need to exist at startup. The server handles missing index gracefully
per-tool-call (FR-017). The server starts and waits for tool calls regardless.

---

## Transport

- **Protocol**: MCP (Model Context Protocol) over **stdio** transport
- **stdin**: MCP protocol messages from the AI tool (JSON-RPC 2.0)
- **stdout**: MCP protocol responses to the AI tool (JSON-RPC 2.0)
- **stderr**: Server diagnostics only (not part of MCP protocol)

The server MUST NOT write any non-MCP content to stdout. Any debug output goes to stderr.

---

## Exposed Tools

The server exposes exactly three tools (FR-014):

### Tool: `plan`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `description` | string | Yes | Feature description to plan for |
| `top_k` | integer | No | KNN result count (default: config `top_k` or 10) |

**Response**: Same structured data as `cerebrofy plan --json` (FR-015).

```json
{
  "schema_version": 1,
  "matched_neurons": [...],
  "blast_radius": [...],
  "affected_lobes": [...],
  "reindex_scope": [...]
}
```

Response is returned as a `TextContent` item containing the JSON string.

### Tool: `tasks`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `description` | string | Yes | Feature description to generate tasks for |
| `top_k` | integer | No | KNN result count (default: config `top_k` or 10) |

**Response**: Structured task list as JSON.

```json
{
  "tasks": [
    {"number": 1, "neuron_name": "login_user", "neuron_file": "src/auth/login.py", "lobe": "auth", "blast_count": 3, "similarity": 0.92},
    ...
  ]
}
```

### Tool: `specify`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `description` | string | Yes | Feature description to generate a spec for |
| `top_k` | integer | No | KNN result count (default: config `top_k` or 10) |

**Response**: File path and content (FR-016).

```json
{
  "output_file": "docs/cerebrofy/specs/2026-04-04T14-32-07_spec.md",
  "content": "# Feature Specification: ..."
}
```

---

## MCP Tool Input Schema (JSON Schema)

All three tools share the same input schema:

```json
{
  "type": "object",
  "properties": {
    "description": {
      "type": "string",
      "description": "Feature description or query"
    },
    "top_k": {
      "type": "integer",
      "description": "Number of KNN results to return (default: 10)",
      "minimum": 1,
      "maximum": 100
    }
  },
  "required": ["description"]
}
```

---

## Error Handling

When a tool call fails (FR-017), the MCP server returns a structured error:

```json
{
  "content": [{"type": "text", "text": "<error message>"}],
  "isError": true
}
```

| Error Condition | Message |
|-----------------|---------|
| No index in CWD | `"No Cerebrofy index found. Run 'cerebrofy build' first."` |
| Schema version mismatch | `"Schema version mismatch. Run 'cerebrofy migrate' to update."` |
| Embedding model mismatch | `"Embedding model mismatch. Run 'cerebrofy build' to rebuild."` |
| `mcp` package not installed | Exit 1 at startup (never reaches tool call) |
| LLM timeout (specify only) | `"LLM request timed out. Increase 'llm_timeout' in config.yaml."` |

**No silent failure**: Every error condition produces an explicit error response. The server
MUST NOT return an empty response or a success response when an error occurred.

---

## Key Invariants

1. **CWD routing**: `cerebrofy mcp` reads `os.getcwd()` at each tool call invocation to
   determine the active repository. It walks up the directory tree to find `.cerebrofy/config.yaml`.
   This is the same `find_repo_root()` logic used by all other commands.

2. **Single MCP entry**: The MCP server registered in the AI tool's config is:
   ```json
   {"command": "cerebrofy", "args": ["mcp"]}
   ```
   No repository-specific arguments. The same entry serves all repos.

3. **Read-only DB access**: The `plan` and `tasks` tools MUST NOT write to `cerebrofy.db`.
   The `specify` tool writes only to `docs/cerebrofy/specs/` (same as the CLI command).

4. **MCP protocol compliance**: The server uses the `mcp` Python SDK. It MUST correctly
   implement the `initialize` handshake and `list_tools` / `call_tool` operations.

5. **`specify` requires LLM config**: If `llm_endpoint` is not configured and the `specify`
   tool is called, return the same error as the CLI: `"LLM endpoint not configured. Set 'llm_endpoint' in config.yaml."`

6. **`plan` and `tasks` are offline**: These tools MUST NOT make any network calls, even if
   LLM config is present. Presence of LLM config in `config.yaml` MUST NOT trigger any network
   call (FR-027).

---

## Registration Flow (executed by `cerebrofy init`)

When `cerebrofy init` runs, it writes the MCP entry to the first writable config file from
the priority list (FR-012). The exact JSON merged into the config file:

```json
{
  "mcpServers": {
    "cerebrofy": {
      "command": "cerebrofy",
      "args": ["mcp"]
    }
  }
}
```

**Idempotency**: If `mcpServers.cerebrofy` already exists, do NOT overwrite it.

**Multi-installation detection**: If `cerebrofy` resolves to a different binary than the
existing entry's `command` field value, print a warning (FR-018):
```
Warning: Multiple Cerebrofy installations detected.
  Current PATH entry: /opt/homebrew/bin/cerebrofy (v1.0.0)
  Existing MCP entry: /usr/local/bin/cerebrofy (v0.9.0)
To fix: remove the older installation or update the MCP entry manually.
```

---

## Implementation Notes

- `commands/mcp.py` — Click command entry point
- `mcp/server.py` — MCP server implementation using `mcp.server.Server` and `mcp.server.stdio.stdio_server`
- The three tools delegate to the same logic as `commands/plan.py`, `commands/tasks.py`, `commands/specify.py`
- The `mcp` package is an optional dependency: `pip install cerebrofy[mcp]`
- Homebrew, Snap, and Windows installer builds include `cerebrofy[mcp]` by default
