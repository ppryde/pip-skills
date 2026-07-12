"""Resolve a status-line payload's worktree-level cwd — the census index key.

Pure functions, no I/O beyond `os.path.realpath` (which touches the filesystem
only to resolve symlinks and is safe on non-existent paths).
"""
from __future__ import annotations

import os
from typing import Any


def normalise(path: str) -> str:
    """Collapse symlinks and trailing-slash / `.` variants to one canonical key."""
    return os.path.realpath(path)


def worktree_cwd(payload: dict[str, Any]) -> str | None:
    """The worktree-level directory to index this session by.

    First present wins:
      1. ``worktree.path``          — ``--worktree`` sessions
      2. ``workspace.current_dir``  — ``git worktree add`` sessions and the plain case
      3. ``cwd``                    — last resort

    Returns a normalised absolute path, or None if the payload carries no usable
    directory.
    """
    worktree = payload.get("worktree")
    if isinstance(worktree, dict):
        path = worktree.get("path")
        if isinstance(path, str) and path:
            return normalise(path)

    workspace = payload.get("workspace")
    if isinstance(workspace, dict):
        current = workspace.get("current_dir")
        if isinstance(current, str) and current:
            return normalise(current)

    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        return normalise(cwd)

    return None
