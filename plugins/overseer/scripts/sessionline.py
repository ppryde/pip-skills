"""SessionStart one-liner: which cards are in flight in this repo (WF-265 PR B).

Replaces the ledger skill's "at the start of any session" auto-trigger, which cost ~2.3k
tokens in every tracked repo for a notice that fits one line. Standard library plus
``scripts.config`` (json, hashlib, sqlite3, subprocess for one ``git`` call): it never
imports ``cli.py``, PyYAML or the card model. The board is opened read-only and the
hook stays silent on anything unexpected (no board, no cards, a corrupt file).

    python3 sessionline.py <canonical-repo-root>   # prints hook JSON, or nothing
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct script invocation: put plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import config  # noqa: E402

LIST_CAP = 5


def board_path(repo_root: Path) -> Path:
    override = os.environ.get("OVERSEER_DB")
    return Path(override) if override else config.central_root(repo_root) / "board.db"


def in_flight(db_path: Path) -> list[tuple[str, str]]:
    if not db_path.is_file():
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
    try:
        rows = conn.execute(
            "SELECT id, stage FROM cards WHERE archived=0 AND status='in-flight' ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [(str(i), str(s or "-")) for i, s in rows]


def line(cards: list[tuple[str, str]]) -> str:
    shown = ", ".join(f"{i} {s}" for i, s in cards[:LIST_CAP])
    more = f" and {len(cards) - LIST_CAP} more" if len(cards) > LIST_CAP else ""
    return f"overseer: {len(cards)} in-flight ({shown}{more}). /overseer:ledger to resume."


def main(argv: list[str]) -> int:
    try:
        cards = in_flight(board_path(Path(argv[0]))) if argv else []
        if cards:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "SessionStart", "additionalContext": line(cards)}}))
    except Exception:  # noqa: BLE001 -- a notice is never worth a failed session start
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
