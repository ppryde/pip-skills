"""Every filesystem location context-vigil uses, in one place.

All state lives under one data root (``$CONTEXT_VIGIL_HOME`` or
``$CLAUDE_CONFIG_DIR/context-vigil``). Per-worktree state is keyed by the git
top level (the resolved cwd outside git), so a hook in the repo root and the CLI
in a sub-directory share one scope; never by the session id: ``/clear`` mints a
new session id and the fresh session must still find its handover.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

HOME_ENV = "CONTEXT_VIGIL_HOME"
SESSION_ENV = "CONTEXT_VIGIL_SESSION"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    return Path(override) if override else Path.home() / ".claude"


def data_root() -> Path:
    override = os.environ.get(HOME_ENV)
    return Path(override) if override else config_dir() / "context-vigil"


def skill_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def launcher_path() -> Path:
    return skill_dir() / "scripts" / "context-vigil"


ENTRYPOINT_ENV = "CLAUDE_CODE_ENTRYPOINT"
_HEADLESS_ENTRYPOINTS = ("sdk-cli", "sdk-ts", "sdk-py")
_INTERACTIVE_ENTRYPOINTS = ("cli", "claude-vscode", "claude-desktop")
_GIT_TIMEOUT_SECONDS = 2
_toplevels: dict = {}  # per-process only: realpath(cwd) -> worktree key


def headless_from_env() -> Optional[bool]:
    """Headless-ness from the hook/CLI environment (Claude Code sets the entrypoint
    on its own process and its children inherit it); None when absent or unknown."""
    entrypoint = os.environ.get(ENTRYPOINT_ENV)
    if entrypoint in _HEADLESS_ENTRYPOINTS:
        return True
    if entrypoint in _INTERACTIVE_ENTRYPOINTS:
        return False
    return None


def worktree_key(cwd: Path) -> str:
    """The git top level of ``cwd`` (realpath), else realpath(cwd) outside git."""
    real = os.path.realpath(str(cwd))
    if real not in _toplevels:
        top = real
        try:
            result = subprocess.run(
                ["git", "-C", real, "rev-parse", "--show-toplevel"],
                timeout=_GIT_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL,
                capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                top = os.path.realpath(result.stdout.strip())
        except Exception:
            pass
        _toplevels[real] = top
    return _toplevels[real]


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
