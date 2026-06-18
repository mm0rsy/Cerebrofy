# Cerebrofy Viz Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `cerebrofy viz` command that opens an interactive 3D brain visualization of the indexed codebase in the browser.

**Architecture:** `graph_export.py` reads `cerebrofy.db` and produces a `VizGraph` JSON payload. `server.py` starts a local HTTP server serving a static Three.js app from `viz/static/` plus a `/data` endpoint returning the `VizGraph`. The `viz` CLI command wires these together and opens the browser.

**Tech Stack:** Python stdlib (`http.server`, `threading`, `webbrowser`), Three.js r0.157 (bundled, no CDN), `UnrealBloomPass`, `GLTFLoader`, `rich_click`.

---

## File Map

```
src/cerebrofy/
├── commands/viz.py          CREATE  CLI entry point
├── viz/
│   ├── __init__.py          CREATE  empty
│   ├── graph_export.py      CREATE  VizNode/VizEdge/VizGraph + export_graph()
│   ├── server.py            CREATE  VizServer (HTTP + /data endpoint)
│   └── static/
│       ├── index.html       CREATE  Three.js app (fetches /data, renders brain)
│       └── vendor/          CREATE  copy from docs/viz-prototypes/vendor/
├── cli.py                   MODIFY  import + register cerebrofy_viz

tests/
├── unit/viz/
│   ├── __init__.py          CREATE  empty
│   ├── test_graph_export.py CREATE
│   └── test_server.py       CREATE
└── integration/
    └── test_viz_command.py  CREATE
```

---

## Task 1: VizGraph data model and graph export

**Files:**
- Create: `src/cerebrofy/viz/__init__.py`
- Create: `src/cerebrofy/viz/graph_export.py`
- Create: `tests/unit/viz/__init__.py`
- Create: `tests/unit/viz/test_graph_export.py`

- [ ] **Step 1: Create empty package init files**

```bash
mkdir -p src/cerebrofy/viz tests/unit/viz
touch src/cerebrofy/viz/__init__.py tests/unit/viz/__init__.py
```

- [ ] **Step 2: Write the failing tests**

Create `tests/unit/viz/test_graph_export.py`:

```python
import json
import sqlite3
from pathlib import Path
import pytest
from cerebrofy.viz.graph_export import (
    export_graph, VizGraph, VizNode, VizEdge, ANATOMICAL_REGIONS
)


@pytest.fixture
def db_path(tmp_path):
    db = tmp_path / ".cerebrofy" / "db" / "cerebrofy.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE nodes (
            id TEXT, name TEXT, type TEXT, lobe TEXT,
            file TEXT, line_start INTEGER, line_end INTEGER
        );
        CREATE TABLE edges (src_id TEXT, dst_id TEXT, rel_type TEXT);
        INSERT INTO nodes VALUES ('pkg::foo','foo','function','pkg','pkg.py',1,5);
        INSERT INTO nodes VALUES ('pkg::bar','bar','function','pkg','pkg.py',7,12);
        INSERT INTO nodes VALUES ('cmd::run','run','function','cmd','cmd.py',1,10);
        INSERT INTO edges VALUES ('pkg::foo','pkg::bar','CALLS');
        INSERT INTO edges VALUES ('pkg::foo','cmd::run','RUNTIME_BOUNDARY');
    """)
    con.commit()
    con.close()
    return db


def test_export_returns_viz_graph(db_path):
    assert isinstance(export_graph(db_path), VizGraph)


def test_nodes_include_all_db_nodes(db_path):
    assert len(export_graph(db_path).nodes) == 3


def test_region_is_one_of_five_anatomical(db_path):
    for node in export_graph(db_path).nodes:
        assert node.region in ANATOMICAL_REGIONS


def test_runtime_boundary_excluded_from_edges(db_path):
    assert all(e.rel != "RUNTIME_BOUNDARY" for e in export_graph(db_path).edges)


def test_calls_edge_included(db_path):
    assert any(e.rel == "CALLS" for e in export_graph(db_path).edges)


def test_same_lobe_gets_same_region(db_path):
    pkg_regions = {n.region for n in export_graph(db_path).nodes if n.lobe == "pkg"}
    assert len(pkg_regions) == 1


def test_meta_counts(db_path):
    graph = export_graph(db_path)
    assert graph.meta.node_count == 3
    assert graph.meta.edge_count == 1
    assert graph.meta.lobe_count == 2


def test_to_json_produces_valid_structure(db_path):
    data = json.loads(export_graph(db_path).to_json())
    assert set(data.keys()) == {"nodes", "edges", "meta"}
    assert data["nodes"][0].keys() >= {"id", "name", "type", "lobe", "region", "file", "line"}
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
uv run pytest tests/unit/viz/test_graph_export.py -v
```

Expected: `ModuleNotFoundError: No module named 'cerebrofy.viz.graph_export'`

- [ ] **Step 4: Implement `graph_export.py`**

Create `src/cerebrofy/viz/graph_export.py`:

```python
"""Read cerebrofy.db and produce a VizGraph JSON payload for the viz server."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

ANATOMICAL_REGIONS = ["frontal", "parietal", "temporal", "occipital", "limbic"]


@dataclass(frozen=True)
class VizNode:
    id: str
    name: str
    type: str
    lobe: str    # code lobe name (from DB)
    region: str  # anatomical region (one of ANATOMICAL_REGIONS)
    file: str
    line: int


@dataclass(frozen=True)
class VizEdge:
    src: str
    dst: str
    rel: str


@dataclass
class VizMeta:
    repo: str
    node_count: int
    edge_count: int
    lobe_count: int


@dataclass
class VizGraph:
    nodes: list[VizNode]
    edges: list[VizEdge]
    meta: VizMeta

    def to_json(self) -> str:
        return json.dumps({
            "nodes": [asdict(n) for n in self.nodes],
            "edges": [asdict(e) for e in self.edges],
            "meta": asdict(self.meta),
        })


def _assign_region(lobe: str, lobe_index: dict[str, int]) -> str:
    """Stable round-robin: maps any code lobe name to one of 5 anatomical regions."""
    return ANATOMICAL_REGIONS[lobe_index.get(lobe, 0) % len(ANATOMICAL_REGIONS)]


def export_graph(db_path: Path) -> VizGraph:
    """Read nodes and edges from cerebrofy.db and return a VizGraph."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        node_rows = con.execute(
            "SELECT id, name, type, lobe, file, line_start FROM nodes ORDER BY lobe, name"
        ).fetchall()

        seen: set[str] = set()
        unique_lobes: list[str] = []
        for r in node_rows:
            if r["lobe"] not in seen:
                unique_lobes.append(r["lobe"])
                seen.add(r["lobe"])
        lobe_index = {lobe: i for i, lobe in enumerate(unique_lobes)}

        nodes = [
            VizNode(
                id=r["id"],
                name=r["name"],
                type=r["type"],
                lobe=r["lobe"],
                region=_assign_region(r["lobe"], lobe_index),
                file=r["file"],
                line=r["line_start"],
            )
            for r in node_rows
        ]

        edge_rows = con.execute(
            "SELECT src_id, dst_id, rel_type FROM edges"
            " WHERE rel_type != 'RUNTIME_BOUNDARY'"
        ).fetchall()
        edges = [
            VizEdge(src=r["src_id"], dst=r["dst_id"], rel=r["rel_type"])
            for r in edge_rows
        ]

        # repo name = grandparent of .cerebrofy/db/cerebrofy.db
        repo = db_path.parent.parent.parent.name

        return VizGraph(
            nodes=nodes,
            edges=edges,
            meta=VizMeta(
                repo=repo,
                node_count=len(nodes),
                edge_count=len(edges),
                lobe_count=len(unique_lobes),
            ),
        )
    finally:
        con.close()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/unit/viz/test_graph_export.py -v
```

Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add src/cerebrofy/viz/__init__.py src/cerebrofy/viz/graph_export.py \
        tests/unit/viz/__init__.py tests/unit/viz/test_graph_export.py
git commit -m "feat(viz): add VizGraph data model and graph_export from cerebrofy.db"
```

---

## Task 2: HTTP server

**Files:**
- Create: `src/cerebrofy/viz/server.py`
- Create: `tests/unit/viz/test_server.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/viz/test_server.py`:

```python
import json
import socket
import urllib.request
import pytest
from cerebrofy.viz.graph_export import VizGraph, VizNode, VizEdge, VizMeta
from cerebrofy.viz.server import VizServer


@pytest.fixture
def static_dir(tmp_path):
    (tmp_path / "index.html").write_text("<html>cerebrofy viz</html>")
    return tmp_path


@pytest.fixture
def graph():
    return VizGraph(
        nodes=[VizNode(id="a::b", name="b", type="function",
                       lobe="a", region="frontal", file="a.py", line=1)],
        edges=[VizEdge(src="a::b", dst="a::b", rel="CALLS")],
        meta=VizMeta(repo="test", node_count=1, edge_count=1, lobe_count=1),
    )


@pytest.fixture
def server(static_dir, graph):
    srv = VizServer(static_dir, graph, port=17331)
    srv.start()
    yield srv
    srv.stop()


def test_data_endpoint_returns_json(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/data") as r:
        data = json.loads(r.read())
    assert set(data.keys()) == {"nodes", "edges", "meta"}


def test_data_node_has_correct_fields(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/data") as r:
        data = json.loads(r.read())
    assert data["nodes"][0]["id"] == "a::b"
    assert data["nodes"][0]["region"] == "frontal"


def test_static_index_served(server):
    with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/index.html") as r:
        assert "cerebrofy viz" in r.read().decode()


def test_port_retry_on_conflict(static_dir, graph):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 17340))
    blocker.listen(1)
    try:
        srv = VizServer(static_dir, graph, port=17340)
        actual = srv.start()
        assert actual != 17340
        srv.stop()
    finally:
        blocker.close()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/viz/test_server.py -v
```

Expected: `ModuleNotFoundError: No module named 'cerebrofy.viz.server'`

- [ ] **Step 3: Implement `server.py`**

Create `src/cerebrofy/viz/server.py`:

```python
"""Local HTTP server: serves viz/static/ files and a /data JSON endpoint."""
from __future__ import annotations

import threading
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from cerebrofy.viz.graph_export import VizGraph


class _VizHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: object, graph_json: str, **kwargs: object) -> None:
        self._graph_json = graph_json
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        if self.path == "/data":
            body = self._graph_json.encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def log_message(self, fmt: str, *args: object) -> None:
        pass  # silence per-request logs


class VizServer:
    def __init__(
        self, static_dir: Path, graph: VizGraph, port: int = 7331
    ) -> None:
        self.static_dir = static_dir
        self.graph = graph
        self.port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> int:
        """Start in background thread. Returns actual port used."""
        graph_json = self.graph.to_json()
        handler = partial(
            _VizHandler,
            directory=str(self.static_dir),
            graph_json=graph_json,
        )
        for offset in range(10):
            candidate = self.port + offset
            try:
                self._server = HTTPServer(("127.0.0.1", candidate), handler)
                self.port = candidate
                break
            except OSError:
                continue
        else:
            raise RuntimeError(
                f"Could not bind to any port in {self.port}–{self.port + 9}"
            )
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()
        return self.port

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server = None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/viz/test_server.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/cerebrofy/viz/server.py tests/unit/viz/test_server.py
git commit -m "feat(viz): add VizServer serving static files and /data endpoint"
```

---

## Task 3: Static bundle

**Files:**
- Create: `src/cerebrofy/viz/static/index.html`
- Create: `src/cerebrofy/viz/static/vendor/` (copy from `docs/viz-prototypes/vendor/`)

- [ ] **Step 1: Copy vendor JS files**

```bash
cp -r docs/viz-prototypes/vendor src/cerebrofy/viz/static/vendor
ls src/cerebrofy/viz/static/vendor/
```

Expected: `three.module.js  d3.min.js  3d-force-graph.min.js  jsm/`

- [ ] **Step 2: Create `index.html`**

Create `src/cerebrofy/viz/static/index.html`. Key differences from the prototype: fetches `/data` instead of hardcoded lobes; groups DB nodes by anatomical region; subsamples to 15 nodes per region and 200 edges max; builds legend with safe DOM methods (no `innerHTML` with data).

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Cerebrofy Viz</title>
  <style>
    * { margin: 0; padding: 0; }
    body { background: #000; overflow: hidden; font-family: monospace; }
    canvas { display: block; }
    #hud { position: fixed; top: 16px; left: 16px; z-index: 10; pointer-events: none; }
    #title { color: #4fc3f7; font-size: 13px; line-height: 1.7; }
    #subtitle { color: #446; font-size: 11px; display: block; }
    #status { position: fixed; top: 16px; right: 16px; color: #446; font-size: 11px; z-index: 10; }
    #legend { position: fixed; bottom: 16px; left: 16px; display: flex;
              flex-direction: column; gap: 5px; z-index: 10; pointer-events: none; }
    .li { display: flex; align-items: center; gap: 8px; color: #778; font-size: 11px; }
    .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  </style>
</head>
<body>
<div id="hud">
  <div id="title">CEREBROFY VIZ<span id="subtitle"> loading…</span></div>
</div>
<div id="status">loading…</div>
<div id="legend"></div>

<script type="module">
import * as THREE from './vendor/three.module.js';
import { OrbitControls }   from './vendor/jsm/controls/OrbitControls.js';
import { EffectComposer }  from './vendor/jsm/postprocessing/EffectComposer.js';
import { RenderPass }      from './vendor/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from './vendor/jsm/postprocessing/UnrealBloomPass.js';
import { GLTFLoader }      from './vendor/jsm/loaders/GLTFLoader.js';

const setStatus = s => { document.getElementById('status').textContent = s; };

// ── Renderer / scene / camera ─────────────────────────────────────────────────
const W = window.innerWidth, H = window.innerHeight;
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(W, H);
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.toneMapping = THREE.ReinhardToneMapping;
renderer.toneMappingExposure = 1.6;
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x000510);

const camera = new THREE.PerspectiveCamera(50, W / H, 0.1, 2000);
camera.position.set(0, 40, 310);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.04;
controls.autoRotate = true;
controls.autoRotateSpeed = 0.28;
controls.target.set(0, 10, 0);

const composer = new EffectComposer(renderer);
composer.addPass(new RenderPass(scene, camera));
composer.addPass(new UnrealBloomPass(new THREE.Vector2(W, H), 2.6, 0.65, 0.03));

scene.add(new THREE.AmbientLight(0x0a1828, 3.0));
const key = new THREE.DirectionalLight(0x3399cc, 1.8);
key.position.set(1, 1.5, 1); scene.add(key);
const fill = new THREE.DirectionalLight(0x112244, 0.8);
fill.position.set(-1, -0.5, -1); scene.add(fill);

// ── Noise helpers ─────────────────────────────────────────────────────────────
function h3(xi,yi,zi){return((Math.sin(xi*127.1+yi*311.7+zi*74.7)*43758.5453)%1+1)%1;}
function sm(t){return t*t*(3-2*t);}
function lerp(a,b,t){return a+t*(b-a);}
function noise3(x,y,z){
  const ix=Math.floor(x),iy=Math.floor(y),iz=Math.floor(z);
  const ux=sm(x-ix),uy=sm(y-iy),uz=sm(z-iz);
  return lerp(
    lerp(lerp(h3(ix,iy,iz),h3(ix+1,iy,iz),ux),lerp(h3(ix,iy+1,iz),h3(ix+1,iy+1,iz),ux),uy),
    lerp(lerp(h3(ix,iy,iz+1),h3(ix+1,iy,iz+1),ux),lerp(h3(ix,iy+1,iz+1),h3(ix+1,iy+1,iz+1),ux),uy),uz);
}
function ridgedMF(x,y,z){
  let v=0,amp=1,freq=1,prev=1;
  for(let i=0;i<5;i++){
    const n=1-Math.abs(noise3(x*freq,y*freq,z*freq)*2-1);
    v+=n*n*amp*prev; prev=n*n; amp*=0.5; freq*=2.1;
  }
  return v;
}

// ── Procedural brain geometry ─────────────────────────────────────────────────
function makeBrainGeo(){
  const R=88, geo=new THREE.IcosahedronGeometry(R,6), pos=geo.attributes.position;
  for(let i=0;i<pos.count;i++){
    const v=new THREE.Vector3(pos.getX(i),pos.getY(i),pos.getZ(i));
    const n=v.clone().normalize();
    let sx=1.02,sy=0.87,sz=1.22;
    const temp=Math.pow(Math.abs(n.x),1.2)*Math.max(0,-n.y+0.3)*Math.max(0,1-Math.abs(n.z));
    sx+=temp*0.22; sy-=temp*0.10;
    sz+=Math.max(0,n.z)*Math.max(0,n.y+0.25)*0.10;
    sy-=Math.max(0,-n.y-0.15)*0.6;
    const sh=new THREE.Vector3(n.x*sx,n.y*sy,n.z*sz).normalize();
    const fissure=Math.exp(-sh.x*sh.x*28)*Math.max(0,sh.y+0.05)*0.17;
    const central=Math.exp(-(sh.z-0.05)*(sh.z-0.05)*55)*Math.max(0,sh.y-0.3)*0.065;
    const sylvian=Math.exp(-(sh.y+0.2)*(sh.y+0.2)*20)*Math.max(0,Math.abs(sh.x)-0.3)*0.07;
    const s=2.6;
    const wx=noise3(sh.x*s+1.7,sh.y*s+0.3,sh.z*s+0.9)*0.30;
    const wy=noise3(sh.x*s+3.2,sh.y*s+2.1,sh.z*s+1.4)*0.30;
    const wz=noise3(sh.x*s+0.5,sh.y*s+4.7,sh.z*s+2.8)*0.30;
    const folds=ridgedMF(sh.x*s+wx,sh.y*s+wy,sh.z*s+wz)*9
              + ridgedMF(sh.x*s*2+wy,sh.y*s*2+wz,sh.z*s*2+wx)*3.5 - 8;
    const r=R*(1-fissure-central-sylvian)+folds;
    v.set(sh.x*r,sh.y*r,sh.z*r);
    pos.setXYZ(i,v.x,v.y,v.z);
  }
  geo.computeVertexNormals();
  return geo;
}

function addBrainMeshes(geo){
  scene.add(new THREE.Mesh(geo,new THREE.MeshPhongMaterial({
    color:0x071828,emissive:0x040e1a,specular:0x1a6688,shininess:50,
    transparent:true,opacity:0.52,side:THREE.FrontSide,depthWrite:false})));
  scene.add(new THREE.Mesh(geo,new THREE.MeshPhongMaterial({
    color:0x0a2035,transparent:true,opacity:0.18,side:THREE.BackSide,depthWrite:false})));
  scene.add(new THREE.Mesh(geo,new THREE.MeshBasicMaterial({
    color:0x0e3d5a,wireframe:true,transparent:true,opacity:0.045})));
}

function collectSurfaceVerts(geo){
  const map=new Map(), p=geo.attributes.position;
  for(let i=0;i<p.count;i++){
    const k=`${Math.round(p.getX(i))}|${Math.round(p.getY(i))}|${Math.round(p.getZ(i))}`;
    if(!map.has(k)) map.set(k,new THREE.Vector3(p.getX(i),p.getY(i),p.getZ(i)));
  }
  return [...map.values()];
}

// ── GLSL shaders ──────────────────────────────────────────────────────────────
const nodeVert=`
  attribute vec3 instanceColor;
  varying vec3 vColor,vNormal,vViewDir;
  void main(){
    vColor=instanceColor;
    vec4 wp=modelMatrix*instanceMatrix*vec4(position,1.0);
    vNormal=normalize(mat3(modelMatrix)*mat3(instanceMatrix)*normal);
    vViewDir=normalize(cameraPosition-wp.xyz);
    gl_Position=projectionMatrix*viewMatrix*wp;
  }`;
const nodeFrag=`
  varying vec3 vColor,vNormal,vViewDir;
  void main(){
    float rim=pow(1.0-clamp(dot(normalize(vNormal),normalize(vViewDir)),0.0,1.0),1.4);
    float core=pow(clamp(dot(normalize(vNormal),normalize(vViewDir)),0.0,1.0),4.0)*0.25;
    gl_FragColor=vec4(vColor*(core+rim*3.4),1.0);
  }`;
const edgeVert=`
  attribute float t;attribute vec3 colA,colB;
  varying float vT;varying vec3 vCA,vCB;
  void main(){vT=t;vCA=colA;vCB=colB;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}`;
const edgeFrag=`
  varying float vT;varying vec3 vCA,vCB;
  void main(){gl_FragColor=vec4(mix(vCA,vCB,vT)*2.2,0.8*sin(vT*3.14159));}`;
const partVert=`
  attribute vec3 pColor;attribute float phase;
  varying vec3 vColor;uniform float uTime;
  void main(){
    vColor=pColor;
    float p=0.5+0.5*sin(uTime*5.0+phase);
    vec4 mv=modelViewMatrix*vec4(position,1.0);
    gl_PointSize=(2.0+p*3.5)*(260.0/-mv.z);
    gl_Position=projectionMatrix*mv;
  }`;
const partFrag=`
  varying vec3 vColor;
  void main(){
    float d=length(gl_PointCoord-0.5);
    if(d>0.5)discard;
    gl_FragColor=vec4(vColor*2.8,1.0-d*2.0);
  }`;

// ── Anatomical region definitions ─────────────────────────────────────────────
const REGION_DEFS = {
  frontal:   { color: new THREE.Color(0x4fc3f7), dir: new THREE.Vector3( 0.0, 0.3, 1.0).normalize() },
  parietal:  { color: new THREE.Color(0x81c784), dir: new THREE.Vector3( 0.0, 1.0, 0.0).normalize() },
  temporal:  { color: new THREE.Color(0xffb74d), dir: new THREE.Vector3( 1.0,-0.2, 0.2).normalize() },
  occipital: { color: new THREE.Color(0xf06292), dir: new THREE.Vector3( 0.0, 0.2,-1.0).normalize() },
  limbic:    { color: new THREE.Color(0xce93d8), dir: new THREE.Vector3( 0.3, 0.8, 0.1).normalize() },
};

// ── Build neural graph from /data payload ─────────────────────────────────────
function buildNeural(surfaceVerts, vizNodes, vizEdges){
  const MAX_PER_REGION = 15, MAX_EDGES = 200;

  // Group nodes by region; subsample to MAX_PER_REGION each
  const byRegion = {};
  for(const node of vizNodes){
    if(!byRegion[node.region]) byRegion[node.region] = [];
    if(byRegion[node.region].length < MAX_PER_REGION) byRegion[node.region].push(node);
  }

  // Place each displayed node on the brain surface
  const nodePositions = new Map(); // id -> THREE.Vector3
  const nodeRegions   = new Map(); // id -> region string
  const allPositions  = [];
  const allRegions    = [];

  for(const [region, nodes] of Object.entries(byRegion)){
    const def = REGION_DEFS[region] || REGION_DEFS.limbic;
    let pool = surfaceVerts.filter(v => v.clone().normalize().dot(def.dir) > 0.42);
    if(pool.length < 12)
      pool = surfaceVerts.filter(v => v.clone().normalize().dot(def.dir) > 0.25);
    pool = pool.sort(() => Math.random() - 0.5);
    for(let i = 0; i < nodes.length; i++){
      const v = pool[i % pool.length].clone().multiplyScalar(0.94);
      nodePositions.set(nodes[i].id, v);
      nodeRegions.set(nodes[i].id, region);
      allPositions.push(v);
      allRegions.push(region);
    }
  }

  if(allPositions.length === 0) return null;

  // Instanced node spheres
  const sphereGeo = new THREE.SphereGeometry(2.0, 14, 14);
  const icAttr = new THREE.InstancedBufferAttribute(new Float32Array(allPositions.length * 3), 3);
  sphereGeo.setAttribute('instanceColor', icAttr);
  const iMesh = new THREE.InstancedMesh(
    sphereGeo,
    new THREE.ShaderMaterial({ vertexShader: nodeVert, fragmentShader: nodeFrag }),
    allPositions.length
  );
  iMesh.frustumCulled = false;
  const dummy = new THREE.Object3D();
  allPositions.forEach((pos, i) => {
    const def = REGION_DEFS[allRegions[i]] || REGION_DEFS.limbic;
    dummy.position.copy(pos); dummy.updateMatrix();
    iMesh.setMatrixAt(i, dummy.matrix);
    icAttr.setXYZ(i, def.color.r, def.color.g, def.color.b);
  });
  iMesh.instanceMatrix.needsUpdate = true; icAttr.needsUpdate = true;
  scene.add(iMesh);

  // Filter and cap edges
  const displayedEdges = vizEdges
    .filter(e => nodePositions.has(e.src) && nodePositions.has(e.dst))
    .slice(0, MAX_EDGES);

  // Bezier edges with gradient GLSL
  const edgeRegistry = [];
  function addEdge(p1, p2, r1, r2){
    const S=26, pts=[], ts=[], cas=[], cbs=[];
    const c1=(REGION_DEFS[r1]||REGION_DEFS.limbic).color;
    const c2=(REGION_DEFS[r2]||REGION_DEFS.limbic).color;
    const mid = p1.clone().lerp(p2, 0.5);
    const ctrl = mid.clone()
      .add(mid.clone().normalize().multiplyScalar(-(12 + Math.random()*18)))
      .add(new THREE.Vector3((Math.random()-.5)*12,(Math.random()-.5)*12,(Math.random()-.5)*12));
    edgeRegistry.push({ p1: p1.clone(), p2: p2.clone(), ctrl: ctrl.clone(), r: r1 });
    for(let i=0;i<=S;i++){
      const t=i/S, q=p1.clone().lerp(ctrl,t).lerp(ctrl.clone().lerp(p2,t),t);
      pts.push(q.x,q.y,q.z); ts.push(t);
      cas.push(c1.r,c1.g,c1.b); cbs.push(c2.r,c2.g,c2.b);
    }
    const g=new THREE.BufferGeometry();
    g.setAttribute('position',new THREE.Float32BufferAttribute(pts,3));
    g.setAttribute('t',       new THREE.Float32BufferAttribute(ts,1));
    g.setAttribute('colA',    new THREE.Float32BufferAttribute(cas,3));
    g.setAttribute('colB',    new THREE.Float32BufferAttribute(cbs,3));
    scene.add(new THREE.Line(g, new THREE.ShaderMaterial({
      vertexShader:edgeVert,fragmentShader:edgeFrag,transparent:true,depthWrite:false})));
  }

  for(const e of displayedEdges){
    const p1=nodePositions.get(e.src), p2=nodePositions.get(e.dst);
    if(p1 && p2) addEdge(p1,p2,nodeRegions.get(e.src),nodeRegions.get(e.dst));
  }

  // Signal particles riding the bezier curves
  const PSIG = Math.min(220, Math.max(0, edgeRegistry.length * 3));
  if(PSIG === 0) return null;

  const sigEdges = Array.from({length:PSIG},()=>{
    const e=edgeRegistry[Math.floor(Math.random()*edgeRegistry.length)];
    return { edge:e, t:Math.random(), speed:0.003+Math.random()*0.007, r:e.r };
  });
  const pPos=new Float32Array(PSIG*3), pCol=new Float32Array(PSIG*3), pPhase=new Float32Array(PSIG);
  sigEdges.forEach((e,i)=>{
    const c=(REGION_DEFS[e.r]||REGION_DEFS.limbic).color;
    pCol[i*3]=c.r; pCol[i*3+1]=c.g; pCol[i*3+2]=c.b;
    pPhase[i]=Math.random()*Math.PI*2;
  });
  const pGeo=new THREE.BufferGeometry();
  pGeo.setAttribute('position',new THREE.BufferAttribute(pPos,3));
  pGeo.setAttribute('pColor',  new THREE.BufferAttribute(pCol,3));
  pGeo.setAttribute('phase',   new THREE.BufferAttribute(pPhase,1));
  const uTime={value:0};
  scene.add(new THREE.Points(pGeo,new THREE.ShaderMaterial({
    vertexShader:partVert,fragmentShader:partFrag,
    transparent:true,depthWrite:false,uniforms:{uTime}})));

  return { sigEdges, pPos, pGeo, uTime };
}

// ── Build legend using safe DOM methods ───────────────────────────────────────
function buildLegend(vizNodes){
  const seen = new Set();
  const container = document.getElementById('legend');
  container.textContent = '';           // clear safely
  for(const n of vizNodes){
    if(seen.has(n.region)) continue;
    seen.add(n.region);
    const def = REGION_DEFS[n.region] || REGION_DEFS.limbic;
    const row = document.createElement('div');
    row.className = 'li';
    const dot = document.createElement('div');
    dot.className = 'dot';
    dot.style.background = '#' + def.color.getHexString();
    const label = document.createElement('span');
    label.textContent = n.region + ' (' + n.lobe + ')';
    row.appendChild(dot);
    row.appendChild(label);
    container.appendChild(row);
  }
}

// ── Main: fetch data, load brain, wire neural graph ───────────────────────────
let neural = null;

const { nodes: vizNodes, edges: vizEdges, meta } = await fetch('/data').then(r => r.json());

document.getElementById('subtitle').textContent =
  ' · ' + meta.repo + ' · ' + meta.node_count + ' nodes · ' + meta.edge_count + ' edges';
buildLegend(vizNodes);
setStatus('');

function init(brainGeo){
  addBrainMeshes(brainGeo);
  neural = buildNeural(collectSurfaceVerts(brainGeo), vizNodes, vizEdges);
}

new GLTFLoader().load('./vendor/brain.glb',
  gltf => {
    let geo = null;
    gltf.scene.traverse(c => { if(c.isMesh && !geo) geo = c.geometry; });
    if(!geo){ init(makeBrainGeo()); setStatus('procedural brain'); return; }
    geo.computeBoundingBox();
    const box = geo.boundingBox;
    const scale = 200 / box.getSize(new THREE.Vector3()).length();
    geo.scale(scale, scale, scale);
    const center = box.getCenter(new THREE.Vector3()).multiplyScalar(scale);
    geo.translate(-center.x, -center.y, -center.z);
    geo.computeVertexNormals();
    init(geo);
    setStatus('real brain model');
  },
  undefined,
  () => {
    init(makeBrainGeo());
    setStatus('procedural brain · drop brain.glb in vendor/ for real model');
  }
);

// ── Render loop ───────────────────────────────────────────────────────────────
(function animate(t){
  requestAnimationFrame(animate);
  controls.update();
  if(neural){
    neural.uTime.value = t * 0.001;
    neural.sigEdges.forEach((e, i) => {
      e.t = (e.t + e.speed) % 1;
      const { p1, p2, ctrl } = e.edge, tt = e.t;
      const p = p1.clone().lerp(ctrl, tt).lerp(ctrl.clone().lerp(p2, tt), tt);
      neural.pPos[i*3] = p.x; neural.pPos[i*3+1] = p.y; neural.pPos[i*3+2] = p.z;
    });
    neural.pGeo.attributes.position.needsUpdate = true;
  }
  composer.render();
})(0);

window.addEventListener('resize', () => {
  const w = window.innerWidth, h = window.innerHeight;
  camera.aspect = w / h; camera.updateProjectionMatrix();
  renderer.setSize(w, h); composer.setSize(w, h);
});
</script>
</body>
</html>
```

- [ ] **Step 3: Smoke-test the static bundle**

```bash
cd src/cerebrofy/viz/static && python3 -m http.server 7399
```

Open `http://localhost:7399` in Firefox. Expected: brain renders, status shows `procedural brain · drop brain.glb…`, `/data` fetch fails gracefully (404 from python server — that is expected here). Ctrl+C when done.

- [ ] **Step 4: Commit**

```bash
git add src/cerebrofy/viz/static/
git commit -m "feat(viz): add Three.js static bundle with /data integration and safe DOM legend"
```

---

## Task 4: CLI command and registration

**Files:**
- Create: `src/cerebrofy/commands/viz.py`
- Modify: `src/cerebrofy/cli.py`
- Create: `tests/integration/test_viz_command.py`

- [ ] **Step 1: Write the failing integration tests**

Create `tests/integration/test_viz_command.py`:

```python
import json
import sqlite3
import threading
import time
import urllib.request
from pathlib import Path

import pytest
from click.testing import CliRunner

from cerebrofy.cli import main


@pytest.fixture
def repo_with_index(tmp_path):
    config_dir = tmp_path / ".cerebrofy"
    db_dir = config_dir / "db"
    db_dir.mkdir(parents=True)
    (config_dir / "config.yaml").write_text("version: 1\nproject: test\n")
    db = db_dir / "cerebrofy.db"
    con = sqlite3.connect(db)
    con.executescript("""
        CREATE TABLE nodes (
            id TEXT, name TEXT, type TEXT, lobe TEXT,
            file TEXT, line_start INTEGER, line_end INTEGER
        );
        CREATE TABLE edges (src_id TEXT, dst_id TEXT, rel_type TEXT);
        INSERT INTO nodes VALUES ('mod::alpha','alpha','function','mod','mod.py',1,5);
        INSERT INTO nodes VALUES ('mod::beta', 'beta', 'function','mod','mod.py',7,12);
        INSERT INTO edges VALUES ('mod::alpha','mod::beta','CALLS');
    """)
    con.commit()
    con.close()
    return tmp_path


def test_viz_errors_without_init(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(main, ["viz", "--no-open"])
    assert result.exit_code != 0
    assert "cerebrofy init" in result.output


def test_viz_errors_without_build(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".cerebrofy").mkdir()
    (tmp_path / ".cerebrofy" / "config.yaml").write_text("version: 1\n")
    result = CliRunner().invoke(main, ["viz", "--no-open"])
    assert result.exit_code != 0
    assert "cerebrofy build" in result.output


def test_viz_serves_data_endpoint(repo_with_index, monkeypatch):
    monkeypatch.chdir(repo_with_index)
    PORT = 17360

    def run():
        CliRunner().invoke(main, ["viz", "--port", str(PORT), "--no-open"])

    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(1.5)

    with urllib.request.urlopen(f"http://localhost:{PORT}/data") as resp:
        data = json.loads(resp.read())

    assert data["meta"]["node_count"] == 2
    assert data["meta"]["edge_count"] == 1
    assert all(
        n["region"] in ["frontal", "parietal", "temporal", "occipital", "limbic"]
        for n in data["nodes"]
    )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/integration/test_viz_command.py -v
```

Expected: `Error: No such command 'viz'.`

- [ ] **Step 3: Implement `commands/viz.py`**

Create `src/cerebrofy/commands/viz.py`:

```python
"""cerebrofy viz — serve interactive 3D brain visualization in the browser."""
from __future__ import annotations

import time
import webbrowser
from pathlib import Path

import rich_click as click

from cerebrofy.viz.graph_export import export_graph
from cerebrofy.viz.server import VizServer

_STATIC_DIR = Path(__file__).parent.parent / "viz" / "static"


@click.command("viz")
@click.option("--port", default=7331, show_default=True, help="Port to serve on.")
@click.option("--no-open", is_flag=True, help="Start server without opening browser.")
def cerebrofy_viz(port: int, no_open: bool) -> None:
    """Open interactive 3D brain visualization of the indexed codebase."""
    config_path = Path(".cerebrofy") / "config.yaml"
    if not config_path.exists():
        raise click.ClickException(
            "No .cerebrofy/ found. Run cerebrofy init first."
        )

    db_path = Path(".cerebrofy") / "db" / "cerebrofy.db"
    if not db_path.exists():
        raise click.ClickException(
            "No index found. Run cerebrofy build first."
        )

    click.echo("Reading graph from cerebrofy.db…")
    graph = export_graph(db_path)
    click.echo(
        f"  {graph.meta.node_count} nodes · "
        f"{graph.meta.edge_count} edges · "
        f"{graph.meta.lobe_count} lobes"
    )

    server = VizServer(_STATIC_DIR, graph, port=port)
    actual_port = server.start()
    url = f"http://localhost:{actual_port}"
    click.echo(f"Serving at {url}  (Ctrl+C to stop)")

    if not no_open:
        webbrowser.open(url)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
        click.echo("\nStopped.")
```

- [ ] **Step 4: Register in `cli.py`**

In `src/cerebrofy/cli.py`, add to the import block after line 11:

```python
from cerebrofy.commands.viz import cerebrofy_viz
```

Add after `main.add_command(cerebrofy_migrate)`:

```python
main.add_command(cerebrofy_viz)
```

- [ ] **Step 5: Run all viz tests**

```bash
uv run pytest tests/unit/viz/ tests/integration/test_viz_command.py -v
```

Expected: 15 passed.

- [ ] **Step 6: Commit**

```bash
git add src/cerebrofy/commands/viz.py src/cerebrofy/cli.py \
        tests/integration/test_viz_command.py
git commit -m "feat(viz): add cerebrofy viz command with HTTP server and browser launch"
```

---

## Task 5: Full suite, coverage, and push

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest -v
```

Expected: all existing tests pass, zero regressions.

- [ ] **Step 2: Check coverage on new modules**

```bash
uv run pytest tests/unit/viz/ --cov=src/cerebrofy/viz --cov-report=term-missing
```

Expected: `graph_export.py` and `server.py` each ≥85%.

- [ ] **Step 3: Lint**

```bash
uv run ruff check src/cerebrofy/viz/ src/cerebrofy/commands/viz.py
```

Expected: no errors.

- [ ] **Step 4: Push**

```bash
git push origin feat/cerebrofy-viz
```

---

## Self-Review

**Spec coverage:**
- `cerebrofy viz --port --no-open` → Task 4
- Reads `cerebrofy.db`, no re-indexing → Task 1
- `RUNTIME_BOUNDARY` excluded → Task 1 (SQL + test)
- Stable lobe→region round-robin → Task 1 (`_assign_region`)
- Unknown lobe → limbic fallback → Task 3 (`REGION_DEFS[n.region] || REGION_DEFS.limbic`)
- Local HTTP server + `/data` endpoint → Task 2
- Static Three.js bundle, no CDN → Task 3
- GLB load with procedural fallback → Task 3
- Bloom, rim-glow nodes, bezier edges, signal particles → Task 3
- Subsampling MAX_PER_REGION=15, MAX_EDGES=200 → Task 3
- Port retry → Task 2 (tested)
- Clear error for missing init/build → Task 4 (tested)
- Empty DB → `neural=null`, brain renders without nodes → Task 3 (graceful guard)
- Unit tests for graph_export and server → Tasks 1, 2
- Integration test → Task 4
- `innerHTML` with data avoided — safe DOM methods used in `buildLegend` → Task 3
