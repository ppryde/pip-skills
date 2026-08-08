"""Resolve overseer's per-repo central state folder and backup dir.

Precedence for the central folder:
  OVERSEER_CENTRAL env  >  config.local.json:central_dir  >  default
    ($CLAUDE_CONFIG_DIR/overseer/<repo-label>/)
The live board.db lives inside this folder; OVERSEER_DB (in db.py) still
overrides the DB *file* path for back-compat.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.store import derive_repo_label, derive_repo_root, slugify

CENTRAL_ENV = "OVERSEER_CENTRAL"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
REPO_CONFIG_DIRNAME = ".overseer"


def _config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    return Path(override) if override else Path.home() / ".claude"


def repo_config_dir(repo_root: Path) -> Path:
    root = derive_repo_root(repo_root) or repo_root
    return root / REPO_CONFIG_DIRNAME


def load_config(repo_root: Path) -> dict:
    base = repo_config_dir(repo_root)
    merged: dict = {}
    for name in ("config.json", "config.local.json"):  # local wins
        path = base / name
        if path.exists():
            try:
                merged.update(json.loads(path.read_text() or "{}"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}: malformed config JSON: {exc}") from exc
    return merged


def central_root(repo_root: Path) -> Path:
    env = os.environ.get(CENTRAL_ENV)
    if env:
        return Path(env)
    cfg = load_config(repo_root)
    if cfg.get("central_dir"):
        return Path(cfg["central_dir"])
    label = derive_repo_label(repo_root) or slugify(repo_root.resolve().name) or "repo"
    return _config_dir() / "overseer" / label


def backup_dir(repo_root: Path) -> Path:
    """The COMMITTED backup dir — resolved against the actual working tree
    passed in (``repo_root``), never ``derive_repo_root``. Unlike
    ``repo_config_dir``/``central_root`` (config + live state, correctly
    shared across worktrees via the main repo root), the committed backup
    must live in and ride the branch of whichever working tree is doing the
    `git push` — a linked worktree pushes its OWN branch, and a backup
    resolved onto the main root would either dirty the main tree or commit
    onto the wrong branch entirely."""
    cfg = load_config(repo_root)
    if cfg.get("backup_dir"):
        p = Path(cfg["backup_dir"])
        return p if p.is_absolute() else repo_root / p
    return repo_root / REPO_CONFIG_DIRNAME / "backups"
