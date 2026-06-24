"""Vulnerability blast radius scanner — offline package-based exposure analysis."""

from __future__ import annotations

import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cerebrofy.graph.edges import IMPORT_REL, RUNTIME_BOUNDARY


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VulnNeuron:
    """A neuron that directly calls a vulnerable package."""

    id: str
    name: str
    file: str
    line_start: int
    lobe: str
    call_target: str       # e.g. "external::requests.get"
    is_trust_boundary: bool
    is_test: bool


@dataclass(frozen=True)
class ExposurePath:
    """Critical exposure: a trust boundary entry point that reaches a package caller."""

    entry_point_name: str
    entry_point_file: str
    call_chain: list[str]   # function names from entry point → package caller
    exposure_score: float


@dataclass
class VulnResult:
    """Full result of a vulnerability blast radius scan."""

    package: str
    function_pattern: str | None
    pinned_version: str | None
    direct_callers: list[VulnNeuron] = field(default_factory=list)
    upstream_count: int = 0
    critical_exposure: list[ExposurePath] = field(default_factory=list)
    low_exposure: list[VulnNeuron] = field(default_factory=list)
    remediation_sequence: list[dict[str, Any]] = field(default_factory=list)
    memories_written: int = 0


# ---------------------------------------------------------------------------
# Package caller detection
# ---------------------------------------------------------------------------

def find_package_callers(
    package: str,
    function_pattern: str | None,
    conn: sqlite3.Connection,
) -> list[VulnNeuron]:
    """Find neurons that directly call the vulnerable package via RUNTIME_BOUNDARY edges."""
    if function_pattern:
        target_dst = f"external::{function_pattern}"
        rows = conn.execute(
            "SELECT DISTINCT e.src_id, e.dst_id FROM edges e "
            "WHERE e.rel_type = ? AND e.dst_id = ?",
            (RUNTIME_BOUNDARY, target_dst),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT e.src_id, e.dst_id FROM edges e "
            "WHERE e.rel_type = ? "
            "AND (e.dst_id = ? OR e.dst_id LIKE ?)",
            (RUNTIME_BOUNDARY, f"external::{package}", f"external::{package}.%"),
        ).fetchall()

    callers: list[VulnNeuron] = []
    seen_src: set[str] = set()

    for src_id, dst_id in rows:
        if src_id in seen_src or src_id.startswith("external::"):
            continue
        seen_src.add(src_id)

        row = conn.execute(
            "SELECT id, name, file, line_start FROM nodes WHERE id = ? LIMIT 1",
            (src_id,),
        ).fetchone()
        if not row:
            continue

        node_id, name, nfile, line_start = row
        lobe = Path(nfile).parts[0] if len(Path(nfile).parts) > 1 else "root"
        tb = _is_trust_boundary(node_id, conn)
        is_test = Path(nfile).parts[0] == "tests"

        callers.append(VulnNeuron(
            id=node_id,
            name=name,
            file=nfile,
            line_start=line_start,
            lobe=lobe,
            call_target=dst_id,
            is_trust_boundary=tb,
            is_test=is_test,
        ))

    return callers


def _is_trust_boundary(neuron_id: str, conn: sqlite3.Connection) -> bool:
    """Return True if no structural call edges point to this neuron (in_degree == 0).

    Excludes IMPORT and RUNTIME_BOUNDARY edges — only LOCAL_CALL/EXTERNAL_CALL count.
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE dst_id = ? AND rel_type NOT IN (?, ?)",
        (neuron_id, RUNTIME_BOUNDARY, IMPORT_REL),
    ).fetchone()
    return bool(row and row[0] == 0)


# ---------------------------------------------------------------------------
# Exposure path building (per-caller BFS for accurate attribution)
# ---------------------------------------------------------------------------

def _build_exposure_paths(
    direct_callers: list[VulnNeuron],
    conn: sqlite3.Connection,
    depth: int,
) -> tuple[list[ExposurePath], list[VulnNeuron], int]:
    """Classify each direct caller as critical or low exposure.

    Uses per-caller BFS so that trust boundary ancestors are correctly attributed
    to the specific caller they can reach (not pooled across all callers).

    Returns (critical_paths, low_exposure_neurons, total_upstream_count).
    """
    from cerebrofy.analysis.impact import bfs_callers

    critical: list[ExposurePath] = []
    low: list[VulnNeuron] = []
    seen_upstream_ids: set[str] = set()

    for caller in direct_callers:
        if caller.is_test:
            low.append(caller)
            continue

        if caller.is_trust_boundary:
            critical.append(ExposurePath(
                entry_point_name=caller.name,
                entry_point_file=caller.file,
                call_chain=[caller.name],
                exposure_score=1.0,
            ))
            continue

        # BFS upstream from this specific caller to find its own trust boundaries
        caller_upstream = bfs_callers(caller.id, conn, max_depth=depth)
        for ns in caller_upstream.values():
            for n in ns:
                seen_upstream_ids.add(n.id)

        ancestor_tb = _first_trust_boundary_ancestor(caller_upstream, conn)
        if ancestor_tb:
            critical.append(ExposurePath(
                entry_point_name=ancestor_tb["name"],
                entry_point_file=ancestor_tb["file"],
                call_chain=[ancestor_tb["name"], "→", caller.name],
                exposure_score=0.6,
            ))
        else:
            low.append(caller)

    return critical, low, len(seen_upstream_ids)


def _first_trust_boundary_ancestor(
    upstream: dict[int, list[Any]],
    conn: sqlite3.Connection,
) -> dict[str, str] | None:
    """Return the shallowest non-test trust boundary ancestor from a BFS result."""
    for _depth in sorted(upstream.keys()):
        for neuron in upstream[_depth]:
            if Path(neuron.file).parts[0] != "tests" and _is_trust_boundary(neuron.id, conn):
                return {"id": neuron.id, "name": neuron.name, "file": neuron.file}
    return None


# ---------------------------------------------------------------------------
# Remediation sequence
# ---------------------------------------------------------------------------

def _build_remediation(
    critical: list[ExposurePath],
    low: list[VulnNeuron],
    package: str,
    pinned_version: str | None,
) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []

    for i, path in enumerate(sorted(critical, key=lambda p: -p.exposure_score), start=1):
        steps.append({
            "step": i,
            "description": f"Patch {path.entry_point_name} ({path.entry_point_file}) — highest exposure",
            "neuron": f"{path.entry_point_file}::{path.entry_point_name}",
            "exposure_score": path.exposure_score,
        })

    for low_caller in low:
        steps.append({
            "step": len(steps) + 1,
            "description": f"Review {low_caller.name} ({low_caller.file}) — low/test exposure",
            "neuron": f"{low_caller.file}::{low_caller.name}",
            "exposure_score": 0.1,
        })

    version_hint = ">= <safe_version>" if pinned_version is None else f"> {pinned_version}"
    steps.append({
        "step": len(steps) + 1,
        "description": f"Pin {package} {version_hint} in pyproject.toml after patching call sites",
        "neuron": None,
        "exposure_score": 0.0,
    })

    return steps


# ---------------------------------------------------------------------------
# Pinned version detection
# ---------------------------------------------------------------------------

def read_pinned_version(package: str, root: Path) -> str | None:
    """Read the pinned version of *package* from pyproject.toml or requirements.txt."""
    version = _read_from_pyproject(package, root / "pyproject.toml")
    if version:
        return version
    return _read_from_requirements(package, root / "requirements.txt")


def _read_from_pyproject(package: str, path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef,import-not-found]
        except ImportError:
            return None
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        deps: list[str] = []
        deps += data.get("project", {}).get("dependencies", [])
        poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        for name, spec in poetry_deps.items():
            if isinstance(spec, str):
                deps.append(f"{name}{spec}")
            elif isinstance(spec, dict):
                deps.append(f"{name}{spec.get('version', '')}")
        pkg_norm = re.escape(package.lower().replace("-", "_").replace(".", "_"))
        for dep in deps:
            dep_norm = dep.strip().lower().replace("-", "_")
            # Match package name followed by a version operator, bracket, or end-of-string
            if re.match(rf"^{pkg_norm}[\s><=!;@\[]", dep_norm) or dep_norm == pkg_norm:
                return dep.strip()
    except Exception:
        pass
    return None


def _read_from_requirements(package: str, path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        pkg_norm = re.escape(package.lower().replace("-", "_").replace(".", "_"))
        for line in path.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            line_norm = line.lower().replace("-", "_")
            if re.match(rf"^{pkg_norm}[\s><=!;@\[]", line_norm) or line_norm == package.lower():
                return line
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Memory writing
# ---------------------------------------------------------------------------

def write_vuln_memories(
    callers: list[VulnNeuron],
    package: str,
    cerebrofy_dir: Path,
) -> int:
    """Write one warning memory per direct caller neuron. Returns count written."""
    try:
        from cerebrofy.memory.embedder import embed_memory
        from cerebrofy.memory.store import Memory, open_memories_db, write_memory

        conn = open_memories_db(cerebrofy_dir)
        written = 0
        try:
            for caller in callers:
                title = f"Calls {package} package — check for CVE advisories before modifying"
                body = (
                    f"This function calls `{caller.call_target}` from the `{package}` package. "
                    f"If a CVE affecting `{package}` is disclosed, this is a direct exposure point. "
                    f"{'Entry point — external input can reach this call.' if caller.is_trust_boundary else 'Internal caller — trace to entry points for full exposure.'}"
                )
                mem = Memory(
                    id=str(uuid.uuid4()),
                    neuron_id=caller.id,
                    lobe=caller.lobe,
                    type="warning",
                    title=title,
                    body=body,
                    author="agent:vuln-scanner",
                    created_ts=int(time.time()),
                    tags=("security", "vuln", package),
                    decay_score=1.0,
                    status="active",
                )
                embedding = embed_memory(title, body)
                write_memory(conn, mem, embedding)
                written += 1
            conn.commit()
        finally:
            conn.close()
        return written
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def compute_vuln_blast_radius(
    package: str,
    function_pattern: str | None,
    conn: sqlite3.Connection,
    depth: int = 2,
    cerebrofy_dir: Path | None = None,
    write_memories: bool = False,
    root: Path | None = None,
) -> VulnResult:
    """Run full vulnerability blast radius computation."""
    pinned = read_pinned_version(package, root) if root else None

    direct_callers = find_package_callers(package, function_pattern, conn)
    if not direct_callers:
        return VulnResult(
            package=package,
            function_pattern=function_pattern,
            pinned_version=pinned,
        )

    critical, low, upstream_count = _build_exposure_paths(direct_callers, conn, depth)
    remediation = _build_remediation(critical, low, package, pinned)

    memories_written = 0
    if write_memories and cerebrofy_dir:
        memories_written = write_vuln_memories(direct_callers, package, cerebrofy_dir)

    return VulnResult(
        package=package,
        function_pattern=function_pattern,
        pinned_version=pinned,
        direct_callers=direct_callers,
        upstream_count=upstream_count,
        critical_exposure=critical,
        low_exposure=low,
        remediation_sequence=remediation,
        memories_written=memories_written,
    )
