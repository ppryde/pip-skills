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

# Inherited git settings that choose code, config or the repo: dropped, so the
# two pins above are ALL the config the environment carries (GIT_CONFIG_PARAMETERS
# is applied after GIT_CONFIG_COUNT and would override them; a CI-style
# GIT_CONFIG_VALUE_n may hold a token).
_DROPPED_PREFIXES = ("GIT_CONFIG_", "GIT_SSH")
_DROPPED = {
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE", "GIT_EXEC_PATH",
    "GIT_ASKPASS", "GIT_PAGER", "GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_EXTERNAL_DIFF",
    "GIT_PROXY_COMMAND", "GIT_TEMPLATE_DIR",
}


def hardened_git_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """A copy of ``env`` (default: the process environment) without inherited git
    config or execution variables, carrying only the hardening pins."""
    out = {
        k: v for k, v in (os.environ if env is None else env).items()
        if k not in _DROPPED and not k.startswith(_DROPPED_PREFIXES)
    }
    for i, (key, value) in enumerate(_PINNED_CONFIG):
        out[f"GIT_CONFIG_KEY_{i}"] = key
        out[f"GIT_CONFIG_VALUE_{i}"] = value
    out["GIT_CONFIG_COUNT"] = str(len(_PINNED_CONFIG))
    out["GIT_CONFIG_NOSYSTEM"] = "1"
    out["GIT_TERMINAL_PROMPT"] = "0"
    return out
