"""Where concordance keeps its store: under the account's config dir, one folder per repo.

Rooted at CLAUDE_CONFIG_DIR (never a hardcoded ~/.claude) so each Claude account keeps its
own index; keyed by the git common dir so every worktree of a repo shares one store.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path


def config_dir() -> Path:
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env).expanduser() if env else Path.home() / ".claude"


def repo_key(common_dir: Path) -> str:
    common = common_dir.resolve()
    name = common.parent.name if common.name == ".git" else common.name.removesuffix(".git")
    digest = hashlib.sha1(os.fsencode(str(common))).hexdigest()[:8]
    return f"{name}-{digest}"


def store_path(common_dir: Path) -> Path:
    override = os.environ.get("CONCORDANCE_DB")
    if override:
        return Path(override)
    return config_dir() / "concordance" / repo_key(common_dir) / "index.db"
