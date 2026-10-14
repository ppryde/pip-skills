"""Mechanics for remote board access from a dev container (``POST /api/exec``).

No FastAPI app lives here: ``main.create_app`` mounts the route and the LAN
guard. This module holds argv sanitisation, the denied-verb list, the child
environment, and ``run_cli``, which runs the real overseer CLI on the host
against a board PINNED when the app started — the mechanism the container's
``overseer --remote`` forwards every verb and hook to.

The host CLI stays the single writer of board.db; this module only shells it,
exactly as the dashboard backend's cli_client already does.
"""
from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel
from scripts.gitenv import hardened_git_env

# backend/app/board_service.py -> parents: [0]=app [1]=backend [2]=dashboard [3]=overseer
_OVERSEER_CLI = Path(__file__).resolve().parents[3] / "scripts" / "cli.py"
_EXEC_TIMEOUT = 30
# One request's argv plus stdin may not exceed this many bytes (413).
MAX_EXEC_BYTES = 1024 * 1024
# At most this many CLI children at once; a fifth caller is told to retry (503).
_EXEC_SLOTS = threading.BoundedSemaphore(4)

# The child gets the server's environment minus anything that looks like a
# credential. A strip, not an allowlist: the CLI needs PATH, HOME, git, the
# ssh agent, CENSUS_*, CHRONICLE_* and test pins, and every new variable would
# silently break an allowlist.
_ALWAYS_DROPPED = {"OVERSEER_REMOTE", "OVERSEER_REMOTE_TOKEN", "OVERSEER_DASHBOARD_TOKEN"}
_SECRET_SUBSTRINGS = ("TOKEN", "SECRET", "KEY", "PASSWORD")
_SECRET_PREFIXES = ("AWS_", "GH_", "GITHUB_")
_NEEDED_PREFIXES = ("CENSUS_", "CHRONICLE_")


def _child_env(central: Path) -> dict[str, str]:
    """The exec child's environment: secrets stripped, the board pinned."""
    env: dict[str, str] = {}
    for name, value in os.environ.items():
        upper = name.upper()
        if name in _ALWAYS_DROPPED:
            continue
        if not upper.startswith(_NEEDED_PREFIXES) and (
            any(s in upper for s in _SECRET_SUBSTRINGS) or upper.startswith(_SECRET_PREFIXES)
        ):
            continue
        env[name] = value
    env["OVERSEER_CENTRAL"] = str(central)
    return hardened_git_env(env)


class ExecRequest(BaseModel):
    argv: list[str]
    stdin: str | None = None


class ExecResult(BaseModel):
    stdout: str
    stderr: str
    returncode: int


_IPV6_ULA = ipaddress.ip_network("fc00::/7")


def _is_lan_client(host: str | None) -> bool:
    """True only for a private/loopback/link-local source address.

    Guarantees the service never answers a remote, non-LAN caller even when
    bound to 0.0.0.0. An absent/unparseable client is rejected (safe default).
    """
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    # 6to4 (2002::/16) and IPv4-mapped addresses are judged by the IPv4 inside.
    if isinstance(ip, ipaddress.IPv6Address):
        ip = ip.sixtofour or ip.ipv4_mapped or ip
    if isinstance(ip, ipaddress.IPv6Address):
        # Only loopback, link-local and ULA: `is_private` also covers Teredo,
        # documentation and NAT64-adjacent ranges.
        return ip.is_loopback or ip.is_link_local or ip in _IPV6_ULA
    return ip.is_private or ip.is_loopback or ip.is_link_local


# Flags whose value is a HOST path (or an outbound URL) that a container caller
# must never be able to inject: --root/--remote (global) plus every host-path
# option on the admin verbs — --central/--backup-dir (init) and --dir
# (backup/restore). These verbs are additionally denied outright (see
# _DENIED_VERBS); stripping the flags is defense-in-depth so a value can never
# reach the subprocess even if the denylist is ever bypassed.
_STRIPPED_FLAGS = ("--root", "--remote", "--dir", "--central", "--backup-dir")

# Verbs refused on the remote board API: they wipe, re-bootstrap, or read/write
# arbitrary host paths, none of which a remote container caller may drive.
# The hook verbs take their root from the stdin payload's `cwd` in preference to
# `--root` (cli._hook_root), so any of them escapes the pinned root, and
# `report-hook` writes; `dashboard-refresh-hook` restarts the host dashboard.
# `pretool-hook` is the one hook forwarded remotely: its `cwd` is overwritten.
# `bootstrap` (fetch + `worktree add`, a checkout) and `dispatch-prep` (`status`
# and `diff` in the card's worktree) run git in a tree the container can write:
# hooks and filters planted there would run on the host. They move client-side
# in the follow-up card; until then run them on the host.
GIT_FOLLOWUP_CARD = "WF-300"
_GIT_VERBS = {"bootstrap", "dispatch-prep"}
_DENIED_VERBS = {
    "clear", "init", "backup", "restore",
    "claude-dirs", "merge-boards",
    "checklist-sync-hook", "claim-stop-hook", "claim-prompt-hook", "report-hook",
    "dashboard-refresh-hook",
} | _GIT_VERBS

# Options that read a HOST file. Refused, not stripped: stripping would turn
# `set-section --file F` into a call that silently waits on stdin. The client
# (`cli._run_remote`) inlines the file as stdin before it gets here. Matched by
# prefix, so `--filename` is refused too (a value starting with one of these is
# a rare, loud, safe false positive).
_FILE_FLAGS = ("--file", "--text-file", "--brief-file")


def _strip_root_flags(argv: list[str]) -> list[str]:
    """Drop path-override flags (and their values) from a forwarded argv.

    A container root/host path is meaningless (or dangerous) on the host, and a
    forwarded --remote must never recurse. The service injects its own pinned
    root instead. Handles both ``--flag value`` and ``--flag=value`` forms.
    """
    out: list[str] = []
    skip = False
    for tok in argv:
        if skip:
            skip = False
            continue
        if tok in _STRIPPED_FLAGS:
            skip = True
            continue
        if tok.startswith(tuple(f"{flag}=" for flag in _STRIPPED_FLAGS)):
            continue
        out.append(tok)
    return out


def _invoked_verb(argv: list[str]) -> str | None:
    """Return the subcommand verb in a (already root-flag-stripped) argv.

    The verb is the first bare (non ``--``-prefixed) token, skipping a leading
    ``--session-id`` and its value (``--session-id X`` or ``--session-id=X``)
    and any other option token. Returns None if no verb is present.
    """
    it = iter(argv)
    for tok in it:
        if tok == "--session-id":
            next(it, None)  # consume its value
            continue
        if tok.startswith("--"):
            continue
        return tok
    return None


def sanitise_argv(argv: list[str]) -> list[str]:
    """Strip the path-override flags, then refuse a host file option or a denied
    verb (403). Returns the argv that may be handed to the CLI."""
    argv = _strip_root_flags(argv)
    if any(tok.startswith(_FILE_FLAGS) for tok in argv):
        raise HTTPException(status_code=403, detail="host path options are not permitted remotely")
    verb = _invoked_verb(argv)
    if verb in _GIT_VERBS:
        raise HTTPException(
            status_code=403,
            detail=f"verb '{verb}' runs git in the repo; run it locally (follow-up {GIT_FOLLOWUP_CARD})",
        )
    if verb in _DENIED_VERBS:
        raise HTTPException(
            status_code=403,
            detail=f"verb '{verb}' is not permitted on the remote board API",
        )
    return argv


def _pin_hook_cwd(stdin: str | None, pinned_root: Path) -> str:
    """`pretool-hook` reads its root from the payload's `cwd`: pin it."""
    try:
        payload = json.loads(stdin or "")
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="pretool-hook needs a JSON object on stdin")
    payload["cwd"] = str(pinned_root)
    return json.dumps(payload)


def run_cli(pinned_root: Path, central: Path, req: ExecRequest) -> ExecResult:
    """Sanitise argv, refuse denied verbs, and run the host CLI against the
    PINNED root and board (``central`` becomes the child's ``OVERSEER_CENTRAL``).
    Raises HTTPException for every failure mode; a CLI that ran and exited
    non-zero is a SUCCESSFUL RPC and comes back as a 200 body.
    """
    size = sum(len(t.encode()) for t in req.argv) + len((req.stdin or "").encode())
    if size > MAX_EXEC_BYTES:
        raise HTTPException(status_code=413, detail=f"request exceeds {MAX_EXEC_BYTES} bytes")
    argv = sanitise_argv(req.argv)
    stdin = req.stdin
    if _invoked_verb(argv) == "pretool-hook":
        stdin = _pin_hook_cwd(stdin, pinned_root)
    if not _EXEC_SLOTS.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="exec busy: too many CLI calls in flight")
    try:
        proc = subprocess.run(
            [sys.executable, str(_OVERSEER_CLI), "--root", str(pinned_root), *argv],
            env=_child_env(central),
            input=stdin,
            capture_output=True,
            text=True,
            timeout=_EXEC_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="overseer CLI timed out")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"cannot run overseer CLI: {exc}")
    finally:
        _EXEC_SLOTS.release()
    return ExecResult(stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)
