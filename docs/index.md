# 🧠 Cerebrofy

**AI-powered codebase intelligence CLI.**  
Cerebrofy indexes your repository into a local graph + vector database, then exposes it to AI assistants via MCP — letting them navigate your codebase with surgical precision instead of reading entire files. Zero code uploaded to any server.

```
cerebrofy init && cerebrofy build
# → Parses, graphs, embeds — one local index, ready for AI tools
cerebrofy validate
# → clean
```

---

## What Cerebrofy Does

When you ask an AI agent to help with a feature in a real codebase, the naive approach is to dump files into the context window. That approach has three problems:

- **Cost**: a 20,000 LOC codebase is ~600,000 tokens per query
- **Noise**: the LLM reads code that is irrelevant to the task
- **Hallucination**: without structural grounding, the LLM guesses at call relationships and import paths

Cerebrofy solves this by pre-computing a structural + semantic index of your code. Instead of dumping files, it gives the LLM exactly what it needs:

| What the LLM receives | Token count | How it's selected |
|-----------------------|-------------|-------------------|
| 10 matched Neuron signatures | ~500 tokens | KNN cosine similarity search |
| Their depth-2 call graph | ~800 tokens | BFS over the `edges` table |
| 2–3 pre-written lobe summaries | ~8,000 tokens | Affected lobe `.md` files |
| **Total** | **~10,000 tokens** | vs. ~600,000 for raw files |

**~97% token reduction** on a typical mid-size codebase. The LLM gets a precise, grounded, zero-hallucination view of the code it actually needs — not a random 20-file dump.

## How It Works

Cerebrofy builds a **structural + semantic index** of your code in one SQLite file (`.cerebrofy/db/cerebrofy.db`):

1. **Parse** — Tree-sitter extracts named functions, classes, and modules as *Neurons*
2. **Graph** — Call relationships become typed edges (`LOCAL_CALL`, `EXTERNAL_CALL`, `IMPORT`, `RUNTIME_BOUNDARY`)
3. **Embed** — Each Neuron is embedded into a `sqlite-vec` vector table for semantic search
4. **Query** — Hybrid search (KNN cosine + BFS depth-2) finds affected code units for any description
5. **Expose** — An MCP stdio server lets AI clients trigger builds, run drift checks, and update the index

No cloud index. No code upload. One file, one connection.

## Platform Support

Cerebrofy runs on **Linux**, **macOS**, and **Windows**. All commands behave identically across platforms with one prerequisite difference:

| Platform | Prerequisites | Notes |
|---|---|---|
| Linux / macOS | Python 3.11+, Git | No extra setup |
| Windows | Python 3.11+, **[Git for Windows](https://git-scm.com/download/win)** | Required for git hook execution (MSYS bash) |

> **Windows users:** Install [Git for Windows](https://git-scm.com/download/win) before running `cerebrofy init`. Git for Windows bundles MSYS bash, which is what runs the installed git hooks. Without it, `cerebrofy init` succeeds but the pre-commit / pre-push / post-merge hooks will not fire.

## Quick Start

**Three commands, then git handles everything automatically:**

```bash
# Step 1 — one time per repo
cerebrofy init

# Step 2 — one time after init (takes ~30s on a typical codebase)
cerebrofy build

# Step 3 — optional: wire your AI client so it uses the index instead of reading files
cerebrofy init --ai claude      # writes navigation rules to CLAUDE.md
cerebrofy init --ai copilot     # writes rules to .github/copilot-instructions.md
cerebrofy init --ai opencode    # writes rules to .opencode/instructions.md
```

**That's it.** From here, `cerebrofy update` runs automatically on every `git commit` (via the installed pre-commit hook) and the index is validated before every `git push`. You never need to run `cerebrofy update` manually.

```
your workflow:
  code → git commit  →  index auto-updated  ✓
                ↓
           git push   →  index validated     ✓
```

> **First time on a new machine?** After cloning a repo that already has cerebrofy:
> ```bash
> cerebrofy init   # re-installs hooks
> cerebrofy build  # builds your local index from scratch
> ```

## Documentation

This site is organized into the following sections:

### [Getting Started](./getting-started/)
- [Installation](./getting-started/installation.md) — `uv`, `pip`, `pipx`, from source; platform support
- [Quick Start](./getting-started/quickstart.md) — three commands, git hooks, multi-developer workflow
- [Configuration](./getting-started/configuration.md) — `.cerebrofy/config.yaml` schema, field reference, ignore files

### [Concepts](./concepts/)
- [Architecture](./concepts/architecture.md) — module map, data flow, invariants, Neuron, edge types, hybrid search
- [Cognitive Layers](./concepts/cognitive-layers.md) — lobes, lobe summaries, auto-detection
- [Memory Model](./concepts/memory-model.md) — structured memories, types, persistence, decay
- [Sessions](./concepts/sessions.md) — agent session recording, replay, audit trail

### [Features](./features/)
- [Blast Radius](./features/blast-radius.md) — caller traversal, risk scoring
- [Health](./features/health.md) — longitudinal codebase health metrics
- [Memory](./features/memory.md) — write and query structured memories
- [Sessions](./features/sessions.md) — record, replay, and audit AI agent sessions
- [Synthesizer](./features/synthesizer.md) — cross-session pattern detection (Idea #24)
- [Narrative](./features/narrative.md) — codebase narrative engine (Idea #26)
- [Insights](./features/insights.md) — insight daemon, trend alerts
- [Changelog](./features/changelog.md) — semantic changelog from the call graph
- [Coordination](./features/coordination.md) — multi-agent coordination protocol
- [Governance](./features/governance.md) — lobe ownership, CODEOWNERS, reviewers
- [Silo Detection](./features/silo-detection.md) — knowledge silo detection, bus factor
- [Upgrade](./features/upgrade.md) — dependency upgrade navigator
- [Coverage Gap](./features/coverage-gap.md) — test coverage gap predictor
- [Vulnerability](./features/vulnerability.md) — vulnerability blast radius
- [Onboarding](./features/onboarding.md) — personalized onboarding guide
- [Review](./features/review.md) — graph-aware AI review copilot
- [Security](./features/security.md) — security model and guarantees

### [Reference](./reference/)
- [CLI](./reference/cli.md) — complete command reference
- [MCP Tools](./reference/mcp-tools.md) — all 39 MCP tools and resources
- [Config](./reference/config.md) — configuration schema quick reference
- [Schema](./reference/schema.md) — database schema and transaction model

### [Development](./development/)
- [Contributing](./development/contributing.md) — architecture guide, lint, type check
- [Testing](./development/testing.md) — unit and integration tests
- [Releasing](./development/releasing.md) — release process

---

## License

MIT