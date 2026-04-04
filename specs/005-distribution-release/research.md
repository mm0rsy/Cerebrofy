# Research: Phase 5 — Distribution, Release Engineering & Cross-Phase Corrections

**Feature**: 005-distribution-release
**Date**: 2026-04-04
**Status**: Complete — all unknowns resolved

---

## 1. MCP Python SDK — Stdio Server Implementation

**Decision**: Use the `mcp` package (PyPI) with `mcp.server.Server` + `mcp.server.stdio.stdio_server`.

**Rationale**: The `mcp` package is the official Anthropic Python SDK for the Model Context
Protocol. It provides a high-level `Server` class with decorator-based tool registration and
async stdio transport. This is the standard implementation path for MCP stdio servers.

**Key API**:
```python
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, CallToolResult

app = Server("cerebrofy")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(name="plan", description="...", inputSchema={
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "top_k": {"type": "integer", "default": 10}
            },
            "required": ["description"]
        }),
        # tasks, specify tools follow same pattern
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    ...

async def run_mcp_server():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())
```

**MCP config entry** (Claude Desktop / dispatcher pattern):
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

The single entry works across all repos because `cerebrofy mcp` reads `os.getcwd()` at
invocation time to determine the active repo root (searches upward for `.cerebrofy/config.yaml`).

**Package version**: `mcp >= 1.0` (pinned in `pyproject.toml` optional extras: `pip install cerebrofy[mcp]`)

**Alternatives considered**:
- `fastmcp` library — provides higher-level abstractions but introduces additional dependency. Rejected: the official `mcp` SDK is sufficient and is the standard.
- Implementing the JSON-RPC 2.0 protocol manually — rejected: unnecessary complexity when the official SDK exists.

---

## 2. Windows Self-Contained Executable — Nuitka

**Decision**: Use Nuitka `--standalone --onefile` to compile `cerebrofy` to a single `.exe` with
all Python dependencies (including `tree_sitter_languages` grammar binaries and `sqlite-vec`)
bundled. Distributed via winget.

**Rationale**: Nuitka compiles Python to C and then to a native binary using the system C
compiler. The `--onefile` flag produces a single `.exe` that self-extracts to a temp directory
on first run. This is the industry-standard approach for distributing Python CLI tools to
Windows users who do not have Python installed.

**Key build command**:
```bash
nuitka \
  --standalone \
  --onefile \
  --output-filename=cerebrofy.exe \
  --include-package=tree_sitter_languages \
  --include-data-dir=src/cerebrofy/queries=cerebrofy/queries \
  --windows-console-mode=attach \
  --windows-company-name=Cerebrofy \
  --windows-product-name=Cerebrofy \
  --windows-file-version=1.0.0.0 \
  src/cerebrofy/__main__.py
```

**sqlite-vec bundling**: `sqlite-vec` ships as a compiled extension (`.dll` on Windows).
Nuitka's `--include-data-files` or `--include-package` handles this. The extension path is
resolved at runtime via the bundled package's `__file__` attribute.

**Cold-start**: The `--onefile` self-extraction adds 2–5 seconds on first cold invocation
(extraction to `%TEMP%`). Subsequent invocations from the same extraction cache are fast.
This is the documented v1 Windows limitation (SC-008).

**Visual C++ Redistributable**: Nuitka links against the MSVC runtime. When using
`--onefile`, the MSVC DLLs can be bundled directly (Nuitka handles this with
`--windows-console-mode=attach` and the correct Python 3.11 Windows build). No external
vcredist install required.

**Alternatives considered**:
- PyInstaller — also produces self-contained executables but has known compatibility issues
  with `tree_sitter_languages` and `sqlite-vec` on Windows due to the ctypes extension loading
  pattern. Nuitka compiles these properly as it handles C extension imports at compile time.
- cx_Freeze — similar to PyInstaller; same extension loading concerns. Rejected.
- Shipping a Python installer alongside Cerebrofy — violates the "no pre-installation" requirement (FR-003).

**CI runner**: `windows-latest` GitHub Actions runner (Windows Server 2022 with MSVC build tools pre-installed).

---

## 3. Linux Snap Packaging — snapcraft.yaml

**Decision**: Use `snapcraft` with `plugin: python`, `confinement: classic`, `base: core22`
(Ubuntu 22.04 LTS base).

**Rationale**: Classic confinement bypasses Snap's AppArmor sandbox, giving Cerebrofy
unrestricted filesystem access — required for indexing arbitrary repository paths (FR-002).
`core22` is the current stable base for new snaps (matching Ubuntu 22.04 LTS).

**Key snapcraft.yaml structure**:
```yaml
name: cerebrofy
base: core22
version: git
summary: AI-ready codebase indexer
description: |
  Cerebrofy indexes your codebase into a local graph + vector database
  and provides AI-grounded planning and specification tools.
grade: stable
confinement: classic

apps:
  cerebrofy:
    command: bin/cerebrofy
    # classic confinement: no plugs needed

parts:
  cerebrofy:
    plugin: python
    source: .
    python-packages:
      - cerebrofy
    build-packages:
      - python3-dev
      - gcc
```

**Snap Store `--classic` approval**: First-time `--classic` requests require Snap Store review
(~1–2 weeks). Until approved, Snap is published in `strict` mode with limited filesystem access
(`home` plug only). The `pip install cerebrofy` fallback covers this gap (per spec edge case).

**Alternatives considered**:
- AppImage — portable Linux format. Not available via a standard package manager (`snap install`
  is the single-command install target). Rejected.
- Flatpak — good coverage but requires Flathub submission. Snap Store has broader CLI tool
  precedent and is pre-installed on Ubuntu. Rejected for v1.
- `.deb` / `.rpm` packages — require separate packaging per distro. Snap covers all distros
  from one package. Rejected.

---

## 4. macOS Homebrew Distribution — Custom Tap

**Decision**: Custom Homebrew tap `cerebrofy/homebrew-cerebrofy` (GitHub repo:
`cerebrofy/homebrew-cerebrofy`). Distribute a pre-built bottle (tarball of the compiled
binary + bundled resources) to avoid Python version dependency issues.

**Rationale**: The official `homebrew-core` tap has strict inclusion requirements. A custom
tap (`brew tap cerebrofy/tap`) is immediately available for v1 without waiting for homebrew-core
approval. Pre-built bottles mean users don't need Python or a compiler installed.

**Key formula structure** (`Formula/cerebrofy.rb`):
```ruby
class Cerebrofy < Formula
  desc "AI-ready codebase indexer with hybrid graph + vector search"
  homepage "https://github.com/cerebrofy/cerebrofy"
  url "https://github.com/cerebrofy/cerebrofy/releases/download/v#{version}/cerebrofy-#{version}-macos-x86_64.tar.gz"
  sha256 "COMPUTED_AT_RELEASE_TIME"
  version "1.0.0"
  
  bottle :unneeded  # pre-built binary distribution

  def install
    bin.install "cerebrofy"
    # Bundle queries directory alongside binary
    (share/"cerebrofy").install "queries"
  end

  test do
    system "#{bin}/cerebrofy", "--version"
  end
end
```

**macOS binary build**: Use `pyinstaller` or Nuitka on `macos-latest` GitHub Actions runner.
Since macOS has stricter binary signing requirements, the approach is a frozen Python app
(PyInstaller) packaged as a tarball. Cerebrofy's `tree_sitter_languages` and `sqlite-vec`
both ship with macOS dylib files that PyInstaller handles correctly.

**Alternative for macOS**: Nuitka also works on macOS but requires the Apple Clang toolchain
(available on `macos-latest` runner). Either PyInstaller or Nuitka is acceptable; the decision
is deferred to implementation. The formula structure is toolchain-agnostic.

**Tap CI automation**: On each tagged release, GitHub Actions:
1. Builds the macOS tarball and computes SHA-256
2. Clones `cerebrofy/homebrew-cerebrofy`
3. Updates `sha256` and `url` fields in `Formula/cerebrofy.rb`
4. Commits and pushes to the tap repo

**Homebrew-core migration**: Deferred until adoption warrants it (per spec Assumptions).

---

## 5. Windows winget Manifest

**Decision**: Standard winget multi-file manifest format (version, installer, locale YAML files)
submitted as a PR to `microsoft/winget-pkgs`.

**Rationale**: The winget manifest format is well-documented. The CI pipeline generates and
submits the PR automatically using the `wingetcreate` CLI tool, which builds the manifest
from a URL and computes the SHA-256 automatically.

**Key manifest files** (under `manifests/c/cerebrofy/cerebrofy/1.0.0/`):
```
cerebrofy.cerebrofy.yaml          ← version manifest
cerebrofy.cerebrofy.installer.yaml ← installer details
cerebrofy.cerebrofy.locale.en-US.yaml ← English locale
```

**Installer manifest key fields**:
```yaml
PackageIdentifier: cerebrofy.cerebrofy
PackageVersion: 1.0.0
Installers:
- Architecture: x64
  InstallerType: exe
  InstallerUrl: https://github.com/cerebrofy/cerebrofy/releases/download/v1.0.0/cerebrofy-setup.exe
  InstallerSha256: <SHA-256>
  InstallerSwitches:
    Silent: /S
    SilentWithProgress: /S
  UpgradeBehavior: install
```

**PATH configuration**: Nuitka `--onefile` output is a single `.exe`. A lightweight NSIS
installer wrapper (`cerebrofy-setup.exe`) installs the exe to `%PROGRAMFILES%\Cerebrofy\`
and adds that path to the system `%PATH%` via the Windows registry. This is the standard
winget installer pattern.

**Automation**: `wingetcreate update cerebrofy.cerebrofy --version X.Y.Z --urls <url> --submit`
creates and submits the PR automatically from GitHub Actions.

**Review time**: Microsoft typically reviews winget PRs within 1–5 business days. The
automated PR submission is the Cerebrofy responsibility; the review is external.

---

## 6. GitHub Actions Multi-Platform CI/CD Pipeline

**Decision**: GitHub Actions with matrix strategy across `macos-latest`, `ubuntu-22.04`,
and `windows-latest` runners. Release pipeline triggered on `v*` tag push.

**Key pipeline structure**:
```yaml
on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    strategy:
      fail-fast: false   # one platform failure does NOT block others
      matrix:
        include:
          - os: macos-latest
            artifact_name: cerebrofy-macos-x86_64.tar.gz
          - os: ubuntu-22.04
            artifact_name: cerebrofy-linux-amd64.snap
          - os: windows-latest
            artifact_name: cerebrofy-windows-x64-setup.exe
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - name: Build artifact
        run: ...
      - name: Compute SHA-256
        run: sha256sum ${{ matrix.artifact_name }} > ${{ matrix.artifact_name }}.sha256
      - name: Upload to release
        uses: softprops/action-gh-release@v2
        with:
          files: ${{ matrix.artifact_name }}*

  publish-pypi:
    runs-on: ubuntu-22.04
    steps:
      - uses: actions/checkout@v4
      - name: Build wheel
        run: pip install build && python -m build
      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1

  update-homebrew:
    needs: build
    runs-on: ubuntu-22.04
    steps:
      - name: Update Homebrew tap
        ...

  submit-winget:
    needs: build
    runs-on: windows-latest
    steps:
      - name: Submit winget PR
        run: wingetcreate update cerebrofy.cerebrofy ...
```

**`fail-fast: false`**: Ensures a single platform build failure doesn't cancel all other
platform builds — required by FR-005 acceptance scenario 4.

---

## 7. `cerebrofy parse` Command — Diagnostic Read-Only Parser

**Decision**: New Click command `parse` in `commands/parse.py`. Accepts a file or directory
path. Runs `parser/engine.py` directly. Outputs Neurons as NDJSON (one JSON object per line).
Reads `config.yaml` for language extensions and ignore rules. Does NOT open `cerebrofy.db`.

**Key output format** (NDJSON):
```json
{"file": "src/auth/login.py", "name": "login_user", "kind": "function", "line_start": 42, "line_end": 58, "signature": "def login_user(username: str, password: str) -> Optional[User]", "lobe": "auth"}
{"file": "src/auth/login.py", "name": "logout_user", "kind": "function", "line_start": 60, "line_end": 71, "signature": "def logout_user(session_id: str) -> None", "lobe": "auth"}
```

**Error handling**:
- `cerebrofy parse` without prior `cerebrofy init`: exit 1, message: `"No Cerebrofy config found. Run 'cerebrofy init' first."`
- File not found: exit 1, message: `"Path not found: <path>"`
- File excluded by ignore rules: print `"<path>: excluded by ignore rules"`, exit 0
- Syntax error in file: print warning to stderr, continue with successfully extracted Neurons

**Alternatives considered**:
- Using the existing `cerebrofy build` dry-run mode — rejected: adds complexity to the build
  pipeline. A dedicated command is cleaner and aligns with the diagnostic intent.
- JSON array output (`[{...}]`) — rejected: NDJSON is streamable and works for large files
  without buffering the entire output.

---

## 8. MCP Dispatcher Pattern — CWD Routing

**Decision**: The registered MCP command is `cerebrofy mcp` with no arguments. When invoked,
`cerebrofy mcp` calls `find_repo_root()` — the same upward search for `.cerebrofy/config.yaml`
used by all other commands. This resolves the active repo context from the AI tool's CWD.

**Rationale**: AI tools set the working directory to the workspace root when invoking MCP
servers. `cerebrofy mcp` reads `os.getcwd()` at invocation time and walks up the directory
tree to find `.cerebrofy/config.yaml`. This means the single MCP entry automatically serves
all repos.

**MCP config JSON written by `cerebrofy init`**:
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

The key `"cerebrofy"` is stable across all repos. If the key already exists, `cerebrofy init`
does NOT overwrite it — idempotency requirement (FR-011, SC-003).

**No-index error**: When `find_repo_root()` fails or `cerebrofy.db` is absent, all three MCP
tools return a structured error:
```json
{
  "content": [{"type": "text", "text": "No Cerebrofy index found. Run 'cerebrofy build' first."}],
  "isError": true
}
```

---

## 9. Hook Sentinel Format Unification (FR-020)

**Decision**: Use the `# BEGIN cerebrofy` / `# END cerebrofy` sentinel format with
`# cerebrofy-hook-version: N` marker, as documented in CLAUDE.md. The `cli-init.md` spec
must be updated to match.

**Correct hook script** (installed by Phase 1 `cerebrofy init`):
```bash
# BEGIN cerebrofy
# cerebrofy-hook-version: 1
cerebrofy validate --hook pre-push
# END cerebrofy
```

**Phase 3 upgrade** detects `# cerebrofy-hook-version: 1` within the `# BEGIN cerebrofy` /
`# END cerebrofy` block and replaces the entire block:
```bash
# BEGIN cerebrofy
# cerebrofy-hook-version: 2
if ! cerebrofy validate --hook pre-push; then
    echo "Cerebrofy: Structural drift detected. Run 'cerebrofy update' to sync."
    exit 1
fi
# END cerebrofy
```

The `# cerebrofy-hook-start` / `# cerebrofy-hook-end` markers in the existing `cli-init.md`
spec are incorrect and MUST be replaced. This is authorized by FR-020 / Retroactive Corrections
Scope entry.

---

## 10. pyproject.toml Optional Extras for Phase 5

**Decision**: Add `mcp` as an optional dependency group:
```toml
[project.optional-dependencies]
mcp = ["mcp>=1.0"]
dev = [...existing...]
```

Installation for MCP use: `pip install cerebrofy[mcp]`

**Rationale**: Not all Cerebrofy users need the MCP server. Making it optional keeps the
base install lightweight. The Homebrew, Snap, and Windows installer builds include the MCP
dependency by default (for end-users), while the pip package keeps it optional.

**Distribution builds** use: `pip install cerebrofy[mcp]` before compiling/bundling.

---

## Summary of Key Decisions

| Topic | Decision | Rationale |
|-------|----------|-----------|
| MCP SDK | `mcp` Python package, `mcp.server.Server` + stdio | Official SDK, standard pattern |
| Windows binary | Nuitka `--standalone --onefile` + NSIS wrapper | Better C-extension support than PyInstaller |
| Linux package | Snap with `classic` confinement, `core22` base | Single package, all distros, unrestricted FS |
| macOS package | Homebrew custom tap, pre-built bottle/tarball | Immediate availability, no Python required |
| winget | Multi-file manifest, `wingetcreate` automation | Standard Windows package manager pattern |
| CI/CD | GitHub Actions matrix, `fail-fast: false` | Parallel builds, isolated failures |
| MCP dispatcher | Single entry, CWD routing at invocation time | Spec requirement SC-003 |
| Hook sentinels | `# BEGIN cerebrofy` / `# cerebrofy-hook-version: N` | Aligns CLAUDE.md + spec (retroactive fix) |
| `cerebrofy parse` | New Click command, NDJSON output, read-only | Clean diagnostic, no DB required |
| MCP extras | Optional `cerebrofy[mcp]` pip install | Lightweight base, full-featured bundles |
