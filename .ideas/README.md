# Cerebrofy Product Ideas

26 ideas + 1 HOW-TO guide for making Cerebrofy the repo-specific mind that every AI
coding agent plugs into. Each folder contains a detailed IDEA.md with feature description,
technical implementation plan, MCP interface schema, slash command spec, integrations with
other ideas, and integration with the current codebase.

**Quick links:** [HOW-TO.md](./HOW-TO.md) — how any AI agent uses Cerebrofy as a persistent mind

---

## All 26 Ideas

### Original 10 — Core Differentiation
| # | Name | One-Line Pitch | Moat | Status |
|---|------|---------------|------|--------|
| [01](./01-semantic-pr-blast-radius/) | Semantic PR Blast Radius | Auto-post PR comment with every caller affected by the change | No competitor shows graph-derived PR risk | 🔵 Planned |
| [02](./02-llm-context-budget-optimizer/) | LLM Context Budget Optimizer | Graph-aware, budget-constrained optimal context window for any task | First formal context packing optimization | 🔵 Planned |
| [03](./03-codebase-health-timeline/) | Codebase Health Timeline | Longitudinal health metrics derived from the call graph on every build | Graph-derived metrics no text tool can compute | 🔵 Planned |
| [04](./04-cross-repo-dependency-graph/) | Cross-Repo Dependency Graph | Unified semantic graph across multiple repos + services | Enterprise platform play | 🔵 Planned |
| [05](./05-ai-agent-memory-layer/) | AI Agent Memory Layer | Agents write structured memories back into the graph | 12-month stickiness moat | 🔵 Planned |
| [06](./06-onboarding-navigator/) | Onboarding Navigator | Graph-topology-derived reading order for new developers | Most viral demo possible | 🔵 Planned |
| [07](./07-refactor-impact-predictor/) | Refactor Impact Predictor | Pre-flight cost prediction before any change is made | Pre-change answer no tool provides | 🔵 Planned |
| [08](./08-vulnerability-blast-radius/) | Vulnerability Blast Radius | Map CVEs to exactly which of YOUR functions are at risk | Security meets call graph | 🔵 Planned |
| [09](./09-knowledge-silo-detector/) | Knowledge Silo Detector | Bus factor risk from git blame overlaid on call graph | C-level metric hiding in dev tool | 🔵 Planned |
| [10](./10-mcp-resource-streaming/) | MCP Resource Streaming | Codebase graph as ambient MCP resources, pushed proactively | Inverts AI tool interaction model | 🔵 Planned |

### Bonus 10 — Platform & Enterprise
| # | Name | One-Line Pitch | Moat | Status |
|---|------|---------------|------|--------|
| [11](./11-live-agent-session-recorder/) | Live Agent Session Recorder | Audit trail of every AI coding session with graph diffs | First AI accountability tool | 🔵 Planned |
| [12](./12-natural-language-refactor-planner/) | NL Refactor Planner | Describe a refactor in English → get a sequenced graph-aware plan | Human-in-loop for safe AI refactors | 🔵 Planned |
| [13](./13-test-coverage-gap-predictor/) | Test Coverage Gap Predictor | Rank uncovered neurons by blast radius × change velocity | Coverage prioritized by actual risk | 🔵 Planned |
| [14](./14-semantic-changelog-generator/) | Semantic Changelog Generator | Changelogs derived from graph changes, not commit messages | First graph-native changelog | 🔵 Planned |
| [15](./15-multi-language-polyglot-graph/) | Multi-Language Polyglot Graph | Unified graph across Python + TypeScript + Rust + Go | Full-stack team unlock | 🔵 Planned |
| [16](./16-architecture-drift-alerts/) | Architecture Drift Alerts | DSL for defining arch rules enforced via graph queries on commit | Graph-semantic ArchUnit for any language | 🔵 Planned |
| [17](./17-ai-review-copilot/) | AI Review Copilot | AI reviewer with blast radius, memories, arch rules, and coverage context | First graph-informed AI reviewer | 🔵 Planned |
| [18](./18-lobe-ownership-governance/) | Lobe Ownership & Governance | Dynamic CODEOWNERS from git blame + call graph topology | Auto-maintained, graph-derived ownership | 🔵 Planned |
| [19](./19-dependency-upgrade-navigator/) | Dependency Upgrade Navigator | Map exactly which of YOUR calls break on a library upgrade | Migration effort computed, not guessed | 🔵 Planned |
| [20](./20-cerebrofy-cloud-sync/) | Cerebrofy Cloud Sync | Sync graph metadata (never source) to cloud for team sharing | "Source never leaves your machine" moat | 🔵 Planned |

### The Agent Mind Layer — 6 New Ideas
*Added after strategic analysis of what's still missing after Ideas #01–#20 to reach true "agent cognition."*

| # | Name | One-Line Pitch | Mind Layer | Status |
|---|------|---------------|-----------|--------|
| [21](./21-insight-daemon/) | Cerebrofy Insight Daemon | Background reasoning that notices things without being asked | Proactive Cognition | 🔵 Planned |
| [22](./22-epistemic-confidence-layer/) | Epistemic Confidence Layer | Every output carries a confidence score and staleness warning | Self-Awareness | 🔵 Planned |
| [23](./23-product-intent-layer/) | Product Intent Layer | Sprint goals, incidents, and priorities give agents judgment | Goal Awareness | 🔵 Planned |
| [24](./24-cross-session-synthesizer/) | Cross-Session Pattern Synthesizer | Learns from patterns across all recorded sessions | Learning from Experience | 🔵 Planned |
| [25](./25-multi-agent-coordination/) | Multi-Agent Coordination Protocol | Multiple agents see each other, claim neurons, resolve conflicts | Social Cognition | 🔵 Planned |
| [26](./26-narrative-memory-engine/) | Codebase Narrative Engine | The story of the codebase — how it evolved and where it's going | Narrative Identity | 🔵 Planned |

---

## Build Priority Matrix

### Tier 1 — Ship First (highest viral + lowest effort)
| Idea | Why Now |
|------|---------|
| #07 Refactor Impact Predictor | Low effort, reuses existing BFS, immediately useful for every developer |
| #03 Codebase Health Timeline | Low effort (metrics already computable), makes every build more valuable |
| #06 Onboarding Navigator | Medium effort, highest virality — best demo moment |

### Tier 2 — Core Platform Features
| Idea | Why Next |
|------|---------|
| #01 Blast Radius (PR) | Medium effort, unlocks enterprise adoption |
| #02 Context Optimizer | Medium effort, makes Cerebrofy "the context layer" |
| #16 Architecture Drift Alerts | Medium effort, turns Cerebrofy into team infrastructure |

### Tier 3 — Moat Features (6–18 months)
| Idea | Why Later |
|------|---------|
| #05 Agent Memory Layer | High effort, 12-month stickiness moat |
| #20 Cloud Sync | High effort, unlocks business model and team features |
| #04 Cross-Repo Graph | High effort, enterprise only |

### Tier 4 — Platform Completers
Ideas that compound on Tier 1–3 engines (BFS, semantic search, memories, health metrics):
08 · 09 · 10 · 11 · 12 · 13 · 14 · 15 · 17 · 18 · 19

### Tier 1 additions — start these immediately alongside Tier 1
| Idea | Why Now |
|------|---------|
| #22 Epistemic Confidence | Zero deps — cross-cutting amendment to every tool. Adds confidence scores from day one. |
| #23 Product Intent | Zero deps — one new config file. Gives every answer team context immediately. |

### Tier 5 — Agent Mind Layer
Ideas that give Cerebrofy genuine cognitive capabilities. Require Tiers 1–3 to be solid
before building — they synthesize across everything below them.

| Idea | Requires | Why This Tier |
|------|----------|--------------|
| #25 Multi-Agent Coordination | #05 (memory, conflict detection) | Can build as soon as memory layer exists |
| #24 Cross-Session Synthesizer | #05 + #11 | Reads sessions, writes patterns back as memories |
| #21 Insight Daemon | #03 + #05 + #09 + #11 + #16 | Orchestrates all analysis layers — build last |
| #26 Narrative Engine | #03 + #05 + #14 + #23 | Final cognitive layer — synthesises everything |

---

## Build Dependency Order

Features that must be completed before others can be built.

### Dependency Graph

| Feature | Depends On | Can Build Independently | Implemented |
|---------|-----------|------------------------|-------------|
| #01 Blast Radius | — | ✅ Yes | ⬜ Not started |
| #02 Context Optimizer | — | ✅ Yes | ⬜ Not started |
| #03 Health Timeline | — | ✅ Yes | ⬜ Not started |
| #04 Cross-Repo | — (new workspace concept) | ✅ Yes | ⬜ Not started |
| #05 Agent Memory | — | ✅ Yes | ⬜ Not started |
| #06 Onboarding | #03 (health for safe zones), #05 (warnings) | Partial: works without #03/#05 | ⬜ Not started |
| #07 Refactor Impact | #01 (BFS engine) | ✅ Yes (BFS is shared code) | ✅ Done |
| #08 Vulnerability | #01 (BFS engine), #05 (optional: write memories) | ✅ Yes | ⬜ Not started |
| #09 Knowledge Silo | — | ✅ Yes | ⬜ Not started |
| #10 MCP Resources | #03 (health resource), #05 (memory resource) | Partial | ⬜ Not started |
| #11 Session Recorder | — | ✅ Yes | ⬜ Not started |
| #12 NL Refactor Planner | #07 (impact for sequencing) | ✅ Yes (degrades without #07) | ⬜ Not started |
| #13 Coverage Gaps | #01 (blast radius for scoring) | ✅ Yes | ⬜ Not started |
| #14 Semantic Changelog | #05 (memories for "why"), #03 (health delta) | Partial | ⬜ Not started |
| #15 Polyglot Graph | — (new .scm files) | ✅ Yes | ⬜ Not started |
| #16 Arch Drift Alerts | — | ✅ Yes | ⬜ Not started |
| #17 AI Review Copilot | #01, #05, #07, #13, #16 | ❌ No — orchestrates others | ⬜ Not started |
| #18 Lobe Governance | #09 (silo data for ownership) | ✅ Yes (degrades without #09) | ⬜ Not started |
| #19 Dependency Upgrade | #07 (impact sequencing), #01 (blast radius) | ✅ Yes | ⬜ Not started |
| #20 Cloud Sync | All others (syncs their artifacts) | ✅ Yes (partial sync) | ⬜ Not started |
| #21 Insight Daemon | #03, #05, #09, #11, #16 | ❌ No — reads all others | ⬜ Not started |
| #22 Epistemic Confidence | — | ✅ Yes (cross-cutting amendment to all tools) | ⬜ Not started |
| #23 Product Intent | — | ✅ Yes (new config file, zero dependencies) | ⬜ Not started |
| #24 Cross-Session Synthesizer | #05 (writes memories), #11 (reads sessions) | ❌ No | ⬜ Not started |
| #25 Multi-Agent Coordination | #05 (conflict detection) | ✅ Yes (degrades without #05) | ⬜ Not started |
| #26 Narrative Engine | #03, #05, #14, #23 | ❌ No — synthesizes others | ⬜ Not started |

### Recommended Build Waves

**Wave 1 — Independent Foundations** (build in any order, all standalone)
- #01 Semantic PR Blast Radius
- #03 Codebase Health Timeline
- #07 Refactor Impact Predictor
- #09 Knowledge Silo Detector
- #16 Architecture Drift Alerts
- #05 Agent Memory Layer
- #11 Live Agent Session Recorder
- #22 Epistemic Confidence (cross-cutting, zero deps — amend all tools immediately)
- #23 Product Intent (new config file, zero deps — add early for intent-aware answers)

**Wave 2 — Compound Features** (require Wave 1 output)
- #02 LLM Context Optimizer (benefits from #01 as seed)
- #06 Onboarding Navigator (#03 + #05)
- #08 Vulnerability Blast Radius (#01 BFS + #05 memories)
- #13 Test Coverage Gap Predictor (#01 blast radius)
- #14 Semantic Changelog (#05 + #03)
- #18 Lobe Ownership Governance (#09)
- #19 Dependency Upgrade Navigator (#07 + #01)
- #25 Multi-Agent Coordination (needs #05 for conflict detection)

**Wave 3 — Orchestrators** (require Wave 1 + 2)
- #12 NL Refactor Planner (#07)
- #17 AI Review Copilot (#01 + #05 + #07 + #13 + #16)
- #24 Cross-Session Synthesizer (needs #05 + #11)
- #21 Insight Daemon (needs #03 + #05 + #09 + #11 + #16)

**Wave 4 — Platform Layer** (require most of Wave 1-3)
- #04 Cross-Repo Dependency Graph
- #10 MCP Resource Streaming (#03 + #05 resources)
- #15 Multi-Language Polyglot Graph
- #20 Cerebrofy Cloud Sync (syncs all artifacts)
- #26 Narrative Engine (needs #03 + #05 + #14 + #23)

---

## Agent Mind Layer — Coverage Map

After implementing all 26 ideas, Cerebrofy covers every cognitive layer required for an
AI agent to operate with genuine codebase intelligence:

| Cognitive Layer | Status | Covered By |
|----------------|--------|-----------|
| Semantic Memory (what the code is) | ✅ Full | Core graph + all 20 features |
| Episodic Memory (what happened) | ✅ Full | #11 Session Recorder |
| Procedural Memory (how to do things) | ✅ Full | #12 Refactor Planner, #19 Upgrade Navigator |
| Long-term Memory (decisions, patterns) | ✅ Full | #05 Agent Memory Layer |
| Causal Memory (why things happened) | ✅ Full | #05 Phase 2 — memory_edges |
| Memory Decay (forgetting stale knowledge) | ✅ Full | #05 Phase 3 — decay_score |
| Attention / Focus | ✅ Full | #02 Context Optimizer |
| Epistemic Self-Awareness | ✅ Full | #22 Epistemic Confidence Layer |
| Proactive Cognition | ✅ Full | #21 Insight Daemon |
| Goal Awareness | ✅ Full | #23 Product Intent Layer |
| Learning from Experience | ✅ Full | #24 Cross-Session Synthesizer |
| Social Cognition (other agents) | ✅ Full | #25 Multi-Agent Coordination |
| Narrative Identity | ✅ Full | #26 Narrative Engine |
| Domain Ontology (business meaning) | ⚠️ Partial | #23 intent.yaml + #05 memories |
| Emotional/Priority Modeling | ⚠️ Partial | #23 Product Intent (sprint urgency) |
| Predictive Modeling | ⚠️ Partial | #21 Insight Daemon (trend_alert type) |

---

## How the Ideas Connect

```
                    ┌─────────────────────────────┐
                    │   FOUNDATION LAYER           │
                    │  (current codebase)          │
                    │  nodes, edges, vec_neurons   │
                    │  search/hybrid.py            │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┼─────────────────┐
              ▼                ▼                  ▼
      ┌──────────────┐  ┌─────────────┐  ┌─────────────────┐
      │  ANALYSIS    │  │  KNOWLEDGE  │  │  ENFORCEMENT    │
      │  #01 Blast   │  │  #05 Memory │  │  #16 Arch Rules │
      │  #07 Impact  │  │  #09 Silos  │  │  #18 Governance │
      │  #13 Coverage│  │  #11 Session│  │  #08 Vuln Map   │
      │  #03 Health  │  │  #14 Change │  └─────────────────┘
      └──────┬───────┘  └─────┬───────┘
             │                │
             └────────┬───────┘
                      ▼
              ┌───────────────────┐
              │  INTELLIGENCE     │
              │  #02 Context Opt  │
              │  #12 NL Planner   │
              │  #17 AI Review    │
              │  #06 Onboarding   │
              └───────┬───────────┘
                      │
              ┌───────▼───────────┐
              │  PLATFORM         │
              │  #04 Cross-Repo   │
              │  #10 MCP Resources│
              │  #15 Polyglot     │
              │  #19 Dep Upgrade  │
              │  #20 Cloud Sync   │
              └───────┬───────────┘
                      │
              ┌───────▼─────────────────────────────┐
              │  AGENT MIND LAYER                    │
              │  #22 Epistemic  ← knows its limits   │
              │  #23 Intent     ← knows team goals   │
              │  #25 Coord      ← knows other agents │
              │  #24 Synthesize ← learns from past   │
              │  #21 Insight    ← thinks proactively │
              │  #26 Narrative  ← knows its history  │
              └──────────────────────────────────────┘
```

---

## Files in This Directory

- **[HOW-TO.md](./HOW-TO.md)** — practical guide for Claude, Copilot, OpenCode, and Antigravity
  on how to use Cerebrofy as a repo-specific mind. Covers the 5-step golden workflow,
  7 concrete walkthroughs, token savings benchmarks, agent-specific setup, and full tool index.

- **`XX-<name>/IDEA.md`** — one folder per idea (26 total), each containing:
  - Problem statement and competitive context
  - Feature description with CLI commands and output examples
  - Technical implementation plan with new modules and algorithms
  - MCP Interface — full JSON input/output schema, error codes, transport
  - Slash Command — supported AI clients, skill file paths, agent invocation pattern
  - Integration tables (other ideas + current codebase)
  - Competitive moat

This directory is gitignored. Do not commit.
