"""concordance CLI. Run as `python <plugin>/scripts/cli.py <command>` from inside a worktree."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # direct invocation: put the plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import extract_ts, gitio
from scripts.commands import common, queries, records
from scripts.index import LockTimeout

DEFAULT_BUDGET = 1500
REVIEW_BUDGET = 4000  # provisional: tune from the usage log (render stats + diff size)
DEFAULT_DEADLINE = 60.0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="concordance", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str, diff: bool = True, name_arg: bool = False) -> None:
        sp = sub.add_parser(name, help=help_text)
        if name_arg:
            sp.add_argument("name")
        if diff:
            sp.add_argument("--base", default=None,
                            help="base ref (default: merge-base with the default branch)")
        sp.add_argument("--budget", type=int,
                        default=REVIEW_BUDGET if name == "review-context" else DEFAULT_BUDGET)
        sp.add_argument("--deadline", type=float, default=DEFAULT_DEADLINE)

    add("index", "build or refresh this worktree's view (and the base view)")
    add("review-context", "everything a reviewer needs for this diff, within a budget")
    add("removed", "references to what the diff removed")
    add("sig-drift", "call sites that no longer match a changed signature")
    add("literals", "changed literals, reordered statements, removed comments")
    add("touched", "touched symbols, callers of changed behaviour, guarding tests")
    add("check", "verdicts only (BR-002, BR-005); exit 1 when any")
    add("callers", "who calls NAME", diff=False, name_arg=True)
    add("tests", "tests that reach NAME within --hops", diff=False, name_arg=True)
    sub.choices["tests"].add_argument("--hops", type=int, default=2)
    add("coverage", "files indexed, failed and skipped in this worktree's view", diff=False)
    sub.add_parser("setup-ts", help="install the pinned TypeScript parser (npm ci)")
    rr = sub.add_parser("record-review", help="record a finished review's findings (usage log)")
    rr.add_argument("--findings", type=int, required=True)
    rr.add_argument("--via-index", type=int, required=True)
    rr.add_argument("--steps", default="", help="findings per procedure step, e.g. 1:2,3:1")
    st = sub.add_parser("stats", help="usage and effectiveness report from the usage log")
    st.add_argument("--days", type=int, default=30)
    st.add_argument("--repo", choices=("this", "all"), default="all")
    st.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    common.utf8_streams()
    args = _parser().parse_args(argv)
    if args.command == "setup-ts":
        return extract_ts.setup()
    cwd = Path.cwd()
    if args.command == "record-review":
        return records.record_review(args, cwd)
    if args.command == "stats":
        return records.stats(args, cwd)
    started = time.monotonic()
    stats: dict[str, object] = {}
    facts: dict[str, object] = {}
    try:
        if args.command in ("callers", "tests", "coverage"):
            text, code, view_id = queries.name_command(args, cwd, stats, facts)
        else:
            text, code, view_id = queries.diff_command(args, cwd, stats, facts)
    except (gitio.GitError, LockTimeout) as exc:
        print(f"concordance: {exc}", file=sys.stderr)
        common.log_event(args.command, cwd, None, started, "", 2, {"error": type(exc).__name__})
        return 2
    except Exception as exc:  # noqa: BLE001 - internal error: exit 2, never a bare traceback
        print(f"concordance: internal error: {exc!r}", file=sys.stderr)
        common.log_event(args.command, cwd, None, started, "", 2, {"error": type(exc).__name__})
        return 2
    common.say(text)
    common.log_event(args.command, cwd, view_id, started, text, code, stats)
    return code


if __name__ == "__main__":
    sys.exit(main())
