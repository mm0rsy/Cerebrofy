# Quickstart: Phase 4 — AI Bridge

**Feature**: 004-ai-bridge
**Date**: 2026-04-04

---

## Prerequisites

Phase 4 requires:
- A valid `cerebrofy.db` built by Phase 2 (`cerebrofy build`)
- Phase 3 `cerebrofy update` and `cerebrofy validate` verified working
- `config.yaml` with `llm_endpoint` and `llm_model` configured (for `cerebrofy specify` only)
- The LLM API key set in your shell environment

---

## Setup

### 1. Verify your index is current

```bash
cerebrofy validate
# "Cerebrofy: Index is clean." — ready to proceed
# If structural drift: run cerebrofy update first
```

### 2. Configure LLM endpoint in config.yaml

```yaml
# .cerebrofy/config.yaml
llm_endpoint: "https://api.openai.com/v1"
llm_model: "gpt-4o"
llm_timeout: 60          # optional; default 60 seconds
top_k: 10                # optional; KNN results count
```

For Ollama (local): `llm_endpoint: "http://localhost:11434/v1"`  
For Azure OpenAI: `llm_endpoint: "https://<your-resource>.openai.azure.com/openai/deployments/<model>"`

### 3. Set your API key

```bash
export OPENAI_API_KEY="sk-..."
# For other providers: set the appropriate key for your endpoint
```

---

## Using `cerebrofy plan` (offline, no API key needed)

Understand the impact area before writing any code:

```bash
cerebrofy plan "add OAuth2 login support"
```

Output: Matched Neurons with similarity scores, Blast Radius (depth-2 structural neighbors),
Affected Lobes, and Re-index Scope — all sourced from your local index.

```bash
# Machine-readable output for CI scripts or IDE plugins
cerebrofy plan --json "add OAuth2 login support"

# Adjust KNN results count
cerebrofy plan --top-k 20 "add rate limiting to API endpoints"
```

---

## Using `cerebrofy tasks` (offline, no API key needed)

Get a numbered implementation checklist:

```bash
cerebrofy tasks "add OAuth2 login support"
```

Output: Numbered task list ordered by relevance. Each item identifies the exact Neuron to
modify, its lobe location, and the blast radius of that specific change.

```bash
# Narrow to top 5 most relevant code units
cerebrofy tasks --top-k 5 "add rate limiting"
```

---

## Using `cerebrofy specify` (requires LLM)

Generate an AI-grounded feature spec:

```bash
cerebrofy specify "add OAuth2 login support"
```

What happens:
1. Hybrid search (local, ~50ms) finds relevant Neurons and their lobe context
2. Search summary printed to stderr (so you can see what context was sent)
3. LLM receives only the relevant lobe `.md` files — not your raw source code
4. Spec is streamed to stdout and saved to `docs/cerebrofy/specs/<timestamp>_spec.md`

```bash
# Fewer KNN results = smaller LLM context (faster, cheaper)
cerebrofy specify --top-k 5 "add rate limiting to API endpoints"
```

---

## Custom System Prompt

Override the built-in prompt template with your own:

```yaml
# .cerebrofy/config.yaml
system_prompt_template: ".cerebrofy/my-spec-template.txt"
```

Template format (Python `string.Template`):

```text
You are an expert developer familiar with this codebase.

## Relevant Code Context

$lobe_context

## Task

Generate a detailed implementation plan for: {the user's description will go here}
```

The only substitution variable is `$lobe_context` — the concatenated lobe Markdown files.

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `No index found. Run 'cerebrofy build' first.` | Missing `cerebrofy.db` | Run `cerebrofy build` |
| `Schema version mismatch.` | Outdated DB schema | Run `cerebrofy migrate` |
| `Embedding model mismatch` | Config changed since last build | Run `cerebrofy build` |
| `No relevant code units found.` | Description too abstract | Use more specific terms |
| `LLM request timed out after 60s.` | Slow endpoint or large context | Increase `llm_timeout` or reduce `top_k` |
| `Error: LLM rate limit exceeded` | API quota hit | Wait and retry manually |
| `system_prompt_template file not found` | Missing template file | Check path in `config.yaml` |

---

## Output Files

Spec files are written to `docs/cerebrofy/specs/` with ISO timestamp filenames:

```
docs/cerebrofy/specs/
├── 2026-04-04T14-32-07_spec.md
├── 2026-04-04T14-35-22_spec.md
└── 2026-04-04T14-35-22_2_spec.md   ← collision suffix (two calls at same second)
```

These files are committed to git. They serve as a record of AI-assisted planning sessions
grounded in real codebase state at a specific `state_hash`.

---

## Key Invariants

- `cerebrofy plan` and `cerebrofy tasks` make zero network calls — safe offline, in air-gapped environments, or in CI
- `cerebrofy specify` writes only to `docs/cerebrofy/specs/` — your source files and index are never modified
- The LLM receives only pre-generated lobe `.md` files, not raw source code
- Concurrent `cerebrofy specify` calls are safe — each writes a unique timestamped file
