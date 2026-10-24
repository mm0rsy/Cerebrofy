# Installation

Cerebrofy is distributed as a Python package on PyPI and can be installed with `uv`, `pip`, or `pipx`. You can also install from source.

## Recommended: `uv tool install`

```bash
# Base install — includes local embeddings (BAAI/bge-small-en-v1.5, offline)
uv tool install cerebrofy

# With MCP server support (Claude Desktop, Cursor, VS Code, etc.)
uv tool install "cerebrofy[mcp]"
```

> **Note:** Embeddings are bundled in the base install via `fastembed`. No extra is required for `cerebrofy build` or `cerebrofy update`. The only optional extra is `[mcp]`, which pulls in the `mcp` package needed to run `cerebrofy mcp`.

## Alternative installers

```bash
pip install cerebrofy
pipx install cerebrofy

# With MCP
pip install "cerebrofy[mcp]"
pipx install "cerebrofy[mcp]"
```

## From source

```bash
git clone https://github.com/mm0rsy/Cerebrofy
cd cerebrofy
uv sync --group dev
```

Run tests:

```bash
# Unit + integration tests (no MCP)
uv run pytest tests/unit/ tests/integration/test_update_command.py \
  tests/integration/test_validate_command.py tests/integration/test_migrate_command.py

# Full suite including MCP integration tests
uv sync --extra mcp --group dev
uv run pytest
```

## Platform Support

Cerebrofy runs on **Linux**, **macOS**, and **Windows**. All commands (`init`, `build`, `update`, `validate`, `viz`, `mcp`) behave identically across platforms with one prerequisite difference:

| Platform | Prerequisites | Notes |
|---|---|---|
| Linux / macOS | Python 3.11+, Git | No extra setup |
| Windows | Python 3.11+, **[Git for Windows](https://git-scm.com/download/win)** | Required for git hook execution (MSYS bash) |

> **Windows users:** Install [Git for Windows](https://git-scm.com/download/win) before running `cerebrofy init`. Git for Windows bundles MSYS bash, which is what runs the installed git hooks. Without it, `cerebrofy init` succeeds but the pre-commit / pre-push / post-merge hooks will not fire.

## Next Step

After installing, proceed to [Quick Start](./quickstart.md) to initialize your first repository.