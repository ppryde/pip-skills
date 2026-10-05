"""Read live context % through the census CLI (``census read``).

census (the sibling status-line recorder) records each session's live context
usage, keyed by session id, with its worktree cwd. Asking it is how vigil
measures context correctly inside a git worktree — where reconstructing the
transcript path from a cwd-slug fails because the worktree has no project dir
of its own. When the caller knows its own session id, lookup is keyed by that
id (``census read --session``) — this keeps two live sessions sharing a
worktree from reading each other's context %; without a session id (or when
census has no entry for it yet), lookup falls back to the newest write for the
worktree (``census read --worktree``).

census is a HARD-coupled contract: vigil reads only through the ``census read``
CLI (``CENSUS_CLI``, the sibling plugin's cli.py, or ``census`` on PATH) and
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
STALE_HORIZON_SECONDS = 90  # ~1.5x the status line's 60s refresh; older = not live
_TIMEOUT_SECONDS: float = 2


def _version_key(name: str) -> tuple[int, ...]:
    """A directory name as a comparable version; non-numeric parts sort as 0."""
    return tuple(int(part) if part.isdigit() else 0 for part in name.split("."))


def find_census(_from: Path | None = None) -> Path | None:
    """The census plugin's ``scripts/cli.py`` in EITHER layout, or None.

    Walks up from this file and, at each level, tests ``<parent>/census/scripts/cli.py``
    (repo checkout), else the highest-version ``<parent>/census/<ver>/scripts/cli.py``
    (marketplace cache, skipping versions Claude Code marked ``.orphaned_at``).
    A local copy of ``find_plugin`` in overseer's cli_client: plugins cannot import
    each other.
    """
    start = (_from or Path(__file__)).resolve()
    for parent in start.parents:
        candidate = parent / "census"
        if not candidate.is_dir():
            continue
        direct = candidate / "scripts" / "cli.py"
        if direct.is_file():
            return direct
        versioned = [
            child / "scripts" / "cli.py"
            for child in candidate.iterdir()
            if child.is_dir()
            and not (child / ".orphaned_at").exists()
            and (child / "scripts" / "cli.py").is_file()
        ]
        if versioned:
            return max(versioned, key=lambda cli: _version_key(cli.parents[1].name))
    return None


def census_cli() -> list[str] | None:
    """How to run census: ``CENSUS_CLI``, else the census plugin found by walking up (either layout), else
    ``census`` on PATH. None when none is found."""
    override = os.environ.get(CLI_ENV)
    if override:
        return [sys.executable, override] if override.endswith(".py") else [override]
    found_cli = find_census()
    if found_cli is not None:
        return [sys.executable, str(found_cli)]
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


def _fresh_entry(root: Path, now: float, session_id: str | None = None) -> dict | None:
    if session_id is not None:
        own = _read(["--session", session_id])
        if own is _FAILED:
            # Can't tell whether we have an entry: never guess with a sibling's.
            return None
        if own is not None:
            # Our own entry IS this session: if it is stale, the answer is
            # "unavailable" -- never a sibling's reading (misattribution guard).
            return own if now - _entry_ts(own) <= STALE_HORIZON_SECONDS else None
    best = _read(["--worktree", os.path.realpath(str(root))])
    if best is None or best is _FAILED or now - _entry_ts(best) > STALE_HORIZON_SECONDS:
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
