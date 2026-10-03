"""Every filesystem location context-vigil uses, in one place.

All state lives under one data root (``$CONTEXT_VIGIL_HOME`` or
``$CLAUDE_CONFIG_DIR/context-vigil``). Per-worktree state is keyed by the repository
root (a filesystem walk-up; the resolved cwd outside a repo), so a hook in the repo root and the CLI
in a sub-directory share one scope; never by the session id: ``/clear`` mints a
new session id and the fresh session must still find its handover.
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Iterable, Optional

HOME_ENV = "CONTEXT_VIGIL_HOME"
SESSION_ENV = "CONTEXT_VIGIL_SESSION"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    return Path(override) if override else Path.home() / ".claude"


class DataRootError(ValueError):
    """``CONTEXT_VIGIL_HOME`` is unusable (relative); nothing was written."""


class UnsafeDataRoot(PermissionError):
    """The data root is not ours alone (another owner, or group/world-writable and
    impossible to tighten): refuse to read or write anything under it."""


def data_root() -> Path:
    """``$CONTEXT_VIGIL_HOME`` (must be absolute), else ``<config dir>/context-vigil``.

    A relative override is refused rather than resolved: it would land under whatever
    directory a hook or the CLI happens to run from (a repository, usually)."""
    override = os.environ.get(HOME_ENV)
    if override:
        if not os.path.isabs(override):
            raise DataRootError(f"{HOME_ENV} must be an absolute path; refusing to use a "
                                "relative one (it would land inside whatever directory "
                                "the command runs from)")
        return Path(override)
    return config_dir() / "context-vigil"


PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
TMP_PREFIX = ".cv-tmp."          # every atomic-write temp file starts with this
STALE_TMP_SECONDS = 60           # a temp file older than this is a crash's leftover
NOFOLLOW = os.O_NOFOLLOW     # POSIX; every platform context-vigil supports
_IGNORE_ALL = "*\n"


def make_private_dirs(path: Path) -> None:
    """Create ``path`` and any missing parents with ``os.mkdir(..., 0o700)``: no new
    directory is ever wider than 0700, whatever the umask."""
    missing = []
    current = path
    while not os.path.lexists(str(current)):
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    for directory in reversed(missing):
        try:
            os.mkdir(str(directory), PRIVATE_DIR_MODE)
        except FileExistsError:
            pass


def check_root(root: Path) -> None:
    """Raise UnsafeDataRoot unless ``root`` (when it exists) is owned by this user and
    not group/world-writable. A root of ours left wider by an older version is
    tightened first; one that cannot be tightened, or that someone else owns, is
    refused: its owner could plant a handover (prompt injection) or symlinks."""
    try:
        st = os.stat(str(root))
    except FileNotFoundError:
        return
    if st.st_uid != os.getuid():
        raise UnsafeDataRoot(f"the data root {root} is owned by another user; refusing to "
                             f"use it (set {HOME_ENV} to a directory of your own)")
    if st.st_mode & 0o022:
        try:
            os.chmod(str(root), PRIVATE_DIR_MODE)
        except OSError:
            pass
        try:
            wide = os.stat(str(root)).st_mode & 0o022
        except OSError:
            wide = 1
        if wide:
            raise UnsafeDataRoot(f"the data root {root} is writable by other users and "
                                 "could not be made private; refusing to use it")
    elif st.st_mode & 0o077:
        try:
            os.chmod(str(root), PRIVATE_DIR_MODE)   # readable by others: tighten quietly
        except OSError:
            pass


def _ignore_everything(root: Path) -> None:
    """``<root>/.gitignore`` = ``*``: the data root ignores itself wherever it lands
    (a dotfiles-managed config dir is a git repository), so ``git add -A`` never
    picks up a handover. Created once, 0600, never through a symlink."""
    marker = root / ".gitignore"
    if os.path.lexists(str(marker)):
        return
    try:
        fd = os.open(str(marker), os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW,
                     PRIVATE_FILE_MODE)
    except OSError:
        return
    with os.fdopen(fd, "w") as handle:
        handle.write(_IGNORE_ALL)


def ensure_dir(path: Path) -> Path:
    """Create ``path`` (and missing parents) 0700; under the data root, first check
    the root is ours alone (``check_root``) and make it self-ignoring."""
    root = data_root()
    under_root = path == root or root in path.parents
    if under_root:
        check_root(root)
    make_private_dirs(path)
    if under_root:
        check_root(root)          # it may have just been created: still ours, 0700
        _ignore_everything(root)
    return path


def guard_read(path: Path) -> None:
    """Before reading state under the data root: refuse a root that is not ours."""
    root = data_root()
    if path == root or root in path.parents:
        check_root(root)


def read_private(path: Path) -> str:
    """Read a state file without following a symlink (O_NOFOLLOW), after checking the
    data root is ours. Raises OSError (ELOOP for a symlink) or UnicodeError."""
    guard_read(path)
    fd = os.open(str(path), os.O_RDONLY | NOFOLLOW)
    with os.fdopen(fd, "r", encoding="utf-8") as handle:
        return handle.read()


def open_private(path: Path, flags: int = os.O_WRONLY | os.O_CREAT | os.O_APPEND) -> int:
    """An fd for ``path``, created 0600 (lock files, markers and other sidecars).
    Never follows a symlink: a planted link fails with ELOOP instead of redirecting."""
    ensure_dir(path.parent)
    return os.open(str(path), flags | NOFOLLOW, PRIVATE_FILE_MODE)


def sweep_stale(directory: Path, patterns: Iterable[str],
                older_than: float = STALE_TMP_SECONDS) -> None:
    """Unlink files in ``directory`` matching any glob in ``patterns`` that this user
    owns and that are older than ``older_than`` seconds: the private leftovers of an
    atomic write killed (SIGKILL, power loss) between creating its temp file and the
    rename. Fresh ones may belong to a write in flight and are kept. Never raises."""
    import fnmatch
    import time
    try:
        names = os.listdir(str(directory))
    except OSError:
        return
    cutoff = time.time() - older_than
    uid = os.getuid()
    for name in names:
        if not any(fnmatch.fnmatchcase(name, p) for p in patterns):
            continue
        entry = directory / name
        try:
            st = os.lstat(str(entry))
            if st.st_uid == uid and st.st_mtime < cutoff and not os.path.isdir(str(entry)):
                os.unlink(str(entry))
        except OSError:
            pass


def write_private(path: Path, text: str) -> None:
    """Atomically replace ``path`` with ``text``, as a 0600 file from the first byte.

    The temp file comes from ``mkstemp`` (0600, O_EXCL, random name, ``.cv-tmp.``
    prefix) in the same directory, so a crash leaves at worst a private stray, never
    a readable copy, and the next write there sweeps strays older than a minute.
    ``os.replace`` gives the target the temp file's mode (an existing file left wider
    by an older version is tightened) and replaces a planted symlink, never its target."""
    import tempfile
    ensure_dir(path.parent)
    sweep_stale(path.parent, (f"{TMP_PREFIX}*.tmp", f".{path.name}.*.tmp"))
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f"{TMP_PREFIX}{path.name}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def skill_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def launcher_path() -> Path:
    return skill_dir() / "scripts" / "context-vigil"


ENTRYPOINT_ENV = "CLAUDE_CODE_ENTRYPOINT"
_HEADLESS_ENTRYPOINTS = ("sdk-cli", "sdk-ts", "sdk-py")
_INTERACTIVE_ENTRYPOINTS = ("cli", "claude-vscode", "claude-desktop")


def headless_from_entrypoint(entrypoint: Any) -> Optional[bool]:
    """The SDK entrypoints are headless, the interactive ones are not, others unknown."""
    if entrypoint in _HEADLESS_ENTRYPOINTS:
        return True
    if entrypoint in _INTERACTIVE_ENTRYPOINTS:
        return False
    return None


def headless_from_env() -> Optional[bool]:
    """Headless-ness from the hook/CLI environment (Claude Code sets the entrypoint
    on its own process and its children inherit it); None when absent or unknown."""
    return headless_from_entrypoint(os.environ.get(ENTRYPOINT_ENV))


def _gitdir_of(marker: Path) -> Optional[str]:
    """The ``gitdir:`` target of a ``.git`` file, resolved against its directory."""
    try:
        first = marker.read_text().splitlines()[0]
    except (OSError, IndexError, UnicodeError):
        return None
    if not first.startswith("gitdir:"):
        return None
    target = first[len("gitdir:"):].strip()
    return os.path.normpath(os.path.join(str(marker.parent), target))


def worktree_key(cwd: Path) -> str:
    """The repository root of ``cwd`` (realpath), else realpath(cwd) outside a repo.

    A pure filesystem walk-up, no subprocess (this runs on every hook): the first
    ancestor holding ``.git``. A ``.git`` directory marks the root. A ``.git`` file
    points at its git dir: under ``.git/worktrees/`` it is a linked worktree (its own
    root); under ``.git/modules/`` it is a submodule, so the walk continues up to the
    superproject, and hook and CLI scope alike whether run from the submodule or above.
    """
    real = os.path.realpath(str(cwd))
    submodule: Optional[str] = None
    current = Path(real)
    while True:
        marker = current / ".git"
        try:
            if marker.is_dir():
                return str(current)
            if marker.is_file():
                gitdir = _gitdir_of(marker)
                if gitdir is not None and "/.git/modules/" in gitdir + "/":
                    submodule = submodule or str(current)
                else:
                    return str(current)
        except OSError:
            pass
        if current.parent == current:
            return submodule or real
        current = current.parent


def enclosing_repo(path: Path) -> Optional[str]:
    """The git worktree (or repository) holding ``path``, by a filesystem walk-up from
    its nearest existing ancestor (no subprocess); None when it is in none."""
    current = Path(os.path.realpath(str(path)))
    while not current.exists() and current.parent != current:
        current = current.parent
    while True:
        if os.path.lexists(str(current / ".git")):
            return str(current)
        if current.parent == current:
            return None
        current = current.parent


def worktree_slug(cwd: Path) -> str:
    """Readable slug plus a hash of the full path: sanitising alone is lossy
    (``/r/foo-bar`` and ``/r/foo/bar`` would otherwise share state)."""
    key = worktree_key(cwd)
    digest = hashlib.sha1(key.encode("utf-8", "surrogateescape")).hexdigest()[:8]
    return f"{_UNSAFE.sub('-', key)}-{digest}"


def worktree_dir(cwd: Path) -> Path:
    return data_root() / "worktrees" / worktree_slug(cwd)


def session_name() -> Optional[str]:
    """Who this session is, for per-session scoping within one worktree.

    ``CONTEXT_VIGIL_SESSION`` (set by claude-tmux) names the session, with the
    pane id appended inside tmux: a new window or split inherits the tmux session
    environment, so the name alone would be shared by two Claude instances. The
    pane id survives ``/clear`` (same process, same pane). Without the variable,
    inside tmux, the pane id alone, with the socket name folded in to keep two
    servers' ``%3`` apart. Outside tmux there is no stable per-session key, so all sessions in a
    worktree share its scope — harmless, because outside tmux ``/clear`` is
    typed by hand in one place at a time.
    """
    explicit = os.environ.get(SESSION_ENV)
    tmux_env = os.environ.get("TMUX")
    pane = os.environ.get("TMUX_PANE")
    if explicit:
        return f"{explicit}-{pane.lstrip('%')}" if tmux_env and pane else explicit
    if tmux_env and pane:
        socket = os.path.basename(tmux_env.split(",", 1)[0]) or "tmux"
        return f"tmux-{socket}-{pane.lstrip('%')}"
    return None


def scope_dir(cwd: Path, session: Optional[str] = None) -> Path:
    name = session if session is not None else session_name()
    base = worktree_dir(cwd)
    if not name:
        return base
    return base / "sessions" / _UNSAFE.sub("-", name)


def headless_scope(cwd: Path, session_id: Optional[str]) -> Path:
    """A headless session's own scope: it never shares a parent's cycle, gate,
    cooldown, clear flag or handoff, whatever tmux/session env it inherited."""
    return scope_dir(cwd, session="headless-" + (session_id or "unknown"))


def headless_handoff_dir(cwd: Path) -> Path:
    """Where headless sessions of one worktree keep their handoff (and its archive):
    shared across session ids, because the next ``claude -p`` mints a new one and must
    still find it. Never read by an interactive session."""
    return worktree_dir(cwd) / "headless"


def census_path() -> Path:
    return data_root() / "census.json"


def sessions_dir() -> Path:
    return data_root() / "sessions"


def session_record_path(session_id: str) -> Path:
    return sessions_dir() / f"{_UNSAFE.sub('-', session_id)}.json"


def session_lock_path(key: str) -> Path:
    return sessions_dir() / f"{_UNSAFE.sub('-', key)}.lock"


def windows_path() -> Path:
    return data_root() / "windows.json"


def global_config_path() -> Path:
    return data_root() / "config.json"


def worktree_config_path(cwd: Path) -> Path:
    return worktree_dir(cwd) / "config.json"


def install_record_path() -> Path:
    return data_root() / "install.json"
