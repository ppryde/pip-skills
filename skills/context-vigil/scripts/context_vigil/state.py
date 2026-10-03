"""Handover runtime state in a scope dir under the data root (`paths.scope_dir`).

One scope per worktree, or per `CONTEXT_VIGIL_SESSION` within a worktree. Every
function takes that scope dir and is quarantine-safe — it only touches its own
marker files and never raises on a missing path.

The markers (`paused`, `cooldown`, `clear-requested`, `handover-gate`,
`handoff.md`) carry no session identity. If two live sessions share a single
scope they share — and race on — the same markers: one session's nudge gates the
other, one session's post-`/clear` cooldown silences the other. Sharing one scope
across concurrent sessions is therefore unsupported without
`CONTEXT_VIGIL_SESSION`.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

COOLDOWN_SECONDS = 60  # default; the live value is config `handover.cooldown_seconds`
GATE_TTL_SECONDS = 6 * 60 * 60  # 6h self-heal for a stranded gate


def _uniquify(target: Path) -> Path:
    """If target exists, append a numeric suffix ({stem}.1{suffix}, .2, …) until free."""
    original = target
    counter = 0
    while target.exists():
        counter += 1
        target = original.parent / f"{original.stem}.{counter}{original.suffix}"
    return target


def clear_flag(scope: Path) -> Path:
    return scope / "clear-requested"


def gate_marker(scope: Path) -> Path:
    return scope / "handover-gate"


def paused_flag(scope: Path) -> Path:
    return scope / "paused"


def cooldown_marker(scope: Path) -> Path:
    return scope / "cooldown"


def handoff_path(scope: Path) -> Path:
    return scope / "handoff.md"


def handoff_archive_dir(scope: Path) -> Path:
    return scope / "archive"


def is_paused(scope: Path) -> bool:
    return paused_flag(scope).exists()


def pause(scope: Path) -> None:
    scope.mkdir(parents=True, exist_ok=True)
    paused_flag(scope).touch()


def resume(scope: Path) -> None:
    paused_flag(scope).unlink(missing_ok=True)
    # Do not clear the gate while a handover is queued: the gate is what stops
    # the trigger re-nudging over an already-armed `clear-requested`. Clearing it
    # here would fire a redundant nudge on top of the pending handover.
    if not clear_flag(scope).exists():
        clear_gate(scope)


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


def cooldown_active(scope: Path, seconds: int = COOLDOWN_SECONDS) -> bool:
    """Read-only (self-healing) check: is a post-/clear grace window still running?

    ``seconds`` is the window length (config `handover.cooldown_seconds`); 0 means
    no cooldown at all. The window suppresses nudges only — never an explicit handover.
    """
    if seconds <= 0:
        return False
    return _marker_active(cooldown_marker(scope), seconds)


def set_gate(scope: Path) -> None:
    scope.mkdir(parents=True, exist_ok=True)
    gate_marker(scope).touch()


def gate_active(scope: Path) -> bool:
    """TTL-aware: a stranded gate (crash between nudge and clear) self-heals."""
    return _marker_active(gate_marker(scope), GATE_TTL_SECONDS)


def clear_gate(scope: Path) -> None:
    gate_marker(scope).unlink(missing_ok=True)


def clear_requested(scope: Path) -> bool:
    """Read-only check: would a Stop hook currently dispatch a clear?

    Mirrors ``consume_clear_flag``'s conditions (not paused, flag present)
    WITHOUT consuming the flag — the manual Stop hook needs to know whether to
    print the loud instruction line without eating the flag the human's own
    ``/clear`` (and the following SessionStart) still depends on.
    """
    if is_paused(scope):
        return False
    return clear_flag(scope).exists()


def request_clear(scope: Path, handoff_text: str) -> str:
    """Save the handoff and arm /clear. An explicit handover is never refused for a cooldown.

    The write is atomic, and an unconsumed older handoff it replaces is archived
    (uniquified), never destroyed.
    """
    if is_paused(scope):
        return "paused"
    scope.mkdir(parents=True, exist_ok=True)
    target = handoff_path(scope)
    if target.exists():
        try:
            archive = handoff_archive_dir(scope)
            archive.mkdir(parents=True, exist_ok=True)
            target.rename(_uniquify(archive / "handoff.md"))
        except OSError:
            pass  # replacing below still keeps the new handoff; the old one is best-effort
    tmp = scope / "handoff.md.tmp"
    tmp.write_text(handoff_text)
    os.replace(tmp, target)
    clear_flag(scope).touch()
    return "armed"


def consume_clear_flag(scope: Path) -> bool:
    if is_paused(scope):
        return False
    if not clear_flag(scope).exists():
        return False
    clear_flag(scope).unlink(missing_ok=True)  # remove FIRST: cannot re-fire
    return True


def begin_cycle(scope: Path, cooldown: bool = False) -> None:
    """Start a fresh handover cycle: any session start in this scope.

    Every SessionStart in a scope opens a new cycle:

    - unlink any queued ``clear-requested`` (its dispatch is done or moot);
    - clear the ``handover-gate`` so the trigger can re-arm this session.

    ``cooldown=True`` — passed only for a ``/clear`` that actually loaded a
    handover — also touches the ``cooldown`` marker, the storm guard: census can
    lag a /clear and re-present the OLD session's high ctx% on the first prompt,
    and with the gate cleared that would nudge an obedient agent into
    re-handing-over. The cooldown suppresses nudges for ``handover.cooldown_seconds``
    only; an explicit ``handover --file`` always proceeds. A plain startup,
    resume or bare /clear starts none.
    """
    scope.mkdir(parents=True, exist_ok=True)
    clear_flag(scope).unlink(missing_ok=True)
    clear_gate(scope)
    if cooldown:
        cooldown_marker(scope).touch()


def read_handoff(scope: Path) -> str | None:
    path = handoff_path(scope)
    if not path.exists():
        return None
    try:
        return path.read_text()
    except OSError:
        return None


def handoff_written_at(scope: Path) -> float | None:
    try:
        return handoff_path(scope).stat().st_mtime
    except OSError:
        return None


def consume_handoff(scope: Path) -> str | None:
    """Read the pending handoff, then archive it so it injects at most once.

    Returns the handoff text, or None if there is no pending handoff. Archiving
    (move to <scope>/archive/, uniquified) clears the re-injection gate —
    the handoff file's presence IS that gate — so a later unrelated launch will
    not re-inject a stale briefing. Quarantine-safe: on any archive failure it
    still removes the live handoff so re-injection cannot repeat, and never
    raises.
    """
    path = handoff_path(scope)
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
        archive = handoff_archive_dir(scope)
        archive.mkdir(parents=True, exist_ok=True)
        target = _uniquify(archive / "handoff.md")
        path.rename(target)
    except OSError:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return text
