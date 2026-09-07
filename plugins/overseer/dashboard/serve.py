"""Launcher for the overseer dashboard.

Wires the FastAPI backend (`backend/app/main.py::create_app`) — which serves
the committed frontend `dist/` at `/` plus `/api/*` — up to a real uvicorn
server and opens a browser tab. Frontend `dist/` is committed (WF-005 C7), so
running this needs only the Python deps (fastapi + uvicorn); node/Vite are
dev-only and not required at runtime.

Binds to 127.0.0.1 by default: this is a local, single-user tool, never
0.0.0.0, unless the caller explicitly opts into a different `--host`.

WF-053: the server STAMPS itself once the bind succeeds — a runtime record
(pid, host, port, root, version, how to relaunch) at `<CLAUDE_CONFIG_DIR>/
overseer/.dashboard.json`, removed on clean shutdown — so a SessionStart hook
can spot a running server that is older than the installed overseer and
restart it in place. One dashboard per config dir, literally: a launch
refuses while a recorded server is still answering on ANY port, unless
`--replace`, which stops that server first.

Usage (from the repo root):
    python plugins/overseer/dashboard/serve.py [--root PATH] [--host HOST] [--port PORT] [--no-browser] [--replace]
"""
from __future__ import annotations

import argparse
import os
import secrets
import socket
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn

# `app` (the FastAPI package) lives in `backend/`, one directory below this
# file. Add it to sys.path so `from app.main import create_app` resolves the
# same way the backend's own tests do (via their `pythonpath=["."]` config).
_BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
# `scripts` (overseer's own package) lives two directories up; the runtime
# record helpers are shared with the CLI's SessionStart hook verb.
_OVERSEER_ROOT = Path(__file__).resolve().parent.parent
if str(_OVERSEER_ROOT) not in sys.path:
    sys.path.insert(0, str(_OVERSEER_ROOT))

from app.main import LOOPBACK_HOSTS, create_app

from scripts import dashboard_record

DEFAULT_PORT = 8770


def resolve_token(host: str) -> str | None:
    """The dashboard token in effect for this bind, or None (gate off).

    Explicit ``OVERSEER_DASHBOARD_TOKEN`` always wins. Otherwise a token is
    auto-generated ONLY for a non-loopback bind — exposing the mutation
    surface beyond localhost must not be tokenless. A pure loopback bind with
    no env var stays token-free (the common single-user case).
    """
    env = os.environ.get("OVERSEER_DASHBOARD_TOKEN")
    if env:
        return env
    if host not in LOOPBACK_HOSTS:
        return secrets.token_urlsafe(24)
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse launcher CLI args."""
    parser = argparse.ArgumentParser(
        prog="serve.py",
        description="Launch the overseer dashboard (FastAPI + committed frontend dist/).",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repo root to serve the dashboard for (default: current directory).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host (default: 127.0.0.1 — local-only; do not expose this beyond localhost).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Bind port (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open a browser tab automatically.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="If a recorded dashboard is still answering (on any port), stop it and take over.",
    )
    return parser.parse_args(argv)


def _open_browser(url: str) -> None:
    """Open `url` in the default browser; never raise (headless envs, etc.)."""
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _claim_dashboard(replace: bool) -> str | None:
    """Singleton guard (WF-053 B4): one dashboard per config dir.

    When the runtime record names a server that is really there — a live pid
    that also ANSWERS ``GET /api/version`` — either take it over (``replace``)
    or refuse, whatever port it holds: a second launch on another port would
    otherwise stamp over the live server's record and leave it unmanaged.

    A record whose pid is dead, or alive but silent, is a leftover (a reboot
    can hand its pid to an unrelated process). It is dropped and the launch
    goes ahead. Nothing is ever signalled without the probe answering first.

    Returns the refusal message, or None to go ahead.
    """
    record = dashboard_record.read_record()
    if record is None:
        return None
    pid = record.get("pid")
    if not isinstance(pid, int) or not dashboard_record.pid_alive(pid):
        dashboard_record.remove_record(pid if isinstance(pid, int) else None)
        return None
    host, port = str(record.get("host") or "127.0.0.1"), int(record.get("port") or 0)
    if dashboard_record.probe_dashboard(host, port) is None:
        dashboard_record.remove_record(pid)
        return None
    if not replace:
        return (
            f"overseer dashboard already running at http://{host}:{port}/ "
            f"(pid {pid}); pass --replace to take over"
        )
    if not dashboard_record.terminate_pid(pid):
        return f"overseer dashboard pid {pid} would not stop; not taking over"
    dashboard_record.remove_record(pid)
    print(f"overseer dashboard replaced pid {pid}")
    return None


def _bind(host: str, port: int) -> socket.socket:
    """Bind and listen on the dashboard's socket BEFORE anything is stamped.

    uvicorn runs the ASGI lifespan startup first and only then binds, so a
    lifespan hook cannot tell "listening" from "about to fail with address
    already in use". Owning the bind here means the record is written only
    once the port is really ours; a launch that cannot bind raises out of
    this call having claimed nothing. The listening socket is handed to
    uvicorn by file descriptor.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(128)
        sock.set_inheritable(True)
    except OSError:
        sock.close()
        raise
    return sock


def _unstamp_on_shutdown(app: Any, pid: int) -> Any:
    """Wrap the ASGI app so OUR record is removed when the lifespan shutdown
    completes.

    A `finally` around `uvicorn.run` is not enough: on SIGTERM (which is how
    `terminate_pid` and the restart hook stop us) uvicorn drains the server,
    restores the default handler and re-raises the signal, so the process
    dies inside `run()` and the `finally` never executes. The
    `lifespan.shutdown.complete` message is sent before that re-raise.
    Done at the raw ASGI layer because Starlette 1.x dropped
    `add_event_handler` / `on_shutdown`; the lifespan message names are the
    stable contract.
    """
    async def wrapper(scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "lifespan":
            await app(scope, receive, send)
            return

        async def _send(message: dict) -> None:
            if message.get("type") == "lifespan.shutdown.complete":
                dashboard_record.remove_record(pid)
            await send(message)

        await app(scope, receive, _send)

    return wrapper


def main(argv: list[str] | None = None) -> int:
    """Build the dashboard app and serve it. Returns a process exit code."""
    args = parse_args(argv)
    root = Path(args.root).resolve()
    refusal = _claim_dashboard(args.replace)
    if refusal:
        print(refusal, file=sys.stderr)
        return 1
    token = resolve_token(args.host)
    app = create_app(root, host=args.host, token=token)
    url = f"http://{args.host}:{args.port}/"
    print(f"overseer dashboard serving {root} at {url}")
    if token:
        print(f"dashboard token (send as X-Overseer-Token header): {token}")

    if not args.no_browser:
        threading.Timer(1.0, _open_browser, args=(url,)).start()

    # Bind first: a launch that loses the port raises here and never stamps,
    # so it cannot claim to be the running dashboard nor delete a real one's
    # record on the way out.
    sock = _bind(args.host, args.port)
    record = dashboard_record.stamp(
        host=args.host, port=args.port, root=root, serve=Path(__file__).resolve()
    )
    dashboard_record.write_record(record)
    try:
        uvicorn.run(
            _unstamp_on_shutdown(app, record["pid"]),
            host=args.host, port=args.port, fd=sock.fileno(),
        )
    finally:
        # Belt and braces for exits that are not a signal (the lifespan hook
        # above handles SIGTERM, which never reaches this line). Only OUR
        # record: a replacement that stamped over ours while we were
        # shutting down keeps its own.
        dashboard_record.remove_record(record["pid"])
        sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
