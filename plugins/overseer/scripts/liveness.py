"""Read the census store for the set of currently live session ids.

overseer's stale-claim reclaim (``db.reclaim_stale``) needs to tell a
genuinely abandoned claim (the holder's session is gone) apart from one
that's merely idle for a while. Like vigil's ``census.py``, this is a SOFT
dependency addressed purely through census's documented on-disk data
contract (``plugins/census/scripts/store.py``): overseer imports no census
code and shells nothing here. If the store is absent (census not installed),
stale, unreadable, or malformed, ``live_session_ids`` returns ``None`` and
the caller (``db.reclaim_stale``) falls back to its own TTL-based staleness
check instead. Quarantine-safe — never raises.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

STORE_ENV = "CENSUS_STORE"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
STALE_HORIZON_SECONDS = 90  # matches census/vigil's own staleness horizon


def _now_epoch() -> float:
    return time.time()


def _store_path() -> Path:
    """Resolve the census store, rooted at CLAUDE_CONFIG_DIR like census itself."""
    override = os.environ.get(STORE_ENV)
    if override:
        return Path(override)
    config = os.environ.get(CONFIG_DIR_ENV)
    base = Path(config) if config else Path.home() / ".claude"
    return base / "census" / "status.json"


def live_session_ids() -> "set[str] | None":
    """Session ids whose census entry is fresh within the staleness horizon.

    ``None`` covers every failure path uniformly — missing store, unreadable
    file, malformed JSON, or a shape that doesn't match census's documented
    contract (a top-level ``sessions`` object) — never raises. Callers treat
    ``None`` as "liveness unknown" and fall back to their own TTL check.
    """
    try:
        raw = _store_path().read_text()
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    sessions = data.get("sessions")
    if not isinstance(sessions, dict):
        return None

    now = _now_epoch()
    live: set[str] = set()
    for session_id, entry in sessions.items():
        if not isinstance(entry, dict):
            continue
        try:
            updated_at = float(entry.get("updated_at", 0) or 0)
        except (TypeError, ValueError):
            continue
        if now - updated_at <= STALE_HORIZON_SECONDS:
            live.add(session_id)
    return live
