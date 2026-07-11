"""Read the census store for worktree-correct live context %.

census (the sibling status-line recorder) writes each session's live context
usage, indexed by worktree, to a JSON store. Reading it is how vigil measures
context correctly inside a git worktree — where reconstructing the transcript
path from a cwd-slug fails because the worktree has no project dir of its own.

census is a SOFT dependency addressed purely through its documented on-disk data
contract: vigil imports no census code and shells nothing. If the store is
absent (census not installed, or no status line configured), stale, or lacks an
entry for this worktree, every function returns None and the caller falls back
to transcript-slug measurement. Quarantine-safe — never raises.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

STORE_ENV = "CENSUS_STORE"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
STALE_HORIZON_SECONDS = 90  # ~1.5x the status line's 60s refresh; older = not live


def store_path() -> Path:
    """Resolve the census store, rooted at CLAUDE_CONFIG_DIR like census itself.

    Matching census's own rooting is what keeps multi-account setups correct: a
    session reads the store of the account it runs under.
    """
    override = os.environ.get(STORE_ENV)
    if override:
        return Path(override)
    config = os.environ.get(CONFIG_DIR_ENV)
    base = Path(config) if config else Path.home() / ".claude"
    return base / "census" / "status.json"


def _fresh_entry(root: Path, now: float) -> dict | None:
    try:
        store = json.loads(store_path().read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(store, dict):
        return None
    key = os.path.realpath(str(root))
    best: dict | None = None
    best_ts = -1.0
    for entry in (store.get("sessions") or {}).values():
        if not isinstance(entry, dict) or entry.get("worktree_cwd") != key:
            continue
        ts = float(entry.get("updated_at", 0) or 0)
        if ts > best_ts:
            best_ts, best = ts, entry
    if best is None or now - best_ts > STALE_HORIZON_SECONDS:
        return None
    return best


def context_percent(root: Path, now: float | None = None) -> int | None:
    """Live context % for ``root`` from census, or None if unavailable/stale.

    Uses census's pre-computed ``used_percentage``, which already divides by the
    session's real window size (200k or the extended 1M) — so this is correct
    without vigil knowing the window.
    """
    if now is None:
        now = time.time()
    entry = _fresh_entry(root, now)
    if entry is None:
        return None
    payload = entry.get("payload")
    window = payload.get("context_window") if isinstance(payload, dict) else None
    pct = window.get("used_percentage") if isinstance(window, dict) else None
    if pct is None:
        return None
    try:
        return round(float(pct))
    except (TypeError, ValueError):
        return None
