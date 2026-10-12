"""Helpers shared by every CLI command group."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from scripts import gitio, paths, usage
from scripts.render import est_tokens


def repo_key_of(cwd: Path) -> str:
    try:
        return paths.repo_key(gitio.common_dir(cwd))
    except gitio.GitError:
        return ""


def say(text: str) -> None:
    """Print to stdout; a closed pipe (`| head`) is a quiet end, not a traceback."""
    try:
        print(text)
        sys.stdout.flush()
    except BrokenPipeError:
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())  # silence exit-time flush


def session_id() -> str:
    return os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID", "")


def log_event(command: str, cwd: Path, view_id: str | None, started: float, text: str,
              code: int, payload: dict[str, object]) -> None:
    origin = os.environ.get("CONCORDANCE_ORIGIN")
    if origin:
        payload = {**payload, "origin": origin}
    try:
        usage.record(command, repo_key_of(cwd), view_id,
                     int((time.monotonic() - started) * 1000), est_tokens(text), code,
                     payload, session=session_id())
    except Exception:  # noqa: BLE001, S110 - the usage log must never fail a query
        pass


def utf8_streams() -> None:
    """Never let an odd terminal encoding turn output into a traceback."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
