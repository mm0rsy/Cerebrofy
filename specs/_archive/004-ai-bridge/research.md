# Research: Phase 4 — AI Bridge

**Feature**: 004-ai-bridge
**Date**: 2026-04-04

---

## Decision 1: Hybrid Search Architecture — Single SQLite Connection

**Decision**: Implement hybrid search as a single read-only SQLite connection that executes
both the KNN cosine similarity query on `vec_neurons` and the BFS depth-2 graph traversal
on `edges` within the same Python function, sharing the same `sqlite3.Connection` object.

**Rationale**: This is the zero-IPC, zero-serialization architecture described in Blueprint
§IV and §VI. Both queries operate on `cerebrofy.db` tables that are co-located in one file.
A shared connection means BFS can begin immediately after KNN without opening a second
connection, eliminating any lock contention and keeping the total hybrid search latency under
50ms (SC-001). The `blast_radius()` function from Blueprint §VI is the reference
implementation for BFS — `search/hybrid.py` calls it directly.

**New module**: `src/cerebrofy/search/hybrid.py` — orchestrates the two phases and merges
results into a `HybridSearchResult`. Opens the DB via `open_db()` (Phase 2, read-only
URI mode: `?mode=ro`) and holds the connection for the entire search, then closes it.

**Alternatives considered**:
- Two separate connections (one KNN, one BFS) — rejected: doubles connection overhead,
  introduces lock races in WAL mode.
- Run KNN in a separate thread — rejected: SQLite connections are not thread-safe by default;
  adds complexity with zero benefit for a sub-50ms sequential operation.

---

## Decision 2: LLM Client — OpenAI SDK with `base_url` Override

**Decision**: Use the `openai` Python SDK (already an optional dep from Phase 2 embeddings)
for all LLM calls in `cerebrofy specify`. Override `base_url` from `config.yaml`'s
`llm_endpoint` to support any OpenAI-compatible endpoint.

**Rationale**: The `openai` SDK supports arbitrary `base_url` via its constructor
(`openai.OpenAI(base_url="...", api_key="...")`). This means `cerebrofy specify` works with
OpenAI, Azure OpenAI, Ollama, LM Studio, Anyscale, Together AI, and any other
OpenAI-compatible server — with zero code changes per provider. The SDK also handles
streaming via `client.chat.completions.create(stream=True)` natively. No new dependency is
introduced — `openai` is already listed as an optional dep in `pyproject.toml`.

**Streaming vs. non-streaming**: The SDK returns a `Stream` object for streaming or a
`ChatCompletion` object for non-streaming. `llm/client.py` inspects the response type and
handles both, satisfying FR-015.

**Retry implementation**: Catch `openai.APIStatusError` (status >= 500) and
`openai.APIConnectionError`; retry exactly once (FR-022). Do not retry on
`openai.RateLimitError` (HTTP 429) or any `openai.BadRequestError` (4xx).

**Alternatives considered**:
- `httpx` direct HTTP client — rejected: verbose for streaming; would need to reimplement
  the SSE parsing that the openai SDK handles correctly.
- `anthropic` SDK — rejected: not OpenAI-compatible; contradicts FR-014.
- `requests` + manual SSE parsing — rejected: no async support, fragile for streaming.

---

## Decision 3: System Prompt Template — String Template with File Override

**Decision**: Use Python's `string.Template` with a `$lobe_context` substitution variable
for the system prompt. The built-in default template is a Markdown string bundled in
`llm/prompt_builder.py`. If `system_prompt_template` is set in `config.yaml`, the file at
that path is loaded and used instead. Template loading happens at command start before any
DB query — a missing file exits immediately (FR-023).

**Rationale**: `string.Template` is stdlib (no new dep), safe (no arbitrary code execution
unlike f-strings on user-supplied content), and supports simple `$variable` substitution
that non-technical users can understand when writing their own templates. The lobe context
is the only injected variable — keeping the template interface minimal.

**Built-in default template structure**:
```
You are a senior software architect with deep knowledge of the following codebase.

## Codebase Context (from Cerebrofy index)

$lobe_context

## Your Task

Generate a structured feature specification for the following feature request.
The spec must reference only real code units shown in the context above.
Format the output as Markdown with sections: Overview, Requirements, Acceptance Criteria.
```

**Alternatives considered**:
- Jinja2 templates — rejected: adds a dependency, overkill for a single variable substitution.
- f-strings on user-supplied template files — rejected: arbitrary code execution risk.
- Hardcoded prompt, no customization — rejected: contradicts FR-023, limits team adoption.

---

## Decision 4: Output File Path — ISO Timestamp with Hyphenated Time Component

**Decision**: Output files are written to `docs/cerebrofy/specs/<timestamp>_spec.md` where
`<timestamp>` is `YYYY-MM-DDTHH-MM-SS` (hyphens replace colons in the time component for
cross-platform filename safety — colons are illegal in filenames on Windows/macOS HFS+).
Collision resolution: if the same timestamp file exists, append `_2`, `_3`, etc. (FR-016).

**Rationale**: ISO 8601 timestamp with hyphenated time gives lexicographically sortable
filenames (oldest spec sorts first) while being valid on all platforms. The `T` separator
between date and time is preserved for readability.

**Alternatives considered**:
- Unix epoch timestamp — rejected: not human-readable in file listings.
- UUID suffix — rejected: not sortable; hides creation time.
- Sequence number (`spec_001.md`) — rejected: requires reading existing files and
  maintaining state; timestamp is simpler and stateless.

---

## Decision 5: `cerebrofy plan --json` Schema Stability

**Decision**: The JSON output of `cerebrofy plan --json` uses stable top-level field names:
`matched_neurons`, `blast_radius`, `affected_lobes`, `reindex_scope`. Each field is always
present even if empty (empty array `[]`). A `schema_version: 1` field is included for
forward compatibility.

**`matched_neurons` entry shape**:
```json
{"id": "auth/validator.py::validate_token", "name": "validate_token",
 "file": "auth/validator.py", "line_start": 42, "similarity": 0.91}
```

**`blast_radius` entry shape**:
```json
{"id": "auth/session.py::create_session", "name": "create_session",
 "file": "auth/session.py", "line_start": 18}
```

**Rationale**: Consumers (CI scripts, IDE plugins, MCP tools) must be able to rely on field
names without version-sniffing. Including `schema_version` allows future additions without
breaking existing consumers. Always-present fields prevent null-checks in downstream tools.

**Alternatives considered**:
- Flat array of all matched + BFS nodes — rejected: loses distinction between KNN-matched
  and BFS-expanded; important for consumers that want only the KNN results.
- Nested `search` / `graph` objects — rejected: over-engineered for four flat fields.

---

## Decision 6: LLM Timeout — Wall-Clock Deadline on Streaming

**Decision**: Apply the `llm_timeout` value (default 60s) as a wall-clock deadline covering
the full response — from initiating the HTTP request to receiving the last streaming token
(or the complete non-streaming response). Implemented as a `threading.Timer` or asyncio
timeout wrapping the openai SDK call. On timeout, the partially-received content is
discarded and the error is raised (no partial file written, per FR-021).

**Rationale**: A per-request timeout covering the full response is the correct model for CLI
tools — the developer gets a clean failure rather than a hung terminal. The `openai` SDK
does not natively expose a streaming timeout (only a connection timeout), so a wrapper
deadline is needed. 60s covers most production LLM responses even for large lobe contexts.

**Alternatives considered**:
- Connection-only timeout (first token) — rejected: large streaming responses could hang
  indefinitely after the first token arrives.
- No timeout (rely on OS TCP keepalive) — rejected: TCP keepalive timers are typically
  minutes; unacceptable for a CLI tool.
