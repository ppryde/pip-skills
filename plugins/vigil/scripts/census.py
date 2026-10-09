"""Read live context % through the census CLI (``census read``).

census (the sibling recorder, fed by its status-line hook or the census-mod mod) records each session's live context
usage, keyed by session id, with its worktree cwd. Asking it is how vigil
measures context correctly inside a git worktree — where reconstructing the
transcript path from a cwd-slug fails because the worktree has no project dir
of its own. When the caller knows its own session id, lookup is keyed by that
id (``census read --session``) — this keeps two live sessions sharing a
worktree from reading each other's context %; without a session id (or when
census has no entry for it yet), lookup falls back to the newest write for the
worktree (``census read --worktree``).

census is a HARD-coupled contract: vigil reads only through the ``census read``
CLI (``CENSUS_CLI``, the ``cli.path`` pointer census publishes, or ``census`` on PATH) and
parses its v1 entry JSON; it never touches census's on-disk store. Still
quarantine-safe: if the CLI is missing, slow, fails, or prints junk, or the
entry is stale or absent, every function returns None and the caller falls back
to transcript-slug measurement. Never raises.

A non-.py ``CENSUS_CLI`` must be executable. One context_percent can make two
CLI calls (--session then --worktree), so the worst case is ~2x the timeout
(~4 s). A FAILED --session call yields None outright; only an empty answer
falls through to the worktree lookup.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

CLI_ENV = "CENSUS_CLI"
STALE_HORIZON_SECONDS = 90  # ~1.5x the status line's 60s refresh; older = not live (when census sent no verdict)
_TIMEOUT_SECONDS: float = 2


def _pointer_file() -> Path:
    """Where census publishes its CLI location (``cli.path`` in its directory).

    Mirrors census's own directory rules: ``CENSUS_STORE`` (a value ending ``.json``
    means its parent), else ``$CLAUDE_CONFIG_DIR/census``, else ``~/.claude/census``.
    """
    store = os.environ.get("CENSUS_STORE")
    if store:
        path = Path(store)
        return (path.parent if path.suffix == ".json" else path) / "cli.path"
    config = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(config) if config else Path.home() / ".claude") / "census" / "cli.path"


def census_cli() -> list[str] | None:
    """How to run census: ``CENSUS_CLI``, else the path census published in ``cli.path``,
    else ``census`` on PATH. None when none is found. Never raises."""
    override = os.environ.get(CLI_ENV)
    if override:
        return [sys.executable, override] if override.endswith(".py") else [override]
    try:
        recorded = _pointer_file().read_text(encoding="utf-8").strip()
        if recorded and Path(recorded).is_file():
            return [sys.executable, recorded]
    except (OSError, ValueError):
        pass
    found = shutil.which("census")
    return [found] if found else None


_FAILED: dict[str, Any] = {}  # sentinel (compared by identity): the call itself failed


def _read(args: list[str]) -> dict[str, Any] | None:
    """One ``census read`` call -> its JSON object; None when census answered
    ``{}`` (no matching entry); ``_FAILED`` on ANY failure (no CLI, timeout,
    crash, non-zero exit, junk). Inherits the environment, so CLAUDE_CONFIG_DIR
    / CENSUS_STORE pick the right account."""
    cmd = census_cli()
    if cmd is None:
        return _FAILED
    try:
        result = subprocess.run(
            [*cmd, "read", *args], capture_output=True, text=True, timeout=_TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return _FAILED
    if result.returncode != 0:
        return _FAILED
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return _FAILED
    if not isinstance(data, dict):
        return _FAILED
    return data or None


def _entry_ts(entry: dict) -> float:
    """The entry's ``updated_at`` as a float; malformed/missing reads as 0.0
    (i.e. beyond any staleness horizon) -- quarantine-safe, never raises."""
    try:
        return float(entry.get("updated_at", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_live(entry: dict, now: float) -> bool:
    """Is this census entry a live session? census's own ``stale`` verdict when it sent a
    bool (a census-mod session has no heartbeat, so it is judged by its process), else
    the age rule on ``updated_at``."""
    verdict = entry.get("stale")
    if isinstance(verdict, bool):
        return not verdict
    return now - _entry_ts(entry) <= STALE_HORIZON_SECONDS


def _fresh_entry(root: Path, now: float, session_id: str | None = None) -> dict | None:
    if session_id is not None:
        own = _read(["--session", session_id])
        if own is _FAILED:
            # Can't tell whether we have an entry: never guess with a sibling's.
            return None
        if own is not None:
            # Our own entry IS this session: if it is stale, the answer is
            # "unavailable" -- never a sibling's reading (misattribution guard).
            return own if _is_live(own, now) else None
    best = _read(["--worktree", os.path.realpath(str(root))])
    if best is None or best is _FAILED or not _is_live(best, now):
        return None
    return best


def context_percent(
    root: Path, now: float | None = None, session_id: str | None = None
) -> int | None:
    """Live context % for ``root`` from census, or None if unavailable/stale.

    Uses census's pre-computed ``used_percentage``, which already divides by the
    session's real window size (200k or the extended 1M) — so this is correct
    without vigil knowing the window.

    When ``session_id`` is given and the store has an entry for it, that entry
    is used directly (still subject to the staleness horizon) — this is what
    keeps two live sessions sharing a worktree from reading each other's
    context %. Falls back to the worktree newest-write scan when no
    ``session_id`` is given, or when the store has no entry for it.
    """
    if now is None:
        now = time.time()
    entry = _fresh_entry(root, now, session_id)
    if entry is None:
        return None
    payload = entry.get("payload")
    window = payload.get("context_window") if isinstance(payload, dict) else None
    pct = window.get("used_percentage") if isinstance(window, dict) else None
    if pct is None:
        return None
    try:
        return round(float(pct))
    except (TypeError, ValueError):
        return None
