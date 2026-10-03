"""This session's context %: census first, transcript estimate second.

census carries Claude Code's own ``used_percentage`` against the session's real
window, keyed by session id. It is trusted while the transcript has not changed
since census last wrote (a newer transcript means the status line is behind) and
never for a headless session, which has no status line. Otherwise the percentage
is the transcript's last usage total ÷ the session's window, found by a chain
(see ``resolve_window``). The transcript is read incrementally from a stored
offset (``transcript.py``). Quarantine-safe: any failure yields None.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from context_vigil import census, session, transcript

EXTENDED_WINDOW = 1_000_000
_STANDARD_WINDOW = 200_000
_FRESH_TOLERANCE_SECONDS = 2.0   # the status line renders just after the transcript write


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _entry_window(entry: Optional[Dict[str, Any]]) -> Optional[int]:
    payload = entry.get("payload") if entry else None
    window = payload.get("context_window") if isinstance(payload, dict) else None
    return _positive_int(window.get("context_window_size")) if isinstance(window, dict) else None


def _entry_model(entry: Optional[Dict[str, Any]]) -> Optional[str]:
    payload = entry.get("payload") if entry else None
    model = payload.get("model") if isinstance(payload, dict) else None
    model_id = model.get("id") if isinstance(model, dict) else None
    return model_id if isinstance(model_id, str) and model_id else None


def _usage_exceeds_standard(record: Dict[str, Any]) -> bool:
    return any(isinstance(v, int) and v > _STANDARD_WINDOW
               for v in (record.get("max_usage_tokens"), record.get("last_usage_tokens")))


def resolve_window(entry: Optional[Dict[str, Any]], record: Dict[str, Any],
                   configured: int) -> Tuple[int, str]:
    """The session's window and where it came from.

    A resolved window is fixed: the stored one is reused, never re-derived. The one
    exception is 200k -> 1M when observed usage proves more than 200k fits. A first
    resolution walks the chain below; first hit wins.
    """
    stored = _positive_int(record.get("window"))
    if stored:
        if stored == _STANDARD_WINDOW and _usage_exceeds_standard(record):
            return EXTENDED_WINDOW, "evidence"
        return stored, str(record.get("window_source") or "config")
    size = _entry_window(entry)                       # a. census, even if the reading is stale
    if size:
        return size, "census"
    size = session.lookup_window(_entry_model(entry))  # b. learned, via the status line's model
    if size:
        return size, "learned"
    model_id, message_model = record.get("model_id"), record.get("message_model")
    size = session.lookup_window(model_id) or session.lookup_window(message_model)
    if size:                                           # c. the transcript's model
        return size, "learned"
    if isinstance(model_id, str) and "[1m]" in model_id:
        return EXTENDED_WINDOW, "model-suffix"
    if _usage_exceeds_standard(record):                # d. evidence: more than 200k cannot fit
        return EXTENDED_WINDOW, "evidence"
    return configured, "config"                        # e. configured


def _census_unchanged(entry: Dict[str, Any], transcript_path: Optional[str]) -> bool:
    """True unless the transcript was written after census last heard from the session."""
    if not transcript_path:
        return True
    try:
        mtime = os.stat(transcript_path).st_mtime
        updated = float(entry.get("updated_at", 0) or 0)
    except (OSError, TypeError, ValueError):
        return True
    return mtime <= updated + _FRESH_TOLERANCE_SECONDS


def _census_percent(cwd: Path, session_id: Optional[str], transcript_path: Optional[str],
                    entry: Optional[Dict[str, Any]]) -> Optional[int]:
    if session_id is None:
        return census.context_percent(cwd)
    if entry is None:
        # unknown to census: a transcript is better evidence than a sibling's entry
        return None if transcript_path else census.context_percent(cwd, session_id=session_id)
    if not _census_unchanged(entry, transcript_path):
        return None
    return census.entry_percent(entry)


def _transcript_percent(path: str, record: Dict[str, Any], entry: Optional[Dict[str, Any]],
                        configured: int) -> Optional[int]:
    if record.get("transcript_path") != path:
        record["transcript_path"] = path
        record["transcript_offset"] = None
    tail = transcript.read_tail(path, record.get("transcript_offset"))
    if tail is None:
        return None
    record["transcript_offset"] = tail.offset
    if tail.model_id:
        record["model_id"] = tail.model_id
    if tail.message_model:
        record["message_model"] = tail.message_model
    if tail.has_usage:
        record["last_usage_tokens"] = tail.tokens
        peak = record.get("max_usage_tokens")
        if tail.tokens is not None and (not isinstance(peak, int) or tail.tokens > peak):
            record["max_usage_tokens"] = tail.tokens
    tokens = record.get("last_usage_tokens")
    window, source = resolve_window(entry, record, configured)
    record["window"], record["window_source"] = window, source
    if not isinstance(tokens, int):
        return None
    return round(100 * tokens / window)


def transcript_percent(transcript_path: Optional[str], window: int,
                       session_id: Optional[str] = None) -> Optional[int]:
    """Percent from the transcript alone (no census); ``window`` is the configured fallback."""
    if not transcript_path or window <= 0:
        return None
    record = session.load(session_id) if session_id else session.blank()
    before = dict(record)
    try:
        pct = _transcript_percent(transcript_path, record, None, window)
    except Exception:
        return None
    if session_id and record != before:
        session.save(session_id, record)
    return pct


def _detect_headless(record: Dict[str, Any], transcript_path: str) -> None:
    readable, headless = transcript.read_entrypoint(transcript_path)
    if readable:
        record["head_checked"] = True
    if headless is not None:
        record["headless"] = headless


def current_percent(cwd: Path, session_id: Optional[str],
                    transcript_path: Optional[str], window: int) -> Optional[int]:
    try:
        return _current_percent(cwd, session_id, transcript_path, window)
    except Exception:  # measurement must never raise
        return None


def _current_percent(cwd: Path, session_id: Optional[str],
                     transcript_path: Optional[str], window: int) -> Optional[int]:
    record = session.load(session_id) if session_id else session.blank()
    before = dict(record)
    if (transcript_path and record["headless"] is None and not record["head_checked"]):
        _detect_headless(record, transcript_path)
    entry: Optional[Dict[str, Any]] = None
    pct: Optional[int] = None
    if record["headless"] is not True:
        try:
            entry = census.for_session(session_id) if session_id else None
            pct = _census_percent(cwd, session_id, transcript_path, entry)
        except Exception:  # census trouble: use the transcript
            pct = None
        if entry is not None:
            record["has_statusline"] = True
    if pct is None and transcript_path and window > 0:
        pct = _transcript_percent(transcript_path, record, entry, window)
    if session_id and record != before:
        session.save(session_id, record)
    return pct


def context_line(pct: Optional[int], threshold: int) -> str:
    if pct is None:
        return "ctx unknown"
    if pct >= threshold:
        return f"ctx {pct}% — over the {threshold}% threshold"
    return f"ctx {pct}%"
