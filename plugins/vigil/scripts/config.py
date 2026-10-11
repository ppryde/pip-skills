"""Per-repo runtime config for context stewardship. Single-writer, under the vigil root.

`context.window` defaults to 200000 only as the last resort: when it is not set
explicitly, the transcript fallback detects the real window (see context.py).
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.store import ensure_root, read_private, vigil_root, write_private

DEFAULTS: dict[str, object] = {
    "context.threshold": 35,
    "context.mode": "local",
    "context.window": 200000,
}

_MODES = {"local", "remote"}


class ConfigError(ValueError):
    """An invalid config key or value."""


def config_path(repo_root: Path) -> Path:
    return vigil_root(repo_root) / "config.json"


def _stored(repo_root: Path) -> dict[str, object]:
    """Only the keys explicitly set (never the defaults); {} if absent or corrupt."""
    text = read_private(config_path(repo_root))
    if text is None:
        return {}
    try:
        stored = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return {k: v for k, v in stored.items() if k in DEFAULTS} if isinstance(stored, dict) else {}


def load_config(repo_root: Path) -> dict[str, object]:
    return {**DEFAULTS, **_stored(repo_root)}


def stored_window(repo_root: Path) -> int | None:
    """The explicitly configured `context.window`, or None when it was never set."""
    window = _stored(repo_root).get("context.window")
    return window if isinstance(window, int) and not isinstance(window, bool) and window > 0 else None


def get_config(repo_root: Path, key: str) -> object:
    if key not in DEFAULTS:
        raise ConfigError(f"unknown config key: {key}")
    return load_config(repo_root)[key]


def _coerce(key: str, value: str) -> object:
    if key == "context.mode":
        if value not in _MODES:
            raise ConfigError(f"context.mode must be one of {sorted(_MODES)}")
        return value
    if key in ("context.threshold", "context.window"):
        try:
            number = int(value)
        except ValueError as exc:
            raise ConfigError(f"{key} must be an integer") from exc
        if key == "context.threshold" and not 1 <= number <= 100:
            raise ConfigError("context.threshold must be between 1 and 100")
        if key == "context.window" and number <= 0:
            raise ConfigError("context.window must be positive")
        return number
    raise ConfigError(f"unknown config key: {key}")


def set_config(repo_root: Path, key: str, value: str) -> object:
    if key not in DEFAULTS:
        raise ConfigError(f"unknown config key: {key}")
    coerced = _coerce(key, value)
    stored = _stored(repo_root)  # explicit keys only: a default is never persisted as a choice
    stored[key] = coerced
    ensure_root(repo_root)
    write_private(config_path(repo_root), json.dumps(stored, indent=2, sort_keys=True) + "\n")
    return coerced
