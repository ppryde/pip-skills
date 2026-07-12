"""Launcher for the overseer dashboard.

Wires the FastAPI backend (`backend/app/main.py::create_app`) — which serves
the committed frontend `dist/` at `/` plus `/api/*` — up to a real uvicorn
server and opens a browser tab. Frontend `dist/` is committed (WF-005 C7), so
running this needs only the Python deps (fastapi + uvicorn); node/Vite are
dev-only and not required at runtime.

Binds to 127.0.0.1 by default: this is a local, single-user tool, never
0.0.0.0, unless the caller explicitly opts into a different `--host`.

Usage (from the repo root):
    python plugins/overseer/dashboard/serve.py [--root PATH] [--host HOST] [--port PORT] [--no-browser]
"""
from __future__ import annotations

import argparse
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

from app.main import create_app  # noqa: E402  (must follow the sys.path setup above)

DEFAULT_PORT = 8770


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
    return parser.parse_args(argv)


def _open_browser(url: str) -> None:
    """Open `url` in the default browser; never raise (headless envs, etc.)."""
    try:
        webbrowser.open(url)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    """Build the dashboard app and serve it. Returns a process exit code."""
    args = parse_args(argv)
    root = Path(args.root).resolve()
    app = create_app(root)
    url = f"http://{args.host}:{args.port}/"
    print(f"overseer dashboard serving {root} at {url}")

    if not args.no_browser:
        threading.Timer(1.0, _open_browser, args=(url,)).start()

    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
