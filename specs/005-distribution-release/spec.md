# Feature Specification: Phase 5 — Distribution, Release Engineering & Cross-Phase Corrections

**Feature Branch**: `005-distribution-release`
**Created**: 2026-04-04
**Status**: Draft
**Input**: Based on specs/BLUEPRINT_REVIEW.md — Phase 5 covering Distribution and Release Engineering (blueprint Section XI + DIST GAP 1–10) and all cross-phase inconsistencies identified in the blueprint review.

---

## Overview

Phase 5 makes Cerebrofy installable by anyone on any platform and ensures the release process
is fully automated. It also resolves all specification inconsistencies and omissions identified
in the blueprint review that were not addressed in Phases 1–4.

Phase 5 has two tracks:

**Track A — Distribution & Release**: Cerebrofy ships as a native package on macOS (Homebrew),
Linux (Snap), and Windows (winget), plus a universal Python package (pip). Every tagged release
triggers an automated CI/CD pipeline that builds all platform artifacts and publishes them
without manual intervention. The MCP server integration is fully specified so AI tools can
invoke Cerebrofy natively.

**Track B — Cross-Phase Corrections**: Specification gaps and inconsistencies identified in the
blueprint review are formally corrected across Phases 1–4 before implementation of those phases
begins. These corrections change existing spec artifacts, not new runtime behavior.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Single-Command Installation on macOS (Priority: P1)

A macOS developer discovers Cerebrofy and installs it in under 30 seconds using Homebrew.
The installation is self-contained: all required components are bundled or downloaded
automatically. After installation, `cerebrofy` is immediately available on their `PATH`
with no manual setup.

**Why this priority**: macOS is the primary development platform for a large share of the
target audience. Homebrew is the de facto standard for developer CLI tools on macOS. Without
a Homebrew formula, adoption requires manual installation which significantly reduces uptake.

**Independent Test**: On a clean macOS machine with Homebrew installed:
1. `brew tap cerebrofy/tap && brew install cerebrofy`
2. `cerebrofy --help` succeeds immediately without PATH configuration
3. `cerebrofy init` runs in a test repo without error
4. `brew upgrade cerebrofy` after a new release delivers the updated version

**Acceptance Scenarios**:

1. **Given** a macOS developer with Homebrew installed, **When** they run
   `brew tap cerebrofy/tap && brew install cerebrofy`, **Then** `cerebrofy` is available on
   their `PATH` within 60 seconds (excluding network download time).

2. **Given** a new Cerebrofy release is published, **When** the developer runs
   `brew upgrade cerebrofy`, **Then** the latest version is installed and the prior version
   is replaced automatically.

3. **Given** the developer installs Cerebrofy via Homebrew, **When** they run
   `cerebrofy init` in any project, **Then** the command succeeds without the developer
   installing any additional tools or configuring environment variables.

4. **Given** a new minor release is tagged, **When** the CI/CD pipeline runs,
   **Then** the updated Homebrew formula is available for upgrade within 30 minutes of release.

---

### User Story 2 — Single-Command Installation on Linux (Priority: P2)

A Linux developer installs Cerebrofy via Snap — a universal Linux package format available
on Ubuntu, Fedora, Arch, and others. The installation grants Cerebrofy unrestricted filesystem
access (necessary for indexing arbitrary repositories) without requiring the developer to trust
a third-party repository or manually manage binary permissions.

**Why this priority**: Snap provides coverage across all major Linux distributions from a
single package. Linux is a critical platform for CI/CD environments where Cerebrofy's offline
`plan` and `tasks` commands are especially valuable.

**Independent Test**: On a clean Ubuntu 22.04 machine:
1. `snap install cerebrofy --classic`
2. `cerebrofy --help` succeeds without PATH configuration
3. `cerebrofy init && cerebrofy build` completes in a test repository
4. Confirm no system-wide installation of any additional runtime was required

**Acceptance Scenarios**:

1. **Given** a Linux developer with Snap installed, **When** they run
   `snap install cerebrofy --classic`, **Then** `cerebrofy` is available on their `PATH`
   without additional setup.

2. **Given** the Snap is installed with classic confinement, **When** the developer runs
   any Cerebrofy command, **Then** it can read and write to any filesystem path the developer
   has access to.

3. **Given** a new Cerebrofy release is published, **When** the Snap Store propagates the
   update (within 24 hours), **Then** installed Snap packages are updated automatically.

4. **Given** Cerebrofy is not yet available via Snap (during Snap Store approval period),
   **When** a developer needs to install it on Linux, **Then** `pip install cerebrofy`
   provides a complete, functional installation with identical behavior.

---

### User Story 3 — Single-Command Installation on Windows (Priority: P3)

A Windows developer installs Cerebrofy via winget with no separate downloads, no manual PATH
configuration, and no compiler or runtime prerequisites. The installer bundles everything
Cerebrofy needs to run.

**Why this priority**: Windows installation is the most complex platform due to bundling
requirements. Without a fully self-contained installer, Windows users face a frustrating
multi-step manual setup.

**Independent Test**: On a clean Windows 10 machine with no developer tools pre-installed:
1. `winget install cerebrofy`
2. Open a new terminal — `cerebrofy --help` succeeds without PATH configuration
3. `cerebrofy init` runs without error
4. The pre-push git hook successfully invokes `cerebrofy validate` within the accepted timeout

**Acceptance Scenarios**:

1. **Given** a Windows 10/11 developer, **When** they run `winget install cerebrofy`,
   **Then** `cerebrofy` is available on their `%PATH%` in a new terminal session without
   any additional installation steps.

2. **Given** no additional runtimes on the machine, **When** the developer installs and runs
   Cerebrofy, **Then** all commands work correctly including database operations and language
   parsing.

3. **Given** the pre-push git hook is active on Windows, **When** the developer pushes code
   with structural drift, **Then** the hook correctly blocks the push. The v1 cold-start
   limitation (2–5 seconds on Windows) is documented for users.

4. **Given** a new Cerebrofy release is tagged, **When** the winget manifest is approved
   (typically 1–5 business days), **Then** developers can upgrade with `winget upgrade cerebrofy`.

---

### User Story 4 — Automated Release Pipeline (Priority: P4)

A Cerebrofy maintainer publishes a new version by creating a git tag. Everything else —
building platform artifacts, computing integrity hashes, publishing to all channels, and
opening the winget pull request — happens automatically.

**Why this priority**: Manual releases are error-prone and unsustainable across four
simultaneous distribution channels. Automation is required to maintain release quality.

**Independent Test**:
1. Push a git tag `v1.0.0` to the main branch
2. Confirm CI/CD pipeline triggers automatically within 2 minutes
3. Confirm all four artifact builds complete (macOS, Linux, Windows, pip wheel)
4. Confirm PyPI package is published, Homebrew formula updated, winget PR opened, Snap submitted
5. Confirm SHA-256 hashes attached to the GitHub Release

**Acceptance Scenarios**:

1. **Given** a maintainer pushes a git tag, **When** the CI/CD pipeline runs,
   **Then** all four distribution artifacts are built in parallel on their respective platforms.

2. **Given** the build pipeline completes successfully, **When** artifacts are published,
   **Then** SHA-256 hashes for all binaries are attached to the GitHub Release.

3. **Given** a new release is published, **When** a `pip install cerebrofy` user runs
   `pip install --upgrade cerebrofy`, **Then** the new version is available immediately.

4. **Given** a build job fails for one platform, **When** the pipeline completes,
   **Then** the failure is reported clearly and the remaining platform artifacts continue
   to be built and published — a single platform failure does not block the others.

5. **Given** a release is tagged, **When** CI updates the Homebrew tap,
   **Then** `brew upgrade cerebrofy` delivers the new version without maintainer intervention.

---

### User Story 5 — Multi-Repository MCP Registration (Priority: P5)

A developer uses Cerebrofy across 10 different repositories. After running `cerebrofy init`
in each, they find exactly one entry in their AI tool's MCP server configuration. When the
AI tool invokes Cerebrofy, it automatically uses the correct repository based on the current
working directory.

**Why this priority**: Without a dispatcher pattern, each `cerebrofy init` call would add a
new MCP entry, bloating the AI tool configuration and causing routing confusion.

**Independent Test**:
1. Run `cerebrofy init` in three different repositories
2. Open the AI tool MCP config — confirm exactly one `cerebrofy` entry exists
3. Invoke Cerebrofy via the AI tool from repo A — confirm it uses repo A's index
4. Invoke Cerebrofy via the AI tool from repo B — confirm it uses repo B's index
5. Run `cerebrofy init` in repo A again — confirm still exactly one entry

**Acceptance Scenarios**:

1. **Given** `cerebrofy init` has been run in repo A and repo B, **When** the developer
   inspects their AI tool's MCP config file, **Then** exactly one Cerebrofy entry exists.

2. **Given** a single MCP dispatcher entry, **When** the AI tool invokes Cerebrofy from
   within repo A, **Then** Cerebrofy uses repo A's index and configuration.

3. **Given** a single MCP dispatcher entry, **When** the AI tool invokes Cerebrofy from
   within repo B, **Then** Cerebrofy uses repo B's index and configuration, switching
   context automatically.

4. **Given** an existing Cerebrofy MCP entry, **When** `cerebrofy init` is run in any
   additional repository, **Then** the existing MCP entry is not modified or duplicated.

5. **Given** `cerebrofy init --global` is run, **When** the developer inspects the config,
   **Then** the entry is written to the generic MCP standard path
   (`~/.config/mcp/servers.json`), compatible with any MCP-compliant AI tool.

---

### User Story 6 — AI-Native Cerebrofy Commands via MCP (Priority: P6)

An AI coding assistant can call `cerebrofy plan`, `cerebrofy tasks`, and `cerebrofy specify`
as structured tools — receiving structured results directly without the developer leaving
their IDE or copy-pasting terminal output.

**Why this priority**: The MCP integration is the primary delivery mechanism for Phase 4
AI Bridge capabilities in day-to-day use. Without it, developers must manually run commands
and share output, reducing the value of Phase 4.

**Independent Test**:
1. With Cerebrofy registered as MCP server, open an AI tool in an indexed repo
2. Ask the AI: "What code would I need to change to add OAuth2 support?"
3. Confirm the AI invoked the `plan` MCP tool with the description as input
4. Confirm the response references actual function names and files from the codebase
5. Ask for a spec — confirm the `specify` tool was invoked and a file was written

**Acceptance Scenarios**:

1. **Given** Cerebrofy is registered as an MCP server, **When** an AI tool is opened in
   an indexed repository, **Then** the AI has access to `plan`, `tasks`, and `specify`
   as callable tools with defined input/output schemas.

2. **Given** the AI tool calls the `plan` tool with a feature description, **When** Cerebrofy
   returns the response, **Then** the response contains: matched Neurons with similarity
   scores, structural neighbors, affected modules, and scope estimate.

3. **Given** the AI tool calls the `specify` tool, **When** Cerebrofy processes the request,
   **Then** a codebase-grounded spec file is written and the AI receives the output file
   path and spec content in the tool response.

4. **Given** no index exists in the current directory, **When** the AI tool calls any
   Cerebrofy MCP tool, **Then** the error response directs the developer to `cerebrofy build`.

---

### User Story 7 — Developer Parse Diagnostics Command (Priority: P7)

A developer verifies that Cerebrofy correctly parses their source files before running a
full build. They run `cerebrofy parse` on a specific file or directory and see the exact
Neurons that would be extracted — without creating or modifying any index.

**Why this priority**: Without a diagnostic command, developers cannot verify parser behavior
without running a full `cerebrofy build`. The parse command shortens the feedback loop when
adding new language support or debugging unexpected extraction results.

**Independent Test**:
1. `cerebrofy parse src/auth/login.py` — confirm JSON Neurons matching known functions
2. `cerebrofy parse src/` — confirm Neurons from all tracked files in the directory
3. Confirm no `cerebrofy.db` was created or modified
4. `cerebrofy parse nonexistent.py` — confirm exit 1 with clear error

**Acceptance Scenarios**:

1. **Given** a tracked source file, **When** the developer runs `cerebrofy parse <file>`,
   **Then** the command prints the Neurons that would be extracted to stdout as
   newline-delimited JSON objects. Exit 0.

2. **Given** a directory path, **When** the developer runs `cerebrofy parse <dir>`,
   **Then** the command processes all tracked files in the directory recursively,
   respecting `.cerebrofy-ignore` and `.gitignore`.

3. **Given** a file excluded by ignore rules, **When** the developer runs `cerebrofy parse <file>`,
   **Then** the command prints that the file is excluded and exits 0 with no Neuron output.

4. **Given** the developer runs `cerebrofy parse` on any path, **When** the command
   completes, **Then** no index file is created or modified — strictly read-only.

5. **Given** a file with a syntax error, **When** the developer runs `cerebrofy parse <file>`,
   **Then** a warning identifies the error and any successfully extracted Neurons are printed.

---

### User Story 8 — Accidental Index Commit Prevention (Priority: P8)

A developer running `git add .` in a Cerebrofy-initialized repository never accidentally
stages the local index database for commit. The `.gitignore` is configured automatically
during initialization.

**Why this priority**: Committing `cerebrofy.db` would bloat the repository, cause merge
conflicts, and break the multi-developer synchronization model. This is a data-integrity
requirement that must be automatic — not reliant on developer discipline.

**Independent Test**:
1. `cerebrofy init` in a new repository
2. `cerebrofy build` to create the index
3. `git add .` — confirm `cerebrofy.db` does NOT appear in `git status`
4. Inspect `.gitignore` — confirm `.cerebrofy/db/` is present
5. `cerebrofy init --force` — confirm `.gitignore` remains correct, no duplicate entry

**Acceptance Scenarios**:

1. **Given** a developer runs `cerebrofy init`, **When** they run `git add .`,
   **Then** `.cerebrofy/db/cerebrofy.db` does not appear in staged files.

2. **Given** `.gitignore` already exists, **When** `cerebrofy init` runs,
   **Then** `.cerebrofy/db/` is added without overwriting existing contents.

3. **Given** `.cerebrofy/db/` is already in `.gitignore`, **When** `cerebrofy init`
   runs again, **Then** no duplicate entry is added.

---

### User Story 9 — Consistent Hook Upgrade Behavior (Priority: P9)

A developer who installed Cerebrofy's pre-push hook during Phase 1 (warn-only) and later
upgraded to Phase 3 (hard-block) sees exactly the behavior specified: the hook upgrade is
detected reliably and applied cleanly, with no duplicate blocks or stale warn-only behavior.

**Why this priority**: An undetected or double-applied hook upgrade is a silent correctness
failure. Developers may believe they are protected when they are not, or face broken pushes
from duplicate hook invocations.

**Independent Test**:
1. `cerebrofy init` — confirm pre-push hook contains `cerebrofy-hook-version: 1`
2. Phase 3 hook upgrade — confirm hook now contains `cerebrofy-hook-version: 2`
3. Push with structural drift — confirm exit 1 (hard block)
4. Upgrade again — confirm no duplicate blocks inserted

**Acceptance Scenarios**:

1. **Given** a Phase 1 warn-only hook is installed, **When** Phase 3 upgrades it,
   **Then** the hook script is modified in-place — no new block appended alongside the old one.

2. **Given** a Phase 1 hook (version 1), **When** the developer pushes with structural
   drift after the Phase 3 upgrade, **Then** the push is blocked (exit 1).

3. **Given** a Phase 3 hard-block hook (version 2) is already installed, **When** the
   upgrade function runs again, **Then** no changes are made (idempotent).

4. **Given** a pre-existing non-Cerebrofy hook file, **When** `cerebrofy init` runs,
   **Then** Cerebrofy appends its versioned block within the `# BEGIN cerebrofy` /
   `# END cerebrofy` sentinels without disturbing pre-existing hook content.

---

### Edge Cases

- What happens when the Snap Store `--classic` confinement approval is still pending at release time? → `pip install cerebrofy` is the documented Linux fallback. The Snap is available in strict mode with limited permissions until `--classic` is approved (estimated 1–2 weeks for first submission).
- What happens when the winget pull request review takes longer than expected? → Release notes document the delay; users can install via pip. The CI/CD pipeline opens the PR automatically on each release.
- What happens when a developer installs Cerebrofy via both Homebrew and pip? → Each installation is independent. The `PATH` order determines which is invoked. `cerebrofy init` detects the version mismatch, prints all installation paths, and provides remediation steps.
- What happens when `cerebrofy parse` is run without `cerebrofy init` having been run first? → Exit 1 with a message directing the user to `cerebrofy init` first — `config.yaml` is required for the extension list and ignore rules.
- What happens when `cerebrofy init` runs on a repository where `.gitignore` is a tracked committed file? → The `.gitignore` modification is applied to the working tree. The developer must commit the change.
- What happens when the CI/CD pipeline is triggered but one platform's build runner is unavailable? → Other platform builds continue. The failing job is retried once. A second failure produces a clear error on the GitHub Release without blocking other channels.
- What happens when `cerebrofy mcp` is invoked directly from the terminal? → The command starts the MCP stdio server and waits for MCP protocol input. It is safe to invoke from terminal but designed for AI tool invocation.
- What happens when `cerebrofy init --global` is run on a machine with no existing `~/.config/mcp/` directory? → The directory and `servers.json` file are created.
- What happens when two Cerebrofy versions are detected at init time? → `cerebrofy init` warns, prints all installation paths and versions, provides specific remediation steps, and does NOT silently overwrite an existing MCP entry with a path from the wrong installation.

---

## Requirements *(mandatory)*

### Functional Requirements

**Track A — Distribution**

- **FR-001**: Cerebrofy MUST be installable on macOS via `brew tap cerebrofy/tap && brew install cerebrofy` with `cerebrofy` available on `PATH` immediately. No Python, compiler, or manual configuration required.

- **FR-002**: Cerebrofy MUST be installable on Linux via `snap install cerebrofy --classic` with `cerebrofy` available on `PATH` immediately. All required runtime components MUST be bundled in the Snap package.

- **FR-003**: Cerebrofy MUST be installable on Windows 10/11 via `winget install cerebrofy` with `cerebrofy` available on `%PATH%` in new terminal sessions without rebooting or manual PATH editing. The installer MUST bundle all native runtime components (database vector extension, language grammar binaries, runtime). No Visual C++ Redistributable pre-installation required — the installer handles it silently if needed.

- **FR-004**: Cerebrofy MUST be installable via `pip install cerebrofy` as a universal fallback on all platforms. The pip package MUST be published to PyPI on every tagged release.

- **FR-005**: A tagged release MUST trigger an automated CI/CD pipeline that builds macOS, Linux, and Windows artifacts in parallel, computes SHA-256 hashes of all binaries, and attaches them to the GitHub Release.

- **FR-006**: The CI/CD pipeline MUST automatically update the Homebrew formula in the custom tap (`cerebrofy/homebrew-cerebrofy`) with the new version and artifact hash. `brew upgrade cerebrofy` MUST deliver the new version without maintainer action beyond tagging.

- **FR-007**: The CI/CD pipeline MUST automatically submit the Snap package to the Snap Store. Snap users MUST receive the update within 24 hours of submission (subject to Snap Store propagation).

- **FR-008**: The CI/CD pipeline MUST automatically open a pull request against the winget community manifest repository with the updated manifest, including correct SHA-256 hashes for the Windows installer.

- **FR-009**: The Windows installer MUST add `cerebrofy` to `%PATH%` automatically via the package manager's standard mechanism — no manual PATH editing required.

- **FR-010**: The Windows installation documentation MUST include a known-limitation notice: the initial cold start of `cerebrofy validate` on Windows may take 2–5 seconds. This is an accepted v1 limitation targeting optimization in a future release.

**Track A — MCP Integration**

- **FR-011**: `cerebrofy init` MUST write an MCP server entry that uses a dispatcher pattern: a single entry that reads the current working directory at invocation time, routing to the correct repository's index and configuration. Running `cerebrofy init` in multiple repositories MUST result in exactly one MCP entry in the AI tool config.

- **FR-012**: `cerebrofy init` MUST check MCP config paths in this exact priority order and write to the first writable path found:
  1. Claude Desktop (macOS): `~/Library/Application Support/Claude/claude_desktop_config.json`
  2. Claude Desktop (Windows): `%APPDATA%\Claude\claude_desktop_config.json`
  3. Cursor (macOS/Linux): `~/.cursor/mcp.json`
  4. Cursor (Windows): `%APPDATA%\Cursor\mcp.json`
  5. Opencode: `~/.config/opencode/mcp.json`
  6. Generic MCP standard (Windsurf, others): `~/.config/mcp/servers.json`
  7. Fallback: create `~/.config/mcp/servers.json` and print a note listing which tools will auto-detect it

- **FR-013**: `cerebrofy init --global` MUST write the MCP entry to `~/.config/mcp/servers.json` regardless of which tool-specific paths are present. The dispatcher pattern applies to `--global` as well.

- **FR-014**: `cerebrofy mcp` MUST be a valid sub-command that starts an MCP stdio server. The server MUST expose at minimum three tools: `plan` (maps to `cerebrofy plan`), `tasks` (maps to `cerebrofy tasks`), and `specify` (maps to `cerebrofy specify`). Each tool MUST accept `description` (string, required) and `top_k` (integer, optional) as input parameters.

- **FR-015**: When an AI tool invokes the `plan` MCP tool, the response MUST be the same structured data as `cerebrofy plan --json` output: matched Neurons, blast radius, affected lobes, re-index scope, and `schema_version: 1`.

- **FR-016**: When an AI tool invokes the `specify` MCP tool, Cerebrofy MUST write the spec file to `docs/cerebrofy/specs/` and return the output file path and spec content in the tool response.

- **FR-017**: When no Cerebrofy index exists in the current directory, the MCP server MUST return a structured error directing the developer to run `cerebrofy build` — no silent failure or empty response.

- **FR-018**: If multiple Cerebrofy installations are detected when `cerebrofy init` runs, `cerebrofy init` MUST warn the developer, print all detected installation paths and versions, and provide specific remediation steps. It MUST NOT silently overwrite an existing MCP entry.

**Track B — Cross-Phase Corrections**

- **FR-019**: `cerebrofy init` MUST add `.cerebrofy/db/` to the repository's `.gitignore`. If `.gitignore` does not exist, it MUST be created. If `.cerebrofy/db/` is already present, no duplicate entry is added. This prevents `git add .` from staging `cerebrofy.db`.

- **FR-020**: The pre-push git hook installed by `cerebrofy init` MUST use the following versioned sentinel format:
  ```
  # BEGIN cerebrofy
  # cerebrofy-hook-version: 1
  cerebrofy validate --hook pre-push
  # END cerebrofy
  ```
  Phase 3's upgrade function MUST detect the `# cerebrofy-hook-version: N` marker within the `# BEGIN cerebrofy` / `# END cerebrofy` block to determine current hook version before upgrading. Idempotency: if the version marker already matches the target version, no changes are made.

- **FR-021**: `cerebrofy validate` output when the index is current and no drift is detected MUST be exactly: `"Cerebrofy: Index is clean."`. This message MUST be consistent across all spec documents, all contracts, all quickstart guides, and all integration test assertions across Phases 3 and 4.

- **FR-022**: `cerebrofy tasks` MUST compute `blast_count` per task item as the count of BFS neighbors directly reachable from that specific matched Neuron — not the total blast radius count across all matched Neurons. Each task item independently reflects the structural risk of changing that specific Neuron.

- **FR-023**: The `cerebrofy plan --json` output schema MUST include `schema_version: 1` as a top-level field. This field MUST be present in the Phase 4 `spec.md` FR-007, all `cli-plan.md` contract examples, and all `data-model.md` PlanReport schema definitions.

- **FR-024**: `cerebrofy parse <path>` MUST be a valid command accepting a file path or directory path. The command MUST run the Phase 1 parser on the specified path(s), print extracted Neurons to stdout as newline-delimited JSON objects, and exit 0. The command MUST be strictly read-only: no index file is created or modified.

- **FR-025**: `cerebrofy parse` MUST respect `.cerebrofy-ignore` and `.gitignore` rules. If the specified path is excluded, the command MUST print a message indicating the path is excluded and exit 0 with no Neuron output.

- **FR-026**: The `cerebrofy specify` pre-flight embed_model mismatch check requires reading `embed_model` from the database meta before embedding the description. The implementation MUST use a dedicated pre-flight connection for the meta read (opened and closed during pre-flight), separate from the main read-only connection used for hybrid search. This two-connection pattern MUST be documented in `contracts/cli-specify.md` execution flow steps 1–4.

- **FR-027**: `cerebrofy plan` and `cerebrofy tasks` MUST silently ignore `llm_endpoint`, `llm_model`, `llm_timeout`, and `system_prompt_template` configuration keys even if present in `config.yaml`. These commands are strictly offline — the presence of LLM config MUST NOT trigger any network call. This invariant MUST be explicitly stated in `contracts/cli-plan.md` and `contracts/cli-tasks.md`.

### Key Entities

- **MCP Dispatcher Entry**: A single MCP server configuration entry pointing to the `cerebrofy mcp` command. Reads the caller's working directory at invocation time to route to the correct repository. One entry per machine, shared across all repositories.

- **MCP Tool**: A structured callable exposed by `cerebrofy mcp`: `plan`, `tasks`, or `specify`. Each maps to the corresponding CLI command and returns the same structured data as the command's JSON output.

- **Platform Artifact**: A platform-specific distributable: Homebrew bottle (macOS), Snap package (Linux), winget-compatible installer (Windows), or Python wheel (pip). Each is self-contained with no external dependencies required on the target machine.

- **Release Manifest**: SHA-256 hashes and version metadata for all platform artifacts in a given release. Attached to the GitHub Release and referenced by Homebrew formulas and winget manifests for integrity verification.

- **Hook Version Block**: The versioned git hook block delimited by `# BEGIN cerebrofy` / `# END cerebrofy` markers, containing a `# cerebrofy-hook-version: N` tag. The version number enables Phase 3 to detect and upgrade from warn-only (v1) to hard-block (v2) without replacing the entire hook file.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer on macOS, Linux, or Windows can install Cerebrofy and run `cerebrofy init` successfully in under 2 minutes on a machine with standard broadband, with no steps beyond a single package manager command.

- **SC-002**: After a tagged release, all four distribution channels (Homebrew, Snap submission, winget PR, PyPI) are updated within 30 minutes of the tag being pushed — excluding winget human review and Snap Store propagation time, which are outside Cerebrofy's control.

- **SC-003**: Running `cerebrofy init` in 10 different repositories results in exactly 1 MCP entry in the AI tool configuration file — verified on macOS, Linux, and Windows.

- **SC-004**: An AI tool can invoke `cerebrofy plan` via MCP and receive a structured response within the same latency envelope as `cerebrofy plan --json` from the terminal (under 200ms for hybrid search on a 10,000-node index).

- **SC-005**: After `cerebrofy init`, running `git add .` does not stage `cerebrofy.db` or any file under `.cerebrofy/db/` — verified across macOS, Linux, Windows, and across Git versions 2.33+.

- **SC-006**: The hook upgrade from Phase 1 warn-only (version 1) to Phase 3 hard-block (version 2) is applied correctly in 100% of test cases: no duplicate blocks, no regression to warn-only after upgrade, no modification of non-Cerebrofy hook content.

- **SC-007**: `cerebrofy tasks` blast_count per task item equals the direct BFS neighbor count for that specific Neuron — verified against a known test index where per-Neuron blast counts are precomputed and intentionally differ from each other.

- **SC-008**: The Windows cold-start for `cerebrofy validate` completes within 10 seconds in 100% of test runs on Windows 10/11 (v1 accepted limit). The limitation is documented in the Windows installation guide.

---

## Assumptions

- Phases 1–4 are implemented from their finalized (corrected) specs before Phase 5 distribution packaging begins. The packaging phase requires a working, tested binary.
- The Snap Store `--classic` confinement request is submitted before the first public release. Estimated review: 1–2 weeks. Until approved, `pip install cerebrofy` is the documented Linux fallback.
- The winget pull request requires Microsoft human review (typically 1–5 business days). The CI/CD pipeline opens the PR automatically; it cannot force-merge it.
- The Homebrew custom tap (`cerebrofy/tap`) is available immediately at v1. Migration to `homebrew-core` is deferred until adoption warrants it.
- The Windows cold-start limitation (2–5 seconds for `cerebrofy validate`) is an accepted v1 constraint, documented in the Windows install guide. Optimization (persistent daemon or lightweight launcher) is deferred to v2.
- `cerebrofy mcp` uses MCP stdio transport. Other MCP transports (HTTP/SSE) are out of scope for v1.
- The MCP server exposes `plan`, `tasks`, and `specify` as tools. Exposing `build`, `update`, or `validate` as MCP tools is deferred to a future version.
- `cerebrofy parse` is a diagnostic tool, not a primary user workflow. It does not need the same performance target as `cerebrofy plan`.
- Cross-phase corrections in Track B (FR-019 through FR-027) are retroactive spec changes. The Phase 1–4 spec artifacts listed in the Retroactive Corrections Scope section MUST be updated before those phases' implementations begin.
- `cerebrofy.db` is not committed to version control. The `.gitignore` modification (FR-019) enforces this automatically rather than relying on developer discipline.
- All platform artifact builds run on CI using ephemeral runners. No developer machine is used for building release artifacts.
- `cerebrofy mcp` is the command registered in MCP config entries. When AI tools invoke it, Cerebrofy reads the calling process's working directory to determine the active repository.

---

## Retroactive Corrections Scope

The following Phase 1–4 spec artifacts MUST be updated to incorporate corrections from this
phase before those phases' implementations begin. This section serves as the authorization
and tracking record for retroactive edits.

| Correction | FR | Target Artifact(s) | Blueprint Review Finding |
|-----------|----|--------------------|-------------------------|
| `.gitignore` modification | FR-019 | `001/spec.md` (add to FR-003), `001/contracts/cli-init.md` filesystem side-effects | G-M2 |
| Hook sentinel format | FR-020 | `001/contracts/cli-init.md` hook script format section | P1-H1, D1 |
| MCP dispatcher pattern | FR-011 | `001/spec.md` FR-005/FR-006, `001/plan.md` Technical Constraints | P1-H2 |
| MCP priority list (all 7 paths) | FR-012 | `001/spec.md` Assumptions, `001/contracts/cli-init.md` behavior matrix | P1-M1 |
| validate clean-state message | FR-021 | `003/contracts/cli-validate.md` stdout section, `004/quickstart.md` | P3-H1, D2 |
| blast_count per-neuron | FR-022 | `004/tasks.md` T033, `004/data-model.md` TaskItem blast_count invariant | P4-H1, D3 |
| `schema_version` in plan FR | FR-023 | `004/spec.md` FR-007 | P4-H3, D4 |
| `cerebrofy parse` contract | FR-024, FR-025 | New file: `001/contracts/cli-parse.md` | G-H1 |
| specify two-connection pattern | FR-026 | `004/contracts/cli-specify.md` execution flow steps 1–4 | P4-M1 |
| LLM config silent ignore | FR-027 | `004/contracts/cli-plan.md` invariants, `004/contracts/cli-tasks.md` invariants | P4-M2 |
| Monorepo manifest file names | — | `001/data-model.md` Lobe entity, `001/contracts/cli-init.md` | P1-L2 |
| Large scope threshold | — | `003/spec.md` add FR-021 (or quantify in existing FR-001) | P3-M2 |
| Post-merge warning exact text | — | New: `003/contracts/cli-post-merge.md` or add to `003/contracts/cli-validate.md` | P3-L1 |
