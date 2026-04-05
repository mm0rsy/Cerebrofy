# Implementation Plan: Phase 5 — Distribution, Release Engineering & Cross-Phase Corrections

**Branch**: `005-distribution-release` | **Date**: 2026-04-04 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/005-distribution-release/spec.md`

---

## Summary

Phase 5 packages and distributes Cerebrofy for macOS (Homebrew), Linux (Snap), and Windows
(winget), adds the `cerebrofy mcp` stdio server for AI tool integration, adds the
`cerebrofy parse` diagnostic command, and resolves all cross-phase spec inconsistencies
identified in the blueprint review.

**Track A** (Distribution): Nuitka `--standalone --onefile` builds a self-contained Windows
`.exe`; a PyInstaller/Nuitka tarball powers the Homebrew bottle; `snapcraft` produces the Snap
package. A GitHub Actions matrix pipeline (`fail-fast: false`) builds all platform artifacts
in parallel on each tagged release. The MCP stdio server uses the official `mcp` Python SDK
with a single dispatcher entry in the AI tool config.

**Track B** (Corrections): Nine retroactive spec fixes (FR-019 through FR-027) align
Phases 1–4 spec artifacts with the blueprint before their implementations begin. The
Retroactive Corrections Scope table in `spec.md` is the authoritative edit authorization.

---

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**:
- `click` ≥ 8.1 (existing CLI framework)
- `mcp` ≥ 1.0 (MCP stdio server — optional extra `cerebrofy[mcp]`)
- `nuitka` (Windows .exe build — CI only, not runtime dep)
- `snapcraft` (Snap build — CI only)
- `pyinstaller` or `nuitka` (macOS/Linux binary — CI only)
- `wingetcreate` (winget manifest submission — CI only)
- GitHub Actions (CI/CD pipeline)

**Storage**: No new tables. Existing `cerebrofy.db` schema unchanged.

**Testing**: `pytest` with `tmp_path` (existing). New integration tests for `parse` and `mcp` commands. GitHub Actions CI verifies cross-platform installation on matrix runners.

**Target Platform**:
- macOS (x86_64 + arm64 via Homebrew universal bottle)
- Linux (all distros via Snap `--classic`, Ubuntu 22.04 base)
- Windows 10/11 x64 (winget NSIS installer, Nuitka `.exe`)
- All platforms (pip wheel — Python 3.11+)

**Project Type**: CLI tool + platform distribution packaging + MCP stdio server

**Performance Goals**:
- MCP tool response ≤ same as CLI equivalent (<200ms for hybrid search on 10k-node index)
- `cerebrofy parse` on a 1000-line file: <500ms
- Release pipeline: all 4 channels updated within 30 min of tag push (excluding external reviews)
- Windows cold-start: <10s (v1 accepted limit, documented)

**Constraints**:
- Snap `--classic` confinement: external approval (1–2 weeks). `pip` is the fallback until approved.
- winget review: external human review (1–5 days). CI opens the PR automatically.
- Windows: no Visual C++ Redistributable pre-installation required (Nuitka bundles MSVC runtime).
- `cerebrofy.db` MUST NOT be committed to git (FR-019 enforces via `.gitignore`).
- MCP entry is idempotent: running `cerebrofy init` in N repos produces exactly 1 MCP entry.

**Scale/Scope**: 4 distribution channels, 1 automated release pipeline, 3 new CLI commands/tools, 9 retroactive spec corrections across 4 phases

---

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Design Check (Phase 0 Gate)

| Law | Status | Justification |
|-----|--------|---------------|
| **I. Precedence** — index must exist before spec | ✅ Pass | `cerebrofy parse` is pre-index diagnostic. `cerebrofy mcp` delegates to existing hybrid search which requires the index. No spec is written without an index. |
| **II. Structural Truth** — typed edges, O(1) lookup | ✅ Pass | Phase 5 adds no new edge types. `cerebrofy mcp plan` returns the same graph data as `cerebrofy plan --json`. |
| **III. Semantic Intent** — same SQLite connection for KNN + BFS | ✅ Pass | `cerebrofy mcp` reuses `search/hybrid.py` unchanged. |
| **IV. Autonomic Health** — update < 2s before hard-block | ✅ Pass | FR-020 (hook sentinel correction) only fixes the format. No new enforcement behavior added in Phase 5. |
| **V. Agnosticism** — no language logic outside .scm files | ✅ Pass | `cerebrofy parse` uses existing `parser/engine.py`. No language-specific changes. |
| **Storage** — single DB, atomic build, no DB on init | ✅ Pass | Phase 5 adds no tables. `cerebrofy parse` never opens `cerebrofy.db`. FR-019 (.gitignore) complies with "cerebrofy.db is a local artifact". |
| **Phase Gate** — Phases 1–4 required | ✅ Pass | Phase 5 builds on Phase 4 (AI Bridge) completion. Distribution packaging requires a working binary. |

**Gate Result**: ALL LAWS PASS. Proceeding to Phase 0.

### Post-Design Re-Check (Phase 1 Gate)

| Law | Status | Post-Design Notes |
|-----|--------|-------------------|
| **I. Precedence** | ✅ Pass | `cli-parse.md` contract confirms no `cerebrofy.db` access. `cli-mcp.md` confirms CWD routing requires existing index. |
| **III. Semantic Intent** | ✅ Pass | `cli-mcp.md` confirms same `search/hybrid.py` single connection path. |
| **Storage** | ✅ Pass | `data-model.md` confirms no new tables; `.gitignore` entry (FR-019) enforced automatically. |

**All gates maintained post-design.**

---

## Project Structure

### Documentation (this feature)

```text
specs/005-distribution-release/
├── plan.md              # This file
├── research.md          # Phase 0: MCP SDK, Nuitka, Snap, Homebrew, winget, GitHub Actions
├── data-model.md        # Phase 1: MCP tool schemas, ParseResult, corrected PlanReport/TaskItem
├── quickstart.md        # Phase 1: Installation guides + diagnostic usage
├── contracts/
│   ├── cli-parse.md     # cerebrofy parse command contract (new command + retroactive P1 fix)
│   ├── cli-mcp.md       # cerebrofy mcp command contract (MCP server lifecycle + tools)
│   └── mcp-tools.md     # MCP tool input/output schemas (plan, tasks, specify)
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
src/
└── cerebrofy/
    ├── cli.py                    ← Add 'parse' and 'mcp' to Click command group
    ├── commands/
    │   ├── parse.py              ← cerebrofy parse: diagnostic read-only parser
    │   └── mcp.py                ← cerebrofy mcp: MCP stdio server entry point
    ├── mcp/
    │   └── server.py             ← MCPServer: tool registration, CWD routing, tool dispatch
    └── hooks/
        └── installer.py          ← Update: versioned sentinel format (FR-020 correction)

tests/
├── unit/
│   └── test_parse_command.py     ← Unit tests for parse NDJSON output
└── integration/
    ├── test_parse_command.py     ← Full parse command against tmp_path repos
    └── test_mcp_command.py       ← MCP server tool call simulation

.github/
└── workflows/
    ├── release.yml               ← Multi-platform release pipeline (matrix, fail-fast: false)
    └── ci.yml                    ← Existing CI (extended with parse/mcp tests)

packaging/
├── snap/
│   └── snapcraft.yaml            ← Snap package definition (classic confinement, core22)
├── windows/
│   ├── nuitka_build.bat          ← Nuitka build script for Windows CI runner
│   └── installer.nsi             ← NSIS installer script (adds to %PATH%)
├── macos/
│   └── build_bottle.sh           ← macOS binary build script (PyInstaller or Nuitka)
└── homebrew/
    └── update_formula.sh         ← Script to update cerebrofy/homebrew-cerebrofy tap

pyproject.toml                    ← Add 'mcp' optional extra dependency
```

**Structure Decision**: Single project layout (Option 1). The packaging artifacts live under
`packaging/` at repo root. GitHub Actions workflows in `.github/workflows/`. The `mcp/`
module under `cerebrofy/` follows the established module pattern (Phase 4 added `search/`,
`llm/` similarly). No new top-level project required.

---

## Technical Constraints

- **`mcp` package is an optional extra**: Base `pip install cerebrofy` does NOT install the
  `mcp` package. Only `pip install cerebrofy[mcp]` does. Distribution builds (Homebrew, Snap,
  Windows) always include the `mcp` extra.

- **Nuitka requires MSVC on Windows CI**: The `windows-latest` GitHub Actions runner has
  MSVC build tools pre-installed. No additional setup required.

- **Snap `--classic` approval**: Submit the `--classic` request before v1 release. Until
  approved, the Snap is published in `strict` mode. The `pip install cerebrofy` fallback is
  documented in the Linux quickstart.

- **Homebrew tap vs homebrew-core**: Custom tap `cerebrofy/homebrew-cerebrofy` for v1.
  Migration to `homebrew-core` deferred (requires adoption threshold).

- **`cerebrofy init` MCP idempotency**: The `mcpServers.cerebrofy` key is the stable identifier.
  If it already exists (any value), the existing entry is preserved. No overwrite.

- **Track B corrections are spec-only in Phase 5**: The retroactive spec edits (FR-019
  through FR-027) update Phase 1–4 spec artifacts. The actual implementation fixes happen
  within their respective phases. Phase 5 implementation focuses on Track A (distribution
  + new commands).

---

## Complexity Tracking

> No constitution violations requiring justification. All gates pass.

*(Section intentionally empty — no violations detected)*
