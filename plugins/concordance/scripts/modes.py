"""Per-session delivery mode for inject-mode hooks: shadow (default) or inject."""
from __future__ import annotations

import re
from pathlib import Path

from scripts.paths import config_dir

MODES = ("shadow", "inject")
_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _dir() -> Path:
    return config_dir() / "concordance" / "modes"


def _file(session: str | None, repo: str) -> Path:
    name = f"session-{_SAFE.sub('_', session)}" if session else f"repo-{_SAFE.sub('_', repo)}"
    return _dir() / name


def set_mode(mode: str, session: str | None, repo: str) -> Path:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    path = _file(session, repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mode, encoding="utf-8")
    return path


def get_mode(session: str, repo: str) -> str:
    for path in (_file(session, repo), _file(None, repo)):
        try:
            mode = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if mode in MODES:
            return mode
    return "shadow"
