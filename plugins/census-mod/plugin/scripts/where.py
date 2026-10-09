"""``census where``: a read-only report of where census and census-mod are on this machine.

It exists so a skill can learn the config dir, the census dir, the installs in the plugin cache and the
enabled plugins from ONE plain command, instead of composing shell with ``${VAR:-default}`` expansions (which
Claude Code stops to ask about even for read-only checks). Never raises; writes nothing.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from scripts import store as st

PLUGIN_DIRS_ENV = "CLAUDE_CODE_PLUGIN_DIRS"
MOD_MARKER = "hooks/hooks.json"  # census-mod is a mod: its plugin root carries hooks/hooks.json


def _settings(path: Path) -> tuple[bool, bool | None, dict[str, Any]]:
    """(exists, valid, data): valid is None when there is no file; data is {} unless it is a JSON object."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False, None, {}
    except OSError:  # there, but not readable (permissions, a directory): it exists, and is no use
        return True, False, {}
    except UnicodeError:  # there, but not text we can read (not UTF-8): invalid, not a crash
        return True, False, {}
    try:
        data = json.loads(text)
    except ValueError:
        return True, False, {}
    return (True, True, data) if isinstance(data, dict) else (True, False, {})


def _installs(cache: Path, plugin: str, marker: str) -> list[dict[str, Any]]:
    """The versions of ``plugin`` in ``<cache>/<marketplace>/<plugin>/<version>/`` that hold ``marker``, orphans marked."""
    found: list[dict[str, Any]] = []
    try:
        marketplaces = sorted(p for p in cache.iterdir() if p.is_dir())
    except OSError:
        return found
    for market in marketplaces:
        try:
            versions = sorted(p for p in (market / plugin).iterdir() if p.is_dir())
        except OSError:
            continue
        for root in versions:
            if (root / marker).is_file():
                found.append({
                    "marketplace": market.name, "version": root.name, "path": str(root),
                    "orphaned": (root / ".orphaned_at").exists(),
                })
    return found


def _plugin_dir_mentions(settings: dict[str, Any], name: str, active: bool = True) -> bool:
    # This process's own plugin dirs describe the ACTIVE account; another account is judged by its settings alone.
    values = [os.environ.get(PLUGIN_DIRS_ENV, "")] if active else []
    env = settings.get("env")
    if isinstance(env, dict) and isinstance(env.get(PLUGIN_DIRS_ENV), str):
        values.append(env[PLUGIN_DIRS_ENV])
    # A root names the plugin only as a whole path component: `/tmp/census-mod-backup/plugin` is not census-mod.
    return any(name in re.split(r"[\\/]", root) for v in values for root in re.split(r"[:;]", v))


def report(active: bool = True) -> dict[str, Any]:
    config = st.config_dir()
    settings_path = config / "settings.json"
    exists, valid, data = _settings(settings_path)
    enabled = data.get("enabledPlugins")
    enabled = enabled if isinstance(enabled, dict) else {}
    line = data.get("statusLine")
    command = line.get("command") if isinstance(line, dict) else None
    cache = config / "plugins" / "cache"
    mod_installs = [i for i in _installs(cache, "census-mod", MOD_MARKER) if not i["orphaned"]]
    via_dir = _plugin_dir_mentions(data, "census-mod", active)
    mod_enabled = via_dir or any(
        v is True for k, v in enabled.items() if isinstance(k, str) and k.startswith("census-mod@")
    )
    plugin_root = Path(__file__).resolve().parents[1]
    census_enabled_keys = [k for k, v in enabled.items() if isinstance(k, str) and k.startswith("census@") and v is True]
    notes: list[str] = []
    if (plugin_root / "hooks" / "hooks.json").is_file():
        # this file is census-mod's bundled copy: the thing to flag is the census plugin it replaces
        # only when census-mod is itself enabled: disabling census beside a disabled census-mod would leave no recorder
        if mod_enabled and census_enabled_keys:
            keys = ", ".join(sorted(census_enabled_keys))
            cmds = "; ".join(f"claude plugin disable {k}" for k in sorted(census_enabled_keys))
            notes.append(f"the census plugin is enabled too ({keys}) — census-mod replaces it; disable it: {cmds}")
    elif mod_enabled and (mod_installs or via_dir):
        notes.append(
            "census-mod is installed — use /census-setup instead; install one or the other "
            "(census and census-mod are alternatives)."
        )
    return {
        "notes": notes,
        "config_dir": str(config),
        "census_dir": str(st.census_dir()),
        "settings_path": str(settings_path),
        "settings_exists": exists,
        "settings_valid": valid,
        "status_line": command if isinstance(command, str) else None,
        "plugin_root": str(plugin_root),
        # whether THIS census ships /census:vitals: asked of the census a caller found, not guessed from a path
        "vitals": (Path(__file__).resolve().parent / "vitals.py").is_file(),
        "census_installs": _installs(cache, "census", "scripts/cli.py"),
        "enabled_census": {k: v for k, v in enabled.items() if isinstance(k, str) and k.startswith("census@")},
        "census_mod": {
            "installed": bool(mod_installs) or via_dir,
            "enabled": mod_enabled,
            "via_plugin_dir": via_dir,
            "installs": [f"{i['marketplace']} {i['version']}" for i in mod_installs],
        },
    }
