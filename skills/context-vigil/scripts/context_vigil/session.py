"""Per-session records and the learned model → window table, under the data root.

Everything here is measured or decided by scripts and written to disk; nothing
reaches the model. A record lives at ``sessions/<session_id>.json`` and holds:

- ``headless`` (bool|null): true for ``entrypoint == "sdk-cli"``, false for
  ``cli`` / ``claude-desktop``, null while unknown. Never inferred from "no
  status line seen yet" — an interactive session's first turn has no census entry;
- ``has_statusline`` (bool): census has ingested this session id;
- ``window`` / ``window_source``: the context window last used and where it came from;
- ``transcript_offset`` / ``transcript_path``: how far the transcript has been read;
- ``last_usage_tokens`` / ``max_usage_tokens``: the latest and largest usage total seen;
- ``model_id`` / ``message_model``: the latest model ids seen in the transcript;
- ``head_checked``: the transcript head was read once for ``headless``;
- ``last_nudged_pct``: the ctx % of the most recent nudge in this cycle.

Quarantine-safe: loads degrade to defaults, saves swallow ``OSError``.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

from context_vigil import paths

RECORD_TTL_SECONDS = 7 * 24 * 3600

_DEFAULTS: Dict[str, Any] = {
    "headless": None,
    "has_statusline": False,
    "window": None,
    "window_source": None,
    "transcript_offset": None,
    "transcript_path": None,
    "last_usage_tokens": None,
    "max_usage_tokens": None,
    "model_id": None,
    "message_model": None,
    "head_checked": False,
    "last_nudged_pct": None,
}


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


def prune(now: Optional[float] = None) -> None:
    """Drop records untouched for a week; opportunistic, on first write of a new one."""
    cutoff = (time.time() if now is None else now) - RECORD_TTL_SECONDS
    try:
        for entry in paths.sessions_dir().iterdir():
            try:
                if entry.stat().st_mtime < cutoff:
                    entry.unlink(missing_ok=True)
            except OSError:
                continue
    except OSError:
        return


def mark_statusline(session_id: str) -> None:
    """Census ingested this session: it has a status line. Writes only on change."""
    record = load(session_id)
    if not record["has_statusline"]:
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
    table = windows()
    if table.get(model_id) == size:
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
    """The learned window for a model id, with the ``[1m]`` suffix and without."""
    if not model_id:
        return None
    table = windows()
    if model_id in table:
        return table[model_id]
    bare = model_id.split("[", 1)[0]
    return table.get(bare)
