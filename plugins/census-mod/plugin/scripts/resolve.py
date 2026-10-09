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


def _candidates(payload: dict[str, Any]) -> list[Any]:
    worktree = payload.get("worktree")
    workspace = payload.get("workspace")
    return [
        worktree.get("path") if isinstance(worktree, dict) else None,
        workspace.get("current_dir") if isinstance(workspace, dict) else None,
        payload.get("cwd"),
    ]


def worktree_cwd(payload: dict[str, Any]) -> str | None:
    """The worktree-level directory to index this session by.

    First usable wins:
      1. ``worktree.path``          — ``--worktree`` sessions
      2. ``workspace.current_dir``  — ``git worktree add`` sessions and the plain case
      3. ``cwd``                    — last resort

    A candidate that is not a non-empty string, or that cannot be resolved (an
    embedded NUL, an unencodable name), is skipped for the next, not fatal.
    Returns a normalised absolute path, or None if the payload carries no usable
    directory.
    """
    for candidate in _candidates(payload):
        if isinstance(candidate, str) and candidate:
            try:
                return normalise(candidate)
            except (ValueError, OSError):
                continue
    return None
