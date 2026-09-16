"""The source list and its credentials.

``<home>/config.json`` holds ``{"sources": [...]}``. The published plugin ships
no file at all, so a fresh install has no sources and the page says "not
configured" rather than "nothing needs you". Swapping transport is a config
edit (``"via": "agent"`` -> ``"via": "api"``), never a refactor.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts import paths

IDENT_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]*\Z")
_REQUIRED = ("type", "via", "label", "context")


class ConfigError(Exception):
    """The config file is unusable. The message names the problem, never a secret."""


@dataclass(frozen=True)
class Source:
    type: str
    via: str
    label: str
    context: str
    options: dict[str, Any] = field(default_factory=dict)


def load_sources(path: Path | None = None) -> list[Source]:
    target = path if path is not None else paths.config_path()
    if not target.exists():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigError(f"config {target} is not readable JSON: {exc}") from None
    entries = data.get("sources", []) if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise ConfigError(f"config {target}: 'sources' must be a list")
    sources: list[Source] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ConfigError(f"config source #{i} must be an object")
        for key in _REQUIRED:
            if not isinstance(entry.get(key), str) or not entry[key]:
                raise ConfigError(f"config source #{i} is missing '{key}'")
        for key in ("label", "context"):
            if not IDENT_RE.match(entry[key]):
                raise ConfigError(f"config source #{i}: '{key}' must be a plain identifier")
        if entry["label"] in seen:
            raise ConfigError(f"config source #{i}: duplicate label '{entry['label']}'")
        seen.add(entry["label"])
        options = {k: v for k, v in entry.items() if k not in _REQUIRED}
        sources.append(Source(entry["type"], entry["via"], entry["label"], entry["context"],
                              options))
    return sources


def read_secret(label: str) -> str | None:
    try:
        value = paths.secret_path(label).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return value or None


def secret_is_private(label: str) -> bool:
    try:
        mode = paths.secret_path(label).stat().st_mode
    except OSError:
        return False
    return mode & 0o077 == 0
