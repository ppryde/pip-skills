"""chronicle CLI — hook entry points plus read/report verbs.

Hook verbs (``session-start-hook``, ``stop-hook``, ``session-end-hook``) read
the Claude Code hook payload from stdin and ALWAYS exit 0 with no stdout: a
hook that fails or prints must never disturb the session it observes.

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


def _payload() -> dict[str, Any]:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _hook(fn: Any) -> int:
    """Run a hook body under quarantine: any exception -> silent exit 0."""
    try:
        fn()
    except Exception:  # noqa: BLE001 — hooks must never surface an error
        return 0
    return 0


def cmd_session_start_hook(_: argparse.Namespace) -> int:
    payload = _payload()

    def body() -> None:
        sid = _str(payload, "session_id")
        if not sid:
            return
        conn = store.connect()
        try:
            ingest.mark_started(
                conn, sid, cwd=_str(payload, "cwd"),
                transcript_path=_str(payload, "transcript_path"),
            )
            transcript = _str(payload, "transcript_path")
            # A resume/clear restart already has history on disk — fold it in.
            if transcript and Path(transcript).is_file():
                ingest.ingest_session(conn, Path(transcript), sid)
        finally:
            conn.close()

    return _hook(body)


def cmd_stop_hook(_: argparse.Namespace) -> int:
    payload = _payload()

    def body() -> None:
        sid = _str(payload, "session_id")
        transcript = _str(payload, "transcript_path")
        if not sid or not transcript:
            return
        path = Path(transcript)
        if not path.is_file():
            return
        conn = store.connect()
        try:
            ingest.ingest_session(conn, path, sid)
        finally:
            conn.close()

    return _hook(body)


def cmd_session_end_hook(_: argparse.Namespace) -> int:
    payload = _payload()

    def body() -> None:
        sid = _str(payload, "session_id")
        if not sid:
            return
        conn = store.connect()
        try:
            transcript = _str(payload, "transcript_path")
            if transcript and Path(transcript).is_file():
                ingest.ingest_session(conn, Path(transcript), sid)
            ingest.mark_ended(conn, sid, reason=_str(payload, "reason"))
        finally:
            conn.close()

    return _hook(body)


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
    """Reconcile the store with the transcripts on disk (see ``ingest.sync``)."""
    projects = Path(args.projects) if args.projects else store.projects_dir()
    conn = store.connect()
    try:
        result = ingest.sync(conn, projects, full=bool(getattr(args, "full", False)))
    finally:
        conn.close()
    out: dict[str, Any] = {**result, "projects_dir": str(projects), "db": str(store.db_path())}
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
        out = report.summary(conn, repo_root=args.root, since=_since(args.days))
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
        rows = report.sessions(conn, repo_root=args.root, since=_since(args.days), limit=args.limit)
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

    sub.add_parser("session-start-hook").set_defaults(fn=cmd_session_start_hook)
    sub.add_parser("stop-hook").set_defaults(fn=cmd_stop_hook)
    sub.add_parser("session-end-hook").set_defaults(fn=cmd_session_end_hook)

    p = sub.add_parser("ingest", help="ingest one transcript (and its subagents) now")
    p.add_argument("--transcript", required=True)
    p.add_argument("--session-id", default=None)
    p.set_defaults(fn=cmd_ingest)

    for verb, help_text in (
        ("sync", "pull-on-demand: ingest every transcript whose file moved since last seen"),
        ("backfill", "alias of sync (a first run over an empty store)"),
    ):
        p = sub.add_parser(verb, help=help_text)
        p.add_argument("--projects", default=None, help="override $CLAUDE_CONFIG_DIR/projects")
        p.add_argument("--full", action="store_true",
                       help="forget every cursor and re-read all transcripts (after a schema change)")
        p.set_defaults(fn=cmd_sync)

    sub.add_parser("status", help="store location and row counts (JSON)").set_defaults(fn=cmd_status)

    p = sub.add_parser("summary", help="aggregate metrics (JSON)")
    p.add_argument("--root", default=None, help="scope to one main repo root")
    p.add_argument("--days", type=int, default=None, help="only sessions active in the last N days")
    p.set_defaults(fn=cmd_summary)

    p = sub.add_parser("sessions", help="session rows, most recent first (JSON)")
    p.add_argument("--root", default=None)
    p.add_argument("--days", type=int, default=None)
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
