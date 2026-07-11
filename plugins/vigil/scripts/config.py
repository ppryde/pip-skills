"""Per-repo runtime config for context stewardship. Single-writer, under the vigil root."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.store import ensure_root, vigil_root

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


def load_config(repo_root: Path) -> dict[str, object]:
    merged = dict(DEFAULTS)
    path = config_path(repo_root)
    if path.exists():
        try:
            stored = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return merged
        if isinstance(stored, dict):
            for key in DEFAULTS:
                if key in stored:
                    merged[key] = stored[key]
    return merged


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
    stored = load_config(repo_root)
    stored[key] = coerced
    ensure_root(repo_root)
    config_path(repo_root).write_text(json.dumps(stored, indent=2, sort_keys=True) + "\n")
    return coerced
