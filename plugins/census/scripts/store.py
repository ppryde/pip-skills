"""Census store: one worktree-indexed JSON file of status-line payloads.

Quarantine-safe: every public entry point swallows read / parse / lock / write
failures and never raises. A broken store must never break the status-line
render or the CLI command it piggybacks on.

Layout of ``~/.claude/census/status.json`` (override with ``CENSUS_STORE``)::

    {
      "version": 1,
      "limits": { "five_hour": {...}, "seven_day": {...}, "updated_at": <epoch> },
      "sessions": {
        "<session_id>": {
          "worktree_cwd": "<abs path>",
          "updated_at": <epoch>,
          "payload": { ...full status-line payload verbatim... }
        }
      }
    }
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from scripts import resolve

STORE_ENV = "CENSUS_STORE"
DEFAULT_STORE = Path.home() / ".claude" / "census" / "status.json"
SCHEMA_VERSION = 1

SESSION_TTL_SECONDS = 24 * 3600      # prune entries older than this on write
STALE_HORIZON_SECONDS = 90           # readers flag entries older than this as stale
_LOCK_ATTEMPTS = 50                  # 50 × 10ms = 0.5s bounded wait for the lock
_LOCK_DELAY_SECONDS = 0.01


def store_path() -> Path:
    override = os.environ.get(STORE_ENV)
    return Path(override) if override else DEFAULT_STORE


def _empty_store() -> dict[str, Any]:
    return {"version": SCHEMA_VERSION, "limits": None, "sessions": {}}


def _load(path: Path) -> dict[str, Any]:
    """Load the store, healing any missing/corrupt shape into a valid skeleton."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return _empty_store()
    if not isinstance(data, dict):
        return _empty_store()
    data.setdefault("version", SCHEMA_VERSION)
    if not isinstance(data.get("sessions"), dict):
        data["sessions"] = {}
    if "limits" not in data:
        data["limits"] = None
    return data


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".status.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _context_is_blank(payload: dict[str, Any]) -> bool:
    """True when the payload carries no live context figure.

    This is the post-``/compact`` and pre-first-API-call gap: ``current_usage``
    and ``used_percentage`` are both null/absent. We must not overwrite a good
    prior reading with this.
    """
    window = payload.get("context_window")
    if not isinstance(window, dict):
        return True
    return window.get("current_usage") is None and window.get("used_percentage") is None


def _prune(sessions: dict[str, Any], now: float) -> None:
    dead = [
        sid
        for sid, entry in sessions.items()
        if not isinstance(entry, dict)
        or now - float(entry.get("updated_at", 0) or 0) > SESSION_TTL_SECONDS
    ]
    for sid in dead:
        sessions.pop(sid, None)


def merge(
    store: dict[str, Any],
    payload: dict[str, Any],
    worktree: str | None,
    now: float,
) -> dict[str, Any]:
    """Fold one status-line payload into ``store`` in place; return ``store``.

    - Upserts the session entry keyed by ``session_id`` (no-op without one).
    - Preserves the prior context window when the incoming one is blank.
    - Hoists ``rate_limits`` to top-level ``limits`` only when present.
    - Prunes stale sessions.
    """
    sid = payload.get("session_id")
    if not isinstance(sid, str) or not sid:
        return store

    sessions = store["sessions"]
    previous = sessions.get(sid)

    if _context_is_blank(payload) and isinstance(previous, dict):
        prior_payload = previous.get("payload")
        if isinstance(prior_payload, dict) and isinstance(
            prior_payload.get("context_window"), dict
        ):
            payload = {**payload, "context_window": prior_payload["context_window"]}

    sessions[sid] = {
        "worktree_cwd": worktree,
        "updated_at": now,
        "payload": payload,
    }

    limits = payload.get("rate_limits")
    if isinstance(limits, dict) and limits:
        store["limits"] = {**limits, "updated_at": now}

    _prune(sessions, now)
    return store


def ingest(raw: str, now: float | None = None) -> None:
    """Parse a status-line payload from ``raw`` and record it. Never raises.

    Holds an exclusive ``fcntl.flock`` for the read-modify-write so concurrent
    per-turn writers from every session cannot lose each other's entries.
    """
    if now is None:
        now = time.time()
    try:
        payload = json.loads(raw)
    except ValueError:
        return
    if not isinstance(payload, dict) or not payload.get("session_id"):
        return

    path = store_path()
    lock_path = path.with_name(path.name + ".lock")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w") as lock:
            if not _acquire(lock):
                return
            store = _load(path)
            merge(store, payload, resolve.worktree_cwd(payload), now)
            _atomic_write(path, store)
    except OSError:
        return


def _acquire(lock: Any) -> bool:
    for _ in range(_LOCK_ATTEMPTS):
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            time.sleep(_LOCK_DELAY_SECONDS)
    return False


# --- Readers -------------------------------------------------------------------


def _with_meta(entry: dict[str, Any], limits: Any, now: float) -> dict[str, Any]:
    updated = float(entry.get("updated_at", 0) or 0)
    result = dict(entry)
    result["stale"] = (now - updated) > STALE_HORIZON_SECONDS
    result["limits"] = limits
    return result


def read_all() -> dict[str, Any]:
    """The whole store, healed to a valid shape."""
    return _load(store_path())


def limits() -> dict[str, Any] | None:
    value = _load(store_path()).get("limits")
    return value if isinstance(value, dict) else None


def latest_for_worktree(cwd: str, now: float | None = None) -> dict[str, Any] | None:
    """The freshest session entry indexed to ``cwd``, plus top-level limits.

    Returns None when no session matches. The result carries a ``stale`` flag
    (True when older than the staleness horizon) so a consumer can distinguish a
    live reading from a frozen one left by a dead session.
    """
    if now is None:
        now = time.time()
    key = resolve.normalise(cwd)
    store = _load(store_path())

    best: dict[str, Any] | None = None
    best_ts = -1.0
    for entry in store.get("sessions", {}).values():
        if not isinstance(entry, dict) or entry.get("worktree_cwd") != key:
            continue
        ts = float(entry.get("updated_at", 0) or 0)
        if ts > best_ts:
            best_ts, best = ts, entry

    if best is None:
        return None
    return _with_meta(best, store.get("limits"), now)


def for_session(sid: str, now: float | None = None) -> dict[str, Any] | None:
    if now is None:
        now = time.time()
    store = _load(store_path())
    entry = store.get("sessions", {}).get(sid)
    if not isinstance(entry, dict):
        return None
    return _with_meta(entry, store.get("limits"), now)
