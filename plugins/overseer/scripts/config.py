"""Resolve overseer's per-repo central state folder and backup dir.

Precedence for the central folder:
  OVERSEER_CENTRAL env  >  config.local.json:central_dir  >  default
    ($CLAUDE_CONFIG_DIR/overseer/<repo-label>-<hash>/)
The live board.db lives inside this folder; OVERSEER_DB (in db.py) still
overrides the DB *file* path for back-compat.

The default folder name is disambiguated by an 8-char hash of the canonical
repo root so two repos with the SAME basename (e.g. ~/work/api and
~/personal/api) never collide on one folder — which would otherwise share a
single board.db AND let `overseer backup` commit one repo's cards into the
OTHER repo's git history. See ``central_root`` for the safe, no-move
resolution that preserves existing single-repo installs.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

from scripts.store import derive_repo_label, derive_repo_root, slugify

CENTRAL_ENV = "OVERSEER_CENTRAL"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
REPO_CONFIG_DIRNAME = ".overseer"


def _config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    return Path(override) if override else Path.home() / ".claude"


def _short_hash(canonical_root: Path) -> str:
    """Stable 8-char hex fingerprint of a canonical repo root path. Same root
    (from any worktree that resolves to it) always yields the same hash, so
    every worktree of a repo lands on the same central folder."""
    return hashlib.sha1(str(canonical_root.resolve()).encode()).hexdigest()[:8]


def _plain_owner(plain: Path) -> str:
    """Read the legacy plain folder's ``board.db`` ``meta['repo_root']`` with
    a SELF-CONTAINED read-only sqlite query (never imports ``scripts.db`` — that
    would create an import cycle). Returns the recorded owner root string, or
    ``"unknown"`` on ANY error (missing file, no table, locked, corrupt) — an
    unclaimed board that we treat as adoptable for back-compat."""
    db_path = plain / "board.db"
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'repo_root'"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return "unknown"
    if row is None or row[0] is None:
        return "unknown"
    return row[0]


def _owns_plain(plain: Path, canonical: Path) -> bool:
    """Whether the legacy plain ``overseer/<label>/`` folder belongs to THIS
    repo, and may therefore be adopted in place (no move, no data loss).

    True when the folder's ``board.db`` records this canonical root as its
    owner, OR when ownership is indeterminate (no board.db / no repo_root
    meta / unreadable) — a truly-legacy, unclaimed folder is treated as ours
    to preserve back-compat for the common single-repo install. False only
    when the board.db positively names a DIFFERENT repo root."""
    owner = _plain_owner(plain)
    return owner == "unknown" or owner == str(canonical.resolve())


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
    # Default resolution, disambiguated by canonical root (finding I2). The
    # folder name is `<label>-<hash>`, but an existing single-repo install
    # keeps its legacy plain `<label>` folder — adopted in place, never moved.
    label = derive_repo_label(repo_root) or slugify(repo_root.resolve().name) or "repo"
    canonical = derive_repo_root(repo_root) or repo_root
    base = _config_dir() / "overseer"
    hashed = base / f"{label}-{_short_hash(canonical)}"
    if hashed.exists():
        return hashed
    plain = base / label
    if plain.exists() and _owns_plain(plain, canonical):
        return plain  # adopt legacy/own folder in place — NO move
    return hashed  # fresh repo, OR plain belongs to a DIFFERENT repo


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
