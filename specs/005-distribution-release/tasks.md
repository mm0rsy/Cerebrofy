# Tasks: Phase 5 — Distribution, Release Engineering & Cross-Phase Corrections

**Input**: Design documents from `/specs/005-distribution-release/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Constraint**: Each task modifies exactly one file or creates exactly one new file.
Tasks are sized to be completable by any LLM (GLM/GPT/Gemini) without additional context.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different file from all other [P]-marked tasks in same phase)
- **[US#]**: User story this task belongs to
- Each task contains the exact file path to modify

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create directory structure, register new commands, add new dependency.
No user story work can begin until this phase is complete.

- [ ] T001 Add `mcp = ["mcp>=1.0"]` under `[project.optional-dependencies]` in `pyproject.toml`
- [ ] T002 [P] Create `src/cerebrofy/mcp/__init__.py` as empty file (creates the `mcp` package)
- [ ] T003 [P] Create `src/cerebrofy/mcp/server.py` as empty stub with module docstring: `"""MCP stdio server for cerebrofy."""`
- [ ] T004 [P] Create `src/cerebrofy/commands/parse.py` as empty stub with module docstring: `"""cerebrofy parse command."""`
- [ ] T005 [P] Create `src/cerebrofy/commands/mcp.py` as empty stub with module docstring: `"""cerebrofy mcp command."""`
- [ ] T006 [P] Create `packaging/snap/` directory with empty `.gitkeep`
- [ ] T007 [P] Create `packaging/windows/` directory with empty `.gitkeep`
- [ ] T008 [P] Create `packaging/macos/` directory with empty `.gitkeep`
- [ ] T009 [P] Create `.github/workflows/` directory with empty `.gitkeep` (if not already present)

**Checkpoint**: Skeleton files exist — implementation can begin

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Wire new commands into the CLI, add shared helpers needed by multiple stories.
MUST be complete before any user story implementation begins.

- [ ] T010 Add `from cerebrofy.commands import parse as parse_cmd` import and `cli.add_command(parse_cmd.parse)` registration in `src/cerebrofy/cli.py`
- [ ] T011 Add `from cerebrofy.commands import mcp as mcp_cmd` import and `cli.add_command(mcp_cmd.mcp)` registration in `src/cerebrofy/cli.py`
- [ ] T012 Add `HOOK_SENTINEL_BEGIN = "# BEGIN cerebrofy"` and `HOOK_SENTINEL_END = "# END cerebrofy"` and `HOOK_VERSION_MARKER = "# cerebrofy-hook-version:"` constants to `src/cerebrofy/hooks/installer.py` (replacing any `cerebrofy-hook-start`/`cerebrofy-hook-end` constants)
- [ ] T013 Update the Phase 1 hook script template string in `src/cerebrofy/hooks/installer.py` to use the new sentinel format: `# BEGIN cerebrofy\n# cerebrofy-hook-version: 1\ncerebrofy validate --hook pre-push\n# END cerebrofy`

**Checkpoint**: CLI registers `parse` and `mcp` commands; hook constants unified

---

## Phase 3: User Story 1 — macOS Homebrew Installation (Priority: P1) 🎯 MVP

**Goal**: macOS developers can install and upgrade Cerebrofy with a single `brew` command.

**Independent Test**:
1. `brew tap cerebrofy/tap && brew install cerebrofy` on clean macOS → `cerebrofy --help` succeeds
2. Tagged release → formula updated automatically, `brew upgrade cerebrofy` delivers new version

- [ ] T014 [US1] Create `packaging/macos/build_bottle.sh`: shell script that runs PyInstaller to build a self-contained macOS binary tarball. Include: `pyinstaller --onefile --name cerebrofy src/cerebrofy/__main__.py`, then `tar czf cerebrofy-${VERSION}-macos.tar.gz cerebrofy`
- [ ] T015 [P] [US1] Create `packaging/homebrew/Formula/cerebrofy.rb`: Homebrew formula with `class Cerebrofy < Formula`, `desc`, `homepage`, `url` (placeholder `__URL__`), `sha256` (placeholder `__SHA256__`), `version` (placeholder `__VERSION__`), `def install` installing `bin/cerebrofy`, and `test do` running `cerebrofy --version`
- [ ] T016 [P] [US1] Create `packaging/homebrew/update_formula.sh`: shell script that accepts `VERSION`, `URL`, `SHA256` as arguments and uses `sed` to replace `__VERSION__`, `__URL__`, `__SHA256__` placeholders in `Formula/cerebrofy.rb`, then commits and pushes to the tap repo

---

## Phase 4: User Story 2 — Linux Snap Installation (Priority: P2)

**Goal**: Linux developers install Cerebrofy via `snap install cerebrofy --classic` with unrestricted filesystem access.

**Independent Test**:
1. `snap install cerebrofy --classic` on clean Ubuntu 22.04 → `cerebrofy --help` succeeds
2. No system runtime installation required

- [ ] T017 [US2] Create `packaging/snap/snapcraft.yaml`: complete Snap definition with `name: cerebrofy`, `base: core22`, `version: git`, `summary`, `description`, `grade: stable`, `confinement: classic`, `apps.cerebrofy.command: bin/cerebrofy`, and `parts.cerebrofy` using `plugin: python` with `source: .` and `python-packages: [cerebrofy]`
- [ ] T018 [P] [US2] Create `packaging/snap/build_snap.sh`: shell script that runs `snapcraft` to produce the `.snap` artifact and names the output `cerebrofy-linux-amd64.snap`

---

## Phase 5: User Story 3 — Windows winget Installation (Priority: P3)

**Goal**: Windows developers install a self-contained Cerebrofy `.exe` with `winget install cerebrofy` — no Python, no PATH editing, no prerequisites.

**Independent Test**:
1. `winget install cerebrofy` on clean Windows 10 → `cerebrofy --help` in new terminal succeeds
2. Pre-push hook runs `cerebrofy validate` within 10 seconds (v1 cold-start limit)

- [ ] T019 [US3] Create `packaging/windows/nuitka_build.bat`: Windows batch script that invokes `nuitka --standalone --onefile --output-filename=cerebrofy.exe --include-package=tree_sitter_languages --include-data-dir=src\cerebrofy\queries=cerebrofy\queries --windows-console-mode=attach --windows-company-name=Cerebrofy --windows-product-name=Cerebrofy src\cerebrofy\__main__.py`
- [ ] T020 [P] [US3] Create `packaging/windows/installer.nsi`: NSIS script with `!define APP_NAME "Cerebrofy"`, `OutFile "cerebrofy-setup.exe"`, `InstallDir "$PROGRAMFILES64\Cerebrofy"`, `Section "Install"` that copies `cerebrofy.exe` to `$INSTDIR`, writes `$INSTDIR` to system PATH via registry key `HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path"`, and creates uninstaller
- [ ] T021 [P] [US3] Create `packaging/windows/winget_manifest/cerebrofy.cerebrofy.yaml`: winget version manifest with `PackageIdentifier: cerebrofy.cerebrofy`, `PackageVersion: __VERSION__`, `DefaultLocale: en-US`, `ManifestType: version`, `ManifestVersion: 1.4.0`
- [ ] T022 [P] [US3] Create `packaging/windows/winget_manifest/cerebrofy.cerebrofy.installer.yaml`: winget installer manifest with `PackageIdentifier: cerebrofy.cerebrofy`, `PackageVersion: __VERSION__`, `Installers` array entry for `Architecture: x64`, `InstallerType: exe`, `InstallerUrl: __URL__`, `InstallerSha256: __SHA256__`, `InstallerSwitches.Silent: /S`
- [ ] T023 [P] [US3] Create `packaging/windows/winget_manifest/cerebrofy.cerebrofy.locale.en-US.yaml`: winget locale manifest with `PackageIdentifier: cerebrofy.cerebrofy`, `PackageVersion: __VERSION__`, `PackageLocale: en-US`, `Publisher: Cerebrofy`, `PackageName: Cerebrofy`, `ShortDescription: AI-ready codebase indexer`, `ManifestType: locale`

---

## Phase 6: User Story 4 — Automated Release Pipeline (Priority: P4)

**Goal**: A maintainer pushes a git tag → all 4 distribution channels updated in parallel within 30 minutes. One platform failure does not block others.

**Independent Test**:
1. Push `v1.0.0` tag → CI triggers within 2 minutes
2. All 4 artifact builds complete; SHA-256 hashes attached to GitHub Release
3. One build failure → other platforms continue

- [ ] T024 [US4] Create `.github/workflows/release.yml`: top-level structure with `name: Release`, `on.push.tags: ['v*']`, and empty `jobs:` key (subsequent tasks fill in individual jobs)
- [ ] T025 [US4] Add `build-macos` job to `.github/workflows/release.yml`: `runs-on: macos-latest`, steps: `checkout`, `pip install pyinstaller cerebrofy[mcp]`, run `packaging/macos/build_bottle.sh`, compute `sha256sum`, `upload-artifact`
- [ ] T026 [US4] Add `build-linux` job to `.github/workflows/release.yml`: `runs-on: ubuntu-22.04`, steps: `checkout`, `snap install snapcraft --classic`, run `packaging/snap/build_snap.sh`, compute `sha256sum`, `upload-artifact`
- [ ] T027 [US4] Add `build-windows` job to `.github/workflows/release.yml`: `runs-on: windows-latest`, steps: `checkout`, `pip install nuitka cerebrofy[mcp]`, run `packaging/windows/nuitka_build.bat`, run NSIS to create installer, compute `sha256`, `upload-artifact`
- [ ] T028 [US4] Add `publish-pypi` job to `.github/workflows/release.yml`: `runs-on: ubuntu-22.04`, steps: `checkout`, `pip install build`, `python -m build`, use `pypa/gh-action-pypi-publish@release/v1` action with `PYPI_API_TOKEN` secret
- [ ] T029 [US4] Add `attach-release-assets` job to `.github/workflows/release.yml`: `needs: [build-macos, build-linux, build-windows]`, `strategy.fail-fast: false`, downloads all artifacts and attaches them plus their `.sha256` files to the GitHub Release using `softprops/action-gh-release@v2`
- [ ] T030 [US4] Add `update-homebrew-tap` job to `.github/workflows/release.yml`: `needs: build-macos`, steps: checkout `cerebrofy/homebrew-cerebrofy` tap repo, run `packaging/homebrew/update_formula.sh` with version and sha256 from build, commit and push to tap
- [ ] T031 [US4] Add `submit-winget-pr` job to `.github/workflows/release.yml`: `needs: build-windows`, `runs-on: windows-latest`, steps: install `wingetcreate`, run `wingetcreate update cerebrofy.cerebrofy --version ${{ github.ref_name }} --urls <installer-url> --submit` with `WINGET_TOKEN` secret
- [ ] T032 [P] [US4] Create `.github/workflows/ci.yml` (or update existing): add a `test-parse` job and `test-mcp` job running `pytest tests/integration/test_parse_command.py` and `pytest tests/integration/test_mcp_command.py` on push to main/PRs

---

## Phase 7: User Story 5 — Multi-Repository MCP Registration (Priority: P5)

**Goal**: Running `cerebrofy init` in N repos results in exactly 1 MCP entry. The entry routes to the correct repo at invocation time.

**Independent Test**:
1. `cerebrofy init` in 3 repos → AI tool config has exactly 1 `"cerebrofy"` MCP entry
2. Invoking from repo A → uses repo A's index
3. Second `cerebrofy init` in repo A → MCP entry unchanged

- [ ] T033 [US5] Add `MCP_CONFIG_PRIORITY_LIST: list[Path]` constant to `src/cerebrofy/mcp/registrar.py` containing all 7 paths from FR-012 (Claude Desktop macOS, Claude Desktop Windows, Cursor macOS/Linux, Cursor Windows, Opencode, generic MCP standard, fallback)
- [ ] T034 [US5] Add `find_writable_mcp_config() -> Path` function to `src/cerebrofy/mcp/registrar.py`: iterates `MCP_CONFIG_PRIORITY_LIST`, returns the first path whose parent directory exists and is writable (creates fallback path if none found)
- [ ] T035 [US5] Add `read_mcp_config(config_path: Path) -> dict` function to `src/cerebrofy/mcp/registrar.py`: reads JSON from `config_path` if it exists, returns empty dict if file absent or malformed
- [ ] T036 [US5] Add `write_mcp_entry(config_path: Path) -> bool` function to `src/cerebrofy/mcp/registrar.py`: reads existing config, checks if `mcpServers.cerebrofy` key already exists (returns `False` if so), merges entry `{"command": "cerebrofy", "args": ["mcp"]}`, writes JSON back atomically, returns `True` if written
- [ ] T037 [US5] Add `detect_multiple_installations() -> list[str]` function to `src/cerebrofy/mcp/registrar.py`: runs `which cerebrofy` (or `where cerebrofy` on Windows) to find all `cerebrofy` binary paths on PATH, returns the list
- [ ] T038 [US5] Add `warn_if_multiple_installations(existing_entry: dict | None) -> None` function to `src/cerebrofy/mcp/registrar.py`: if `detect_multiple_installations()` returns more than 1 path, prints warning with all paths and remediation steps per FR-018
- [ ] T039 [US5] Update `src/cerebrofy/commands/init.py`: import `find_writable_mcp_config`, `write_mcp_entry`, `warn_if_multiple_installations` from `cerebrofy.mcp.registrar`, then after scaffold setup call `config_path = find_writable_mcp_config()`, `write_mcp_entry(config_path)`, `warn_if_multiple_installations(...)`
- [ ] T040 [US5] Update `src/cerebrofy/commands/init.py`: handle the `--global` flag by passing `Path("~/.config/mcp/servers.json").expanduser()` directly to `write_mcp_entry()` instead of calling `find_writable_mcp_config()`

---

## Phase 8: User Story 6 — AI-Native Commands via MCP (Priority: P6)

**Goal**: An AI tool can invoke `cerebrofy plan`, `cerebrofy tasks`, `cerebrofy specify` as structured MCP tools with CWD-based repo routing.

**Independent Test**:
1. `cerebrofy mcp` starts without error
2. MCP tool call `plan` with `{"description": "add OAuth2"}` returns JSON with `schema_version: 1`
3. MCP tool call when no index exists → structured error (not empty response)

- [ ] T041 [US6] Add `_find_repo_root(start: Path) -> Path` function to `src/cerebrofy/mcp/server.py`: walks up from `start` searching for `.cerebrofy/config.yaml`, raises `FileNotFoundError` if not found at filesystem root
- [ ] T042 [US6] Add `_make_error_result(message: str) -> list[TextContent]` helper to `src/cerebrofy/mcp/server.py`: returns `[TextContent(type="text", text=message)]` with `isError=True` set on the `CallToolResult`
- [ ] T043 [US6] Add `app = Server("cerebrofy")` and `@app.list_tools()` handler to `src/cerebrofy/mcp/server.py`: returns list of 3 `Tool` objects for `plan`, `tasks`, `specify` — each with `name`, `description`, and `inputSchema` matching the schemas in `contracts/mcp-tools.md`
- [ ] T044 [US6] Add `_handle_plan(arguments: dict) -> list[TextContent]` function to `src/cerebrofy/mcp/server.py`: calls `_find_repo_root(Path.cwd())`, loads config, runs `HybridSearch.search()` same as `commands/plan.py`, returns JSON-serialized `PlanReport` as `TextContent`
- [ ] T045 [US6] Add `_handle_tasks(arguments: dict) -> list[TextContent]` function to `src/cerebrofy/mcp/server.py`: calls `_find_repo_root(Path.cwd())`, loads config, runs `HybridSearch.search()` same as `commands/tasks.py`, returns JSON-serialized task list as `TextContent`
- [ ] T046 [US6] Add `_handle_specify(arguments: dict) -> list[TextContent]` function to `src/cerebrofy/mcp/server.py`: calls `_find_repo_root(Path.cwd())`, loads config, runs full specify pipeline same as `commands/specify.py`, returns `{"output_file": ..., "content": ...}` as `TextContent`
- [ ] T047 [US6] Add `@app.call_tool()` handler to `src/cerebrofy/mcp/server.py`: dispatches to `_handle_plan`, `_handle_tasks`, or `_handle_specify` based on `name`; wraps all calls in `try/except` — on `FileNotFoundError` returns `_make_error_result("No Cerebrofy index found. Run 'cerebrofy build' first.")`, on schema mismatch returns appropriate error
- [ ] T048 [US6] Add `async def run_mcp_server() -> None` function to `src/cerebrofy/mcp/server.py`: uses `async with stdio_server() as (read_stream, write_stream): await app.run(read_stream, write_stream, app.create_initialization_options())`
- [ ] T049 [US6] Implement `src/cerebrofy/commands/mcp.py`: add `@click.command()` decorated `def mcp()` function that checks `mcp` package availability (import guard with clear error message), then calls `asyncio.run(run_mcp_server())` from `cerebrofy.mcp.server`

---

## Phase 9: User Story 7 — Developer Parse Diagnostics (Priority: P7)

**Goal**: `cerebrofy parse <path>` shows extracted Neurons as NDJSON without touching any index.

**Independent Test**:
1. `cerebrofy parse src/auth/login.py` → NDJSON lines with known function names
2. No `cerebrofy.db` created/modified
3. `cerebrofy parse nonexistent.py` → exit 1 with clear error

- [ ] T050 [US7] Add `@click.command()` and `@click.argument("path", type=click.Path())` to `src/cerebrofy/commands/parse.py`, with the function body calling internal helpers (stubs initially)
- [ ] T051 [US7] Add `_load_parse_context(path_arg: str) -> tuple[CerebrофyConfig, IgnoreRuleSet, Path]` function to `src/cerebrofy/commands/parse.py`: walks up from CWD to find `.cerebrofy/config.yaml` (exit 1 if not found), loads `CerebrофyConfig` and `IgnoreRuleSet`, validates that `path_arg` exists on filesystem (exit 1 if not), returns `(config, ruleset, Path(path_arg))`
- [ ] T052 [US7] Add `_collect_target_files(path: Path, config: CerebrофyConfig, ruleset: IgnoreRuleSet) -> list[Path]` function to `src/cerebrofy/commands/parse.py`: if `path.is_file()` returns `[path]`; if `path.is_dir()` walks recursively collecting files matching `config.tracked_extensions` that pass `ruleset`; returns file list
- [ ] T053 [US7] Add `_parse_and_emit(file_path: Path, repo_root: Path, config: CerebrофyConfig, ruleset: IgnoreRuleSet) -> None` function to `src/cerebrofy/commands/parse.py`: checks if file is excluded by ruleset (prints `"<rel_path>: excluded by ignore rules"` to stdout and returns if so); otherwise calls `parser/engine.py` parse on the file; for each returned `Neuron` calls `json.dumps(dataclasses.asdict(neuron))` and prints to stdout; on parse exception prints warning to stderr and continues
- [ ] T054 [US7] Wire `_load_parse_context`, `_collect_target_files`, and `_parse_and_emit` into the Click `parse` command body in `src/cerebrofy/commands/parse.py`: call `_load_parse_context`, iterate returned files calling `_parse_and_emit` for each

---

## Phase 10: User Story 8 — Accidental Index Commit Prevention (Priority: P8)

**Goal**: `cerebrofy init` automatically adds `.cerebrofy/db/` to `.gitignore`. `git add .` never stages `cerebrofy.db`.

**Independent Test**:
1. `cerebrofy init` → `.gitignore` contains `.cerebrofy/db/`
2. `git add .` after `cerebrofy build` → `cerebrofy.db` not staged
3. Running `cerebrofy init` again → no duplicate `.cerebrofy/db/` entry

- [ ] T055 [US8] Add `add_gitignore_entry(repo_root: Path) -> None` function to `src/cerebrofy/hooks/installer.py`: reads `.gitignore` at `repo_root / ".gitignore"` if it exists (empty string otherwise), checks if `.cerebrofy/db/` already present in content (no-op if found), appends `"\n# cerebrofy — local index (not committed)\n.cerebrofy/db/\n"` and writes back
- [ ] T056 [US8] Update `src/cerebrofy/commands/init.py`: import `add_gitignore_entry` from `cerebrofy.hooks.installer` and call `add_gitignore_entry(repo_root)` as part of the init scaffold sequence (after directory creation, before hook installation)

---

## Phase 11: User Story 9 — Consistent Hook Upgrade Behavior (Priority: P9)

**Goal**: Phase 1 installs `# cerebrofy-hook-version: 1`. Phase 3 upgrades to version 2 reliably — no duplicate blocks, no stale warn-only behavior.

**Independent Test**:
1. `cerebrofy init` → hook contains `# cerebrofy-hook-version: 1`
2. Phase 3 upgrade → hook contains `# cerebrofy-hook-version: 2`, single block
3. Re-run upgrade → no change (idempotent)

- [ ] T057 [US9] Add `HOOK_SCRIPT_V1: str` constant to `src/cerebrofy/hooks/installer.py` with the exact multi-line v1 hook block: `"# BEGIN cerebrofy\n# cerebrofy-hook-version: 1\ncerebrofy validate --hook pre-push\n# END cerebrofy\n"`
- [ ] T058 [US9] Add `HOOK_SCRIPT_V2: str` constant to `src/cerebrofy/hooks/installer.py` with the exact multi-line v2 hook block: `"# BEGIN cerebrofy\n# cerebrofy-hook-version: 2\nif ! cerebrofy validate --hook pre-push; then\n    echo 'Cerebrofy: Structural drift detected. Run cerebrofy update to sync.'\n    exit 1\nfi\n# END cerebrofy\n"`
- [ ] T059 [US9] Add `_get_hook_version(hook_content: str) -> int` function to `src/cerebrofy/hooks/installer.py`: finds the `# BEGIN cerebrofy` block, searches for `# cerebrofy-hook-version: N` within it, returns `N` as int, returns `0` if no block found or no version marker
- [ ] T060 [US9] Add `_replace_hook_block(hook_content: str, new_block: str) -> str` function to `src/cerebrofy/hooks/installer.py`: locates the `# BEGIN cerebrofy` … `# END cerebrofy` block in `hook_content` and replaces it with `new_block`; if no block found, appends `new_block` at end
- [ ] T061 [US9] Update `upgrade_hook(hook_path: Path) -> None` function in `src/cerebrofy/hooks/installer.py`: reads hook file, calls `_get_hook_version()` — if version already `== 2` returns immediately (idempotent); if version `< 2` calls `_replace_hook_block()` with `HOOK_SCRIPT_V2` and writes result back to hook file

---

## Phase 12: Track B — Retroactive Spec Corrections

**Purpose**: Update Phase 1–4 spec artifacts per the Retroactive Corrections Scope in `spec.md`.
These are documentation-only changes. No source code is modified in this phase.

**⚠️ Each task modifies exactly one spec file.**

### Group A: Phase 1 Spec Corrections

- [ ] T062 [P] Update `specs/001-sensory-foundation/contracts/cli-init.md`: find the hook script format section and replace `# cerebrofy-hook-start` / `# cerebrofy-hook-end` with the correct `# BEGIN cerebrofy` / `# cerebrofy-hook-version: 1` / `cerebrofy validate --hook pre-push` / `# END cerebrofy` format (FR-020 / Finding P1-H1)
- [ ] T063 [P] Update `specs/001-sensory-foundation/contracts/cli-init.md`: add a "Filesystem Side-Effects" section listing `.gitignore` modification as a side effect of `cerebrofy init`: creates or appends `.cerebrofy/db/` entry to the repository's `.gitignore` (FR-019 / Finding G-M2)
- [ ] T064 [P] Update `specs/001-sensory-foundation/spec.md`: in FR-005 or FR-006 (MCP registration requirements), add or update text to specify the dispatcher pattern — one MCP entry per machine using `cerebrofy mcp` as the command, reading CWD at invocation time (FR-011 / Finding P1-H2)
- [ ] T065 [P] Update `specs/001-sensory-foundation/spec.md`: in the Assumptions section, expand the MCP config path list to all 7 priority paths from FR-012 (Claude Desktop macOS/Windows, Cursor macOS/Windows, Opencode, generic MCP standard, fallback) (FR-012 / Finding P1-M1)
- [ ] T066 [P] Create `specs/001-sensory-foundation/contracts/cli-parse.md`: copy the full content from `specs/005-distribution-release/contracts/cli-parse.md` — this retroactively adds the `cerebrofy parse` contract to Phase 1 (FR-024/FR-025 / Finding G-H1)

### Group B: Phase 3 Spec Corrections

- [ ] T067 [P] Update `specs/003-autonomic-nervous-system/contracts/cli-validate.md`: find the stdout section showing the clean-state message and change it to exactly `"Cerebrofy: Index is clean."` (no trailing period variation, no alternate wording) (FR-021 / Finding P3-H1)
- [ ] T068 [P] Update `specs/004-ai-bridge/quickstart.md`: find any reference to the `cerebrofy validate` clean output message and change it to exactly `"Cerebrofy: Index is clean."` to match FR-021 (Finding P3-H1)

### Group C: Phase 4 Spec Corrections

- [ ] T069 [P] Update `specs/004-ai-bridge/spec.md`: in FR-007 (plan --json schema), add `schema_version: 1` as a required top-level field in the JSON output schema description (FR-023 / Finding P4-H3)
- [ ] T070 [P] Update `specs/004-ai-bridge/data-model.md`: in the `PlanReport` entity definition, add `schema_version: int` field with description `"Always 1; incremented only on breaking JSON schema changes"` (FR-023 / Finding P4-H3)
- [ ] T071 [P] Update `specs/004-ai-bridge/data-model.md`: in the `TaskItem` entity definition, update the `blast_count` field description to: `"Count of BFS neighbors reachable from THIS specific matched Neuron (depth-2, excluding RUNTIME_BOUNDARY edges) — computed independently per task item, not as a total"` (FR-022 / Finding P4-H1)
- [ ] T072 [P] Update `specs/004-ai-bridge/tasks.md`: find task T033 (the one computing `blast_count` using `len(result.blast_radius)`) and change the implementation note to compute `blast_count` per-neuron: `len(bfs_neighbors(neuron.id, depth=2))` for each matched neuron independently (FR-022 / Finding D3)
- [ ] T073 [P] Update `specs/004-ai-bridge/contracts/cli-plan.md`: add a `schema_version: 1` field to the JSON output example at the top level, and add an invariant: `"schema_version is always present in --json output; AI tools SHOULD check it before parsing"` (FR-023 / Finding P4-H3)
- [ ] T074 [P] Update `specs/004-ai-bridge/contracts/cli-plan.md`: add an invariants section entry: `"cerebrofy plan MUST silently ignore llm_endpoint, llm_model, llm_timeout, and system_prompt_template config keys — their presence MUST NOT trigger any network call"` (FR-027 / Finding P4-M2)
- [ ] T075 [P] Update `specs/004-ai-bridge/contracts/cli-tasks.md`: add an invariants section entry: `"cerebrofy tasks MUST silently ignore llm_endpoint, llm_model, llm_timeout, and system_prompt_template config keys — their presence MUST NOT trigger any network call"` (FR-027 / Finding P4-M2)
- [ ] T076 [P] Update `specs/004-ai-bridge/contracts/cli-specify.md`: in the execution flow steps 1–4, document the two-connection pattern: step 1 opens a dedicated pre-flight connection to read `embed_model` from `meta`, closes it; step 3 opens the main read-only connection for hybrid search (FR-026 / Finding P4-M1)

---

## Final Phase: Polish & Cross-Cutting Concerns

**Purpose**: Integration test stubs, Windows documentation, validation checks.

- [ ] T077 [P] Create `tests/integration/test_parse_command.py`: integration test file with a `test_parse_single_file` test using `tmp_path` that creates a minimal Python file, runs `cerebrofy init`, then invokes the `parse` CLI command via Click's `CliRunner` and asserts NDJSON output contains the expected function name
- [ ] T078 [P] Create `tests/integration/test_mcp_command.py`: integration test file with a `test_mcp_import_guard` test that invokes `cerebrofy mcp` without the `mcp` package and asserts exit code 1 with the expected error message; and a `test_mcp_plan_tool` test that mocks the MCP stdio transport and asserts the `plan` tool returns `schema_version: 1`
- [ ] T079 [P] Create `tests/unit/test_parse_command.py`: unit tests for `_get_hook_version()` and `_replace_hook_block()` from `hooks/installer.py` using raw string inputs (no filesystem) to verify sentinel detection and block replacement logic
- [ ] T080 Create `docs/windows-install.md`: Windows installation guide documenting the cold-start limitation (2–5 seconds for first `cerebrofy validate` invocation), the `%PATH%` new-terminal requirement, and the v1 accepted constraint (SC-008)
- [ ] T081 [P] Update `specs/001-sensory-foundation/data-model.md`: in the `Lobe` entity definition, add a note about monorepo manifest file names — if `package.json`, `Cargo.toml`, `go.mod`, `pyproject.toml`, or `pom.xml` exist in a subdirectory, that subdirectory name becomes a lobe boundary (Finding P1-L2)
- [ ] T082 [P] Update `CLAUDE.md`: verify the "Key Invariants" section reflects all Phase 5 corrections — check that the `blast_count per-Neuron`, `schema_version in plan --json`, `.gitignore on init`, and `Hook sentinel format` invariants are present (already done in plan.md phase, verify not duplicated)

---

## Dependencies

```
Phase 1 (T001–T009)
  └── Phase 2 (T010–T013)
        ├── Phase 3 (T014–T016) [US1 — macOS]
        ├── Phase 4 (T017–T018) [US2 — Linux]   ← can run after Phase 1
        ├── Phase 5 (T019–T023) [US3 — Windows]  ← can run after Phase 1
        ├── Phase 7 (T033–T040) [US5 — MCP Registration]
        ├── Phase 8 (T041–T049) [US6 — MCP Server]
        ├── Phase 9 (T050–T054) [US7 — Parse command]
        ├── Phase 10 (T055–T056) [US8 — gitignore]
        └── Phase 11 (T057–T061) [US9 — Hook upgrade]
  Phase 6 (T024–T032) [US4 — Pipeline]
        └── Depends on: Phase 3 (macOS), Phase 4 (Linux), Phase 5 (Windows)
  Phase 12 (T062–T076) [Track B corrections]
        └── Independent of all code phases — can run in parallel with Phases 3–11
  Final Phase (T077–T082)
        └── Depends on: all prior phases
```

---

## Parallel Execution Examples

### After Phase 2 is complete, these groups can run simultaneously:

**Group 1 (Distribution packaging):**
```
T014 macOS build script → T015 Homebrew formula → T016 tap update script
T017 snapcraft.yaml → T018 Snap build script
T019 Nuitka build → T020 NSIS installer → T021-T023 winget manifests
```

**Group 2 (New commands):**
```
T050 parse Click command → T051 → T052 → T053 → T054
T041 MCP find_repo_root → T042 make_error → T043 list_tools → T044-T048 handlers → T049 mcp command
```

**Group 3 (Init enhancements — no inter-dependencies):**
```
T033 MCP priority list
T055 add_gitignore_entry
T057 HOOK_SCRIPT_V1 constant
```

**Group 4 (Track B — all spec edits are independent):**
```
T062–T076 (all can run in parallel — each touches a different file)
```

---

## Implementation Strategy

### MVP Scope (deliver first)

Complete Phases 1–2 + Phase 9 (US7 `cerebrofy parse`):
- Phases 1–2 wire the CLI and fix hook constants (required for everything)
- Phase 9 (`cerebrofy parse`) is the simplest new command with zero external dependencies
- Verifiable immediately: `cerebrofy parse src/` on any initialized repo

### Incremental Delivery

1. **MVP**: Phases 1, 2, 9 (parse command works, CLI wired)
2. **+MCP**: Phases 7, 8 (MCP registration + server — AI tool integration)
3. **+Corrections**: Phase 12 (spec docs updated — no runtime change)
4. **+Init fixes**: Phases 10, 11 (.gitignore + hook sentinel — init behavior)
5. **+Distribution**: Phases 3, 4, 5 (packaging scripts — platform bundles)
6. **+Pipeline**: Phase 6 (CI/CD — automated releases)
7. **+Polish**: Final Phase (tests + docs)

---

## Task Count Summary

| Phase | Story | Task Range | Count |
|-------|-------|-----------|-------|
| Phase 1: Setup | — | T001–T009 | 9 |
| Phase 2: Foundational | — | T010–T013 | 4 |
| Phase 3 | US1 macOS | T014–T016 | 3 |
| Phase 4 | US2 Linux | T017–T018 | 2 |
| Phase 5 | US3 Windows | T019–T023 | 5 |
| Phase 6 | US4 Pipeline | T024–T032 | 9 |
| Phase 7 | US5 MCP Reg. | T033–T040 | 8 |
| Phase 8 | US6 MCP Server | T041–T049 | 9 |
| Phase 9 | US7 Parse | T050–T054 | 5 |
| Phase 10 | US8 .gitignore | T055–T056 | 2 |
| Phase 11 | US9 Hook upgrade | T057–T061 | 5 |
| Phase 12 | Track B Corrections | T062–T076 | 15 |
| Final: Polish | — | T077–T082 | 6 |
| **Total** | | **T001–T082** | **82** |
