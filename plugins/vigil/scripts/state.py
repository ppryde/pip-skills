"""Vigil runtime state under `$CLAUDE_CONFIG_DIR/vigil/<repo-key>/`, keyed by the repo root.

The vigil root is the key (per repo root, not per session): one root, one watch. Every function is
quarantine-safe — it only touches its own marker files and never raises on a
missing path.

Single-writer assumption: these markers (`active`, `paused`, `cooldown`,
`clear-requested`, `handover-gate`, `handoff.md`) live under one
state dir per root and carry no session identity. If two live sessions share a single root
they share — and race on — the same markers: one session's nudge gates the
other, one session's `/clear` cooldown silences the other. Vigil therefore
assumes exactly one session per root, which the intended per-worktree session
model (one checkout, one watch) gives for free. Sharing a root across concurrent
sessions is unsupported.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from scripts.store import (
    PRIVATE_FILE_MODE,
    _private_dir,
    ensure_root,
    marker_exists,
    read_private,
    touch_private,
    vigil_root,
    write_private,
)

COOLDOWN_TTL_SECONDS = 300
GATE_TTL_SECONDS = 6 * 60 * 60  # 6h self-heal: mirrors COOLDOWN_TTL_SECONDS's pattern
ARCHIVE_KEEP = 20  # consumed handoffs kept in archive/ (newest first)
MAX_TITLE_LENGTH = 60  # keeps a tmux window title readable in the status bar


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


def rename_title_path(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "rename-title"


def _sanitize_title(title: str) -> str | None:
    """Collapse to a single line and cap length for a tmux window title.

    Control characters are dropped and `#` is doubled so tmux does not
    format-expand `#{...}` in the title; the cap never splits a `##` pair.
    """
    cleaned = "".join(ch for ch in title if ch.isprintable() or ch.isspace())
    collapsed = " ".join(cleaned.split())
    if not collapsed:
        return None
    out: list[str] = []
    length = 0
    for ch in collapsed:
        piece = "##" if ch == "#" else ch
        if length + len(piece) > MAX_TITLE_LENGTH:
            break
        out.append(piece)
        length += len(piece)
    return "".join(out)


def handoff_archive_dir(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "archive"


def begin(repo_root: Path) -> None:
    ensure_root(repo_root)
    touch_private(active_marker(repo_root))


def is_active(repo_root: Path) -> bool:
    return marker_exists(active_marker(repo_root))


def is_paused(repo_root: Path) -> bool:
    return marker_exists(paused_flag(repo_root))


def pause(repo_root: Path) -> None:
    ensure_root(repo_root)
    touch_private(paused_flag(repo_root))


def resume(repo_root: Path) -> None:
    paused_flag(repo_root).unlink(missing_ok=True)
    # Do not clear the gate while a handover is queued: the gate is what stops
    # the trigger re-nudging over an already-armed `clear-requested`. Clearing it
    # here would fire a redundant nudge on top of the pending handover.
    if not marker_exists(clear_flag(repo_root)):
        clear_gate(repo_root)


def _marker_active(marker: Path, ttl_seconds: float) -> bool:
    if not marker_exists(marker):
        return False
    try:
        age = time.time() - os.lstat(marker).st_mtime
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
    touch_private(gate_marker(repo_root))


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
    return marker_exists(clear_flag(repo_root))


def request_clear(repo_root: Path, handoff_text: str, title: str | None = None) -> str:
    if not is_active(repo_root):
        return "inactive"
    if is_paused(repo_root):
        return "paused"
    if _cooldown_active(repo_root):
        return "cooldown"
    ensure_root(repo_root)
    write_private(handoff_path(repo_root), handoff_text)
    sanitized = _sanitize_title(title) if title else None
    if sanitized:
        write_private(rename_title_path(repo_root), sanitized)
    else:
        # A stale title from an earlier arm must not bleed into this one.
        rename_title_path(repo_root).unlink(missing_ok=True)
    touch_private(clear_flag(repo_root))
    return "armed"


def consume_rename_title(repo_root: Path) -> str | None:
    """Read the pending window-rename title, then delete it (at most once)."""
    path = rename_title_path(repo_root)
    text = read_private(path)
    if text is None:
        return None
    path.unlink(missing_ok=True)
    return text.strip() or None


def consume_clear_flag(repo_root: Path) -> bool:
    if not is_active(repo_root) or is_paused(repo_root):
        return False
    if not marker_exists(clear_flag(repo_root)):
        return False
    clear_flag(repo_root).unlink(missing_ok=True)  # remove FIRST: cannot re-fire
    ensure_root(repo_root)
    touch_private(cooldown_marker(repo_root))
    return True


def begin_cycle(repo_root: Path) -> None:
    """Start a fresh handover cycle: any session start on an active root.

    Every SessionStart on an active root — whether a handover just landed, a
    bare `/clear` with nothing armed, or a plain relaunch — opens a new cycle:

    - unlink any queued ``clear-requested`` (its dispatch is done or moot);
    - clear the ``handover-gate`` so the trigger can re-arm this session;
    - TOUCH a fresh ``cooldown`` marker.

    The cooldown touch is the storm guard. Census's stale-horizon (~90s) means
    a fresh session can still read the OLD session's high ctx% on its first
    UserPromptSubmit; with the gate cleared and no cooldown, that would nudge →
    an obedient agent re-hands-over → handover storm. The 5-minute cooldown
    outlives census's lag window and suppresses both the nudge and
    ``request_clear`` through the grace period.
    """
    ensure_root(repo_root)
    clear_flag(repo_root).unlink(missing_ok=True)
    rename_title_path(repo_root).unlink(missing_ok=True)
    clear_gate(repo_root)
    touch_private(cooldown_marker(repo_root))


def read_handoff(repo_root: Path) -> str | None:
    return read_private(handoff_path(repo_root))


def prune_archive(repo_root: Path, keep: int = ARCHIVE_KEEP) -> None:
    """Keep only the newest ``keep`` archived handoffs. Never raises."""
    try:
        files = sorted(
            (f for f in handoff_archive_dir(repo_root).iterdir() if f.is_file()),
            key=lambda f: (f.stat().st_mtime_ns, f.name),
            reverse=True,
        )
    except OSError:
        return
    for old in files[max(keep, 0):]:
        try:
            old.unlink()
        except OSError:
            pass


def consume_handoff(repo_root: Path) -> str | None:
    """Read the pending handoff, then archive it so it injects at most once.

    Returns the handoff text, or None if there is no pending handoff. Archiving
    (move to <vigil_root>/archive/ as a timestamped name, newest 20 kept) clears the re-injection gate —
    the handoff file's presence IS that gate — so a later unrelated launch will
    not re-inject a stale briefing. Quarantine-safe: on any archive failure it
    still removes the live handoff so re-injection cannot repeat, and never
    raises.
    """
    path = handoff_path(repo_root)
    text = read_private(path)  # no-follow: a planted symlink reads as nothing
    if text is None:
        return None
    # The text is now in hand — from here we MUST return it, never raise
    # (the docstring's contract). Archiving is best-effort; if it fails we
    # still try to remove the live handoff so a stale briefing cannot re-inject,
    # and even that removal is guarded.
    try:
        archive = handoff_archive_dir(repo_root)
        _private_dir(archive)  # 0700, symlink and owner checked
        target = archive / f"handoff-{time.time_ns()}.md"
        path.rename(target)
        try:
            os.chmod(target, PRIVATE_FILE_MODE)
        except OSError:
            pass
        prune_archive(repo_root)
    except OSError:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return text
