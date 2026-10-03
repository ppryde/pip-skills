"""Layered settings: env → worktree → global → default, re-read on every call.

Nothing is cached, so a `config set` takes effect on the very next hook call.
An invalid value at any layer is skipped (never raised) so a typo in an env
var or a hand-edited file degrades to the next layer instead of breaking hooks.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Tuple

from context_vigil import paths

DEFAULTS: Dict[str, object] = {
    "context.threshold": 35,
    "context.window": 200000,
    "context.mode": "local",
    "nudge.repeat_step": 5,
}
KEYS = tuple(DEFAULTS)
ENV_VARS: Dict[str, str] = {
    "context.threshold": "CONTEXT_VIGIL_THRESHOLD",
    "context.window": "CONTEXT_VIGIL_WINDOW",
    "context.mode": "CONTEXT_VIGIL_MODE",
    "nudge.repeat_step": "CONTEXT_VIGIL_REPEAT_STEP",
}
_MODES = ("local", "remote")


class ConfigError(ValueError):
    """An unknown key or an out-of-range value."""


def coerce(key: str, raw: object) -> object:
    if key not in DEFAULTS:
        raise ConfigError(f"unknown key {key!r}; known: {', '.join(KEYS)}")
    if key == "context.mode":
        if raw not in _MODES:
            raise ConfigError("context.mode must be local or remote")
        return raw
    try:
        number = int(str(raw))
    except ValueError as exc:
        raise ConfigError(f"{key} must be a whole number") from exc
    if key == "context.threshold" and not 1 <= number <= 95:
        raise ConfigError("context.threshold must be a whole number 1–95")
    if key == "context.window" and number <= 0:
        raise ConfigError("context.window must be a positive whole number")
    if key == "nudge.repeat_step" and not 1 <= number <= 50:
        raise ConfigError("nudge.repeat_step must be a whole number 1–50")
    return number


def _read(path: Path) -> Dict[str, object]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _valid(key: str, raw: object) -> Tuple[bool, object]:
    try:
        return True, coerce(key, raw)
    except ConfigError:
        return False, None


def resolve(cwd: Path) -> Dict[str, Tuple[object, str]]:
    layers = (
        ("worktree", _read(paths.worktree_config_path(cwd))),
        ("global", _read(paths.global_config_path())),
    )
    result: Dict[str, Tuple[object, str]] = {}
    for key, default in DEFAULTS.items():
        chosen: Tuple[object, str] = (default, "default")
        env_raw = os.environ.get(ENV_VARS[key])
        ok, value = _valid(key, env_raw) if env_raw is not None else (False, None)
        if ok:
            chosen = (value, "env")
        else:
            for layer, data in layers:
                if key in data:
                    ok, value = _valid(key, data[key])
                    if ok:
                        chosen = (value, layer)
                        break
        result[key] = chosen
    return result


def load(cwd: Path) -> Dict[str, object]:
    return {key: value for key, (value, _) in resolve(cwd).items()}


def set_value(cwd: Path, key: str, raw: str, worktree: bool = False) -> object:
    value = coerce(key, raw)
    path = paths.worktree_config_path(cwd) if worktree else paths.global_config_path()
    data = _read(path)
    data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)
    return value


def threshold(cwd: Path) -> int:
    return int(str(load(cwd)["context.threshold"]))


def window(cwd: Path) -> int:
    return int(str(load(cwd)["context.window"]))


def mode(cwd: Path) -> str:
    return str(load(cwd)["context.mode"])


def repeat_step(cwd: Path) -> int:
    return int(str(load(cwd)["nudge.repeat_step"]))
