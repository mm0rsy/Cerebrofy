---
description: "Task list for Phase 1 — Sensory Foundation"
---

# Tasks: Phase 1 — Sensory Foundation

**Input**: Design documents from `specs/001-sensory-foundation/`
**Prerequisites**: plan.md ✅, spec.md ✅, data-model.md ✅, contracts/ ✅, research.md ✅

**Granularity note**: Tasks are intentionally split to one function or one file per task so
each can be executed independently by any capable LLM with only local file context.

**Tests**: Not requested — no test tasks generated.

**Organization**: Tasks grouped by user story to enable independent delivery of each story.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths included in every task description

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the Python package skeleton. All tasks can run in parallel.

- [ ] T001 Create `pyproject.toml` at repo root with dependencies (`tree-sitter>=0.21`, `tree-sitter-languages>=1.10`, `pathspec>=0.12`, `PyYAML>=6.0`, `click>=8.1`), entry point `cerebrofy = "cerebrofy.cli:main"`, Python `>=3.11`
- [ ] T002 [P] Create `src/cerebrofy/__init__.py` with `__version__ = "0.1.0"` and package docstring
- [ ] T003 [P] Create empty `__init__.py` stubs for all subpackages: `src/cerebrofy/commands/__init__.py`, `src/cerebrofy/parser/__init__.py`, `src/cerebrofy/config/__init__.py`, `src/cerebrofy/ignore/__init__.py`, `src/cerebrofy/hooks/__init__.py`, `src/cerebrofy/mcp/__init__.py`
- [ ] T004 [P] Create `src/cerebrofy/cli.py` with a Click command group named `main` (`@click.group()`), no commands registered yet — this is the entry point stub
- [ ] T005 [P] Create `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py` as empty files

**Checkpoint**: Package installs with `pip install -e .` and `cerebrofy --help` shows an empty command group.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core data structures that EVERY user story depends on.
**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Neuron Data Types (`src/cerebrofy/parser/neuron.py`)

- [ ] T006 [P] Create `src/cerebrofy/parser/neuron.py` with a frozen `@dataclass` named `Neuron` with these fields: `id: str`, `name: str`, `type: str` (literal "function"/"class"/"module"), `file: str`, `line_start: int`, `line_end: int`, `signature: str | None = None`, `docstring: str | None = None`
- [ ] T007 Add a frozen `@dataclass` named `ParseResult` to `src/cerebrofy/parser/neuron.py` with fields: `file: str`, `neurons: list[Neuron]`, `warnings: list[str]`. Use `field(default_factory=list)` for the list fields.
- [ ] T008 Add function `deduplicate_neurons(neurons: list[Neuron]) -> list[Neuron]` to `src/cerebrofy/parser/neuron.py`. It must keep only the first Neuron for each `id` (ordered by `line_start` ascending). Return a new list; do not mutate input.

### Config Data Types (`src/cerebrofy/config/loader.py`)

- [ ] T009 [P] Create `src/cerebrofy/config/loader.py` with a frozen `@dataclass` named `CerebrофyConfig` with fields: `lobes: dict[str, str]`, `tracked_extensions: list[str]`, `embedding_model: str = "local"`, `embed_dim: int = 768`, `llm_endpoint: str = "openai"`, `llm_model: str = "gpt-4o"`, `top_k: int = 10`
- [ ] T010 Add constant `DEFAULT_TRACKED_EXTENSIONS: list[str]` to `src/cerebrofy/config/loader.py` containing: `.py .js .ts .tsx .jsx .go .rs .java .rb .cpp .c .h` (one string per extension with leading dot)
- [ ] T011 Add function `build_default_config(lobes: dict[str, str]) -> dict` to `src/cerebrofy/config/loader.py`. Returns a plain dict matching the `config.yaml` schema from `data-model.md`, using `lobes` as the lobes value and defaults for all other fields.
- [ ] T012 Add function `write_config(config: dict, path: Path) -> None` to `src/cerebrofy/config/loader.py`. Writes `config` as YAML to `path` using `yaml.dump` with `default_flow_style=False` and `allow_unicode=True`.
- [ ] T013 Add function `load_config(path: Path) -> CerebrофyConfig` to `src/cerebrofy/config/loader.py`. Reads YAML from `path`, constructs and returns a `CerebrофyConfig`. Raises `FileNotFoundError` if `path` does not exist.

### Ignore Rule Engine (`src/cerebrofy/ignore/ruleset.py`)

- [ ] T014 [P] Create `src/cerebrofy/ignore/ruleset.py` with string constant `DEFAULT_IGNORE_CONTENT` containing the default `.cerebrofy-ignore` lines from `data-model.md` (node_modules/, __pycache__/, .git/, dist/, build/, out/, vendor/, .venv/, venv/, *.min.js, *.min.css, *.map, *.lock, *.pyc, *.egg-info/, coverage/, .nyc_output/ — each on its own line with a comment header)
- [ ] T015 Add `@dataclass` named `IgnoreRuleSet` to `src/cerebrofy/ignore/ruleset.py` with fields: `cerebrofy_lines: list[str]`, `git_lines: list[str]`. Add classmethod `from_directory(root: Path) -> IgnoreRuleSet` that reads `.cerebrofy-ignore` and `.gitignore` from `root` (each may not exist — default to empty list).
- [ ] T016 Add method `matches(self, path: str) -> bool` to `IgnoreRuleSet` in `src/cerebrofy/ignore/ruleset.py`. Uses `pathspec.PathSpec.from_lines("gitwildmatch", lines)` to check both rulesets. Returns `True` if `path` matches any rule in either set.

**Checkpoint**: Foundation ready — all shared data structures exist and are importable. User story implementation can now begin.

---

## Phase 3: User Story 1 — Repository Initialization (Priority: P1) 🎯 MVP

**Goal**: `cerebrofy init` scaffolds `.cerebrofy/`, installs WARN-only git hooks, and registers an MCP server entry.

**Independent Test**: Run `cerebrofy init` in any git repo → `.cerebrofy/config.yaml` exists, `.cerebrofy/db/` is empty, `.cerebrofy/queries/*.scm` files exist, git hooks are installed in WARN-only mode, MCP entry exists in the first writable config path, terminal prints `cerebrofy build` next-step instruction.

### Bundled Tree-sitter Query Files

All query files are independent — create them all in parallel. Each `.scm` file must capture:
`function_definition`, `class_definition`, `import_statement`, `call_expression` for that language.
Named nested functions MUST be captured. Anonymous/lambda expressions MUST NOT be captured.

- [ ] T017 [P] [US1] Create `src/cerebrofy/queries/python.scm` — captures for Python: `(function_definition)`, `(class_definition)`, `(import_statement)`, `(import_from_statement)`, `(call)`. Use `@function.def`, `@class.def`, `@import`, `@call` as capture names.
- [ ] T018 [P] [US1] Create `src/cerebrofy/queries/javascript.scm` — captures for JavaScript: `(function_declaration)`, `(function_expression)` with identifier, `(class_declaration)`, `(import_declaration)`, `(call_expression)`. Skip arrow functions without names.
- [ ] T019 [P] [US1] Create `src/cerebrofy/queries/jsx.scm` — same captures as `javascript.scm` (JSX is a superset); copy and adjust node types for tree-sitter-languages JSX grammar.
- [ ] T020 [P] [US1] Create `src/cerebrofy/queries/typescript.scm` — same base as `javascript.scm` plus `(type_alias_declaration)` and `(interface_declaration)` as class-equivalent captures.
- [ ] T021 [P] [US1] Create `src/cerebrofy/queries/tsx.scm` — same as `typescript.scm` adjusted for TSX grammar node names.
- [ ] T022 [P] [US1] Create `src/cerebrofy/queries/go.scm` — captures: `(function_declaration)`, `(method_declaration)`, `(type_declaration)` for struct/interface types, `(import_declaration)`, `(call_expression)`.
- [ ] T023 [P] [US1] Create `src/cerebrofy/queries/rust.scm` — captures: `(function_item)`, `(impl_item)` methods, `(struct_item)`, `(enum_item)`, `(use_declaration)`, `(call_expression)`.
- [ ] T024 [P] [US1] Create `src/cerebrofy/queries/java.scm` — captures: `(method_declaration)`, `(class_declaration)`, `(interface_declaration)`, `(import_declaration)`, `(method_invocation)`.
- [ ] T025 [P] [US1] Create `src/cerebrofy/queries/ruby.scm` — captures: `(method)`, `(singleton_method)`, `(class)`, `(module)` definitions, `(require)` calls, `(call)` expressions.
- [ ] T026 [P] [US1] Create `src/cerebrofy/queries/c.scm` — captures: `(function_definition)`, `(struct_specifier)`, `(preproc_include)`, `(call_expression)`.
- [ ] T027 [P] [US1] Create `src/cerebrofy/queries/cpp.scm` — same as `c.scm` plus `(class_specifier)`, `(namespace_definition)`, method captures inside class bodies.
- [ ] T028 [P] [US1] Create `src/cerebrofy/queries/c_header.scm` — captures: `(declaration)` with function declarators, `(struct_specifier)`, `(preproc_include)`.

### Git Hook Installer (`src/cerebrofy/hooks/installer.py`)

- [ ] T029 [P] [US1] Create `src/cerebrofy/hooks/installer.py` with two string constants: `HOOK_MARKER_START = "# cerebrofy-hook-start"` and `HOOK_MARKER_END = "# cerebrofy-hook-end"`. Add string constant `HOOK_SCRIPT_BLOCK` containing the 4-line block: shebang line (for new files), marker start, `cerebrofy validate --hook {hook_name}`, marker end.
- [ ] T030 [US1] Add function `has_cerebrofy_marker(hook_path: Path) -> bool` to `src/cerebrofy/hooks/installer.py`. Returns `True` if `HOOK_MARKER_START` appears in the file content. Returns `False` if the file does not exist.
- [ ] T031 [US1] Add function `create_hook_file(hook_path: Path, hook_name: str) -> None` to `src/cerebrofy/hooks/installer.py`. Creates a new executable shell script at `hook_path` with `#!/bin/sh` on line 1, followed by the `HOOK_SCRIPT_BLOCK` (with `{hook_name}` substituted). Sets file permissions to 755 using `os.chmod`. **Windows note**: `os.chmod` is a no-op on Windows; on that platform, hook executability is determined by the `.exe` association or git's own hook runner — no extra handling is needed, but do not let a `chmod` exception crash init (catch `NotImplementedError`/`OSError` and continue).
- [ ] T032 [US1] Add function `append_to_hook(hook_path: Path, hook_name: str) -> str` to `src/cerebrofy/hooks/installer.py`. Appends the `HOOK_SCRIPT_BLOCK` to an existing hook file. Returns a warning string `"Warning: Pre-existing hook at {hook_path} — appending Cerebrofy call."`.
- [ ] T033 [US1] Add function `install_hooks(root: Path) -> list[str]` to `src/cerebrofy/hooks/installer.py`. For each of `pre-push` and `post-merge`: if hook file does not exist call `create_hook_file`; if it exists and has no marker call `append_to_hook`; if it exists and already has marker skip it. Return list of warning messages.

### MCP Server Registrar (`src/cerebrofy/mcp/registrar.py`)

- [ ] T034 [P] [US1] Create `src/cerebrofy/mcp/registrar.py` with constant `MCP_ENTRY: dict` — the JSON structure `{"command": "cerebrofy", "args": ["mcp"], "env": {}}`. Add `MCP_FALLBACK_SNIPPET: str` — the full JSON block to print when registration fails (from `contracts/cli-init.md`).
- [ ] T035 [US1] Add constant `MCP_CONFIG_PATHS: list[tuple[str, Path]]` to `src/cerebrofy/mcp/registrar.py`. Each entry is `(tool_name, path)` in the priority order from `contracts/cli-init.md`: Claude Desktop macOS, Claude Desktop Windows, Cursor macOS/Linux, Cursor Windows, Opencode, generic `~/.config/mcp/servers.json`. Use `Path.expanduser()` and `os.environ.get` for platform paths. **Windows note**: Claude Desktop Windows path uses `%APPDATA%` (`os.environ.get("APPDATA")`); Cursor Windows uses `%USERPROFILE%\.cursor\mcp.json`. Both must be constructed with `Path(os.environ.get(..., "")) / "..."` guarded against empty env vars.
- [ ] T036 [US1] Add function `find_writable_mcp_path(global_mode: bool) -> Path | None` to `src/cerebrofy/mcp/registrar.py`. If `global_mode=True`, return `Path("~/.config/mcp/servers.json").expanduser()` if writable (or creatable). Otherwise iterate `MCP_CONFIG_PATHS` and return the first path whose parent directory exists and is writable. Return `None` if none found.
- [ ] T037 [US1] Add function `has_cerebrofy_mcp_entry(config_path: Path) -> bool` to `src/cerebrofy/mcp/registrar.py`. Reads the JSON file at `config_path` (if it exists), checks if `data.get("mcpServers", {}).get("cerebrofy")` is present. Returns `False` if file does not exist or cannot be parsed.
- [ ] T038 [US1] Add function `write_mcp_entry(config_path: Path) -> None` to `src/cerebrofy/mcp/registrar.py`. Reads existing JSON from `config_path` (or starts with `{}`), sets `data["mcpServers"]["cerebrofy"] = MCP_ENTRY`, writes back atomically to `config_path` (write to `.tmp`, then rename).
- [ ] T039 [US1] Add function `register_mcp(global_mode: bool) -> tuple[bool, str]` to `src/cerebrofy/mcp/registrar.py`. Calls `find_writable_mcp_path` → if None returns `(False, MCP_FALLBACK_SNIPPET)`. Calls `has_cerebrofy_mcp_entry` → if True returns `(True, "already registered at {path}")`. Otherwise calls `write_mcp_entry` and returns `(True, "registered at {path}")`.

### Init Command (`src/cerebrofy/commands/init.py`)

- [ ] T040 [P] [US1] Create `src/cerebrofy/commands/init.py` with function `detect_lobes(root: Path) -> dict[str, str]`. Algorithm: (1) if `root/src/` exists, return `{dir.name: f"src/{dir.name}/"}` for each immediate subdir of `src/`; (2) else scan top-level dirs for monorepo manifests (`package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `pom.xml`) up to depth 2; (3) else use all top-level directories; (4) if no directories found at all, return `{"root": "."}`. Cap: only include dirs at depth ≤ 2.
- [ ] T041 [US1] Add function `create_scaffold_directories(root: Path) -> None` to `src/cerebrofy/commands/init.py`. Creates these directories (and any missing parents) using `Path.mkdir(parents=True, exist_ok=True)`: `.cerebrofy/db/`, `.cerebrofy/queries/`, `.cerebrofy/scripts/migrations/`.
- [ ] T042 [US1] Add function `copy_query_files(root: Path) -> None` to `src/cerebrofy/commands/init.py`. Copies all `*.scm` files from the bundled `src/cerebrofy/queries/` directory (use `importlib.resources` or `__file__`-relative path) into `root/.cerebrofy/queries/`. Does not overwrite existing files unless `force=True` parameter is passed.
- [ ] T043 [US1] Add function `write_cerebrofy_ignore(root: Path) -> None` to `src/cerebrofy/commands/init.py`. Writes `DEFAULT_IGNORE_CONTENT` (imported from `src/cerebrofy/ignore/ruleset.py`) to `root/.cerebrofy-ignore`. Does not overwrite if file already exists.
- [ ] T044 [US1] Add the `@click.command("init")` function `cerebrofy_init` to `src/cerebrofy/commands/init.py` with options `--global/--no-global` (default False), `--no-mcp` (flag), `--force` (flag). Orchestrates in order: (1) check `.git/` exists or exit 1; (2) check `.cerebrofy/` exists + `--force` logic; (3) `detect_lobes`; (4) `create_scaffold_directories`; (5) `copy_query_files(root, force=force)`  ← pass the `--force` flag through; (6) `write_cerebrofy_ignore`; (7) `write_config` with detected lobes; (8) `install_hooks`; (9) `register_mcp` unless `--no-mcp`; (10) print status messages and final next-step line.
- [ ] T045 [US1] Import `cerebrofy_init` from `src/cerebrofy/commands/init.py` and register it on the Click group in `src/cerebrofy/cli.py` using `main.add_command(cerebrofy_init)`.

**Checkpoint**: `cerebrofy init` is fully functional and independently testable per `quickstart.md` Steps 1–4.

---

## Phase 4: User Story 2 — Multi-Language Code Extraction (Priority: P2)

**Goal**: Universal Parser extracts normalized Neurons from any language configured via `.scm` query files.

**Independent Test**: Run `cerebrofy parse <file>` on a Python file → JSON output lists Neurons with correct id, name, type, file, line_start, line_end. Run on a Go file → same schema. Anonymous lambdas produce no Neurons. Named nested functions produce Neurons.

### Parser Engine (`src/cerebrofy/parser/engine.py`)

- [ ] T046 [P] [US2] Create `src/cerebrofy/parser/engine.py` with constant `EXTENSION_TO_LANGUAGE: dict[str, str]` mapping each tracked extension to its tree-sitter-languages name: `{".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx", ".jsx": "javascript", ".go": "go", ".rs": "rust", ".java": "java", ".rb": "ruby", ".cpp": "cpp", ".c": "c", ".h": "c_header"}`. Note: `.h` maps to `"c_header"` (not `"c"`) so that `load_query` resolves to `c_header.scm`, which contains header-appropriate captures (declarations, not definitions).
- [ ] T047 [US2] Add function `load_language_parser(extension: str) -> Language | None` to `src/cerebrofy/parser/engine.py`. Looks up `extension` in `EXTENSION_TO_LANGUAGE`, calls `tree_sitter_languages.get_language(lang_name)`. Returns `None` if extension is not in the map. Catches any exception and returns `None`.
- [ ] T048 [US2] Add function `load_query(extension: str, queries_dir: Path) -> Query | None` to `src/cerebrofy/parser/engine.py`. Resolves the `.scm` path as `queries_dir / f"{EXTENSION_TO_LANGUAGE[extension]}.scm"`. If file does not exist returns `None`. Loads and returns a `tree_sitter.Language.query(scm_text)` object.
- [ ] T049 [US2] Add function `extract_signature(node: Node, source: bytes) -> str | None` to `src/cerebrofy/parser/engine.py`. For a `function_definition` (or equivalent) node, returns the text of the first line of the node (the declaration line, not the body) decoded as UTF-8, stripped. Returns `None` for class and module nodes.
- [ ] T050 [US2] Add function `extract_docstring(node: Node, source: bytes) -> str | None` to `src/cerebrofy/parser/engine.py`. Looks for the first `string` or `comment` child node immediately after the function/class definition header. Returns its text decoded and stripped, or `None` if not found.
- [ ] T051 [US2] Add function `map_capture_to_neuron(capture_name: str, node: Node, source: bytes, file: str) -> Neuron | None` to `src/cerebrofy/parser/engine.py`. Rules: if `capture_name` contains `"function"` or `"method"` → type `"function"`; if `"class"` or `"struct"` or `"interface"` or `"type"` → type `"class"`; if `"import"` or `"call"` → return `None` (not a Neuron-producing capture). Extract `name` from the node's `name`-field child (the named capture from the `.scm` query). Return `None` if the node yields no name string or if the name string is empty. **Do NOT add any language-specific checks** (e.g., underscore-prefix conventions) — anonymous/private exclusion is the responsibility of the `.scm` query file, not the engine (Law V).
- [ ] T052 [US2] Add function `build_module_neuron(file: str, total_lines: int) -> Neuron` to `src/cerebrofy/parser/engine.py`. Returns a `Neuron` with `type="module"`, `name` set to the stem of `file` (filename without extension), `id=f"{file}::{name}"`, `line_start=1`, `line_end=total_lines`, `signature=None`, `docstring=None`.
- [ ] T053 [US2] Add function `extract_neurons(tree: Tree, source: bytes, file: str, query: Query) -> list[Neuron]` to `src/cerebrofy/parser/engine.py`. Runs `query.captures(tree.root_node)`. For each capture calls `map_capture_to_neuron`; collects non-None results. Appends `build_module_neuron` result. Calls `deduplicate_neurons` (imported from `neuron.py`) before returning.
- [ ] T054 [US2] Add function `parse_file(file_path: Path, queries_dir: Path, repo_root: Path) -> ParseResult` to `src/cerebrofy/parser/engine.py`. Reads file bytes. Gets extension. Calls `load_language_parser` and `load_query`. If either returns `None`, returns `ParseResult(file=rel_path, neurons=[], warnings=[f"No parser for {extension}"])`. Calls `Language.parser().parse(source)`, checks for `root_node.has_error`, calls `extract_neurons`. Returns `ParseResult`.
- [ ] T055 [US2] Add function `parse_directory(root: Path, config: CerebrофyConfig, ignore_rules: IgnoreRuleSet) -> list[ParseResult]` to `src/cerebrofy/parser/engine.py`. Walks all files under `root` recursively. For each file: compute relative path from `root`; skip if `ignore_rules.matches(rel_path)`; skip if file extension not in `config.tracked_extensions`; call `parse_file`. Return list of all `ParseResult` objects.
- [ ] T056 [P] [US2] Create `src/cerebrofy/commands/parse.py` with `@click.command("parse")` function `cerebrofy_parse`. Accepts a `path` argument (file or directory). If path is a file, calls `parse_file` and prints Neurons as JSON. If directory, loads config with `load_config`, creates `IgnoreRuleSet.from_directory`, calls `parse_directory`, prints all Neurons as JSON array.
- [ ] T057 [US2] Import `cerebrofy_parse` from `src/cerebrofy/commands/parse.py` and register it in `src/cerebrofy/cli.py` using `main.add_command(cerebrofy_parse)`.

**Checkpoint**: `cerebrofy parse src/` produces JSON Neurons for all tracked files. All US2 acceptance scenarios verified per `quickstart.md` Steps 5–7.

---

## Phase 5: User Story 3 — Configurable Project Layout (Priority: P3)

**Goal**: Changes to `config.yaml` and `.cerebrofy-ignore` are fully respected by the parser without engine changes.

**Independent Test**: Edit `config.yaml` to rename a Lobe and add a pattern to `.cerebrofy-ignore`. Run `cerebrofy parse` — renamed Lobe is used, newly ignored directory is excluded.

- [ ] T058 [P] [US3] Add function `validate_config(config: CerebrофyConfig, queries_dir: Path) -> list[str]` to `src/cerebrofy/config/loader.py`. Checks: (1) `lobes` is not empty; (2) `tracked_extensions` is not empty; (3) for each extension in `tracked_extensions`, verify a `.scm` file exists in `queries_dir` — warn (don't error) if missing; (4) `embed_dim` matches model: 768 for local, 1536 for openai, 1024 for cohere. Returns list of warning strings.
- [ ] T059 [US3] Update `load_config` in `src/cerebrofy/config/loader.py` to accept an optional `queries_dir: Path | None = None` parameter. When provided, call `validate_config` and print any warnings to stderr.
- [ ] T060 [US3] Verify (no code change needed) that the existing T048 + T054 logic already handles unknown extensions gracefully: `load_query` returns `None` when no `.scm` exists → `parse_file` returns a `ParseResult` with `warnings=["No parser for {extension}"]`. Confirm this warning text is printed to stderr by `cerebrofy_parse` (T056). If `cerebrofy_parse` currently swallows warnings silently, update it to print them.

**Checkpoint**: All US3 acceptance scenarios pass. Config customization is respected end-to-end.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T061 [P] Add `--version` flag to the Click group in `src/cerebrofy/cli.py` using `@click.version_option(version=__version__, prog_name="cerebrofy")`
- [ ] T062 [P] Run `quickstart.md` edge-case scenarios manually: flat repo, syntax-error file, unwritable MCP paths, pre-existing hook — fix any issues found
- [ ] T063 Run `ruff check src/ tests/` and `mypy src/` — fix all reported issues in source files
- [ ] T064 [P] Verify SC-001: time `cerebrofy init` against a repo containing at least 1,000 files (e.g., using `time cerebrofy init` in a generated fixture directory). Confirm wall-clock time is under 30 seconds. Document result in a comment or CI note — no automated assertion required for Phase 1.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — blocks all user stories
- **US1 (Phase 3)**: Depends on Foundational — requires Neuron, CerebrофyConfig, IgnoreRuleSet
- **US2 (Phase 4)**: Depends on Foundational — requires Neuron, ParseResult, CerebrофyConfig, IgnoreRuleSet
- **US3 (Phase 5)**: Depends on US1 + US2 (config and parser both complete)
- **Polish (Phase 6)**: Depends on all user stories complete

### User Story Dependencies

- **US1 (P1)**: Can start after Phase 2. No dependency on US2 or US3.
- **US2 (P2)**: Can start after Phase 2. No dependency on US1 or US3.
- **US3 (P3)**: Can start after US1 + US2 both complete (it validates their integration).

### Within Phase 3 (US1)

- T017–T028 (query files + installer + registrar skeletons): all [P] — run first
- T029–T033 (hook installer methods): sequential within the module
- T034–T039 (MCP registrar methods): sequential within the module
- T040–T043 (init command sub-functions): T040 [P] with previous group; T041–T043 sequential
- T044 (orchestrator): depends on T040–T043 + T033 + T039 + T012
- T045 (CLI registration): depends on T044

### Within Phase 4 (US2)

- T046 (constants): [P] with Phase 3 work
- T047–T048 (loaders): sequential, depend on T046
- T049–T052 (extraction functions): can run [P] relative to each other
- T053 (extract_neurons): depends on T049–T052
- T054 (parse_file): depends on T047–T050, T053
- T055 (parse_directory): depends on T054
- T056–T057 (CLI command): depends on T055

---

## Parallel Execution Examples

### All Phase 1 Setup Tasks Together
```
T001 pyproject.toml
T002 src/cerebrofy/__init__.py
T003 all subpackage __init__.py stubs
T004 src/cerebrofy/cli.py stub
T005 tests/__init__.py files
```

### All Phase 2 Foundational In Two Waves

**Wave 1** (all parallel):
```
T006 Neuron dataclass
T009 CerebrофyConfig dataclass
T014 IgnoreRuleSet skeleton + DEFAULT_IGNORE_CONTENT
```

**Wave 2** (after wave 1):
```
T007 ParseResult dataclass     T010 DEFAULT_TRACKED_EXTENSIONS
T008 deduplicate_neurons()     T011 build_default_config()
T015 from_directory()          T012 write_config()
T016 matches()                 T013 load_config()
```

### All 12 Query Files in Phase 3 (fully parallel)
```
T017 python.scm    T018 javascript.scm  T019 jsx.scm
T020 typescript.scm T021 tsx.scm        T022 go.scm
T023 rust.scm      T024 java.scm        T025 ruby.scm
T026 c.scm         T027 cpp.scm         T028 c_header.scm
```

### Phase 3 Sub-Component Skeletons (parallel)
```
T029 hooks/installer.py constants
T034 mcp/registrar.py constants
T040 commands/init.py detect_lobes()
T046 parser/engine.py EXTENSION_TO_LANGUAGE
```

---

## Implementation Strategy

### MVP: User Story 1 Only

1. Complete Phase 1 (Setup)
2. Complete Phase 2 (Foundational)
3. Complete Phase 3 (US1 — cerebrofy init)
4. **STOP AND VALIDATE**: Run `quickstart.md` Steps 1–4
5. `cerebrofy init` works end-to-end → MVP delivered

### Incremental Delivery

1. Setup + Foundational → scaffolding complete
2. Add US1 → `cerebrofy init` works → validate → demo
3. Add US2 → `cerebrofy parse` works → validate all parser scenarios
4. Add US3 → config customization validated → all acceptance criteria met
5. Polish → production-ready

### Parallel Team Strategy

With multiple developers (or parallel LLM sessions):

1. Team completes Setup + Foundational together (T001–T016)
2. Once Foundational is done:
   - **Stream A**: All 12 query files (T017–T028) + hook installer (T029–T033) + MCP (T034–T039)
   - **Stream B**: Parser engine constants + loaders (T046–T050)
3. Once Stream A completes: init command (T040–T045)
4. Once Stream B completes: extraction + parse functions (T051–T057)
5. US3 after both streams: T058–T060
6. Polish: T061–T063

---

## Notes

- Every task modifies or creates **exactly one file** or **one function** — sized for execution by any capable LLM with only the relevant contract/data-model as context.
- **[P]** tasks touch different files with no inter-task dependencies — safe to execute in parallel.
- **Story labels** ([US1], [US2], [US3]) map to user stories in `spec.md` for traceability.
- The `.scm` query files (T017–T028) can be generated from the tree-sitter documentation for each language without needing full system context.
- After each checkpoint, the delivered user story can be independently tested before proceeding.
- Avoid modifying the same file in two concurrent [P] tasks.
