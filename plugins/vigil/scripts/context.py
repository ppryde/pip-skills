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


def find_transcript(
    cwd: Path, home: Path, config_dir: Path | None = None
) -> Path | None:
    """Newest transcript for cwd under `config_dir` (default `home/.claude`)."""
    base = config_dir if config_dir is not None else home / ".claude"
    proj = base / "projects" / transcript_slug(cwd)
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


_FIRST_CHUNK = 64 * 1024


def _tail_text(path: Path, size: int) -> tuple[str, bool]:
    """Last `size` bytes of path as text, plus whether that is the whole file."""
    with path.open("rb") as fh:
        fh.seek(0, 2)
        total = fh.tell()
        start = max(0, total - size)
        fh.seek(start)
        data = fh.read()
    return data.decode("utf-8", errors="replace"), start == 0


def _latest_usage(path: Path) -> dict | None:
    """Newest usage record, reading from the end in doubling chunks."""
    size = _FIRST_CHUNK
    while True:
        text, whole = _tail_text(path, size)
        lines = text.splitlines()
        if not whole and lines:
            lines = lines[1:]  # the first line is probably cut mid-record
        for line in reversed(lines):
            usage = _usage_of(line)
            if usage is not None:
                return usage
        if whole:
            return None
        size *= 2


def context_tokens(transcript_path: Path) -> int | None:
    try:
        latest = _latest_usage(transcript_path)
    except OSError:
        return None
    if latest is None:
        return None
    try:
        return sum(int(latest.get(field, 0) or 0) for field in _USAGE_FIELDS)
    except (ValueError, TypeError):
        return None


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
