"""almoner CLI — gather configured sources into one digest, read-only.

Every verb prints one JSON object to stdout for the overseer dashboard. Pull
only: no hooks, no schedule — refresh is a person pressing Gather. The CLI
fetches and pre-filters; ranking is a separate judging skill, so with no skill
behind it the digest is unranked newest-first but still usable.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

# Allow `python plugins/almoner/scripts/cli.py` from anywhere.
_PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from scripts import config, gather, paths, store

# Tests swap these; production uses the adapter registry and the wall clock.
_REGISTRY: dict[tuple[str, str], gather.AdapterFactory] | None = None


def _now() -> float:
    return time.time()


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload))


def _fail(message: str) -> int:
    print(f"almoner: {message}", file=sys.stderr)
    return 2


def _sources() -> list[config.Source] | None:
    try:
        return config.load_sources()
    except config.ConfigError as exc:
        _fail(str(exc))
        return None


def cmd_status(_: argparse.Namespace) -> int:
    sources = _sources()
    if sources is None:
        return 2
    # Read-only, and only opened if the store already exists: `status` must
    # never create work-content storage just by being asked. An absent store
    # is not an error here — every watermark simply reads as None.
    try:
        conn: sqlite3.Connection | None = store.connect_readonly()
    except FileNotFoundError:
        conn = None
    try:
        rows = []
        for s in sources:
            has_secret = config.read_secret(s.label) is not None
            watermark = store.get_watermark(conn, s.label) if conn is not None else None
            row = gather.SourceReport(s.label, s.type, s.via, s.context, has_secret,
                                      None if has_secret else "no credentials",
                                      watermark).to_json()
            if has_secret and not config.secret_is_private(s.label):
                row["warnings"] = [*row.get("warnings", []), "secret file is readable by others"]
            rows.append(row)
    finally:
        if conn is not None:
            conn.close()
    _emit({"config": str(paths.config_path()), "db": str(paths.db_path()), "sources": rows})
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    sources = _sources()
    if sources is None:
        return 2
    read_source: str | None = None
    if args.source is not None:
        chosen = [s for s in sources if s.label == args.source]
        if not chosen:
            return _fail(f"no configured source labelled '{args.source}'")
        sources, read_source = chosen, chosen[0].type
    if args.context is not None:
        sources = [s for s in sources if s.context == args.context]
    now = _now()
    conn = store.connect()
    try:
        outcome = gather.gather_and_store(conn, sources, hours=args.hours, now=now,
                                          registry=_REGISTRY)
        items = store.read_digest(conn, days=args.days, now=now, context=args.context,
                                  source=read_source, new_only=args.new)
    finally:
        conn.close()
    _emit({"items": items, "sources": [r.to_json() for r in outcome.reports],
           "fetched_at": now, "ranked": False, "suppressed": outcome.suppressed,
           "days": args.days})
    return 0


def _set_state(item_id: str, state: str) -> int:
    conn = store.connect()
    try:
        known = store.set_state(conn, item_id, state, _now())
    finally:
        conn.close()
    if not known:
        _emit({"id": item_id, "error": "unknown id"})
        return 1
    _emit({"id": item_id, "state": state})
    return 0


def cmd_dismiss(args: argparse.Namespace) -> int:
    return _set_state(args.id, "dismissed")


def cmd_ack(args: argparse.Namespace) -> int:
    return _set_state(args.id, "acted")


def cmd_log(args: argparse.Namespace) -> int:
    conn = store.connect()
    try:
        payload = (store.log_runs(conn, args.limit) if args.runs
                   else store.log_suppressed(conn, args.limit))
    finally:
        conn.close()
    _emit(payload)
    return 0


def _hours(value: str) -> int:
    hours = int(value)
    if not 1 <= hours <= 24 * 30:
        raise argparse.ArgumentTypeError("hours must be between 1 and 720")
    return hours


def _ident(value: str) -> str:
    if not config.IDENT_RE.match(value):
        raise argparse.ArgumentTypeError("must be a plain identifier")
    return value


def _limit(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("limit must be >= 1")
    return n


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="almoner")
    sub = parser.add_subparsers(dest="verb", required=True)

    sub.add_parser("status", help="sources, credentials, last fetch").set_defaults(fn=cmd_status)

    digest = sub.add_parser("digest", help="gather every source, then read the digest back")
    digest.add_argument("--json", action="store_true",
                        help="accepted for the spec; output is always JSON")
    digest.add_argument("--source", type=_ident, help="one source, by label")
    digest.add_argument("--context", type=_ident, help="one context")
    digest.add_argument("--hours", type=_hours, default=48,
                        help="how far back to FETCH (default 48)")
    digest.add_argument("--days", type=int, choices=(7, 14, 30), default=14,
                        help="how far back to READ from the store (default 14)")
    digest.add_argument("--new", action="store_true", help="only rows not shown before")
    digest.set_defaults(fn=cmd_digest)

    for verb, fn, what in (("dismiss", cmd_dismiss, "hide until it changes — local only"),
                           ("ack", cmd_ack, "mark actioned — local only")):
        p = sub.add_parser(verb, help=what)
        p.add_argument("id")
        p.set_defaults(fn=fn)

    log = sub.add_parser("log", help="refresh history, or what was filtered")
    which = log.add_mutually_exclusive_group(required=True)
    which.add_argument("--runs", action="store_true")
    which.add_argument("--suppressed", action="store_true")
    log.add_argument("--limit", type=_limit, default=50)
    log.set_defaults(fn=cmd_log)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
