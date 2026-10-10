"""Orchestrator markers: the cheap "is this session guarded?" signal (WF-265).

``pretool.sh`` runs on almost every tool call in every session. To keep that
free for sessions that orchestrate nothing, ``stamp_orchestrator`` also writes
one small JSON file per orchestrating session::

    <config dir>/overseer/.orchestrating/<session_id>
    {"db": "<abs board.db>", "repo": "<abs canonical repo root>", "state": "<abs central folder>"}

The shell hook only tests whether that file exists; ``hookfast.py`` reads it to
find the board without any git call. The marker is a HINT, never the source of
truth: ``board.db``'s ``orchestrators`` table decides. A stale marker (no live
card for its session) is deleted by the next ``hookfast`` run, and ``stamp``
sweeps week-old markers whose session no longer has a live card.

Stdlib only: this module is imported by ``hookfast.py`` on the hot path.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from scripts.guard import GuardCard

MARKER_DIRNAME = ".orchestrating"
STALE_AFTER_SECONDS = 7 * 24 * 3600
_SAFE_SESSION = re.compile(r"[A-Za-z0-9_-]+\Z")


@dataclass(frozen=True)
class Board:
    db: Path
    repo: Path
    state: Path


def config_dir() -> Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(override) if override else Path.home() / ".claude"


def marker_dir() -> Path:
    return config_dir() / "overseer" / MARKER_DIRNAME


def marker_path(session_id: str) -> Path | None:
    """None for an id that is not a plain token (it would be a path)."""
    return marker_dir() / session_id if _SAFE_SESSION.match(session_id) else None


def write_marker(session_id: str, board: Board) -> None:
    path = marker_path(session_id)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"db": str(board.db), "repo": str(board.repo), "state": str(board.state)}
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, path)


def read_marker(session_id: str) -> Board | None:
    path = marker_path(session_id)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text())
        return Board(Path(data["db"]), Path(data["repo"]), Path(data["state"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def remove_marker(session_id: str) -> None:
    path = marker_path(session_id)
    if path is not None:
        path.unlink(missing_ok=True)


def live_cards(db: Path, session_id: str) -> list[GuardCard] | None:
    """Live cards ``session_id`` orchestrates, via a READ-ONLY connection: no
    schema pass, no pragma writes, no git. Parked cards are shelved, so the
    guard lets go of them; blocked cards keep it. ``None`` = could not tell
    (no board file, locked, unreadable) — callers fail open."""
    if not db.is_file():
        return None
    try:
        conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return None
    try:
        rows = conn.execute(
            "SELECT c.id, c.worktree, c.budget_estimate, c.budget_actual "
            "FROM cards c JOIN orchestrators o ON o.card_id = c.id "
            "WHERE o.session_id = ? AND c.archived = 0 AND c.status != 'parked' "
            "ORDER BY c.id",
            (session_id,),
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        conn.close()
    return [GuardCard(r[0], r[1], r[2], r[3] or 0) for r in rows]


def sweep(now: float | None = None) -> int:
    """Delete markers older than a week whose session has no live card.
    Best effort; returns how many were removed."""
    directory = marker_dir()
    if not directory.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - STALE_AFTER_SECONDS
    removed = 0
    for path in directory.iterdir():
        try:
            if path.name.startswith(".") or path.stat().st_mtime > cutoff:
                continue
        except OSError:
            continue
        board = read_marker(path.name)
        missing = board is None or not board.db.is_file()
        cards = [] if missing else live_cards(board.db, path.name)  # type: ignore[union-attr]
        if cards is None or cards:
            continue
        path.unlink(missing_ok=True)
        removed += 1
    return removed
