"""Filesystem root for vigil state, under the user's Claude config dir.

State lives in ``$CLAUDE_CONFIG_DIR/vigil/<repo-key>/`` (``~/.claude`` when the
variable is unset), never inside the repository, so a cloned repo cannot ship
or pre-seed it. ``<repo-key>`` is the repository name plus a hash of its
resolved root path. The root itself is resolved once, here, for the CLI and
every hook (see ``resolve_root``). Directories are 0700, files 0600, and nothing
is read or written through a symlink.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from pathlib import Path

VIGIL_DIRNAME = "vigil"
PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")


def config_dir() -> Path:
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(override) if override else Path.home() / ".claude"


def resolve_root(path: Path, honour_env: bool = True) -> Path:
    """The one state root for ``path``: ``$CLAUDE_PROJECT_DIR`` when set (and
    ``honour_env``), else the nearest enclosing git work tree (a ``.git`` dir or
    file, so worktrees are their own root), else ``path`` itself. CLI (default
    ``--root``) and hooks (payload cwd) therefore agree even when the shell sits
    in a subdirectory. An explicit ``--root`` calls this with ``honour_env=False``
    so it stays authoritative over the session's project dir."""
    project = os.environ.get("CLAUDE_PROJECT_DIR") if honour_env else None
    if project:
        return Path(os.path.realpath(project))
    start = Path(os.path.realpath(path))
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def repo_key(repo_root: Path) -> str:
    resolved = resolve_root(repo_root, honour_env=False)  # callers already resolved it
    digest = hashlib.sha256(str(resolved).encode("utf-8", "surrogateescape")).hexdigest()[:16]
    name = _UNSAFE.sub("-", resolved.name)[:40] or "root"
    return f"{name}-{digest}"


def vigil_root(repo_root: Path) -> Path:
    return config_dir() / VIGIL_DIRNAME / repo_key(repo_root)


def _private_dir(path: Path) -> None:
    """Create ``path`` (0700) if needed; refuse a symlink or a dir another user owns."""
    if path.is_symlink():
        raise PermissionError(f"vigil state dir is a symlink: {path}")
    path.mkdir(mode=PRIVATE_DIR_MODE, parents=True, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid():
        raise PermissionError(f"vigil state dir is not owned by you: {path}")
    if info.st_mode & 0o077:
        os.chmod(path, PRIVATE_DIR_MODE)


def ensure_root(repo_root: Path) -> Path:
    """Create the 0700 state dir for ``repo_root`` (idempotent) and return it."""
    root = vigil_root(repo_root)
    _private_dir(root.parent)
    _private_dir(root)
    return root


def open_private(path: Path, flags: int) -> int:
    """Open ``path`` (0600 on create) without following a symlink; returns the fd."""
    return os.open(path, flags | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), PRIVATE_FILE_MODE)


def write_private(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` as a 0600 file, never through a symlink."""
    fd = open_private(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    try:
        os.fchmod(fd, PRIVATE_FILE_MODE)  # tighten a file that pre-existed wider
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(text)
    finally:
        if fd >= 0:
            os.close(fd)


def touch_private(path: Path) -> None:
    """Create (0600) or refresh a marker, never through a symlink."""
    fd = open_private(path, os.O_WRONLY | os.O_CREAT)
    try:
        os.fchmod(fd, PRIVATE_FILE_MODE)
        os.utime(fd, None)
    finally:
        os.close(fd)


def marker_exists(path: Path) -> bool:
    """True only for a regular file; a symlink (even to a real file) is not a marker."""
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def read_private(path: Path) -> str | None:
    """The file's text, or None when missing, a symlink, not ours, or unreadable."""
    try:
        fd = open_private(path, os.O_RDONLY)
    except OSError:
        return None
    try:
        if os.fstat(fd).st_uid != os.getuid():
            return None
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            return handle.read()
    except (OSError, UnicodeError):
        return None
    finally:
        if fd >= 0:
            os.close(fd)
