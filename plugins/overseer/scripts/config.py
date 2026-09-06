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
# Extra Claude config dirs to watch, os.pathsep-separated — an override for
# the machine config file's `claude_dirs` list (both are honoured).
CLAUDE_DIRS_ENV = "CLAUDE_CONFIG_DIRS"
REPO_CONFIG_DIRNAME = ".overseer"
# The ONE machine-level config file, under the primary config dir. Shared with
# the chronicle plugin (which reads the same file with its own small loader):
#   { "claude_dirs": ["~/.claude-personal", ...] }
MACHINE_CONFIG_RELPATH = ("overseer", "config.json")


def _config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    return Path(override) if override else Path.home() / ".claude"


def machine_config_path() -> Path:
    return _config_dir().joinpath(*MACHINE_CONFIG_RELPATH)


def load_machine_config() -> dict:
    """The machine-level config (per config dir, never committed). Missing or
    empty is `{}`; malformed JSON raises so a typo is never silently ignored."""
    path = machine_config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text() or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: malformed config JSON: {exc}") from exc
    return data if isinstance(data, dict) else {}


def save_machine_config(data: dict) -> Path:
    path = machine_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def claude_dirs() -> list[Path]:
    """Every Claude config dir to watch: the primary (`CLAUDE_CONFIG_DIR` or
    `~/.claude`) first, then the `CLAUDE_CONFIG_DIRS` env list, then the
    machine config's `claude_dirs` — deduplicated, order kept, missing dirs
    dropped. A second account (`~/.claude-personal`) writes its own
    transcripts, census store and boards under its own dir; listing it here
    is what lets the dashboard and chronicle see them as one machine."""
    primary = _config_dir()
    candidates: list[Path] = [primary]
    env = os.environ.get(CLAUDE_DIRS_ENV, "")
    candidates.extend(Path(p).expanduser() for p in env.split(os.pathsep) if p.strip())
    try:
        cfg = load_machine_config()
    except ValueError:
        # A hand-edited, broken machine config must not take every board on
        # the machine down with it (this sits under the dashboard's repo
        # list): watch the primary and the env list, and let `overseer
        # claude-dirs` — which calls load_machine_config directly — be the
        # place that reports the malformed file.
        cfg = {}
    listed = cfg.get("claude_dirs") or []
    if isinstance(listed, list):
        candidates.extend(Path(str(p)).expanduser() for p in listed if p)
    out: list[Path] = []
    seen: set[Path] = set()
    for c in candidates:
        try:
            key = c.resolve()
        except OSError:
            continue
        if key in seen or not key.is_dir():
            continue
        seen.add(key)
        out.append(c)
    return out


def _update_claude_dirs(mutate) -> list[str]:
    """Load the machine config, hand its `claude_dirs` list to `mutate`,
    save what comes back, return it."""
    cfg = load_machine_config()
    listed = mutate([str(p) for p in (cfg.get("claude_dirs") or []) if p])
    cfg["claude_dirs"] = listed
    save_machine_config(cfg)
    return listed


def add_claude_dir(path: Path) -> list[str]:
    """Record an extra config dir in the machine config; returns the list.
    Stored absolute (resolved): a relative path would mean something
    different from every working directory the file is later read from."""
    entry = str(path.expanduser().resolve())
    return _update_claude_dirs(lambda listed: listed if entry in listed else [*listed, entry])


def remove_claude_dir(path: Path) -> list[str]:
    target = path.expanduser().resolve()
    return _update_claude_dirs(
        lambda listed: [p for p in listed if Path(p).expanduser().resolve() != target]
    )


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
        # Build the read-only URI via ``Path.as_uri()`` so a central path
        # containing a space / ``?`` / ``#`` is percent-encoded rather than
        # mis-parsed by sqlite's URI reader (an unencoded ``?`` or ``#`` would
        # be read as the query/fragment delimiter, truncating the path and
        # failing the open → a false "unknown" that wrongly adopts the folder).
        uri = f"{db_path.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = 'repo_root'"
            ).fetchone()
        finally:
            conn.close()
    except (sqlite3.Error, ValueError):
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
    # Search every watched config dir, primary first, for an EXISTING folder
    # for this repo: a board raised from a second account's session lives
    # under that account's dir, and must be found there rather than an empty
    # twin being created under the primary. Only creation defaults to the
    # primary (the fall-through below).
    for config_dir in claude_dirs():
        base = config_dir / "overseer"
        hashed = base / f"{label}-{_short_hash(canonical)}"
        if hashed.exists():
            return hashed
        plain = base / label
        if plain.exists() and _owns_plain(plain, canonical):
            return plain  # adopt legacy/own folder in place — NO move
    return _config_dir() / "overseer" / f"{label}-{_short_hash(canonical)}"  # fresh repo


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
