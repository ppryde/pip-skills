"""Where almoner keeps its config, store and credentials.

Rooted under the Claude config dir because ``CLAUDE_CONFIG_DIR`` is the account
isolation boundary on this machine (two accounts never share work content).
The source list is per-machine, not per-repo: every board shows the same digest.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
HOME_ENV = "ALMONER_HOME"
DB_ENV = "ALMONER_DB"

# Compiled locally rather than imported from `config` — that module already
# imports `paths`, and importing back would be a cycle.
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*\Z")


def config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    return Path(override) if override else Path.home() / ".claude"


def home() -> Path:
    override = os.environ.get(HOME_ENV)
    return Path(override) if override else config_dir() / "almoner"


def config_path() -> Path:
    return home() / "config.json"


def db_path() -> Path:
    override = os.environ.get(DB_ENV)
    return Path(override) if override else home() / "almoner.db"


def secret_path(label: str) -> Path:
    if not _LABEL_RE.match(label):
        raise ValueError(f"invalid secret label: {label!r}")
    return home() / "secrets" / label
