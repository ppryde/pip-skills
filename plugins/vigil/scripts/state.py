"""Vigil runtime state under `.vigil/`, keyed by the repo root (cwd).

The vigil root is the per-session key: one root, one watch. Every function is
quarantine-safe — it only touches its own marker files and never raises on a
missing path.
"""
from __future__ import annotations

import time
from pathlib import Path

from scripts.store import _uniquify, ensure_root, vigil_root

COOLDOWN_TTL_SECONDS = 300
GATE_TTL_SECONDS = 6 * 60 * 60  # 6h self-heal: mirrors COOLDOWN_TTL_SECONDS's pattern


def active_marker(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "active"


def clear_flag(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "clear-requested"


def gate_marker(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "handover-gate"


def paused_flag(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "paused"


def cooldown_marker(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "cooldown"


def handoff_path(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "handoff.md"


def handoff_archive_dir(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "archive"


def begin(repo_root: Path) -> None:
    ensure_root(repo_root)
    active_marker(repo_root).touch()


def is_active(repo_root: Path) -> bool:
    return active_marker(repo_root).exists()


def is_paused(repo_root: Path) -> bool:
    return paused_flag(repo_root).exists()


def pause(repo_root: Path) -> None:
    ensure_root(repo_root)
    paused_flag(repo_root).touch()


def resume(repo_root: Path) -> None:
    paused_flag(repo_root).unlink(missing_ok=True)
    clear_gate(repo_root)


def _marker_active(marker: Path, ttl_seconds: float) -> bool:
    if not marker.exists():
        return False
    try:
        age = time.time() - marker.stat().st_mtime
    except OSError:
        return False
    if age >= ttl_seconds:
        marker.unlink(missing_ok=True)  # expired — self-heal, allow re-arm
        return False
    return True


def _cooldown_active(repo_root: Path) -> bool:
    return _marker_active(cooldown_marker(repo_root), COOLDOWN_TTL_SECONDS)


def cooldown_active(repo_root: Path) -> bool:
    """Public, read-only cooldown check for callers outside this module."""
    return _cooldown_active(repo_root)


def set_gate(repo_root: Path) -> None:
    ensure_root(repo_root)
    gate_marker(repo_root).touch()


def gate_active(repo_root: Path) -> bool:
    """TTL-aware: a stranded gate (crash between nudge and clear) self-heals."""
    return _marker_active(gate_marker(repo_root), GATE_TTL_SECONDS)


def clear_gate(repo_root: Path) -> None:
    gate_marker(repo_root).unlink(missing_ok=True)


def clear_requested(repo_root: Path) -> bool:
    """Read-only check: would a Stop hook currently dispatch a clear?

    Mirrors ``consume_clear_flag``'s conditions (active, not paused, flag
    present) WITHOUT consuming the flag — the manual Stop hook needs to know
    whether to print the loud instruction line without eating the flag the
    human's own ``/clear`` (and the following SessionStart) still depends on.
    """
    if not is_active(repo_root) or is_paused(repo_root):
        return False
    return clear_flag(repo_root).exists()


def request_clear(repo_root: Path, handoff_text: str) -> str:
    if not is_active(repo_root):
        return "inactive"
    if is_paused(repo_root):
        return "paused"
    if _cooldown_active(repo_root):
        return "cooldown"
    ensure_root(repo_root)
    handoff_path(repo_root).write_text(handoff_text)
    clear_flag(repo_root).touch()
    return "armed"


def consume_clear_flag(repo_root: Path) -> bool:
    if not is_active(repo_root) or is_paused(repo_root):
        return False
    if not clear_flag(repo_root).exists():
        return False
    clear_flag(repo_root).unlink(missing_ok=True)  # remove FIRST: cannot re-fire
    ensure_root(repo_root)
    cooldown_marker(repo_root).touch()
    return True


def arm_ready(repo_root: Path) -> None:
    cooldown_marker(repo_root).unlink(missing_ok=True)
    clear_flag(repo_root).unlink(missing_ok=True)


def read_handoff(repo_root: Path) -> str | None:
    path = handoff_path(repo_root)
    if not path.exists():
        return None
    try:
        return path.read_text()
    except OSError:
        return None


def consume_handoff(repo_root: Path) -> str | None:
    """Read the pending handoff, then archive it so it injects at most once.

    Returns the handoff text, or None if there is no pending handoff. Archiving
    (move to <vigil_root>/archive/, uniquified) clears the re-injection gate —
    the handoff file's presence IS that gate — so a later unrelated launch will
    not re-inject a stale briefing. Quarantine-safe: on any archive failure it
    still removes the live handoff so re-injection cannot repeat, and never
    raises.
    """
    path = handoff_path(repo_root)
    if not path.exists():
        return None
    try:
        text = path.read_text()
    except OSError:
        return None
    # The text is now in hand — from here we MUST return it, never raise
    # (the docstring's contract). Archiving is best-effort; if it fails we
    # still try to remove the live handoff so a stale briefing cannot re-inject,
    # and even that removal is guarded.
    try:
        archive = handoff_archive_dir(repo_root)
        archive.mkdir(parents=True, exist_ok=True)
        target = _uniquify(archive / "handoff.md")
        path.rename(target)
    except OSError:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return text
