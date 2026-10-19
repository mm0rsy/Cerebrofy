"""#05 memory integration for closed sessions (Idea #11 → #05 → #11 Phase 2 loop).

When a session ends, its outcome/duration/neurons/blast-radius summary is
written as a single #05 decision memory so the cross-session synthesizer (#24)
can pattern-match on agent outcomes.

The memory *construction* (``build_session_memory``) is pure — no IO — so it is
unit-testable without mocking the memory store.  The persistence wrapper
(``write_memory_if_possible`` / ``write_session_summary_memory``) handles the
lazy #05 imports and the non-fatal-by-contract write.

Split from ``recorder.py`` (m9 maintainability split).
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from pathlib import Path

# Lightweight collaborator hoisted from function scope (m9): Memory is a plain
# dataclass, so importing it at module scope introduces no heavy/native load and
# makes this file's dependency graph visible.  The #05 store openers
# (``open_memories_db``, ``write_memory``) and the fastembed-backed embedder
# (``embed_memory``) stay lazy — see the inline comments for why.
from cerebrofy.memory.store import Memory
from cerebrofy.session._recorder.models import SessionRecord

# Re-exported logger name preserved for caplog-based tests that assert on
# ``cerebrofy.session.recorder``.
_logger = logging.getLogger("cerebrofy.session.recorder")


def build_session_memory(
    session: SessionRecord,
    *,
    author: str = "agent:session-recorder",
) -> Memory:
    """Build the #05 decision :class:`Memory` for a closed session (pure, no IO).

    The memory title is the session task; its body carries the outcome, duration,
    event count, neurons touched and the depth-2 blast-radius before->after delta
    so the cross-session synthesizer (#24) can pattern-match on agent outcomes —
    the Phase 2 loop #11 -> #05 -> #11.

    Split out from :func:`write_session_summary_memory` so the memory
    construction is unit-testable without mocking the memory store.
    """
    title = (session.task or "").strip()[:120] or "[no task]"
    blast = ""
    if session.blast_radius_before is not None or session.blast_radius_after is not None:
        blast = (
            f"; blast_radius_before={session.blast_radius_before} -> "
            f"after={session.blast_radius_after}"
        )
    body = (
        f"agent={session.agent or 'unknown'}; outcome={session.outcome}; "
        f"duration={session.duration_seconds}s; events={session.event_count}; "
        f"neurons_touched={len(session.neurons_touched)}{blast}"
    )
    if session.outcome_notes:
        body += f"\n\nnotes: {session.outcome_notes.strip()[:500]}"
    tags: tuple[str, ...] = ("session", f"outcome:{session.outcome}")
    return Memory(
        id=str(uuid.uuid4()),
        neuron_id=None,
        lobe=None,
        type="decision",
        title=title,
        body=body,
        author=author,
        created_ts=int(session.ended_at or time.time()),
        tags=tags,
        decay_score=1.0,
        status="active",
    )


def write_memory_if_possible(
    cerebrofy_dir: Path,
    memory: Memory,
    embedder: Callable[[str, str], list[float]],
) -> bool:
    """Persist *memory* to the #05 store, embedding via *embedder*.

    The #05 dependency is imported lazily at call time so tests can patch
    ``cerebrofy.memory.store.open_memories_db`` / ``write_memory``.  Non-fatal
    by contract — any failure (memories.db absent, #05 embedder offline,
    disk error) is logged and ``False`` is returned, mirroring
    ``cerebrofy.arch.memory.write_violation_memories``: the recording path must
    never fail because the memory layer did.
    """
    try:
        # Lazy: kept at call site (not module scope) so tests can monkeypatch
        # ``cerebrofy.memory.store.open_memories_db`` / ``write_memory``; a
        # module-level ``from`` would bind these names at import time and defeat
        # that patching.  Not a true import cycle — this is a deliberate test
        # seam for the #05 memory integration.
        from cerebrofy.memory.store import open_memories_db, write_memory

        conn = open_memories_db(cerebrofy_dir)
        try:
            embedding = embedder(memory.title, memory.body)
            write_memory(conn, memory, embedding)
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        _logger.warning(
            "failed to write session summary memory (title=%r) to %s",
            memory.title, cerebrofy_dir, exc_info=True,
        )
        return False


def write_session_summary_memory(
    cerebrofy_dir: Path,
    session: SessionRecord,
    *,
    author: str = "agent:session-recorder",
    embed_memory_fn: Callable[[str, str], list[float]] | None = None,
) -> bool:
    """Fold a closed session into the #05 memory layer as a single decision memory.

    Thin orchestrator: :func:`build_session_memory` constructs the pure
    :class:`Memory`, then :func:`write_memory_if_possible` persists it.  The
    memory write is non-fatal — a ``False`` return never masks a closed session.

    *embed_memory_fn* overrides the embedder used to embed the memory (defaults
    to the fastembed-backed ``cerebrofy.memory.embedder.embed_memory`` when
    omitted, preserving existing behavior).  Injecting a fake here lets callers —
    and tests — avoid any model/network initialization.
    """
    if embed_memory_fn is None:
        # Lazy: the default embed_memory pulls in the fastembed model provider
        # at import time, so defer it to call time.  This keeps importing this
        # module — which every CLI command does via ``cerebrofy.commands.session``
        # — free of the heavy ONNX model load, and lets callers fully override
        # the embedder via *embed_memory_fn* to avoid model/network init.
        from cerebrofy.memory.embedder import embed_memory

        embed_memory_fn = embed_memory
    memory = build_session_memory(session, author=author)
    return write_memory_if_possible(cerebrofy_dir, memory, embed_memory_fn)
