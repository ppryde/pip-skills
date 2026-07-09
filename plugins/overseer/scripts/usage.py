"""Dispatch-level token telemetry: usage.jsonl append and aggregation."""
from __future__ import annotations

import json
from pathlib import Path

USAGE_FILENAME = "usage.jsonl"


def append_usage(root: Path, entry: dict) -> None:
    with (root / USAGE_FILENAME).open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


def load_usage(root: Path) -> list[dict]:
    path = root / USAGE_FILENAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


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
