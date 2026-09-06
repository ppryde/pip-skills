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
  and, only when a LIVE server — one that ANSWERS ``GET /api/version``, not
  merely a live pid — is running an OLDER version than the one installed,
  restarts it in place with the same host/port/root. Never auto-starts one
  that was not running; never downgrades; fails open.
- the kill-and-relaunch itself runs in a DETACHED worker (this module, run as
  a script), so the hook returns at once and a session start is never delayed
  by a SIGTERM wait. A relaunch that fails leaves a note the next session's
  hook reports.
- a short-lived lock file debounces several sessions starting at once, so
  exactly one of them performs the restart.

Why the probe is mandatory before any kill: the record survives a reboot, and
the recorded pid can by then belong to an unrelated process. Trusting a live
pid alone would SIGKILL a stranger and then start a dashboard nobody asked
for — both forbidden. A pid that is alive but silent is treated as not
running: the record is dropped, nothing is signalled.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from scripts import config
except ImportError:  # pragma: no cover — run directly as the restart worker
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts import config

RECORD_RELPATH = ("overseer", ".dashboard.json")
LOCK_RELPATH = ("overseer", ".dashboard.restart.lock")
FAILURE_RELPATH = ("overseer", ".dashboard.restart-failed")
LOG_RELPATH = ("overseer", "dashboard.log")
# A restart lock older than this is a leftover from a crashed attempt, not a
# restart in progress.
LOCK_TTL_SECONDS = 30.0
# How long a kill is given to take before the relaunch goes ahead anyway.
TERMINATE_WAIT_SECONDS = 5.0
# The liveness probe runs on the session-start path, so it is deliberately
# impatient: a server that cannot answer in this long is not "running".
PROBE_TIMEOUT_SECONDS = 0.5


def plugin_version() -> str:
    """The installed overseer's version, from its plugin manifest; "" when
    that cannot be read (never a reason to fail a caller)."""
    plugin_json = Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    try:
        return str(json.loads(plugin_json.read_text())["version"])
    except Exception:  # noqa: BLE001 — provenance only
        return ""


_VERSION_RE = re.compile(r"v?(\d+(?:\.\d+)*)")


def version_tuple(version: str) -> tuple[int, ...]:
    """A comparable key for a version string; anything unparseable compares
    lowest (the empty tuple).

    Only the LEADING dotted-numeric run counts — ``"0.22.0-rc1"`` is release
    ``0.22.0``, not ``(0, 22, 1)`` as a digits-anywhere scan would have it.
    The key is padded to three components (so ``"1.0" == "1.0.0"``) and ends
    in a release rank: ``0`` for a bare release, ``-1`` when a prerelease or
    any other suffix trails, which is what makes ``0.22.0-rc1`` sort BELOW
    ``0.22.0`` and stops a release candidate from suppressing the upgrade to
    the release it precedes.
    """
    text = version.strip()
    match = _VERSION_RE.match(text)
    if not match:
        return ()
    parts = [int(piece) for piece in match.group(1).split(".")]
    while len(parts) < 3:
        parts.append(0)
    return (*parts, 0 if match.end() == len(text) else -1)


def record_path() -> Path:
    return config._config_dir().joinpath(*RECORD_RELPATH)


def lock_path() -> Path:
    return config._config_dir().joinpath(*LOCK_RELPATH)


def log_path() -> Path:
    return config._config_dir().joinpath(*LOG_RELPATH)


def failure_path() -> Path:
    return config._config_dir().joinpath(*FAILURE_RELPATH)


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


def probe_dashboard(
    host: str, port: int, timeout: float = PROBE_TIMEOUT_SECONDS
) -> dict[str, Any] | None:
    """Ask the server at ``host:port`` what it is (``GET /api/version``).

    Returns the decoded body when it answers — ``{}`` if the body is not a
    JSON object — and ``None`` when it does not. This is the ONLY evidence
    that the recorded pid really is a dashboard, so the distinction matters:
    ``None`` means "nothing is running there", never "running, version
    unknown". A ``0.0.0.0`` bind is reached via loopback.
    """
    if not isinstance(port, int) or port <= 0:
        return None
    reach = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    try:
        with urllib.request.urlopen(f"http://{reach}:{port}/api/version", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 — any failure is "no answer"
        return None
    return data if isinstance(data, dict) else {}


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


def take_failure_note() -> str | None:
    """Read and clear the note a failed restart worker left behind, so the
    next session start reports it once. None when there is nothing to say."""
    path = failure_path()
    try:
        note = path.read_text().strip()
    except OSError:
        return None
    try:
        path.unlink()
    except OSError:
        pass
    return note or None


def _write_failure(note: str) -> None:
    path = failure_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(note + "\n")
    except OSError:
        pass


def _lock_owner() -> str | None:
    try:
        return lock_path().read_text().strip() or None
    except OSError:
        return None


def _take_lock(now: float, owner: str) -> bool:
    """Claim the restart for ``owner``: creates the lock unless a fresh one
    exists. A stale lock (older than the TTL) is taken over ATOMICALLY — a
    uniquely named temp file renamed into place, never unlink-then-create,
    which would leave a window for two sessions to both "win". After the
    rename the owner is read back: if a racer's rename landed last, we lost
    and back off, so at most one session proceeds.
    """
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = owner.encode()
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        pass
    else:
        os.write(fd, payload)
        os.close(fd)
        return True
    try:
        age = now - path.stat().st_mtime
    except OSError:
        return False
    if age < LOCK_TTL_SECONDS:
        return False
    tmp = path.with_name(path.name + f".{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        tmp.write_bytes(payload)
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    return _lock_owner() == owner


def _release_lock(owner: str) -> None:
    """Drop the lock only when it is still OURS — a lock another session took
    over after ours went stale must not be deleted out from under it."""
    if _lock_owner() != owner:
        return
    try:
        lock_path().unlink()
    except OSError:
        pass


def spawn_restart_worker(owner: str) -> int:
    """Run the kill-and-relaunch DETACHED (this module, as a script) and
    return its pid. The session-start hook must not wait on a SIGTERM, so it
    hands the slow half to a child that outlives it and holds ``owner``'s
    lock until it is done."""
    log = log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, str(Path(__file__).resolve()), "--restart-worker", "--lock-owner", owner]
    with log.open("ab") as out:
        proc = subprocess.Popen(
            argv, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    return proc.pid


def restart_if_stale(
    *,
    now: float | None = None,
    installed: str | None = None,
    alive: Callable[[int], bool] = pid_alive,
    probe: Callable[[str, int], dict[str, Any] | None] = probe_dashboard,
    spawn: Callable[[str], int] = spawn_restart_worker,
) -> str | None:
    """The SessionStart check. Returns a one-line message when a restart was
    handed off, else None. Every "do nothing" path is silent; every failure
    is swallowed by the caller (the hook verb) — this must never delay or
    break a session start.

    The steps, per the spec: no record → nothing; pid dead → nothing (the
    stale record is cleaned); the server does not ANSWER the probe → nothing,
    and the record is cleaned — a live-but-silent pid is a stranger that
    inherited the number after a reboot, so it is never signalled and no
    dashboard is started in its place; running version (what the live server
    says it is, with the record's stamp filling in only a probe response that
    omits it) at or above the installed one → nothing; else take the lock and
    hand the kill-and-relaunch to a detached worker.
    """
    record = read_record()
    if record is None:
        return None
    pid = record.get("pid")
    if not isinstance(pid, int) or not alive(pid):
        remove_record(pid if isinstance(pid, int) else None)
        return None
    host, port = str(record.get("host") or "127.0.0.1"), int(record.get("port") or 0)
    answer = probe(host, port)
    if answer is None:
        # Alive pid, no dashboard behind it. Drop the stamp; kill nothing.
        remove_record(pid)
        return None
    running = str(answer.get("version") or record.get("version") or "")
    installed = plugin_version() if installed is None else installed
    if not installed or version_tuple(installed) <= version_tuple(running):
        return None
    if not all(record.get(k) for k in ("serve", "root", "host", "port")):
        return None
    if now is None:
        now = time.time()
    owner = secrets.token_hex(8)
    if not _take_lock(now, owner):
        return None
    try:
        spawn(owner)
    except Exception:  # noqa: BLE001 — nothing was killed; stay silent
        _release_lock(owner)
        return None
    return f"overseer dashboard restarting {running or '?'} → {installed} (pid {pid})"


def run_restart_worker(
    owner: str,
    *,
    terminate: Callable[[int], bool] = terminate_pid,
    relaunch: Callable[[dict[str, Any]], int] = launch,
) -> int:
    """The detached half: kill the recorded server and relaunch it as
    recorded. Returns a process exit code.

    A relaunch that raises AFTER the old server is dead leaves the user with
    no dashboard and no idea why, so it is recorded as a note the next
    session's hook prints. The lock is released whatever happens.
    """
    try:
        record = read_record()
        if record is None:
            return 0
        pid = record.get("pid")
        if not isinstance(pid, int):
            return 0
        if not terminate(pid):
            return 1
        try:
            relaunch(record)
        except Exception as exc:  # noqa: BLE001 — surfaced, not swallowed
            _write_failure(
                "overseer dashboard restart FAILED — the old server was stopped and the new "
                f"one would not start ({exc}); relaunch it by hand (see {log_path()})"
            )
            return 1
        return 0
    finally:
        _release_lock(owner)


def _worker_main(argv: list[str]) -> int:
    """Entry point for ``python dashboard_record.py --restart-worker
    --lock-owner TOKEN``, which ``spawn_restart_worker`` starts detached."""
    owner = ""
    if "--lock-owner" in argv:
        index = argv.index("--lock-owner") + 1
        owner = argv[index] if index < len(argv) else ""
    return run_restart_worker(owner)


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


if __name__ == "__main__":
    raise SystemExit(_worker_main(sys.argv[1:]))
