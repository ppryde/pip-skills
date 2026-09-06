"""Launcher for the overseer dashboard.

Wires the FastAPI backend (`backend/app/main.py::create_app`) — which serves
the committed frontend `dist/` at `/` plus `/api/*` — up to a real uvicorn
server and opens a browser tab. Frontend `dist/` is committed (WF-005 C7), so
running this needs only the Python deps (fastapi + uvicorn); node/Vite are
dev-only and not required at runtime.

Binds to 127.0.0.1 by default: this is a local, single-user tool, never
0.0.0.0, unless the caller explicitly opts into a different `--host`.

WF-053: the server STAMPS itself on launch — a runtime record (pid, host,
port, root, version, how to relaunch) at `<CLAUDE_CONFIG_DIR>/overseer/
.dashboard.json`, removed on clean shutdown — so a SessionStart hook can spot
a running server that is older than the installed overseer and restart it in
place. One dashboard per config dir: a second launch on the same port refuses
unless `--replace`, which kills the recorded server first.

Usage (from the repo root):
    python plugins/overseer/dashboard/serve.py [--root PATH] [--host HOST] [--port PORT] [--no-browser] [--replace]
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
import threading
import webbrowser
from pathlib import Path

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
        help="If a recorded dashboard is still running on this port, stop it and take over.",
    )
    return parser.parse_args(argv)


def _open_browser(url: str) -> None:
    """Open `url` in the default browser; never raise (headless envs, etc.)."""
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _claim_port(port: int, replace: bool) -> str | None:
    """Singleton guard (WF-053 B4): when the runtime record names a LIVE
    server on this port, either take it over (``replace``) or refuse.
    Returns the refusal message, or None to go ahead."""
    record = dashboard_record.read_record()
    if record is None:
        return None
    pid = record.get("pid")
    if not isinstance(pid, int) or record.get("port") != port or not dashboard_record.pid_alive(pid):
        return None
    if not replace:
        return (
            f"overseer dashboard already running at http://{record.get('host')}:{port}/ "
            f"(pid {pid}); pass --replace to take over"
        )
    if not dashboard_record.terminate_pid(pid):
        return f"overseer dashboard pid {pid} would not stop; not taking over"
    print(f"overseer dashboard replaced pid {pid}")
    return None


def main(argv: list[str] | None = None) -> int:
    """Build the dashboard app and serve it. Returns a process exit code."""
    args = parse_args(argv)
    root = Path(args.root).resolve()
    refusal = _claim_port(args.port, args.replace)
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

    record = dashboard_record.stamp(
        host=args.host, port=args.port, root=root, serve=Path(__file__).resolve()
    )
    dashboard_record.write_record(record)
    try:
        uvicorn.run(app, host=args.host, port=args.port)
    finally:
        # Best effort, and only OUR record: a replacement that stamped over
        # ours while we were shutting down keeps its own.
        dashboard_record.remove_record(record["pid"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
