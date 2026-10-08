"""Handover runtime state in a scope dir under the data root (`paths.scope_dir`).

One scope per worktree, or per `CONTEXT_VIGIL_SESSION` within a worktree. Every
function takes that scope dir and is quarantine-safe — it only touches its own
marker files and never raises on a missing path.

The markers (`paused`, `cooldown`, `clear-requested`, `handover-gate`,
`session-start`, `handoff.md`) carry no session identity. If two live sessions share a single
scope they share — and race on — the same markers: one session's nudge gates the
other, one session's post-`/clear` cooldown silences the other. Sharing one scope
across concurrent sessions is therefore unsupported without
`CONTEXT_VIGIL_SESSION`.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List, Tuple

from context_vigil import paths

ARCHIVE_KEEP = 20  # default; the live value is config `handover.archive_keep`
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


def started_marker(scope: Path) -> Path:
    """Touched at every SessionStart in the scope: when the current cycle began."""
    return scope / "session-start"


def started_at(scope: Path) -> float | None:
    try:
        return started_marker(scope).stat().st_mtime
    except OSError:
        return None


def handoff_path(scope: Path) -> Path:
    return scope / "handoff.md"


def prepared_marker(scope: Path) -> Path:
    """Beside handoff.md: this handoff was prepared by last light, not requested."""
    return scope / "handoff-prepared"


def is_prepared(scope: Path) -> bool:
    return prepared_marker(scope).exists() and handoff_path(scope).exists()


def handoff_archive_dir(scope: Path) -> Path:
    return scope / "archive"


def notes_path(scope: Path) -> Path:
    """Where the agent writes its handover notes: private (0600, under the 0700,
    self-ignoring data root) and outside every repository, so notes that mention a
    secret by accident can never be swept into a commit. Removed after a handover."""
    return scope / "notes.md"


def ensure_notes(scope: Path, template: str) -> Path:
    """Create the notes file from ``template`` if it is not there (0600, never
    through a symlink); an existing one is left as the agent wrote it."""
    path = notes_path(scope)
    paths.ensure_dir(scope)
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | paths.NOFOLLOW,
                     paths.PRIVATE_FILE_MODE)
    except FileExistsError:
        if path.is_symlink() or not path.is_file():
            raise IsADirectoryError(f"{path} is not a regular file — remove it and re-run")
        return path
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(template)
    return path


def is_paused(scope: Path) -> bool:
    return paused_flag(scope).exists()


def pause(scope: Path) -> None:
    _touch(paused_flag(scope))


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
    _touch(gate_marker(scope))


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


def _touch(marker: Path) -> None:
    """Create (0600) or refresh a marker; its mtime is what the TTL checks read.

    Never through a symlink: ``open_private`` opens with O_NOFOLLOW (a planted link
    fails with ELOOP), and the fchmod and utime act on that fd, not on a path."""
    fd = paths.open_private(marker, os.O_WRONLY | os.O_CREAT)
    try:
        os.fchmod(fd, paths.PRIVATE_FILE_MODE)   # tighten one left wider by an older version
        if os.utime in os.supports_fd:
            os.utime(fd, None)
        else:   # pragma: no cover - every supported platform has futimes
            os.utime(str(marker), None, follow_symlinks=False)
    finally:
        os.close(fd)


def _archived(archive: Path) -> List[Path]:
    """Archived handovers, newest first (by mtime, then name)."""
    try:
        files = [f for f in archive.iterdir() if f.is_file()]
    except OSError:
        return []

    def key(f: Path) -> Tuple[int, str]:
        try:
            return (f.stat().st_mtime_ns, f.name)
        except OSError:
            return (0, f.name)
    return sorted(files, key=key, reverse=True)


def prune_archive(scope: Path, keep: int = ARCHIVE_KEEP) -> None:
    """Keep only the newest ``keep`` archived handovers (0 keeps none). Never raises."""
    for old in _archived(handoff_archive_dir(scope))[max(keep, 0):]:
        try:
            old.unlink()
        except OSError:
            pass


def _archive(scope: Path, path: Path, keep: int, name: str = "handoff.md") -> None:
    """Move a handoff into the archive (0600), or drop it when ``keep`` is 0; then prune.

    Raises OSError on failure; callers decide whether that matters. A handoff that is
    a symlink was never written by us: it is unlinked, never archived or chmodded
    (that would tighten, or later print, whatever file it points at)."""
    if path.is_symlink():
        path.unlink()
        return
    if keep <= 0:
        path.unlink(missing_ok=True)
        prune_archive(scope, 0)
        return
    archive = paths.ensure_dir(handoff_archive_dir(scope))
    target = _uniquify(archive / name)
    path.rename(target)
    try:
        os.chmod(str(target), paths.PRIVATE_FILE_MODE)   # one written by an older version
    except OSError:
        pass
    prune_archive(scope, keep)


def write_handoff(scope: Path, handoff_text: str, keep: int = ARCHIVE_KEEP) -> None:
    """Save the handoff atomically (0600); an unconsumed older one is archived
    (uniquified), and the archive is pruned to the newest ``keep``."""
    paths.ensure_dir(scope)
    prepared_marker(scope).unlink(missing_ok=True)   # a new handoff is never "prepared" by default
    target = handoff_path(scope)
    if target.exists():
        try:
            _archive(scope, target, keep)
        except OSError:
            pass  # replacing below still keeps the new handoff; the old one is best-effort
    paths.write_private(target, handoff_text)


def write_prepared(scope: Path, handoff_text: str, keep: int = ARCHIVE_KEEP) -> None:
    """Save a last-light handoff: no clear flag, so nothing is cleared; /clear loads it."""
    write_handoff(scope, handoff_text, keep)
    _touch(prepared_marker(scope))


def discard_prepared(scope: Path, keep: int = ARCHIVE_KEEP) -> bool:
    """Archive a prepared handoff as ``handoff.discarded.md``. A real (requested)
    handoff is never touched. Returns whether one was discarded; never raises."""
    if not is_prepared(scope):
        prepared_marker(scope).unlink(missing_ok=True)   # a stray marker
        return False
    try:
        _archive(scope, handoff_path(scope), keep, name="handoff.discarded.md")
    except OSError:
        handoff_path(scope).unlink(missing_ok=True)
    prepared_marker(scope).unlink(missing_ok=True)
    return True


def request_clear(scope: Path, handoff_text: str, keep: int = ARCHIVE_KEEP) -> str:
    """Save the handoff and arm /clear. An explicit handover is never refused for a cooldown."""
    if is_paused(scope):
        return "paused"
    write_handoff(scope, handoff_text, keep)
    _touch(clear_flag(scope))
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
    - clear the ``handover-gate`` so the trigger can re-arm this session;
    - touch ``session-start`` (``status`` uses it to spot a status line that never
      reports in).

    ``cooldown=True`` — passed only for a ``/clear`` that actually loaded a
    handover — also touches the ``cooldown`` marker, the storm guard: census can
    lag a /clear and re-present the OLD session's high ctx% on the first prompt,
    and with the gate cleared that would nudge an obedient agent into
    re-handing-over. The cooldown suppresses nudges for ``handover.cooldown_seconds``
    only; an explicit ``handover --file`` always proceeds. A plain startup,
    resume or bare /clear starts none.
    """
    paths.ensure_dir(scope)
    clear_flag(scope).unlink(missing_ok=True)
    clear_gate(scope)
    _touch(started_marker(scope))
    if cooldown:
        _touch(cooldown_marker(scope))


def drop_orphan_clear(scope: Path, older_than: float | None = None) -> bool:
    """Unlink a ``clear-requested`` whose handoff is gone (resumed or discarded from
    another scope): a /clear for it would load nothing. With ``older_than``, only a
    flag older than that instant. Returns whether one was dropped; never raises."""
    flag = clear_flag(scope)
    try:
        if not flag.exists() or handoff_path(scope).exists():
            return False
        if older_than is not None and flag.stat().st_mtime >= older_than:
            return False
        flag.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _read_no_follow(path: Path) -> str | None:
    """The file's text, or None: missing, a symlink (never followed — a planted link
    must not turn ``--resume`` into a reader of some other file), unreadable, not
    UTF-8, or under a data root that is not ours alone."""
    try:
        return paths.read_private(path)
    except (OSError, UnicodeError):
        return None


def read_handoff(scope: Path) -> str | None:
    return _read_no_follow(handoff_path(scope))


def handoff_written_at(scope: Path) -> float | None:
    try:
        return handoff_path(scope).stat().st_mtime
    except OSError:
        return None


def consume_handoff(scope: Path, keep: int = ARCHIVE_KEEP) -> str | None:
    """Read the pending handoff, then archive it so it injects at most once.

    Returns the handoff text, or None if there is no pending handoff. Archiving
    (move to <scope>/archive/, uniquified, pruned to the newest ``keep``; with
    ``keep`` 0 the handoff is deleted instead) clears the re-injection gate —
    the handoff file's presence IS that gate — so a later unrelated launch will
    not re-inject a stale briefing. Quarantine-safe: on any archive failure it
    still removes the live handoff so re-injection cannot repeat, and never
    raises.
    """
    path = handoff_path(scope)
    text = _read_no_follow(path)
    if text is None:
        return None
    # The text is now in hand — from here we MUST return it, never raise
    # (the docstring's contract). Archiving is best-effort; if it fails we
    # still try to remove the live handoff so a stale briefing cannot re-inject,
    # and even that removal is guarded.
    try:
        _archive(scope, path, keep)
    except OSError:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        prepared_marker(scope).unlink(missing_ok=True)
    except OSError:
        pass
    return text
