"""Launcher for the standalone overseer board API service (dev-container access).

Wires ``backend/app/board_service.py::create_service_app`` up to uvicorn. Unlike
the dashboard launcher this is meant to be reachable from a Docker dev container,
so it binds 0.0.0.0 by default and REQUIRES a token on a non-loopback bind
(auto-generated + printed when OVERSEER_REMOTE_TOKEN isn't set). A LAN-only
source guard (in the app) refuses any non-LAN caller regardless of bind.

Usage (from the repo root):
    python plugins/overseer/dashboard/serve_board_api.py [--root PATH] [--host HOST] [--port PORT]
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

import uvicorn

_BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.board_service import create_service_app
from app.main import LOOPBACK_HOSTS

DEFAULT_PORT = 8771
REMOTE_TOKEN_ENV = "OVERSEER_REMOTE_TOKEN"


def resolve_remote_token(host: str, root: Path) -> str | None:
    """The token in effect for this bind: env wins; loopback stays tokenless;
    else reuse the persisted token file or generate one and persist it (0600) so
    a mounted dev container can read it without a manual copy."""
    env = os.environ.get(REMOTE_TOKEN_ENV)
    if env:
        return env
    if host in LOOPBACK_HOSTS:
        return None
    from scripts.remote_token import read_remote_token, write_remote_token
    existing = read_remote_token(root)
    if existing:
        return existing
    token = secrets.token_urlsafe(24)
    write_remote_token(root, token)
    return token


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="serve_board_api.py")
    parser.add_argument("--root", default=".")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    token = resolve_remote_token(args.host, root)
    app = create_service_app(root, host=args.host, token=token)
    if token:
        from scripts.remote_token import remote_token_path
        print(f"board API token: {token}")
        print(f"token file (auto-read by a container mounting this repo): {remote_token_path(root)}")
    print(f"serving board API for {root} on http://{args.host}:{args.port}/  (LAN-only)")
    # proxy_headers=False: uvicorn trusts X-Forwarded-For by default. If this
    # LAN-only service were ever fronted by a loopback reverse proxy, that
    # header would become attacker-controllable and could spoof a private
    # source IP past _is_lan_client. The LAN guard must not ride on a default.
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
