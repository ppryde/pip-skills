"""chronicle CLI — ingest and read/report verbs.

Pull only: nothing here runs inside a Claude Code session. ``sync`` (and
``ingest`` for one transcript) is how rows get in, driven by a person or by
the dashboard, which syncs on open and every minute while the Chronicle page
shows. There are deliberately no hooks — a Stop hook that runs code after
every turn is a feedback loop waiting to happen, and the per-file cursors make
polling cheap enough that a live feed buys nothing.

Report verbs print JSON to stdout for the dashboard / other tools.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# Allow `python plugins/chronicle/scripts/cli.py` from anywhere.
_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from scripts import ingest, report, store


def cmd_ingest(args: argparse.Namespace) -> int:
    path = Path(args.transcript)
    if not path.is_file():
        print(f"chronicle: no transcript at {path}", file=sys.stderr)
        return 1
    conn = store.connect()
    try:
        result = ingest.ingest_session(conn, path, args.session_id)
    finally:
        conn.close()
    print(json.dumps(result))
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Reconcile the store with the transcripts on disk (see ``ingest.sync``).
    Defaults to every watched config dir's ``projects/``; ``--projects`` (one
    or more) replaces that set."""
    projects = [Path(p) for p in args.projects] if args.projects else store.projects_dirs()
    conn = store.connect()
    try:
        result = ingest.sync(conn, projects, full=bool(getattr(args, "full", False)))
    finally:
        conn.close()
    out: dict[str, Any] = {
        **result,
        "projects_dirs": [str(p) for p in projects],
        "db": str(store.db_path()),
    }
    print(json.dumps(out))
    return 0


def _open_readonly() -> Any:
    try:
        return store.connect(readonly=True)
    except FileNotFoundError:
        return None


def cmd_status(_: argparse.Namespace) -> int:
    path = store.db_path()
    conn = _open_readonly()
    if conn is None:
        print(json.dumps({"db": str(path), "exists": False}))
        return 0
    try:
        out = {"db": str(path), "exists": True, **report.status(conn)}
    finally:
        conn.close()
    print(json.dumps(out))
    return 0


def _since(days: int | None) -> float | None:
    return time.time() - days * 86400 if days else None


def cmd_summary(args: argparse.Namespace) -> int:
    conn = _open_readonly()
    if conn is None:
        print(json.dumps({"totals": None}))
        return 0
    try:
        out = report.summary(conn, repo_root=args.root, since=_since(args.days), branch=args.branch)
    finally:
        conn.close()
    print(json.dumps(out))
    return 0


def cmd_sessions(args: argparse.Namespace) -> int:
    conn = _open_readonly()
    if conn is None:
        print(json.dumps({"sessions": []}))
        return 0
    try:
        rows = report.sessions(conn, repo_root=args.root, since=_since(args.days), limit=args.limit,
                               branch=args.branch)
    finally:
        conn.close()
    print(json.dumps({"sessions": rows}))
    return 0


def cmd_session(args: argparse.Namespace) -> int:
    conn = _open_readonly()
    if conn is None:
        print(f"chronicle: no store at {store.db_path()}", file=sys.stderr)
        return 1
    try:
        detail = report.session_detail(conn, args.session_id)
    finally:
        conn.close()
    if detail is None:
        print(f"chronicle: no session {args.session_id}", file=sys.stderr)
        return 1
    print(json.dumps(detail))
    return 0


def cmd_repos(_: argparse.Namespace) -> int:
    conn = _open_readonly()
    if conn is None:
        print(json.dumps({"repos": []}))
        return 0
    try:
        rows = report.repos(conn)
    finally:
        conn.close()
    print(json.dumps({"repos": rows}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chronicle", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ingest", help="ingest one transcript (and its subagents) now")
    p.add_argument("--transcript", required=True)
    p.add_argument("--session-id", default=None)
    p.set_defaults(fn=cmd_ingest)

    for verb, help_text in (
        ("sync", "pull-on-demand: ingest every transcript whose file moved since last seen"),
        ("backfill", "alias of sync (a first run over an empty store)"),
    ):
        p = sub.add_parser(verb, help=help_text)
        p.add_argument("--projects", action="append", default=None,
                       help="a projects/ dir to scan (repeatable); default: every watched "
                            "config dir's — see `overseer claude-dirs`")
        p.add_argument("--full", action="store_true",
                       help="forget every cursor and re-read all transcripts (after a schema change)")
        p.set_defaults(fn=cmd_sync)

    sub.add_parser("status", help="store location and row counts (JSON)").set_defaults(fn=cmd_status)

    p = sub.add_parser("summary", help="aggregate metrics (JSON)")
    p.add_argument("--root", default=None, help="scope to one main repo root")
    p.add_argument("--days", type=int, default=None, help="only sessions active in the last N days")
    p.add_argument("--branch", default=None,
                   help="only sessions whose last-seen git branch matches (session-level)")
    p.set_defaults(fn=cmd_summary)

    p = sub.add_parser("sessions", help="session rows, most recent first (JSON)")
    p.add_argument("--root", default=None)
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--branch", default=None)
    p.add_argument("--limit", type=int, default=200)
    p.set_defaults(fn=cmd_sessions)

    p = sub.add_parser("session", help="one session in detail, with its turn series (JSON)")
    p.add_argument("session_id")
    p.set_defaults(fn=cmd_session)

    sub.add_parser("repos", help="repo roots seen, with session counts (JSON)").set_defaults(fn=cmd_repos)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
