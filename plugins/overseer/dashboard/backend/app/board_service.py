"""Standalone overseer board API service — HTTP board access for a dev container.

Reuses the dashboard's ``create_app`` (frontend mount disabled) so the ``/api/*``
surface is identical, then adds:
  - a LAN-only source-IP guard (never answer a remote, non-LAN caller), and
  - ``POST /api/exec``, a token-gated passthrough that runs the real overseer
    CLI on the host against a PINNED root — the mechanism the container's
    ``overseer --remote`` forwards every verb/hook to.

The host CLI stays the single writer of board.db; this service only shells it,
exactly as the dashboard backend's cli_client already does.
"""
from __future__ import annotations

import ipaddress
import subprocess
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.main import create_app, make_require_token

# backend/app/board_service.py -> parents: [0]=app [1]=backend [2]=dashboard [3]=overseer
_OVERSEER_CLI = Path(__file__).resolve().parents[3] / "scripts" / "cli.py"
_EXEC_TIMEOUT = 30


class ExecRequest(BaseModel):
    argv: list[str]
    stdin: str | None = None


class ExecResult(BaseModel):
    stdout: str
    stderr: str
    returncode: int


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
_DENIED_VERBS = {"clear", "init", "backup", "restore"}


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


def create_service_app(root: Path, *, host: str = "0.0.0.0", token: str | None = None) -> FastAPI:
    app = create_app(root, host=host, token=token, mount_frontend=False)
    pinned_root = root.resolve()
    require_token = make_require_token(token)

    @app.middleware("http")
    async def _lan_only(request: Request, call_next):
        client = request.client.host if request.client else None
        if not _is_lan_client(client):
            return JSONResponse(status_code=403, content={"detail": "non-LAN caller refused"})
        return await call_next(request)

    @app.post("/api/exec", dependencies=[Depends(require_token)])
    def exec_cli(req: ExecRequest) -> ExecResult:
        argv = _strip_root_flags(req.argv)
        verb = _invoked_verb(argv)
        if verb in _DENIED_VERBS:
            raise HTTPException(
                status_code=403,
                detail=f"verb '{verb}' is not permitted on the remote board API",
            )
        try:
            proc = subprocess.run(
                [sys.executable, str(_OVERSEER_CLI), "--root", str(pinned_root), *argv],
                input=req.stdin,
                capture_output=True,
                text=True,
                timeout=_EXEC_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="overseer CLI timed out")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"cannot run overseer CLI: {exc}")
        return ExecResult(stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)

    return app
