"""Shared location + IO for the remote board API token file.

The dashboard launcher (dashboard/serve.py) persists an auto-generated exec
token to ``<repo>/.overseer/remote-token``; a dev container that mounts the
repo reads the same file via the CLI ``--remote`` path — so the token is never
copied by hand. Stdlib only (no httpx): reading a token must not drag in the
HTTP client. The token still gates /api/exec; this module only distributes it.

Two readers, on purpose. ``read_remote_token`` (container side) is lenient: the
host's uid and file modes differ inside a container. ``read_server_token`` (the
host server minting/reusing its own secret) trusts nothing a rw-mounted
container could have planted: a symlink, a file owned by someone else or one
readable by group/other is ignored, and the caller mints a fresh token.
"""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

_TOKEN_FILENAME = "remote-token"
DASHBOARD_TOKEN_FILENAME = "dashboard-token"


def remote_token_path(root: str | os.PathLike[str]) -> Path:
    """Path to the token file for a repo root: ``<root>/.overseer/remote-token``."""
    return Path(root) / ".overseer" / _TOKEN_FILENAME


def read_remote_token(root: str | os.PathLike[str]) -> str | None:
    """The persisted token for ``root``, or None if missing/empty/unreadable.

    Never raises — a missing or unreadable file simply means "no token here".
    """
    try:
        token = remote_token_path(root).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return token or None


def read_server_token(root: str | os.PathLike[str], name: str = _TOKEN_FILENAME) -> str | None:
    """The persisted token for ``root`` if it is safe for the SERVER to trust.

    None when ``.overseer`` or the token file is a symlink, the file is not
    owned by this uid, or its mode has any group/other bit. A container can
    write to a rw-mounted ``.overseer``, so a token it planted is not a secret
    the host created; the caller re-mints instead of using it.
    """
    path = Path(root) / ".overseer" / name
    try:
        if stat.S_ISLNK(os.lstat(path.parent).st_mode):
            return None
        # One open, no symlink follow; check and read the SAME fd, so the file
        # cannot be swapped between the check and the read.
        fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        with os.fdopen(fd, "rb") as fh:
            st = os.fstat(fh.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
                return None
            return fh.read().decode("utf-8").strip() or None
    except (OSError, UnicodeDecodeError):
        return None


_IGNORED = ("remote-token", "dashboard-token", ".*.tmp")


def _ensure_gitignore(directory: Path) -> None:
    """Make sure ``.overseer/.gitignore`` lists the secret files, so a
    ``git add -A`` in the user's repo cannot commit a token. Appends only the
    missing lines, never rewrites, never follows a symlink; best effort."""
    path = directory / ".gitignore"
    try:
        fd = os.open(str(path), os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, "r+", encoding="utf-8") as fh:
            fh.seek(0)
            text = fh.read()
            missing = [line for line in _IGNORED if line not in text.splitlines()]
            if missing:
                fh.write(("" if not text or text.endswith("\n") else "\n") + "\n".join(missing) + "\n")
    except (OSError, UnicodeDecodeError):
        return


def write_remote_token(
    root: str | os.PathLike[str], token: str, name: str = _TOKEN_FILENAME
) -> Path:
    """Persist ``token`` at ``<root>/.overseer/remote-token`` with mode 0600.

    ``name`` selects another secret file in the same directory (the dashboard
    token has its own: the two secrets never share a file).

    Refuses (OSError) when ``.overseer`` is a symlink. The token itself goes to
    a temp file in the same directory (random name via ``mkstemp``, 0600 from
    the start) and is moved into place with ``os.replace``, which swaps the
    directory entry and never follows a symlink at the destination, so a
    planted ``remote-token`` link cannot redirect the write.
    """
    directory = Path(root) / ".overseer"
    path = directory / name
    try:
        is_link = stat.S_ISLNK(os.lstat(directory).st_mode)
    except FileNotFoundError:
        directory.mkdir(parents=True)
        is_link = stat.S_ISLNK(os.lstat(directory).st_mode)
    if is_link:
        raise OSError(f"{directory} is a symlink; refusing to write the exec token through it")
    _ensure_gitignore(directory)
    # mkstemp: random name, O_EXCL (never an existing file or link), 0600; a
    # predictable name could be pre-planted by a container to disable exec.
    fd, tmp_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=str(directory))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            os.fchmod(fh.fileno(), 0o600)
            fh.write(token)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


def dashboard_token_path(root: str | os.PathLike[str]) -> Path:
    """Path to the dashboard-gate token file: ``<root>/.overseer/dashboard-token``."""
    return Path(root) / ".overseer" / DASHBOARD_TOKEN_FILENAME
