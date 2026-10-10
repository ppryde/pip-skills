"""The client side of a "prod-access" pull (WF-122): bundles ``redact.py`` +
``remote_agent.py`` into one script, runs it on the remote box over ssh, and
turns its NDJSON frames into an append-only local mirror that ``ingest.sync``
then reads like any other Claude config dir.

Nothing here trusts the remote to behave: a nonzero exit, a timeout, or a
frame that fails to parse skips that remote for this round (recorded in
``meta`` and returned as a ``remote_errors`` entry) and never raises past
``sync_remotes`` — the local dirs, and every OTHER remote, must still sync.

Crash safety: for each file, the mirror's on-disk length is checked against
the last COMMITTED length before anything is appended; a length past that
checkpoint (a previous run that appended but crashed before recording the
new checkpoint) is truncated back to it first, so re-applying the same pull
is always safe — a run killed at any point converges to the same state a
run that was not killed would have reached, never duplicated lines. Append,
fsync, THEN the state file is rewritten (atomically) — never the reverse.

`sessions.config_dir` for a session read out of a remote's mirror is the
synthetic ``remote://<name>`` label (see `store.Remote`), never the mirror's
real path — the same trick WF-120 plays for `docker://<volume>`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scripts import store
from scripts.volumes import _MAIN_RE, _SUBAGENT_RE

DISABLE_ENV = "CHRONICLE_NO_REMOTES"

SSH_CONNECT_TIMEOUT_S = 10
SSH_TOTAL_TIMEOUT_S = 90          # hard subprocess timeout for one remote, one call
DEFAULT_MAX_BYTES = 8_000_000
DEFAULT_DEADLINE_S = 45.0
DEFAULT_SYNC_BUDGET_S = 60.0      # shared across every remote in one sync_remotes() call
MAX_BACKOFF_S = 3600.0

_META_PREFIX = "remote_status:"
_SCRIPTS_DIR = Path(__file__).resolve().parent


class RemoteTransportError(Exception):
    """ssh (or the fake standing in for it) could not be run at all — never
    raised past `sync_remotes`/`probe_remote`, only used internally to unify
    "process failed to start", "timed out", and "OS-level failure" into one
    thing the caller reports as one error string."""


@dataclass
class SSHResult:
    """What a transport call returns, real or fake: enough to tell success
    from failure without the caller knowing how the bytes got there."""
    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""


Transport = Callable[[list[str], bytes, float], SSHResult]


def _run_ssh(argv: list[str], stdin: bytes, timeout: float) -> SSHResult:
    """The real transport: never raises — a spawn failure or a timeout comes
    back as a nonzero-returncode `SSHResult`, exactly like a remote ssh
    failure, so the caller has one failure shape to handle."""
    try:
        completed = subprocess.run(
            argv, input=stdin, capture_output=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return SSHResult(124, b"", f"ssh timed out after {timeout:g}s".encode()
                         + (b": " + exc.stderr if exc.stderr else b""))
    except (OSError, subprocess.SubprocessError) as exc:
        return SSHResult(127, b"", str(exc).encode())
    return SSHResult(completed.returncode, completed.stdout, completed.stderr)


def ssh_argv(remote: store.Remote, request_b64: str) -> list[str]:
    """The exact ssh invocation: options first (never disabled: host-key
    checking, batch mode, no agent/X11 forwarding), ``--`` before the host so
    a hostile-looking (but regex-validated) host can never be read as an
    option, then the remote command. The script text travels on stdin; the
    request travels as an argv token (base64: alphanumeric + `+/=`, so it is
    inert wherever a shell might still touch it) because stdin IS the script
    — `python3 -` reads it to EOF before running, so nothing can follow it on
    the same stream (see `remote_agent`'s module docstring)."""
    return [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={SSH_CONNECT_TIMEOUT_S}",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=2",
        "-o", "StrictHostKeyChecking=yes",
        "-a", "-x", "-T",
        "--", remote.host,
        "python3", "-", request_b64,
    ]


def bundle_source() -> str:
    """``redact.py`` + `remote_agent.py``'s source, concatenated into one
    Python 3.8-compatible script: `remote_agent.py` uses `redact`'s names
    directly (no `import redact` — there is nothing on the remote disk to
    import it from), and its own leading ``from __future__ import
    annotations`` is dropped so the bundle carries exactly one (redact.py's,
    at the very top — a `from __future__` after other statements is a
    SyntaxError)."""
    redact_src = (_SCRIPTS_DIR / "redact.py").read_text()
    agent_src = (_SCRIPTS_DIR / "remote_agent.py").read_text()
    agent_lines = [
        line for line in agent_src.splitlines()
        if line.strip() != "from __future__ import annotations"
    ]
    return redact_src + "\n\n" + "\n".join(agent_lines) + "\n"


# ---------------------------------------------------------------------------
# Mirror state: `<mirror>/.state.json`, holding the REMOTE ORIGINAL byte
# offset consumed per jsonl file and the mirror's own committed length (the
# crash-safety checkpoint — see the module docstring), plus meta files' last-
# seen remote size. Chronicle's own ingest cursors track the MIRROR file
# separately (an ordinary local claude dir it reads like any other); nothing
# here reads or writes those.

def _state_path(mirror_root: Path) -> Path:
    return mirror_root / ".state.json"


def _load_state(mirror_root: Path) -> dict[str, Any]:
    path = _state_path(mirror_root)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"files": {}, "meta": {}}
    if not isinstance(data, dict):
        return {"files": {}, "meta": {}}
    data.setdefault("files", {})
    data.setdefault("meta", {})
    return data


def _save_state(mirror_root: Path, state: dict[str, Any]) -> None:
    path = _state_path(mirror_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, separators=(",", ":")))
    os.replace(tmp, path)


_META_RELPATH_RE = re.compile(
    r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+/subagents/agent-[A-Za-z0-9_-]+\.meta\.json$")


def _validate_relpath(mirror_root: Path, relpath: object) -> str:
    """A remote-supplied ``file`` must be a transcript or sub-agent meta path of
    the shape ``claude`` writes, and must resolve inside ``<mirror>/projects``.
    The remote is not trusted: a hostile one could otherwise name ``../..`` and
    make us write or unlink outside the mirror. Raises ``ValueError`` (which
    ``_pull_once`` reports as a garbled response)."""
    if not isinstance(relpath, str) or not (
            _MAIN_RE.match(relpath) or _SUBAGENT_RE.match(relpath)
            or _META_RELPATH_RE.match(relpath)):
        raise ValueError(f"unexpected remote file path {relpath!r}")
    root = (mirror_root / "projects").resolve()
    if root not in (root / relpath).resolve().parents:
        raise ValueError(f"remote file path escapes the mirror: {relpath!r}")
    return relpath


def _mirror_path(mirror_root: Path, relpath: str) -> Path:
    return mirror_root / "projects" / relpath


def _append_file_frame(mirror_root: Path, state: dict[str, Any], frame: dict[str, Any]) -> None:
    """Apply one ``file`` frame to the mirror: truncate-to-checkpoint (undoing
    any partial append a previous crash left behind), append this frame's
    lines, fsync, THEN advance the checkpoint in ``state`` (the caller saves
    it). Never called for a frame with no new lines and no truncation."""
    relpath = _validate_relpath(mirror_root, frame["file"])
    to_offset = frame["to_offset"]
    lines = frame["lines"]
    if (not isinstance(to_offset, int) or isinstance(to_offset, bool) or to_offset < 0
            or not isinstance(lines, list) or not all(isinstance(x, str) for x in lines)):
        raise ValueError("malformed file frame")
    target = _mirror_path(mirror_root, relpath)
    target.parent.mkdir(parents=True, exist_ok=True)
    entry = state["files"].get(relpath) or {"offset": 0, "mirror_bytes": 0}
    if frame.get("truncated"):
        # The REMOTE file shrank or rotated: our mirror's copy of it describes
        # a file that no longer exists at that remote path. Start clean.
        entry = {"offset": 0, "mirror_bytes": 0}
        if target.exists():
            target.unlink()
    checkpoint = int(entry.get("mirror_bytes", 0))
    with open(target, "ab") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() > checkpoint:
            handle.truncate(checkpoint)
            handle.seek(checkpoint)
        for line in lines:
            handle.write(line.encode("utf-8"))
            handle.write(b"\n")
        handle.flush()
        os.fsync(handle.fileno())
        new_len = handle.tell()
    state["files"][relpath] = {"offset": to_offset, "mirror_bytes": new_len}


def _apply_meta_frame(mirror_root: Path, state: dict[str, Any], frame: dict[str, Any],
                      remote_size: int) -> None:
    relpath = _validate_relpath(mirror_root, frame["file"])
    target = _mirror_path(mirror_root, relpath)
    content = frame.get("content")
    if content is not None:
        if not isinstance(content, str):
            raise ValueError("malformed meta frame")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    state["meta"][relpath] = {"remote_size": remote_size}


def _write_account(mirror_root: Path, profile: dict[str, str] | None) -> None:
    if profile is None:
        return   # unreadable this round: leave whatever the mirror already has
    target = mirror_root / ".claude.json"
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps({"oauthAccount": profile}))
    os.replace(tmp, target)


# ---------------------------------------------------------------------------
# One remote, one round trip.

@dataclass
class PullResult:
    ok: bool
    files_sent: int = 0
    bytes_sent: int = 0
    partial: bool = False
    error: str | None = None
    files_seen: int = 0
    python_version: str | None = None
    projects_dir_exists: bool | None = None
    listed: list[dict[str, Any]] = field(default_factory=list)


def _request_for(remote: store.Remote, state: dict[str, Any], *, max_bytes: int,
                 deadline_s: float) -> dict[str, Any]:
    known: dict[str, Any] = {}
    for relpath, entry in state.get("files", {}).items():
        known[relpath] = {"offset": entry.get("offset", 0)}
    for relpath, entry in state.get("meta", {}).items():
        known[relpath] = {"size": entry.get("remote_size", -1)}
    return {"claude_dir": remote.claude_dir, "fidelity": remote.fidelity, "state": known,
            "max_bytes": max_bytes, "deadline_s": deadline_s}


def _b64(request: dict[str, Any]) -> str:
    import base64
    return base64.b64encode(json.dumps(request, separators=(",", ":")).encode()).decode("ascii")


def _pull_once(remote: store.Remote, *, transport: Transport, state: dict[str, Any],
               max_bytes: int = DEFAULT_MAX_BYTES, deadline_s: float = DEFAULT_DEADLINE_S,
               apply: bool = True) -> PullResult:
    """One ssh round trip: builds the request from ``state``, runs the
    transport, and (unless ``apply`` is False — a dry run) applies every frame
    to the mirror, mutating ``state`` in place. The caller saves ``state`` and
    the mirror's `.claude.json` only when this returns ``ok``."""
    request = _request_for(remote, state, max_bytes=max_bytes, deadline_s=deadline_s)
    argv = ssh_argv(remote, _b64(request))
    result = transport(argv, bundle_source().encode("utf-8"), SSH_TOTAL_TIMEOUT_S)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()[:500]
        return PullResult(ok=False, error=f"ssh exited {result.returncode}: {stderr or 'no output'}")
    mirror_root = remote.mirror_root()
    pull = PullResult(ok=True)
    account_profile: dict[str, str] | None = None
    got_done = False
    try:
        for raw_line in result.stdout.decode("utf-8").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            frame = json.loads(raw_line)
            if not isinstance(frame, dict):
                raise ValueError("frame is not an object")  # noqa: TRY004 - part of the frame-parse contract below
            kind = frame.get("t")
            if kind == "list":
                pull.listed = frame.get("files") or []
                pull.files_seen = len(pull.listed)
                pv = frame.get("python_version")
                if isinstance(pv, str):
                    pull.python_version = pv
                pull.projects_dir_exists = frame.get("projects_dir_exists")
            elif kind == "file":
                pull.files_sent += 1
                pull.bytes_sent += sum(len(line) for line in frame.get("lines") or [])
                if apply:
                    _append_file_frame(mirror_root, state, frame)
            elif kind == "meta":
                if apply:
                    remote_size = next(
                        (f["size"] for f in pull.listed if f.get("relpath") == frame.get("file")), 0)
                    _apply_meta_frame(mirror_root, state, frame, remote_size)
            elif kind == "account":
                account_profile = frame.get("profile")
            elif kind == "done":
                got_done = True
                pull.partial = bool(frame.get("partial"))
            elif kind == "error":
                return PullResult(ok=False, error=str(frame.get("error") or "remote reported an error"))
    except (ValueError, KeyError, TypeError) as exc:
        return PullResult(ok=False, error=f"garbled response: {exc}")
    if not got_done:
        return PullResult(ok=False, error="response ended without a `done` frame")
    if apply:
        _write_account(mirror_root, account_profile)
    return pull


# ---------------------------------------------------------------------------
# Throttle + backoff status, persisted in the chronicle store's `meta` table
# so restarts do not stampede every configured remote at once.

def _status_key(name: str) -> str:
    return _META_PREFIX + name


def _load_status(conn: Any, name: str) -> dict[str, Any]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (_status_key(name),)).fetchone()
    if row is None:
        return {}
    try:
        data = json.loads(row[0])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _save_status(conn: Any, name: str, status: dict[str, Any]) -> None:
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                (_status_key(name), json.dumps(status, separators=(",", ":"))))


def _due(status: dict[str, Any], interval_s: int, now: float) -> bool:
    last_attempt = status.get("last_attempt")
    if not isinstance(last_attempt, (int, float)):
        return True
    failures = status.get("consecutive_failures", 0)
    wait = interval_s
    if isinstance(failures, int) and failures > 0:
        wait = min(MAX_BACKOFF_S, interval_s * (2 ** min(failures, 12)))
    return now - last_attempt >= wait


def status_of(conn: Any, remote: store.Remote) -> dict[str, Any]:
    """Everything `chronicle remotes status` shows for one remote: the last
    persisted status, plus its lag (mirror's newest-known activity vs now —
    left to the caller, which has the db connection's other tables)."""
    return {"name": remote.name, "host": remote.host, "enabled": remote.enabled,
           "fidelity": remote.fidelity, "interval_s": remote.interval_s,
           "mirror_dir": str(remote.mirror_root()), **_load_status(conn, remote.name)}


# ---------------------------------------------------------------------------
# The entrypoint `ingest`/`cli` call.

def sync_remotes(conn: Any, remote_list: list[store.Remote], *, now: float | None = None,
                 transport: Transport | None = None, budget_s: float = DEFAULT_SYNC_BUDGET_S,
                 force: bool = False, only: str | None = None,
                 dry_run: bool = False) -> dict[str, Any]:
    """Pull every enabled, due remote's new bytes into its mirror. Never
    raises: a remote that fails (bad ssh, garbled response, timeout) is
    skipped and named in ``remote_errors``; the caller still gets a result
    for every OTHER remote. ``CHRONICLE_NO_REMOTES=1`` short-circuits to a
    no-op before any transport is touched — no ssh call, ever, with it set.

    ``force`` ignores the per-remote throttle (``chronicle remotes sync``);
    ``only`` restricts to one remote by name; ``dry_run`` runs the whole
    round trip but writes nothing (mirror, state, or status untouched) —
    what WOULD sync, without syncing it.
    """
    if now is None:
        now = time.time()
    if os.environ.get(DISABLE_ENV):
        return {"remotes": [], "remote_errors": [], "skipped": "CHRONICLE_NO_REMOTES"}
    run_transport = transport or _run_ssh
    started = time.monotonic()
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for remote in remote_list:
        if only is not None and remote.name != only:
            continue
        if not remote.enabled:
            continue
        status = _load_status(conn, remote.name)
        if not force and not _due(status, remote.interval_s, now):
            continue
        if time.monotonic() - started >= budget_s:
            results.append({"name": remote.name, "skipped": "budget"})
            continue
        mirror_root = remote.mirror_root()
        state = _load_state(mirror_root)
        pull = _pull_once(remote, transport=run_transport, state=state, apply=not dry_run)
        if dry_run:
            results.append({"name": remote.name, "ok": pull.ok, "dry_run": True,
                            "files_pending": pull.files_sent, "bytes_pending": pull.bytes_sent,
                            "error": pull.error})
            continue
        new_status: dict[str, Any]
        if pull.ok:
            _save_state(mirror_root, state)
            new_status = {"last_attempt": now, "last_success": now, "ok": True,
                         "error": None, "consecutive_failures": 0,
                         "files_sent": pull.files_sent, "bytes_sent": pull.bytes_sent,
                         "partial": pull.partial}
        else:
            failures = int(status.get("consecutive_failures", 0)) + 1
            new_status = {**status, "last_attempt": now, "ok": False,
                         "error": pull.error, "consecutive_failures": failures}
            errors.append({"remote": remote.name, "error": pull.error or "unknown error"})
        _save_status(conn, remote.name, new_status)
        results.append({"name": remote.name, "ok": pull.ok, "files_sent": pull.files_sent,
                        "bytes_sent": pull.bytes_sent, "partial": pull.partial,
                        "error": pull.error})
    return {"remotes": results, "remote_errors": errors}


def probe_remote(remote: store.Remote, *, transport: Transport | None = None,
                 timeout: float = 15.0) -> dict[str, Any]:
    """One read-only connection: no file content is pulled (`max_bytes=0`
    stops before the first file), just the listing — python3's version, the
    projects dir's shape, and nothing written anywhere, remote or local."""
    run_transport = transport or _run_ssh
    state: dict[str, Any] = {"files": {}, "meta": {}}
    pull = _pull_once(remote, transport=run_transport, state=state, max_bytes=0,
                      deadline_s=min(timeout, DEFAULT_DEADLINE_S), apply=False)
    if not pull.ok:
        return {"name": remote.name, "ok": False, "error": pull.error}
    jsonl = [f for f in pull.listed if str(f.get("relpath", "")).endswith(".jsonl")]
    mtimes = [f["mtime"] for f in jsonl if isinstance(f.get("mtime"), (int, float))]
    return {
        "name": remote.name, "ok": True, "python_version": pull.python_version,
        "projects_dir_exists": bool(pull.projects_dir_exists), "jsonl_count": len(jsonl),
        "total_bytes": sum(int(f.get("size", 0)) for f in jsonl),
        "oldest_mtime": min(mtimes) if mtimes else None,
        "newest_mtime": max(mtimes) if mtimes else None,
    }
