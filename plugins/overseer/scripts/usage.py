"""Dispatch-level token telemetry: usage.jsonl append and aggregation."""
from __future__ import annotations

import json
import os
from pathlib import Path

USAGE_FILENAME = "usage.jsonl"


def append_usage(root: Path, entry: dict) -> None:
    """Append one line with a single ``os.write`` on an ``O_APPEND`` descriptor:
    the kernel positions and writes it atomically, so concurrent hooks cannot
    interleave bytes. (A line over ``PIPE_BUF`` is still one write on a regular
    file; real lines are ~200 bytes.)"""
    line = (json.dumps(entry) + "\n").encode()
    fd = os.open(root / USAGE_FILENAME, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def load_usage(root: Path) -> tuple[list[dict], int]:
    path = root / USAGE_FILENAME
    if not path.exists():
        return [], 0
    entries: list[dict] = []
    skipped = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            skipped += 1
    return entries, skipped


def summarise(entries: list[dict], card_id: str | None = None) -> dict:
    if card_id:
        entries = [e for e in entries if e.get("card") == card_id]
    by_role: dict[str, int] = {}
    by_card: dict[str, int] = {}
    for e in entries:
        tokens = int(e.get("tokens") or 0)
        role = e.get("role") or "?"
        card = e.get("card") or "?"
        by_role[role] = by_role.get(role, 0) + tokens
        by_card[card] = by_card.get(card, 0) + tokens
    return {"total": sum(by_role.values()), "by_role": by_role, "by_card": by_card}
