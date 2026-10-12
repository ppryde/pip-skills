"""Live context-usage accounting from the session transcript JSONL.

Best-effort and quarantine-safe: any read/parse failure yields None, never an
exception — a context read must never break the CLI command it piggybacks on.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

DEFAULT_WINDOW = 200000
EXTENDED_WINDOW = 1_000_000

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
    if not isinstance(usage, dict) or not isinstance(message, dict):
        return None
    model = message.get("model")
    # carry the record's model next to its usage (for window detection)
    return {**usage, "_model": model} if isinstance(model, str) else usage


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


def context_reading(transcript_path: Path) -> tuple[int, str | None] | None:
    """(context tokens, model id of that record) for the newest usage record."""
    try:
        latest = _latest_usage(transcript_path)
    except OSError:
        return None
    if latest is None:
        return None
    try:
        tokens = sum(int(latest.get(field, 0) or 0) for field in _USAGE_FIELDS)
    except (ValueError, TypeError):
        return None
    model = latest.get("_model")
    return tokens, model if isinstance(model, str) else None


def payload_model_id(payload: dict) -> str | None:
    """The model id a hook payload carries (a string, or ``{"id": ...}``), if any."""
    model = payload.get("model")
    if isinstance(model, dict):
        model = model.get("id")
    return model if isinstance(model, str) and model else None


def configured_model_ids(root: Path) -> list[str]:
    """Model ids the user configured for this session: ``ANTHROPIC_MODEL`` and the
    ``model`` key of the config-dir / project settings files. Hook payloads and
    transcripts do not carry the ``[1m]`` suffix, so these are the only live
    signals for a 1M session below 200k tokens when census is absent."""
    found: list[str] = []
    env_model = os.environ.get("ANTHROPIC_MODEL")
    if env_model:
        found.append(env_model)
    cfg = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(cfg) if cfg else Path.home() / ".claude"
    for settings in (
        base / "settings.json",
        root / ".claude" / "settings.json",
        root / ".claude" / "settings.local.json",
    ):
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        model = data.get("model") if isinstance(data, dict) else None
        if isinstance(model, str) and model:
            found.append(model)
    return found


def detect_window(
    tokens: int, model_ids: list[str | None], configured: int | None = None
) -> int:
    """The session's context window for the transcript-based fallback.

    Order: an explicitly configured ``context.window`` wins; then a ``[1m]``
    suffix on any known model id (hook payload or transcript); then evidence
    (more than 200k tokens in context cannot fit a standard window); else 200k,
    used only when the window is unknown.
    """
    if configured:
        return configured
    if any(m and "[1m]" in m.lower() for m in model_ids):
        return EXTENDED_WINDOW
    if tokens > DEFAULT_WINDOW:
        return EXTENDED_WINDOW
    return DEFAULT_WINDOW


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
