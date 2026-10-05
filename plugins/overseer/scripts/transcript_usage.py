"""Real token usage for one agent, totalled from its transcript JSONL.

The SubagentStop payload names the agent's own transcript
(``agent_transcript_path``). Summing it gives the actual spend that the old
``log-usage --tokens`` guesses undercounted ~100×. Telemetry never raises:
an unreadable file or a malformed line counts as zero.
"""
from __future__ import annotations

import json
from pathlib import Path

FIELDS = ("input", "cache_read", "cache_creation", "output")
_KEYS = {
    "input": "input_tokens",
    "cache_read": "cache_read_input_tokens",
    "cache_creation": "cache_creation_input_tokens",
    "output": "output_tokens",
}


def zero_usage() -> dict[str, int]:
    return dict.fromkeys(FIELDS, 0)


def sum_usage(path: Path) -> dict[str, int]:
    """A message streamed as several content blocks is written as several
    lines repeating the same ``message.id`` with identical usage, so usage is
    counted once per id (last line wins); id-less messages count per line."""
    by_id: dict[str, dict[str, object]] = {}
    anonymous: list[dict[str, object]] = []
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        lines = []
    for raw in lines:
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        message = entry.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
            continue
        msg_id = message.get("id")
        if isinstance(msg_id, str) and msg_id:
            by_id[msg_id] = message["usage"]
        else:
            anonymous.append(message["usage"])
    totals = zero_usage()
    for usage in [*by_id.values(), *anonymous]:
        for name, key in _KEYS.items():
            value = usage.get(key)
            if isinstance(value, int):
                totals[name] += value
    return totals


def raw_total(totals: dict[str, int]) -> int:
    return sum(totals[f] for f in FIELDS)


def budget_tokens(totals: dict[str, int]) -> int:
    """Tokens newly placed in context. Cache reads are excluded: they are the
    re-read amplification, and counting them would trip every card's budget."""
    return totals["input"] + totals["cache_creation"] + totals["output"]
