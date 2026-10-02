"""This session's context %: census first, transcript estimate second.

census carries Claude Code's own ``used_percentage`` against the session's real
window, keyed by session id, so it is correct in git worktrees and with 1M
windows. The transcript fallback (last usage record ÷ configured window) only
runs when census has no fresh entry — first turn, status line not wired, or a
dead status line. Quarantine-safe: any failure yields None.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from context_vigil import census

_USAGE_FIELDS = (
    "input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def transcript_percent(transcript_path: Optional[str], window: int) -> Optional[int]:
    if not transcript_path or window <= 0:
        return None
    try:
        lines = Path(transcript_path).read_text(
            encoding="utf-8", errors="replace").splitlines()
    except (OSError, ValueError):
        return None
    latest = None
    for line in lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        message = record.get("message") if isinstance(record, dict) else None
        usage = message.get("usage") if isinstance(message, dict) else None
        if isinstance(usage, dict):
            latest = usage
    if latest is None:
        return None
    try:
        tokens = sum(int(latest.get(field, 0) or 0) for field in _USAGE_FIELDS)
    except (TypeError, ValueError, OverflowError):
        return None
    return round(100 * tokens / window)


def current_percent(cwd: Path, session_id: Optional[str],
                    transcript_path: Optional[str], window: int) -> Optional[int]:
    try:
        pct = census.context_percent(cwd, session_id=session_id)
    except Exception:  # measurement must never raise; use the transcript
        pct = None
    if pct is not None:
        return pct
    return transcript_percent(transcript_path, window)


def context_line(pct: Optional[int], threshold: int) -> str:
    if pct is None:
        return "ctx unknown"
    if pct >= threshold:
        return f"ctx {pct}% — over the {threshold}% threshold"
    return f"ctx {pct}%"
