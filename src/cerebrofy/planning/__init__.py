"""Natural-language refactor planner (Idea #12).

Pipeline: ``extractor`` (semantic seed + cohesive cluster) → ``sequence``
(dependency-safe migration steps) → ``formatter`` (Markdown + JSON plan).
"""
