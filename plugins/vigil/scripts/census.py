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


def census_cli() -> list[str] | None:
    """How to run census: ``CENSUS_CLI``, else the sibling plugin's cli.py, else
    ``census`` on PATH. None when none is found."""
    override = os.environ.get(CLI_ENV)
    if override:
        return [sys.executable, override] if override.endswith(".py") else [override]
    sibling = Path(__file__).resolve().parents[2] / "census" / "scripts" / "cli.py"
    if sibling.exists():
        return [sys.executable, str(sibling)]
    found = shutil.which("census")
    return [found] if found else None


def _read(args: list[str]) -> dict[str, Any] | None:
    """One ``census read`` call -> its JSON object, or None on ANY failure or an
    empty answer. Inherits the environment, so CLAUDE_CONFIG_DIR / CENSUS_STORE
    pick the right account."""
    cmd = census_cli()
    if cmd is None:
        return None
    try:
        result = subprocess.run(
            [*cmd, "read", *args], capture_output=True, text=True, timeout=_TIMEOUT_SECONDS, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data else None


def _entry_ts(entry: dict) -> float:
    try:
        return float(entry.get("updated_at", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _fresh_entry(root: Path, now: float, session_id: str | None = None) -> dict | None:
    if session_id is not None:
        own = _read(["--session", session_id])
        if own is not None:
            # Our own entry IS this session: if it is stale, the answer is
            # "unavailable" -- never a sibling's reading (misattribution guard).
            return own if now - _entry_ts(own) <= STALE_HORIZON_SECONDS else None
    best = _read(["--worktree", os.path.realpath(str(root))])
    if best is None or now - _entry_ts(best) > STALE_HORIZON_SECONDS:
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
