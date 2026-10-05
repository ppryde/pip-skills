"""Read census, via its ``census read`` CLI, for the set of live session ids.

overseer's stale-claim reclaim (``db.reclaim_stale``) needs to tell a
genuinely abandoned claim (the holder's session is gone) apart from one
that's merely idle for a while. census is a SOFT dependency: overseer imports
no census code and parses no census files; it shells ``census read`` (the
sibling plugin's cli.py, ``CENSUS_CLI``, or ``census`` on PATH), which prints
the v1 view ``{"version": 1, "limits": ..., "sessions": {...}}``.

``live_session_ids`` returns ``None`` ("liveness unknown") if the CLI is
missing, fails, times out, or prints junk, and also when ``sessions`` is
empty: ``census read`` cannot tell a missing store from an empty one, and an
empty set would mark every claim stale. The caller (``db.reclaim_stale``)
then falls back to its own TTL-based check. Quarantine-safe, never raises.
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
STALE_HORIZON_SECONDS = 90  # matches census/vigil's own staleness horizon
_TIMEOUT_SECONDS: float = 5


def _now_epoch() -> float:
    return time.time()


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
    """``CENSUS_CLI``, else the census plugin found by walking up (either layout), else ``census`` on PATH."""
    override = os.environ.get(CLI_ENV)
    if override:
        return [sys.executable, override] if override.endswith(".py") else [override]
    found_cli = find_census()
    if found_cli is not None:
        return [sys.executable, str(found_cli)]
    found = shutil.which("census")
    return [found] if found else None


def _census_view() -> dict[str, Any] | None:
    cmd = census_cli()
    if cmd is None:
        return None
    try:
        result = subprocess.run(
            [*cmd, "read"],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def live_session_ids() -> "set[str] | None":
    """Session ids whose census entry is fresh within the staleness horizon.

    ``None`` = liveness unknown: census missing or failing, or no sessions at all
    (``census read`` cannot tell a missing store from an empty one, and an empty
    set would mark every claim stale). Callers fall back to their own TTL check.
    """
    data = _census_view()
    sessions = data.get("sessions") if data is not None else None
    if not isinstance(sessions, dict) or not sessions:
        return None
    now = _now_epoch()
    live: set[str] = set()
    for session_id, entry in sessions.items():
        if not isinstance(entry, dict):
            continue
        try:
            updated_at = float(entry.get("updated_at", 0) or 0)
        except (TypeError, ValueError):
            continue
        if now - updated_at <= STALE_HORIZON_SECONDS:
            live.add(session_id)
    return live
