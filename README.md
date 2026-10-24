<!-- markdownlint-disable MD040 MD041 MD033 MD060 -->
<p align="center">
  <img src="https://raw.githubusercontent.com/mm0rsy/Cerebrofy/master/assets/banner.svg" alt="Cerebrofy" width="740"/>
</p>

<div align="center">

[![PyPI version](https://img.shields.io/pypi/v/cerebrofy?color=blue&logo=pypi&logoColor=white)](https://pypi.org/project/cerebrofy/)
[![PyPI - Status](https://img.shields.io/badge/PyPI-available-blue?logo=pypi&logoColor=white)](https://pypi.org/project/cerebrofy/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue?logo=python&logoColor=white)](https://pypi.org/project/cerebrofy/)
[![PyPI downloads](https://img.shields.io/pypi/dm/cerebrofy?color=green&logo=pypi&logoColor=white)](https://pypi.org/project/cerebrofy/)
[![CI](https://img.shields.io/github/actions/workflow/status/mm0rsy/Cerebrofy/ci.yml?branch=master&label=CI&logo=github)](https://github.com/mm0rsy/Cerebrofy/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-stdio-blueviolet?logo=anthropic&logoColor=white)](docs/reference/mcp-tools.md)
[![Tree-sitter](https://img.shields.io/badge/parser-tree--sitter-orange)](https://tree-sitter.github.io/)
[![Embeddings](https://img.shields.io/badge/embeddings-BAAI%2Fbge--small--en-lightgrey?logo=huggingface&logoColor=white)](https://huggingface.co/BAAI/bge-small-en-v1.5)
[![SQLite](https://img.shields.io/badge/storage-SQLite%20%2B%20sqlite--vec-003B57?logo=sqlite&logoColor=white)](https://github.com/asg017/sqlite-vec)
[![uv](https://img.shields.io/badge/built%20with-uv-5C4EE5?logo=astral&logoColor=white)](https://docs.astral.sh/uv/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-informational)](docs/getting-started/installation.md#platform-support)
[![Built for Claude](https://img.shields.io/badge/built%20for-Claude-blueviolet?logo=anthropic&logoColor=white)](https://claude.ai)

</div>

---

<p align="center">
  <img src="https://raw.githubusercontent.com/mm0rsy/Cerebrofy/master/assets/demo/cerebrofy-viz.gif" alt="cerebrofy viz — interactive 3D brain visualization of your codebase call graph" width="720"/>
</p>

---

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

## Documentation

Full documentation has moved to [`docs/`](./docs/):

| Section | Description |
|---------|-------------|
| [Getting Started](./docs/getting-started/) | Installation, quick start, configuration |
| [Concepts](./docs/concepts/) | Architecture, cognitive layers, memory model, sessions |
| [Features](./docs/features/) | Blast radius, health, memory, sessions, synthesizer, narrative, insights, changelog, coordination, governance, silo detection, upgrade, coverage gap, vulnerability, onboarding, review, security |
| [Reference](./docs/reference/) | CLI reference, MCP tools, config, database schema |
| [Development](./docs/development/) | Contributing, testing, releasing |

**Start here:** [Getting Started → Installation](./docs/getting-started/installation.md)

---

## License

MIT