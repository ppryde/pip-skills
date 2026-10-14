"""A git environment that cannot run repo-planted code through config.

Used by the two lookups the exec route can still reach (``store`` repo identity,
``resume`` branch check) and by the exec child's own environment. Hooks and the
fsmonitor are switched off through the ``GIT_CONFIG_*`` variables, which sit
above repo config in git's precedence; the system config is ignored and git
never prompts. Clean/smudge filters and diff drivers are NOT covered here: the
commands that run them (``add``, ``checkout``, ``diff``) are denied over exec
instead, and the two lookups never touch the index or the working tree.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

_PINNED_CONFIG = (("core.hooksPath", os.devnull), ("core.fsmonitor", "false"))


def hardened_git_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """A copy of ``env`` (default: the process environment) with the hardening
    appended after any ``GIT_CONFIG_COUNT`` entries it already carries."""
    out = dict(os.environ if env is None else env)
    try:
        count = max(int(out.get("GIT_CONFIG_COUNT", "0")), 0)
    except ValueError:
        count = 0
    for i, (key, value) in enumerate(_PINNED_CONFIG, start=count):
        out[f"GIT_CONFIG_KEY_{i}"] = key
        out[f"GIT_CONFIG_VALUE_{i}"] = value
    out["GIT_CONFIG_COUNT"] = str(count + len(_PINNED_CONFIG))
    out["GIT_CONFIG_NOSYSTEM"] = "1"
    out["GIT_TERMINAL_PROMPT"] = "0"
    return out
