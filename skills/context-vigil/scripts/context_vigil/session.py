"""Per-session records and the learned model → window table, under the data root.

Everything here is measured or decided by scripts and written to disk; nothing
reaches the model. A record lives at ``sessions/<session_id>.json`` and holds:

- ``headless`` (bool|null): true for the SDK entrypoints (``sdk-cli``, ``sdk-ts``,
  ``sdk-py``), false for ``cli`` / ``claude-vscode`` / ``claude-desktop``, null while
  unknown; the hook's ``CLAUDE_CODE_ENTRYPOINT`` wins over the transcript head.
  Never inferred from "no status line seen yet" — an interactive session's first
  turn has no census entry;
- ``has_statusline`` (bool): census has ingested this session id; until it has,
  census is not consulted for the session at all;
- ``window`` / ``window_source`` / ``window_confident``: the context window used,
  where it came from, and whether that source is authoritative (census, learned
  table, ``[1m]`` suffix, evidence) rather than the configured fallback;
- ``transcript_offset`` / ``transcript_path`` / ``transcript_ino`` / ``transcript_dev`` /
  ``transcript_size`` / ``transcript_head`` (hash of the first line): how far the
  transcript has been read, and which file that offset belongs to;
- ``last_usage_tokens`` / ``max_usage_tokens``: the latest and largest usage total seen;
- ``model_id`` / ``message_model``: the latest model ids seen in the transcript;
- ``window_model``: the latest model the window was resolved for (a change re-resolves it);
- ``head_attempts``: reads of a still-unsettled transcript head (bounded);
- ``head_checked``: the transcript head was read once for ``headless``;
- ``last_nudged_pct``: the ctx % of the most recent nudge in this cycle.

Read-modify-write of a record happens under ``locked`` (an flock on a sidecar
``<id>.lock``, bounded wait). Quarantine-safe: loads degrade to defaults, saves
swallow ``OSError``, and a lock that cannot be had means the update is skipped.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from context_vigil import paths

RECORD_TTL_SECONDS = 7 * 24 * 3600
_LOCK_ATTEMPTS = 100             # 100 x 10ms = 1s bounded wait (hooks are latency-bound)
_LOCK_DELAY_SECONDS = 0.01

_DEFAULTS: Dict[str, Any] = {
    "headless": None,
    "has_statusline": False,
    "window": None,
    "window_source": None,
    "window_confident": False,
    "transcript_offset": None,
    "transcript_path": None,
    "transcript_ino": None,
    "transcript_dev": None,
    "transcript_size": None,
    "transcript_head": None,
    "last_usage_tokens": None,
    "max_usage_tokens": None,
    "model_id": None,
    "message_model": None,
    "window_model": None,
    "head_attempts": 0,
    "head_checked": False,
    "last_nudged_pct": None,
}


def _acquire(lock: Any) -> bool:
    for _ in range(_LOCK_ATTEMPTS):
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            time.sleep(_LOCK_DELAY_SECONDS)
    return False


@contextmanager
def locked(key: str) -> Iterator[bool]:
    """Hold the sidecar lock for ``key`` (a session id or scope key); yields whether
    it was got. On False the caller skips its update. Never raises on lock trouble."""
    try:
        path = paths.session_lock_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a")
    except OSError:
        yield False
        return
    got = False
    try:
        got = _acquire(handle)
        yield got
    finally:
        if got:
            try:
                fcntl.flock(handle, fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def blank() -> Dict[str, Any]:
    return dict(_DEFAULTS)


def load(session_id: str) -> Dict[str, Any]:
    record = blank()
    try:
        data = json.loads(paths.session_record_path(session_id).read_text())
    except (OSError, ValueError):
        return record
    if isinstance(data, dict):
        record.update({k: v for k, v in data.items() if k in _DEFAULTS})
    return record


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def save(session_id: str, record: Dict[str, Any]) -> None:
    path = paths.session_record_path(session_id)
    try:
        fresh = not path.exists()
        _atomic_write(path, json.dumps(record, sort_keys=True) + "\n")
        if fresh:
            prune()
    except OSError:
        return


def _lock_free(lock: Path) -> bool:
    """Can ``lock`` be flock'd right now? (non-blocking; released again at once)"""
    try:
        with open(lock, "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle, fcntl.LOCK_UN)
        return True
    except OSError:
        return False


def prune(now: Optional[float] = None) -> None:
    """Drop records untouched for a week; opportunistic, on first write of a new one.

    ``*.lock`` sidecars are never pruned on their own age (their mtime is creation
    time, and unlinking a held lock lets a second process lock a fresh inode): one
    goes only together with its pruned record, and only if it is free right then.
    """
    cutoff = (time.time() if now is None else now) - RECORD_TTL_SECONDS
    try:
        for entry in paths.sessions_dir().iterdir():
            if entry.suffix == ".lock":
                continue
            try:
                if entry.stat().st_mtime >= cutoff:
                    continue
                entry.unlink(missing_ok=True)
                if entry.suffix == ".json":
                    lock = paths.session_lock_path(entry.stem)
                    if lock.exists() and _lock_free(lock):
                        lock.unlink(missing_ok=True)
            except OSError:
                continue
    except OSError:
        return


def mark_statusline(session_id: str) -> None:
    """Census ingested this session: it has a status line. Writes only on change."""
    with locked(session_id) as got:
        record = load(session_id)
        if got and not record["has_statusline"]:
            record["has_statusline"] = True
            save(session_id, record)


# --- learned model → window table ---------------------------------------------


def windows() -> Dict[str, int]:
    try:
        data = json.loads(paths.windows_path().read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items()
            if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v > 0}


def learn_window(model_id: str, size: int) -> None:
    if windows().get(model_id) == size:
        return
    with locked("_windows") as got:
        table = windows()
        if not got or table.get(model_id) == size:
            return
        table[model_id] = size
        try:
            _atomic_write(paths.windows_path(), json.dumps(table, indent=2, sort_keys=True) + "\n")
        except OSError:
            return


def learn_from_payload(payload: Dict[str, Any]) -> None:
    """Record ``model.id`` → ``context_window.context_window_size`` from a status-line payload."""
    model = payload.get("model")
    window = payload.get("context_window")
    model_id = model.get("id") if isinstance(model, dict) else None
    size = window.get("context_window_size") if isinstance(window, dict) else None
    if (isinstance(model_id, str) and model_id and isinstance(size, int)
            and not isinstance(size, bool) and size > 0):
        learn_window(model_id, size)


def lookup_window(model_id: Optional[str]) -> Optional[int]:
    """The learned window for a model id: the exact entry, else (for any suffix but
    ``[1m]``) the bare model's."""
    if not model_id:
        return None
    table = windows()
    if model_id in table:
        return table[model_id]
    if "[1m]" in model_id:
        return None            # an explicit 1M suffix never borrows the bare model's window
    return table.get(model_id.split("[", 1)[0])


def is_headless(session_id: Optional[str]) -> bool:
    """Headless by the environment's entrypoint when present, else by the record."""
    from_env = paths.headless_from_env()
    if from_env is not None:
        return from_env
    return bool(session_id) and load(session_id or "").get("headless") is True


def scope(cwd: Path, session_id: Optional[str]) -> Path:
    """The scope a hook or the CLI acts on: the headless session's own, else the
    worktree/session/pane scope."""
    if is_headless(session_id):
        return paths.headless_scope(cwd, session_id)
    return paths.scope_dir(cwd)
