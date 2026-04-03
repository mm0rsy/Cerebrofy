# Feature Specification: Phase 1 — Sensory Foundation

**Feature Branch**: `001-sensory-foundation`
**Created**: 2026-04-03
**Status**: Draft
**Input**: User description: "Read @cerebrofy_blueprint_v5_0.md and specify the next feature based on phase 1"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Repository Initialization (Priority: P1)

A developer wants to start using Cerebrofy on an existing or new repository. They run
`cerebrofy init` from the project root and Cerebrofy automatically discovers the project
structure, proposes logical groupings (Lobes) based on directory layout, writes the initial
configuration, installs enforcement hooks, and registers itself with any detected AI coding
assistant. The developer needs zero prior knowledge of Cerebrofy internals to complete this step.

**Why this priority**: Without initialization, no other Cerebrofy command can run. This is the
entry point for every user and determines first-impression success. It also gates Phase 2 (the
build).

**Independent Test**: A developer with no prior Cerebrofy setup runs `cerebrofy init` in a
project directory and receives a working configuration scaffold, active WARN-only git hooks, an
MCP server entry for their AI coding assistant, and a clear "next step" instruction — with no
manual file editing required.

**Acceptance Scenarios**:

1. **Given** a repository with a `src/` directory containing multiple subdirectories, **When**
   the developer runs `cerebrofy init`, **Then** Cerebrofy proposes one Lobe per top-level
   subdirectory under `src/` and writes a `config.yaml` reflecting this layout.

2. **Given** a monorepo where packages are identified by the presence of a package manifest
   file, **When** the developer runs `cerebrofy init`, **Then** each package directory is
   proposed as its own Lobe (up to a maximum depth of 2 levels from the project root).

3. **Given** no `src/` directory exists at the repo root, **When** the developer runs
   `cerebrofy init`, **Then** Cerebrofy uses the top-level repository directories as Lobe
   candidates.

4. **Given** the repository is completely flat (only files at root, no subdirectories), **When**
   the developer runs `cerebrofy init`, **Then** Cerebrofy creates a single default Lobe mapped
   to the repo root directory and completes successfully.

5. **Given** a supported AI coding assistant is detected on the developer's machine, **When**
   `cerebrofy init` completes, **Then** Cerebrofy is registered as an MCP server automatically
   and reports exactly which config file it wrote — the developer never manually edits any AI
   tool configuration.

6. **Given** `cerebrofy init` completes successfully, **When** the developer inspects their
   repository, **Then** the `.cerebrofy/` directory scaffold exists with `config.yaml`,
   `.cerebrofy-ignore`, and git hooks in WARN-only mode; no `cerebrofy.db` file exists.

7. **Given** `cerebrofy init` is run a second time in the same repo, **When** an MCP server
   entry already exists, **Then** Cerebrofy does not create a duplicate entry and reports what
   it found.

8. **Given** `cerebrofy init` completes, **When** the developer reads the terminal output,
   **Then** the final message instructs them to run `cerebrofy build` as the next step.

---

### User Story 2 - Multi-Language Code Extraction (Priority: P2)

A developer wants their codebase to be parsed so that functions, classes, and module-level
code are identified and normalized into a consistent structure regardless of programming
language. This parsed output is the raw material for the index that all subsequent Cerebrofy
commands depend on.

**Why this priority**: The parser is the data layer of the entire system. Without reliable,
language-agnostic extraction, the build step (Phase 2) cannot produce a valid graph. This must
work correctly across all configured languages before any indexing or AI features can operate.

**Independent Test**: Given a directory containing source files in at least one configured
language, the parser produces a list of named code units (Neurons) for each file — each unit
has a name, type (function/class/module), file location, line range, and any available
signature or docstring. The output schema is identical regardless of which language was parsed.

**Acceptance Scenarios**:

1. **Given** a source file with named functions and methods, **When** the parser processes it,
   **Then** each named function (including named nested functions) and each method produces
   exactly one Neuron record; anonymous functions and lambdas produce no Neuron.

2. **Given** a source file with a class that has no methods, **When** the parser processes it,
   **Then** the class produces one Neuron of type `class`.

3. **Given** a source file with code at the module level (outside any function or class),
   **When** the parser processes it, **Then** all such module-level code is collected into one
   Neuron of type `module` for that file.

4. **Given** source files in two different supported languages, **When** the parser processes
   both, **Then** the output Neurons share the same field structure: unique ID, name, type,
   file path, line start, line end, signature, and docstring.

5. **Given** a file whose path matches a rule in `.cerebrofy-ignore` or `.gitignore`, **When**
   the parser runs, **Then** that file is silently skipped and produces no Neurons.

6. **Given** a config file (YAML, JSON, TOML) not explicitly listed in `tracked_extensions`,
   **When** the parser runs, **Then** the file is skipped with no error.

7. **Given** a new language is added by placing a query file in `.cerebrofy/queries/` and
   listing its extension in `config.yaml`, **When** the parser runs, **Then** files of that
   language are parsed and produce Neurons in the same normalized schema — no changes to the
   core parser logic are required.

8. **Given** a source file with a syntax error, **When** the parser processes it, **Then**
   Cerebrofy logs a warning identifying the file, skips or partially processes it, and continues
   parsing remaining files without crashing.

---

### User Story 3 - Configurable Project Layout (Priority: P3)

A developer wants to review and adjust the Lobe groupings and ignore rules proposed during
`cerebrofy init` before committing to a full build. They edit the generated configuration files
directly and expect all subsequent commands to respect their changes.

**Why this priority**: Auto-detection covers the common case, but every project is different.
Developers must be confident their configuration is correct before investing time in a full
index build.

**Independent Test**: A developer edits `config.yaml` to rename a Lobe and adds a directory
pattern to `.cerebrofy-ignore`. When the parser subsequently runs, it respects both changes —
the renamed Lobe is used and the newly ignored directory is excluded.

**Acceptance Scenarios**:

1. **Given** the developer edits the Lobe map in `config.yaml`, **When** Cerebrofy reads the
   configuration, **Then** it uses the developer-defined Lobe paths, not the auto-detected ones.

2. **Given** the developer adds a custom pattern to `.cerebrofy-ignore`, **When** the parser
   runs, **Then** all files and directories matching that pattern are excluded.

3. **Given** the developer removes an extension from `tracked_extensions` in `config.yaml`,
   **When** the parser runs, **Then** files of that extension are no longer parsed or included
   in any output.

4. **Given** the developer adds a new extension to `tracked_extensions` in `config.yaml`,
   **When** the parser runs, **Then** files of that extension are included if a corresponding
   query file exists in `.cerebrofy/queries/`.

---

### Edge Cases

- What happens when `cerebrofy init` is run in a completely flat repository with no subdirectories (all files at root)? → A single default Lobe mapped to the repo root is created; init completes successfully.
- What happens when a source file contains a syntax error that prevents full parsing? → Cerebrofy logs a warning identifying the file and line, skips or partially processes it, and continues parsing remaining files without crashing (see FR-015, SC-005).
- What if Cerebrofy detects more than one supported AI coding assistant on the same machine? → Cerebrofy registers with the first writable config path in the priority order defined in `contracts/cli-init.md` (Claude Desktop → Cursor → Opencode → generic fallback). Only one registration is written per `cerebrofy init` run.
- What if the git repository has no commits yet (freshly initialized empty repo)? → `cerebrofy init` proceeds normally — it only requires that `.git/` exists, not that any commits exist. The hook scripts are installed but will never be triggered until the first commit/push.
- What if two names within the same file collide (e.g., a method and a module-level function both named `validate`)? → The first occurrence is kept; subsequent same-name entries in the same file are silently discarded. Cross-file ID collisions cannot occur because the file path is always part of the ID.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `cerebrofy init` MUST detect project structure and propose Lobe groupings without requiring any user input.
- **FR-002**: `cerebrofy init` MUST write a valid `config.yaml` and `.cerebrofy-ignore` to the `.cerebrofy/` directory.
- **FR-003**: `cerebrofy init` MUST create the directory scaffold (`.cerebrofy/db/`, `.cerebrofy/queries/`, `.cerebrofy/scripts/migrations/`) without creating `cerebrofy.db`.
- **FR-004**: `cerebrofy init` MUST install git hooks in WARN-only mode; hard-block enforcement MUST NOT be active after Phase 1. If a hook script already exists at `.git/hooks/pre-push` or `.git/hooks/post-merge`, Cerebrofy MUST append its call to the existing script rather than overwriting it.
- **FR-005**: `cerebrofy init` MUST register Cerebrofy as an MCP server with the first detected compatible AI coding assistant; no manual config editing by the user is required. If all known MCP config paths are unwritable, `cerebrofy init` MUST warn the developer, print the exact MCP config snippet for manual copy-paste, and complete init successfully (non-fatal).
- **FR-006**: Running `cerebrofy init` multiple times in the same repo MUST be idempotent for MCP registration — no duplicate entries are created.
- **FR-007**: `cerebrofy init` MUST print a clear next-step instruction directing the developer to `cerebrofy build` upon successful completion.
- **FR-008**: The parser MUST produce a normalized Neuron record for every named function, named nested function, method, class (without methods), and module-level code block in tracked source files. Anonymous functions and lambda expressions MUST be skipped.
- **FR-009**: Each Neuron MUST include: unique ID (`{file}::{name}`), name, type (function/class/module), file path, line start, line end, and optionally signature and docstring. When multiple code units in the same file share the same name, only the first occurrence is kept; subsequent duplicates are silently discarded.
- **FR-010**: The parser MUST produce identical Neuron schema output regardless of which supported language is being parsed.
- **FR-011**: Files and directories matching rules in `.cerebrofy-ignore` or `.gitignore` MUST be excluded from parsing with no error output.
- **FR-012**: Config files (YAML, JSON, TOML) MUST be skipped by default unless their extension is explicitly listed in `tracked_extensions`.
- **FR-013**: Adding a new language MUST require only a query file in `.cerebrofy/queries/` and an extension entry in `config.yaml` — no modification to core parser logic.
- **FR-014**: Lobe auto-detection MUST cap at a maximum depth of 2 directory levels to prevent over-fragmentation.
- **FR-015**: The parser MUST handle files with syntax errors gracefully — log a warning for the affected file and continue processing remaining files without crashing.

### Key Entities

- **Neuron**: A named code unit extracted from source. Represents a function, method, class
  (without methods), or module-level code block. Attributes: `id` (`{file}::{name}`), `name`,
  `type` (function/class/module), `file`, `line_start`, `line_end`, `signature` (optional),
  `docstring` (optional). IDs are unique per file; when a name collision occurs within the same
  file, only the first occurrence is retained.
- **Lobe**: A logical grouping of related source files, corresponding to a directory path.
  Named and mapped to a directory in `config.yaml`.
- **Ignore Rule**: A gitignore-syntax pattern in `.cerebrofy-ignore` that excludes matching
  paths from tracking and parsing.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer completes `cerebrofy init` on a repository of any size in under 30
  seconds without editing any file manually.
- **SC-002**: The parser identifies 100% of named functions, classes, and module-level code
  blocks in all files matching `tracked_extensions` that are not excluded by ignore rules.
- **SC-003**: Adding a new programming language requires zero changes to core parsing logic —
  verified by adding only a query file and confirming Neuron output matches the standard schema.
- **SC-004**: `cerebrofy init` completes successfully and produces a usable configuration on
  macOS, Linux, and Windows without platform-specific user steps.
- **SC-005**: Files with syntax errors are reported by name as warnings; the parser completes
  and successfully processes all other valid files.
- **SC-006**: Given each of the following representative repo layouts — (a) `src/<module>/` multi-package, (b) top-level monorepo with manifest files, (c) flat single-level directories, (d) completely flat root-only — `cerebrofy init` auto-detects the correct Lobe structure without requiring manual edits to `config.yaml`. All four layouts are covered by integration test scenarios in `quickstart.md`.

## Assumptions

- The developer has Cerebrofy installed and available on their `PATH` before running `cerebrofy init`.
- The repository is a valid git repository (`.git/` exists); behavior on non-git directories is out of scope for Phase 1.
- A default set of tracked extensions (Python, JavaScript, TypeScript, Go, Rust, Java, Ruby, C, C++, C headers) is pre-configured and does not require user setup.
- MCP auto-registration targets: Claude Desktop (macOS and Windows), Cursor (macOS/Linux and Windows), Opencode, and `~/.config/mcp/servers.json` as fallback. Other AI tools are out of scope for Phase 1.
- Config files (YAML, JSON, TOML) are excluded from parsing by default.
- `cerebrofy build` is a Phase 2 deliverable; Phase 1 does not produce `cerebrofy.db` or any indexed output.
- `cerebrofy merge` is out of scope for all of v1.

## Clarifications

### Session 2026-04-03

- Q: When multiple code units in the same file share the same name, how should the Neuron ID collision be handled? → A: Keep `{file}::{name}` — discard all but the first occurrence silently.
- Q: When a git hook script already exists at `.git/hooks/pre-push` or `.git/hooks/post-merge`, how should `cerebrofy init` handle installation? → A: Append Cerebrofy's hook call to the existing script, preserving prior hook behavior.
- Q: When the repository is completely flat (no subdirectories at all), what should `cerebrofy init` propose as Lobes? → A: Create a single default Lobe mapped to the repo root directory; init completes successfully.
- Q: If all known MCP config paths are unwritable, how should `cerebrofy init` behave? → A: Warn, print the exact MCP config snippet for manual copy-paste, and complete init successfully (non-fatal).
- Q: How should the parser handle nested functions and anonymous/lambda functions? → A: Extract named nested functions as individual Neurons; skip anonymous functions and lambdas entirely.
