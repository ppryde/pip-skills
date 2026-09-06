"""The running dashboard's runtime record, and the restart-on-stale check.

WF-053 (spec: docs/superpowers/specs/2026-08-09-dashboard-server-version-
restart-design.md). ``serve.py`` is launched by hand and left running for
days; when the installed overseer moves on, the person keeps looking at a
stale server with no signal. So:

- ``serve.py`` STAMPS itself on launch: one JSON record per config dir at
  ``<CLAUDE_CONFIG_DIR>/overseer/.dashboard.json`` — pid, host, port, root,
  version, the interpreter and launcher path to relaunch with — removed on
  clean shutdown (a leftover record is harmless: liveness is the pid).
- a SessionStart hook (``overseer dashboard-refresh-hook``) reads the record
  and, only when a LIVE server is running an OLDER version than the one
  installed, restarts it in place with the same host/port/root. Never
  auto-starts one that was not running; never downgrades; fails open.
- a short-lived lock file debounces several sessions starting at once, so
  exactly one of them performs the restart.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts import config

RECORD_RELPATH = ("overseer", ".dashboard.json")
LOCK_RELPATH = ("overseer", ".dashboard.restart.lock")
LOG_RELPATH = ("overseer", "dashboard.log")
# A restart lock older than this is a leftover from a crashed attempt, not a
# restart in progress.
LOCK_TTL_SECONDS = 30.0
# How long a kill is given to take before the relaunch goes ahead anyway.
TERMINATE_WAIT_SECONDS = 5.0


def plugin_version() -> str:
    """The installed overseer's version, from its plugin manifest; "" when
    that cannot be read (never a reason to fail a caller)."""
    plugin_json = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    try:
        return str(json.loads(plugin_json.read_text())["version"])
    except Exception:  # noqa: BLE001 — provenance only
        return ""


def version_tuple(version: str) -> tuple[int, ...]:
    """``"0.21.3"`` → ``(0, 21, 3)``; anything unparseable compares lowest."""
    parts: list[int] = []
    for piece in version.strip().split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def record_path() -> Path:
    return config._config_dir().joinpath(*RECORD_RELPATH)


def lock_path() -> Path:
    return config._config_dir().joinpath(*LOCK_RELPATH)


def log_path() -> Path:
    return config._config_dir().joinpath(*LOG_RELPATH)


def write_record(data: dict[str, Any]) -> Path:
    """Atomically write the record (temp file + rename)."""
    path = record_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)
    return path


def read_record() -> dict[str, Any] | None:
    try:
        data = json.loads(record_path().read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def remove_record(pid: int | None = None) -> bool:
    """Remove the record — only if it is OURS (``pid`` matches) when a pid is
    given, so a server shutting down never deletes its replacement's stamp."""
    record = read_record()
    if record is None:
        return False
    if pid is not None and record.get("pid") != pid:
        return False
    try:
        record_path().unlink()
    except OSError:
        return False
    return True


def pid_alive(pid: int) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


def terminate_pid(pid: int, wait: float = TERMINATE_WAIT_SECONDS) -> bool:
    """SIGTERM, wait for exit, then SIGKILL. True when the process is gone."""
    if not pid_alive(pid):
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return not pid_alive(pid)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    time.sleep(0.2)
    return not pid_alive(pid)


def running_version(host: str, port: int, timeout: float = 0.75) -> str | None:
    """Ask the live server what it is running (``GET /api/version``); None
    when it does not answer. A ``0.0.0.0`` bind is reached via loopback."""
    reach = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    try:
        with urllib.request.urlopen(f"http://{reach}:{port}/api/version", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — any failure is "no answer"
        return None
    version = data.get("version") if isinstance(data, dict) else None
    return str(version) if version else None


def launch(record: dict[str, Any]) -> int:
    """Relaunch ``serve.py`` as recorded — same interpreter, host, port and
    root, never a browser tab — detached, its output appended to the
    dashboard log. Returns the new pid."""
    argv = [
        str(record.get("python") or sys.executable),
        str(record["serve"]),
        "--root", str(record["root"]),
        "--host", str(record["host"]),
        "--port", str(record["port"]),
        "--no-browser",
        "--replace",
    ]
    log = log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as out:
        proc = subprocess.Popen(
            argv, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True, cwd=str(record["root"]),
        )
    return proc.pid


def _take_lock(now: float) -> bool:
    """Claim the restart for this process: creates the lock unless a fresh
    one exists. A stale lock (older than the TTL) is taken over."""
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            age = now - path.stat().st_mtime
        except OSError:
            return False
        if age < LOCK_TTL_SECONDS:
            return False
        try:
            path.unlink()
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except OSError:
            return False
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    return True


def _release_lock() -> None:
    try:
        lock_path().unlink()
    except OSError:
        pass


def restart_if_stale(
    *,
    now: float | None = None,
    installed: str | None = None,
    alive: Callable[[int], bool] = pid_alive,
    ask_version: Callable[[str, int], str | None] = running_version,
    terminate: Callable[[int], bool] = terminate_pid,
    relaunch: Callable[[dict[str, Any]], int] = launch,
) -> str | None:
    """The SessionStart check. Returns a one-line message when a restart was
    performed, else None. Every "do nothing" path is silent; every failure
    is swallowed by the caller (the hook verb) — this must never delay or
    break a session start.

    The steps, per the spec: no record → nothing; pid dead → nothing (the
    stale record is cleaned); running version (asked of the live server,
    falling back to the record's stamp) at or above the installed one →
    nothing; else take the lock, kill, relaunch as recorded.
    """
    record = read_record()
    if record is None:
        return None
    pid = record.get("pid")
    if not isinstance(pid, int) or not alive(pid):
        remove_record(pid if isinstance(pid, int) else None)
        return None
    host, port = str(record.get("host") or "127.0.0.1"), int(record.get("port") or 0)
    running = ask_version(host, port) or str(record.get("version") or "")
    installed = plugin_version() if installed is None else installed
    if not installed or version_tuple(installed) <= version_tuple(running):
        return None
    if not all(record.get(k) for k in ("serve", "root", "host", "port")):
        return None
    if now is None:
        now = time.time()
    if not _take_lock(now):
        return None
    try:
        if not terminate(pid):
            return None
        new_pid = relaunch(record)
    finally:
        _release_lock()
    return f"overseer dashboard restarted {running or '?'} → {installed} (pid {pid} → {new_pid})"


def stamp(*, host: str, port: int, root: Path, serve: Path) -> dict[str, Any]:
    """The record ``serve.py`` writes for itself at launch."""
    return {
        "pid": os.getpid(),
        "host": host,
        "port": port,
        "root": str(root),
        "version": plugin_version(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "python": sys.executable,
        "serve": str(serve),
    }
