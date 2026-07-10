"""Live context-usage accounting from the session transcript JSONL.

Best-effort and quarantine-safe: any read/parse failure yields None, never an
exception — a context read must never break the CLI command it piggybacks on.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DEFAULT_WINDOW = 200000

_USAGE_FIELDS = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def transcript_slug(cwd: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(cwd.resolve()))


def find_transcript(cwd: Path, home: Path) -> Path | None:
    proj = home / ".claude" / "projects" / transcript_slug(cwd)
    if not proj.is_dir():
        return None
    candidates = sorted(
        proj.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return candidates[0] if candidates else None


def _usage_of(line: str) -> dict | None:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None
    message = record.get("message") if isinstance(record, dict) else None
    usage = message.get("usage") if isinstance(message, dict) else None
    return usage if isinstance(usage, dict) else None


def context_tokens(transcript_path: Path) -> int | None:
    try:
        text = transcript_path.read_text()
    except OSError:
        return None
    latest: dict | None = None
    for line in text.splitlines():
        usage = _usage_of(line)
        if usage is not None:
            latest = usage
    if latest is None:
        return None
    return sum(int(latest.get(field, 0) or 0) for field in _USAGE_FIELDS)


def context_percent(tokens: int, window: int = DEFAULT_WINDOW) -> int:
    if window <= 0:
        return 0
    return round(100 * tokens / window)


def context_line(pct: int | None, threshold: int | None) -> str:
    if pct is None:
        return "ctx unknown"
    line = f"ctx {pct}%"
    if threshold is not None and pct >= threshold:
        line += f" — over {threshold}% threshold; consider handover"
    return line
