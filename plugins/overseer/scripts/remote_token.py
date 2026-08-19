"""Shared location + IO for the remote board API token file.

The host launcher (serve_board_api) persists an auto-generated token to
``<repo>/.overseer/remote-token``; a dev container that mounts the repo reads
the same file via the CLI ``--remote`` path — so the token is never copied by
hand. Stdlib only (no httpx): reading a token must not drag in the HTTP client.
The token still gates /api/exec; this module only distributes it.
"""
from __future__ import annotations

import os
from pathlib import Path

_TOKEN_FILENAME = "remote-token"


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


def write_remote_token(root: str | os.PathLike[str], token: str) -> Path:
    """Persist ``token`` at ``<root>/.overseer/remote-token`` with mode 0600.

    Creates ``.overseer/`` if needed. Opens with 0600 and re-chmods afterward
    so a pre-existing file with looser permissions is tightened.
    """
    path = remote_token_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token)
    os.chmod(path, 0o600)
    return path
