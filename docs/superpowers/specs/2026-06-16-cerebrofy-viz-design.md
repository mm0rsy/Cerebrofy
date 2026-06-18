# Cerebrofy Viz — Design Spec

**Date:** 2026-06-16  
**Branch:** `feat/cerebrofy-viz`  
**Status:** Approved for implementation

---

## Overview

`cerebrofy viz` is a new CLI command that opens a 3D interactive brain visualization of the indexed codebase in the user's browser. Code regions (lobes) are mapped to anatomical brain regions; neurons (functions, classes, modules) appear as glowing nodes on the cortical surface; edges appear as bezier fiber tracts with animated signal particles riding them.

The command reads from the existing `cerebrofy.db` — no re-indexing required.

---

## User Experience

```bash
cerebrofy viz          # opens browser, serves from port 7331 (configurable)
cerebrofy viz --port 8080
cerebrofy viz --no-open   # start server without auto-opening browser
```

On launch:
1. CLI reads `cerebrofy.db` and exports graph JSON
2. A local HTTP server starts serving the static viz bundle
3. Browser opens automatically to `http://localhost:7331`
4. The 3D brain loads, nodes appear on the cortical surface, signals begin firing
5. Ctrl+C stops the server

---

## Architecture

```
commands/viz.py          ← CLI entry point (Click command)
viz/
  server.py              ← HTTP server wrapper (stdlib http.server)
  graph_export.py        ← Reads cerebrofy.db → VizGraph JSON
  static/
    index.html           ← Three.js app entry point
    brain.glb            ← Optional: real brain mesh (user-provided)
    vendor/              ← Bundled Three.js + addons (no CDN at runtime)
      three.module.js
      jsm/
        controls/OrbitControls.js
        postprocessing/  ← EffectComposer, RenderPass, UnrealBloomPass, etc.
        loaders/GLTFLoader.js
```

### Component responsibilities

**`commands/viz.py`**
- Validates that `.cerebrofy/` and `cerebrofy.db` exist (exits with clear error if not)
- Calls `graph_export.py` to build `VizGraph`
- Starts `viz/server.py` on the requested port
- Opens browser via `webbrowser.open()`
- Blocks until Ctrl+C, then shuts down server cleanly

**`viz/graph_export.py`**
- Queries `nodes` table: `id, name, type, lobe, file, line_start`
- Queries `edges` table: `src_id, dst_id, rel_type` (excludes `RUNTIME_BOUNDARY`)
- Maps each node's lobe string to one of 5 canonical lobe IDs
- Returns `VizGraph(nodes: list[VizNode], edges: list[VizEdge])`
- Serialises to JSON served at `/data`

**`viz/server.py`**
- Extends `http.server.SimpleHTTPRequestHandler`
- Serves static files from `viz/static/` for all paths except `/data`
- `GET /data` → returns `VizGraph` JSON with `Content-Type: application/json`
- Single-threaded; only intended for local single-user use

**`viz/static/index.html`** (Three.js app)
- Fetches `/data` on load
- Tries to load `brain.glb` via `GLTFLoader`; falls back to procedural brain if missing or fails
- Maps `VizNode` → instanced sphere on brain surface (lobe direction sampling)
- Maps `VizEdge` → quadratic bezier edge + signal particle
- Renders with `UnrealBloomPass` bloom pipeline

---

## Data Model

### VizGraph JSON (served at `/data`)

```json
{
  "nodes": [
    {
      "id": "src/cerebrofy/commands/build.py::run_build",
      "name": "run_build",
      "type": "function",
      "lobe": "frontal",
      "file": "src/cerebrofy/commands/build.py",
      "line": 42
    }
  ],
  "edges": [
    {
      "src": "src/cerebrofy/commands/build.py::run_build",
      "dst": "src/cerebrofy/db/writer.py::write_nodes",
      "rel": "CALLS"
    }
  ],
  "meta": {
    "repo": "cerebrofy",
    "node_count": 312,
    "edge_count": 847,
    "lobe_count": 5
  }
}
```

### Lobe mapping

Lobe names come from the `nodes.lobe` column (set during `cerebrofy build`). The viz maps them to anatomical directions for surface placement:

| Lobe name | Anatomical region | Colour |
|---|---|---|
| `frontal` | Anterior-superior | `#4fc3f7` cyan |
| `parietal` | Superior | `#81c784` green |
| `temporal` | Lateral-inferior | `#ffb74d` orange |
| `occipital` | Posterior | `#f06292` pink |
| `limbic` | Superomedial | `#ce93d8` purple |

Nodes whose lobe does not match any of the 5 canonical names are assigned to `limbic` as a catch-all.

---

## Visual Specification

### Brain mesh

- **Primary:** `viz/static/brain.glb` loaded via `GLTFLoader`. User-provided; not bundled.
- **Fallback:** Procedural `IcosahedronGeometry(88, 6)` with ridged multifractal displacement (implemented). Anatomical sulci (interhemispheric, central, Sylvian, parieto-occipital) are approximated analytically.
- **Material:** `MeshPhongMaterial`, dark teal (`#071828`), specular `#1a6688`, opacity 0.52, front-face + separate 0.18 opacity back-face for inner glow. Wireframe overlay at 4.5% opacity for fold texture.

### Nodes

- `InstancedMesh` of `SphereGeometry(2.0, 14, 14)` — 50 instances (one per sampled neuron)
- Custom GLSL: rim-glow shader — dark core, bright rim based on view angle
- Placed at 94% of surface radius (just inside surface)
- Large codebases: nodes are a uniform random sample from each lobe region (10 per lobe)

### Edges (axon tracts)

- Quadratic bezier curves arcing **inward** through the brain interior (control point is biased toward brain centre, not outward)
- Rendered as `THREE.Line` with custom gradient GLSL: colour fades from source lobe to destination lobe
- Opacity follows `sin(t * π)` — fades at both endpoints, brightest at midpoint
- Intra-lobe edges: solid lobe colour both ends
- Cross-lobe edges: gradient from source colour to destination colour

### Signal particles

- 220 particles total, each assigned to a specific edge at creation
- Travel along the edge's exact bezier curve (same control point as the edge geometry)
- GLSL pulsing size: `gl_PointSize = (2.0 + 0.5*sin(time*5+phase) * 3.5) * (260 / -mv.z)`
- Circular soft-disc fragment shader (discard corners, alpha fade toward edge)
- Speed: randomised per particle (0.003–0.01 t/frame)
- **Ambient mode** (default): all particles run continuously
- **Query mode** (future): burst of particles fires along paths connected to the queried node

### Post-processing

- `UnrealBloomPass`: strength 2.6, radius 0.65, threshold 0.03
- `ReinhardToneMapping`, exposure 1.6
- Auto-rotate: 0.28 RPM, OrbitControls for manual interaction

---

## Error Handling

| Condition | Behaviour |
|---|---|
| No `cerebrofy.db` found | CLI exits with `Error: run cerebrofy build first` |
| DB has no nodes | Server starts but viz shows empty brain with warning overlay |
| `brain.glb` missing | Silent fallback to procedural brain; status indicator in top-right |
| `brain.glb` fails to parse | Same silent fallback |
| Port already in use | Retry on port+1 up to 10 times, then exit with error |
| Browser open fails | Print URL to terminal, continue serving |

---

## Testing

- **Unit:** `tests/unit/viz/test_graph_export.py` — mock DB, assert VizGraph JSON structure, lobe assignment, RUNTIME_BOUNDARY exclusion
- **Unit:** `tests/unit/viz/test_server.py` — assert `/data` returns valid JSON, assert static files served correctly
- **Integration:** `tests/integration/test_viz_command.py` — spin up server against a `tmp_path` repo with a built index, assert HTTP 200 on `/` and `/data`, assert data structure matches DB content
- No browser/WebGL tests (UI only; covered by the prototype in `docs/viz-prototypes/`)

---

## Out of Scope

- Query-driven signal burst (ambient only for now; query mode is Phase 2)
- Hover tooltips on nodes
- Filtering by lobe or rel_type
- Authentication or multi-user serving
- Bundling `brain.glb` — user must provide their own
