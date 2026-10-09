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
    """Session ids census reports live: its ``stale`` verdict when the entry has one,
    else a census entry fresh within the staleness horizon.

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
        verdict = entry.get("stale")
        if isinstance(verdict, bool):  # census's own judgement (by process for a census-mod session)
            if not verdict:
                live.add(session_id)
            continue
        try:
            updated_at = float(entry.get("updated_at", 0) or 0)
        except (TypeError, ValueError):
            continue
        if now - updated_at <= STALE_HORIZON_SECONDS:
            live.add(session_id)
    return live
