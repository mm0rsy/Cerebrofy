# Cerebrofy Competitive Market Research Report

**Date:** June 2026 | **Research Scope:** Global codebase intelligence / LLM context tool landscape

---

## Executive Summary

1. **Cerebrofy enters a crowded but rapidly fragmenting market.** In 2025-2026, at least 40+ tools emerged specifically to reduce token waste in AI-assisted coding — spanning flat-file packers, symbol-index MCP servers, knowledge graph engines, and cloud-hosted semantic search platforms. The most direct analogues (CodeGraph, Codebase-Memory, code-graph-mcp, GitNexus, Srclight) all share Cerebrofy's core architecture: tree-sitter AST → SQLite graph → MCP exposure.

2. **The "97% token reduction" claim is directionally defensible but methodologically unverified.** The only controlled benchmark using similar language (grepai, 2025) achieved 97% reduction in *fresh input tokens* on one TypeScript codebase, but actual cost savings were only 27.5% because cached tokens dominate real sessions. Headroom achieves 87.6% on code compression; CodeGraph reports 47-64% fewer tokens in vendor benchmarks. A fair Cerebrofy benchmark would need to compare identical multi-task sessions across 3+ language codebases and measure total tokens (not just uncached input tokens).

3. **Cerebrofy's strongest differentiators** are its Python-native ecosystem (vs. the TypeScript/Rust/Go dominance of competitors), its ONNX offline embedding via fastembed (no Ollama dependency unlike Srclight), and its atomic build + partial re-index pipeline with Law-level architectural discipline. However, CodeGraph (48.8k stars, MIT, 20+ languages, zero embeddings required) and Codebase-Memory (66 languages, sub-second queries, statically-linked binary) are technically superior on most dimensions today.

4. **MCP native is no longer a differentiator** — it is the price of entry. Every serious competitor now ships an MCP server. The real differentiator is CWD routing (one server, many repos) which Cerebrofy has and most competitors do not clearly implement.

5. **Critical gaps:** Cerebrofy's 5 stub MCP tools (search_code, get_neuron, list_lobes, plan, tasks) are unimplemented; competitors ship these capabilities today. Language support (~tree-sitter-languages coverage) needs explicit documentation; CodeGraph claims 20+ and Codebase-Memory claims 66 languages.

---

## Competitor Table

| Tool | Category | Approach | Stars (Jun 2026) | Open Source? | Key Diff vs Cerebrofy |
|---|---|---|---|---|---|
| **CodeGraph** | Knowledge Graph + MCP | Tree-sitter → SQLite FTS5, no embeddings | 48,800 | MIT | 20+ languages, 8-agent MCP, no embeddings needed, far higher adoption |
| **GitNexus** | Knowledge Graph + MCP | Tree-sitter → LadybugDB, BM25+vectors+RRF | ~41,000† | PolyForm NC | Cross-repo groups, Leiden community clustering; non-commercial only |
| **Codebase-Memory** | Knowledge Graph + MCP | Tree-sitter → SQLite, 66 languages, statically linked | ~900 (4 wks) | MIT | 66 languages, 14 MCP tools, LSP-type resolution for C/C++/Go |
| **code-graph-mcp** | Knowledge Graph + MCP | Tree-sitter → SQLite+FTS5+sqlite-vec, Rust | 44 | Apache 2.0 | Same stack as Cerebrofy (Rust), BLAKE3 Merkle tree, 95% line reduction |
| **Serena** | LSP-powered MCP | Language Server Protocol → symbol index | 25,200 | MIT | IDE-grade "go to definition" / "find references"; 30+ languages; no AST graph build needed |
| **Srclight** | Hybrid Search MCP | SQLite FTS5 + tree-sitter + optional embeddings | 46 | MIT | 42 tools, FTS5 trigram+stemmed+semantic, GPU optional, 11 languages |
| **Repomix** | Context Packer | Tree-sitter compression → flat file | 26,200 | MIT | 70% token reduction, 255k npm/month downloads; point-in-time, no live queries |
| **code2prompt** | Context Packer | Template-based repo → prompt (Rust) | 7,400 | MIT | Fastest CLI, Handlebars templates, git diffs; no graph/edges |
| **gpt-repository-loader** | Context Packer | Simple file concatenation | ~4,500 | MIT | Oldest; simplest; no filtering intelligence |
| **Aider (repomap)** | Dynamic Repo Map | tree-sitter + PageRank → token-budgeted map | Built-in | Apache 2.0 | 130+ languages, dynamic per-chat; no persistent store; no MCP |
| **Greptile** | Cloud Semantic Search | Knowledge graph + vector embeddings (cloud) | N/A (SaaS) | No (API) | PR review focus; enterprise; cloud-hosted; no local storage |
| **Sourcegraph Cody** | Cloud/Enterprise RAG | SCIP code graph + vector embeddings | N/A (SaaS) | Partial | Enterprise scale; Cody Free discontinued Jul 2025; SCIP is deeper than AST |
| **Cursor (indexing)** | Editor-embedded | Chunked embeddings → Turbopuffer (cloud) | N/A (product) | No | Deep IDE integration; 12.5% accuracy gain over grep; cloud-stored vectors |
| **Augment Code Context Engine** | Cloud Context API | Custom embeddings + RAG, MCP-exposed | N/A (SaaS) | No | 70%+ agent quality gain; 500k files; processes commit history |
| **Headroom** | Proxy Compression | AST boilerplate collapse + Brotli proxy | 15,000 | MIT | 87.6% token reduction; transparent proxy; not a persistent graph |
| **token-optimizer-mcp** | MCP Cache Layer | Brotli + SQLite cache layer | ~200 | MIT | 95% reduction on cache hits; general-purpose, not code-specific |
| **CodeQL** | Security SAST | Relational DB (QL language), dataflow | N/A (GitHub) | Partial | Security/vuln focus; not for AI context navigation |
| **Semgrep** | Security SAST | Pattern-matching + AI rules | N/A (SaaS) | Partial | SAST not context navigation; different use case |
| **universal-ctags** | Symbol Index | C-based tag generator, regex-based | ~4,100 | GPL-2 | No graph edges; no embeddings; editor "go to def" only |
| **Sourcetrail** | Visual Code Explorer | AST graph + visual UI (deprecated 2021) | ~14,000 | GPL | Deprecated; community fork active Dec 2025; UI-first, no MCP/AI |

†GitNexus: ~4.7k stars confirmed real; remainder may include inflated count per maintainer admission.

---

## Deep-Dives: Top 8 Closest Competitors

### 1. CodeGraph

**Website:** codegraph.codes | **Stars:** 48,800 (Jan 2026 launch — fastest-growing tool in space)

**Technical architecture:** Tree-sitter parses source into ASTs; language-specific `.scm` queries extract symbols (functions, classes, methods) and edges (calls, imports, inheritance); everything lands in a local SQLite DB with FTS5 full-text search. OS-native file watchers (FSEvents/inotify) trigger incremental re-index with 2s debounce. *No embeddings, no vector DB, no API keys required.*

**MCP integration:** 8 agent integrations (Claude Code, Cursor, Codex CLI, opencode, Gemini CLI, Hermes Agent, Antigravity IDE, Kiro). Single `codegraph install` step auto-configures all detected agents.

**Benchmarks (vendor, median of 7 codebases):**
- VS Code (TypeScript, ~10k files): 64% fewer tokens, 81% fewer tool calls
- Alamofire (Swift): 64% fewer tokens, 58% fewer tool calls
- Median across all: 47% fewer tokens, 58% fewer tool calls, 16% cost reduction

**Differentiators vs Cerebrofy:**
- Far higher adoption (48.8k vs Cerebrofy's minimal public presence)
- No embedding dependency (pure graph navigation — faster cold start)
- Cross-language bridges (Swift↔ObjC, React Native↔TurboModules)
- 8 agents vs Cerebrofy's MCP-only approach
- MIT license vs Cerebrofy's Python-only CLI
- Gap: No semantic/vector search (pure structural); Cerebrofy has fastembed for hybrid

---

### 2. GitNexus

**Stars:** ~41k reported (maintainer acknowledged inflation); **License:** PolyForm Noncommercial

**Architecture:** Multi-phase pipeline: file structure → tree-sitter AST → cross-file import resolution → Leiden community detection clustering → execution flow tracing. Storage in LadybugDB (embedded graph DB, formerly KuzuDB). Hybrid search via BM25 + vector embeddings + Reciprocal Rank Fusion.

**MCP tools:** 7 tools including `impact` (blast radius with confidence scoring), `cypher` (raw graph queries), `detect_changes` (git-diff risk), `rename` (multi-file coordinated refactoring), and `list_repos` (multi-repository support).

**Token claims:** Production audit: "88% fewer tool calls, 74% token savings." Smaller models (GPT-4o-mini) can navigate large codebases via precomputed clarity.

**Differentiators vs Cerebrofy:**
- Leiden community clustering groups related code modules automatically
- Multi-repo support out of the box
- RRF hybrid search (BM25 + vectors) vs Cerebrofy's single-model fastembed
- Cross-repo impact analysis
- Gap: PolyForm NC license is commercially restrictive; community maintainer concentration risk; inflated star count concerns trust

---

### 3. Codebase-Memory

**Paper:** arXiv:2603.27277 | **Stars:** ~900 (4 weeks from Feb 2026 launch)

**Architecture:** Statically-linked C binary (zero external dependencies). Three-stage pipeline: (1) Tree-sitter across **66 languages** extracts definitions + calls + imports + references with signatures/return types/decorators/complexity; (2) Multi-phase parallel build pipeline to single SQLite file; (3) MCP server exposes 14 structural query tools.

**Key performance:** Django indexing (49K nodes, 196K edges) in ~6 seconds; query latency <1ms; **10x fewer tokens vs file exploration**; 2.1x fewer tool calls. XXH3 content hashing enables incremental re-index at ~4x speedup.

**Differentiators vs Cerebrofy:**
- 66 languages vs Cerebrofy's tree-sitter-languages coverage
- LSP-style type resolution for Go/C/C++ (method receivers, pointer indirection)
- Statically-linked binary (no Python runtime dependency)
- 14 MCP tools vs Cerebrofy's 3 operational (5 stubbed)
- 8-layer CI security audit (SLSA provenance, VirusTotal, network egress monitoring)
- Gap: No embeddings/semantic search; newer project with less production validation

---

### 4. code-graph-mcp

**GitHub:** sdsrss/code-graph-mcp | **Stars:** 44 | **License:** Apache 2.0 | **Language:** Rust

**Architecture:** Tree-sitter AST parsing; SQLite with FTS5 + **sqlite-vec** for vector similarity (same stack as Cerebrofy). BLAKE3 Merkle tree for incremental re-indexing (skips unchanged subtrees). 16 languages with full extraction for TypeScript/JS/Go/Python/Rust/Java.

**Claims:** "5-20x fewer tokens per code understanding task"; benchmarks show **95% reduction in source lines read into context** and 80% fewer tool invocations; transitive call tracing in single query vs 8-15 manual tool calls.

**Differentiators vs Cerebrofy:**
- Written in Rust (better performance characteristics than Python)
- BLAKE3 Merkle tree (more granular than file-hash comparison)
- HTTP route tracing for web frameworks built-in
- Impact analysis tool showing "change X affects 33 functions across 4 files"
- 173 releases in rapid cadence (v0.50.0 as of Jun 2026)
- Gap: 44 stars only; smaller community; TypeScript/JS ecosystem focus; no Python SDK

---

### 5. Serena

**GitHub:** oraios/serena | **Stars:** 25,200 | **License:** MIT

**Architecture:** LSP (Language Server Protocol) backend — delegates to existing language servers rather than building its own AST graph. Provides "IDE-grade go-to-definition and find-all-references" via MCP. No pre-built graph; relies on LSP's real-time index.

**Languages:** 30+ (any language with an LSP server).

**Differentiators vs Cerebrofy:**
- Zero-build approach: leverages existing LSP infrastructure; instant "ready" after LSP startup
- Higher accuracy for type-aware navigation (LSP resolves types dynamically vs static AST)
- 25.2k stars — 2nd highest in the space
- No persistent graph DB to maintain; always reflects current state
- Gap: Requires running language servers (heavier process overhead); no call-graph traversal for impact analysis; no vector/semantic search; no MCP query tools for graph topology

---

### 6. Srclight

**GitHub:** srclight/srclight | **Stars:** 46 | **License:** MIT | **Language:** Python

**Architecture:** Python 3.11+, SQLite with three specialized FTS5 indexes (symbol names, trigram source, Porter stemmer docstrings) + optional Ollama/Voyage embeddings for semantic layer. Tree-sitter for 11 languages. 42 MCP tools across 7 tiers including git blame, hotspot analysis, community detection, impact analysis, and document extraction (PDF, DOCX, XLSX).

**Differentiators vs Cerebrofy:**
- **42 tools** vs Cerebrofy's 8 registered (3 operational)
- Document ingestion (PDF, DOCX, XLSX, images with OCR) — unique in class
- Multi-repo workspaces via SQLite ATTACH+UNION
- Git intelligence (blame, hotspots)
- Community detection for code clustering
- GPU-accelerated semantic search (optional CUDA)
- SSE transport (persistent connections) vs stdio only
- Gap: Ollama/Voyage required for semantic search (vs Cerebrofy's bundled fastembed); smaller community; 11 languages; Python startup overhead

---

### 7. Repomix

**GitHub:** yamadashy/repomix | **Stars:** 26,200 | **License:** MIT | **Downloads:** ~255k npm/month

**Architecture:** Packs entire repositories into a single AI-friendly file (XML, Markdown, JSON, plain text). Tree-sitter `--compress` option achieves ~70% token reduction by extracting code signatures while stripping function bodies. Secretlint scanning for secrets.

**Differentiators vs Cerebrofy:**
- Massive adoption (26.2k stars, 255k npm/month) — de facto standard for context packing
- Browser-based web UI for zero-install use
- GitHub Actions integration for CI pipelines
- Point-in-time packing (not live graph) — simpler mental model
- Gap: Flat-file output; no graph queries; no incremental updates; no semantic search; no edges. Entire-repo approach hits limits at large monorepos

---

### 8. Aider (RepoMap)

**GitHub:** Aider-AI/aider | **Stars:** ~24,000 | **License:** Apache 2.0

**Architecture:** tree-sitter parses all files; extracts definitions and references; builds a graph where nodes = files and edges = symbol dependencies; applies PageRank to rank symbols by cross-file reference frequency; fits top-ranked symbols into a configurable token budget. Dynamic per-chat — regenerated on each conversation.

**Scale:** Processes 15 billion tokens/week; 130+ languages.

**Differentiators vs Cerebrofy:**
- 130+ language support
- PageRank importance ranking (globally important symbols vs local relevance)
- Zero persistent storage — no DB to maintain or migrate
- Token-budget-aware: never exceeds allocation
- Gap: No persistent graph DB; no semantic vector search; no MCP; designed as chat context, not standalone index

---

## Token Reduction Claim Analysis

### The "97% token reduction" claim

**Origin:** The figure appears in at least two contexts: (1) the grepai benchmark (Feb 2025) comparing semantic search vs grep in Claude Code on Excalidraw (155k+ TypeScript lines); (2) various Medium articles citing structured MCP retrieval vs naive file pasting.

**grepai benchmark dissection:**

| Metric | Baseline (grep) | grepai (semantic) | Change |
|---|---|---|---|
| API cost | $6.78 | $4.92 | -27.5% |
| Fresh input tokens | 51,147 | 1,326 | **-97.4%** |
| Tool calls | 139 | 62 | -55% |
| Cache creation tokens | 563,883 | 162,289 | -71% |

**Critical interpretation:** The 97% applies only to *uncached fresh input tokens*, not total token spend. Cached tokens (which cost 10-30% of fresh input price) dominate real sessions. Actual cost reduction was 27.5% — still meaningful but far from 97%.

**What legitimate benchmarks show:**
- CodeGraph (vendor): 47% fewer total tokens, median 7 codebases
- code-graph-mcp: 95% fewer source *lines* read (lines ≠ tokens)
- Codebase-Memory (arxiv): 10x fewer tokens vs file exploration
- Headroom (vendor): 87.6% token reduction with AST compression
- Srclight: 40-60% of "orientation tokens" eliminated

**Is 97% realistic for Cerebrofy?**

*Under best-case conditions:* Yes. If a developer would otherwise paste 200KB of source files into a prompt and Cerebrofy's MCP `search_code` returns only 3 relevant function signatures (~2KB), the reduction in raw input bytes approaches 99%.

*Under realistic multi-turn sessions:* No. Once prompt caching kicks in, the effective cost reduction is 20-50% in practice.

**Fair benchmark design for Cerebrofy:**
1. Select 3+ codebases spanning 2+ languages and size tiers
2. Define 20 representative tasks (bug fix, feature add, refactor, audit)
3. Measure total tokens (fresh + cached) across tasks
4. Compare: naive file reading vs grep-only vs Cerebrofy MCP vs CodeGraph
5. Measure task completion quality (not just token counts)
6. Run 5 independent sessions per condition; take median

---

## Cerebrofy's Unique Angle / White Space

**What is genuinely differentiated:**

1. **Python-native ecosystem.** The field is dominated by TypeScript (CodeGraph, Repomix, code2prompt), Rust (code-graph-mcp, Headroom), and Go (grepai). Cerebrofy is natural fit for Python ML/data science monorepos.

2. **Bundled offline embeddings (fastembed + BAAI/bge-small-en-v1.5).** CodeGraph has *no* vector search. Codebase-Memory has *no* embeddings. GitNexus needs embedding infrastructure. Srclight requires Ollama or a cloud API. Cerebrofy is the only tool that bundles a SOTA embedding model as a base dependency with zero external runtime — concrete advantage for airgapped/enterprise environments.

3. **CWD-routed single MCP server.** One MCP entry per machine, routing by `os.getcwd()` at each tool call. Competitors like CodeGraph use per-project config entries. Cerebrofy's single-server approach is more elegant for multi-repo developers.

4. **Atomic build discipline (Law-level invariants).** The documented Laws (atomic swap, schema version check, `RUNTIME_BOUNDARY` edges, dedup rules) exceed most competitors' consistency guarantees.

5. **Incremental update pipeline.** `cerebrofy update` with `BEGIN IMMEDIATE` transaction wrapping, DELETE+INSERT for `sqlite-vec`, and 2s target — transactional rigor uncommon in the field.

**Genuine white space:**
- **Python-focused hybrid search:** No competitor offers Python-native, offline, hybrid (structural graph + semantic vector) search with a bundled ONNX model. This is Cerebrofy's clearest unclaimed territory once `search/hybrid.py` is implemented.
- **Compliance/airgapped enterprise:** Offline embeddings + local SQLite + no cloud dependencies positions Cerebrofy for regulated industries (fintech, healthcare, defense) where Cursor/Greptile/Augment are non-starters.

---

## Gaps and Risks

### Technical Gaps

1. **5 of 8 MCP tools are stubs.** `search_code`, `get_neuron`, `list_lobes`, `plan`, `tasks` fail at runtime. Competitors ship these today.
2. **No documented language coverage.** Without counts and per-language test coverage, enterprise buyers can't evaluate.
3. **No benchmark data.** The 97% claim lacks internal validation.
4. **`sqlite-vec` maturity risk.** `vec0` virtual table lacks `UPDATE` support; DELETE+INSERT workaround adds operational complexity.
5. **Python startup latency.** Python-based tree-sitter is ~3-5x slower than Rust bindings for large codebases (50k+ files).

### Competitive Risks

6. **CodeGraph is pulling away.** 48.8k stars, MIT, 20+ languages, 8 agent integrations, no dependencies — it's the default choice today.
7. **Codebase-Memory's 66-language claim.** Makes Cerebrofy's language coverage look narrow for polyglot shops.
8. **Augment Code Context Engine MCP.** Cloud-hosted, 500k-file capacity — superior for non-airgapped teams.
9. **Market convergence.** The field is converging on: tree-sitter → SQLite → MCP. Differentiation will shift to language depth, query expressiveness, agent ecosystem, and compliance.
10. **Serena's LSP approach.** For teams with existing language servers, IDE-grade accuracy with zero index-build overhead (25.2k stars).

### Strategic Risks

11. **Python tool in a TypeScript world.** AI agent tooling community skews TypeScript/Node.js.
12. **Pre-v1.0 with no binary distribution.** CodeGraph and Codebase-Memory ship pre-built binaries today.
13. **Single maintainer concentration.** Sustainability risk for enterprise buyers.

---

## Competitive Positioning Matrix

```
                    LOCAL/OFFLINE  ←————————————→  CLOUD/SaaS
                         │                              │
GRAPH/STRUCTURAL   Cerebrofy*         GitNexus     Greptile
                   CodeGraph          Codebase-Mem  Augment
                   code-graph-mcp     Srclight      Cody (Ent.)
                         │
SEMANTIC/VECTOR    Cerebrofy*         Srclight+GPU   Cursor
  (hybrid)         grepai             Augment MCP    Cody
                         │
FLAT-FILE PACK     Repomix            code2prompt    GitIngest
                   gpt-repo-loader    Aider repomap
                         │
SECURITY/SAST                         Semgrep       CodeQL
                                                    Snyk

* Cerebrofy occupies the Hybrid (graph+vector) + Local quadrant once search/hybrid.py ships
```

---

## Recommended Actions

1. **Ship `search/hybrid.py` immediately.** Hybrid graph+vector is the only real moat vs CodeGraph. Without it, Cerebrofy is a weaker CodeGraph.
2. **Publish a rigorous benchmark.** 3 codebases, 20 tasks, total tokens + quality. Publish methodology.
3. **Clarify the 97% claim.** Replace with: "up to X% fewer fresh input tokens in controlled benchmarks; Y% total cost reduction in practice."
4. **Document language support explicitly.** List every language with a `.scm` file, extraction capabilities, and test coverage.
5. **Distribute a native binary.** Already scaffolded (Nuitka) — ship it.
6. **Lead with the offline embedding angle.** No competitor bundles a SOTA embedding model as a base dependency. Make this the headline claim.

---

## Sources

- grepai vs grep benchmark (97% fresh token reduction)
- CodeGraph GitHub (48.8k stars) + codegraph.codes
- Codebase-Memory arXiv:2603.27277
- code-graph-mcp GitHub (sdsrss/code-graph-mcp)
- Serena GitHub (oraios/serena)
- Srclight GitHub + Hacker News thread
- Repomix website + Ry Walker research
- Aider repomap article
- GitNexus MarkTechPost overview + production audit
- Greptile graph-based context docs
- Sourcegraph Cody embeddings docs
- Cursor codebase indexing docs
- Augment Code Context Engine
- Headroom GitHub + BrightCoding overview
- token-optimizer-mcp GitHub
- SQLite-vec state of vector search (Marco Bambini)
- fastembed PyPI
- Zylos Research: Codebase Intelligence 2026
- IntuitionLabs: AI Code Assistants for Large Codebases
- arXiv:2603.28119: Compressing Code Context for LLM Issue Resolution
