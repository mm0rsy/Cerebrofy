"""Unit tests for memory/decay.py."""
from __future__ import annotations

import time
from pathlib import Path

from cerebrofy.config.loader import MemoryConfig
from cerebrofy.memory.decay import compute_decay, recompute_all_decay, _decay_status
from cerebrofy.memory.store import Memory, open_memories_db, write_memory, get_memory


def _cfg(**kw) -> MemoryConfig:
    defaults = dict(decay_half_life_days=70.0, possibly_stale_threshold=0.3, stale_threshold=0.1)
    defaults.update(kw)
    return MemoryConfig(**defaults)


def _mem(id: str, created_ts: int, neuron_id: str | None = None, status: str = "active") -> Memory:
    return Memory(
        id=id, neuron_id=neuron_id, lobe=None, type="warning",
        title="T", body="B", author=None,
        created_ts=created_ts, tags=(), decay_score=1.0, status=status,
    )


def test_compute_decay_fresh_memory():
    now = int(time.time())
    m = _mem("m1", created_ts=now)
    score = compute_decay(m, neuron_signature_changed=False, current_ts=now, config=_cfg())
    assert 0.99 <= score <= 1.0


def test_compute_decay_one_half_life():
    now = int(time.time())
    old_ts = now - 70 * 86400  # exactly one half-life ago
    m = _mem("m1", created_ts=old_ts)
    score = compute_decay(m, neuron_signature_changed=False, current_ts=now, config=_cfg())
    assert 0.48 <= score <= 0.52  # ~0.5 after one half-life


def test_compute_decay_signature_changed_penalty():
    now = int(time.time())
    m = _mem("m1", created_ts=now)
    score_stable = compute_decay(m, neuron_signature_changed=False, current_ts=now, config=_cfg())
    score_changed = compute_decay(m, neuron_signature_changed=True, current_ts=now, config=_cfg())
    assert score_changed < score_stable
    assert score_changed <= 0.31  # fresh × 0.3


def test_decay_status_transitions():
    cfg = _cfg(possibly_stale_threshold=0.3, stale_threshold=0.1)
    assert _decay_status(1.0, cfg) == "active"
    assert _decay_status(0.5, cfg) == "active"
    assert _decay_status(0.29, cfg) == "possibly_stale"
    assert _decay_status(0.09, cfg) == "stale"
    assert _decay_status(0.0, cfg) == "stale"


def test_recompute_all_decay_updates_status(tmp_path):
    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True)
    conn = open_memories_db(cerebrofy_dir)

    old_ts = int(time.time()) - 200 * 86400  # ~200 days old
    m = _mem("m1", created_ts=old_ts, neuron_id="node-abc")
    write_memory(conn, m, [0.1] * 384)
    conn.commit()

    cfg = _cfg(decay_half_life_days=70.0, possibly_stale_threshold=0.3, stale_threshold=0.1)
    changed = recompute_all_decay(conn, {"node-abc"}, cfg)
    conn.commit()

    updated = get_memory(conn, "m1")
    assert updated is not None
    assert updated.decay_score < 0.3
    assert updated.status in ("possibly_stale", "stale")
    assert changed >= 1


def test_recompute_all_decay_time_only_for_unattached(tmp_path):
    cerebrofy_dir = tmp_path / ".cerebrofy"
    (cerebrofy_dir / "db").mkdir(parents=True)
    conn = open_memories_db(cerebrofy_dir)

    now = int(time.time())
    m = _mem("m1", created_ts=now, neuron_id=None)  # no neuron attached
    write_memory(conn, m, [0.1] * 384)
    conn.commit()

    cfg = _cfg()
    recompute_all_decay(conn, {"some-other-node"}, cfg)
    conn.commit()

    updated = get_memory(conn, "m1")
    assert updated is not None
    assert updated.decay_score > 0.99  # fresh, no signature penalty
