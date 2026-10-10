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


def _read_raw(session_id: str) -> list[Board]:
    path = marker_path(session_id)
    if path is None:
        return []
    try:
        data = json.loads(path.read_text())
        entries = data["boards"] if "boards" in data else [data]  # legacy: one board
        return [Board(Path(e["db"]), Path(e["repo"]), Path(e["state"])) for e in entries]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _store(session_id: str, boards: list[Board]) -> None:
    path = marker_path(session_id)
    if path is None:
        return
    if not boards:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"boards": [
        {"db": str(b.db), "repo": str(b.repo), "state": str(b.state)} for b in boards
    ]}
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload))
    os.replace(tmp, path)


def write_marker(session_id: str, board: Board) -> None:
    """Add ``board`` to the session's marker (one session may orchestrate on
    several boards; the marker lists them all, keyed by board file)."""
    boards = [b for b in _read_raw(session_id) if b.db != board.db]
    _store(session_id, [*boards, board])


CHECKED_PREFIX = ".checked-"


def checked_path(session_id: str) -> Path | None:
    """The per-session "already looked for a board" sentinel (a dotfile in
    the marker dir, so ``pretool.sh`` can test it without an interpreter)."""
    return marker_dir() / (CHECKED_PREFIX + session_id) if _SAFE_SESSION.match(session_id) else None


def is_checked(session_id: str) -> bool:
    path = checked_path(session_id)
    return path is not None and path.exists()


def mark_checked(session_id: str) -> None:
    path = checked_path(session_id)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def read_boards(session_id: str) -> list[Board]:
    return _read_raw(session_id)


def read_marker(session_id: str) -> Board | None:
    boards = _read_raw(session_id)
    return boards[0] if boards else None


def remove_marker(session_id: str, db: Path | None = None) -> None:
    """Drop the marker, or only ``db``'s entry when given (the file goes when
    its last board does)."""
    if db is None:
        _store(session_id, [])
    else:
        _store(session_id, [b for b in _read_raw(session_id) if b.db != db])


def find_boards_for_session(session_id: str) -> list[Board]:
    """Boards on which ``session_id`` has a live orchestrated card, found with
    read-only opens and no git: ``OVERSEER_DB`` if set, else every
    ``<config dir>/overseer/*/board.db``. Used once PER SESSION (the
    ``.checked-<id>`` sentinel), so sessions already orchestrating at upgrade
    time are each picked up, and whenever the marker dir cannot be written."""
    candidates: list[Path] = []
    override = os.environ.get("OVERSEER_DB")
    if override:
        candidates.append(Path(override))
    else:
        base = config_dir() / "overseer"
        if base.is_dir():
            candidates.extend(sorted(base.glob("*/board.db")))
    found: list[Board] = []
    for db in candidates:
        cards = live_cards(db, session_id)
        if not cards:
            continue
        repo = db.parent
        try:
            conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=1.0)
            try:
                row = conn.execute("SELECT value FROM meta WHERE key = 'repo_root'").fetchone()
            finally:
                conn.close()
            if row and row[0]:
                repo = Path(row[0])
        except sqlite3.Error:
            pass
        state = Path(os.environ["OVERSEER_CENTRAL"]) if os.environ.get("OVERSEER_CENTRAL") else db.parent
        found.append(Board(db, repo, state))
    return found


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
            if path.stat().st_mtime > cutoff:
                continue
            if path.name.startswith(CHECKED_PREFIX):
                path.unlink(missing_ok=True)  # the session simply looks again
                continue
            if path.name.startswith("."):
                continue
        except OSError:
            continue
        boards = [b for b in read_boards(path.name) if b.db.is_file()]
        results = [live_cards(b.db, path.name) for b in boards]
        if any(r is None or r for r in results):
            continue
        path.unlink(missing_ok=True)
        removed += 1
    return removed
