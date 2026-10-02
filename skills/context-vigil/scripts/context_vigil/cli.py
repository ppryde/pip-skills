"""context-vigil CLI. Every command prints one short human line; errors go to
stderr with a non-zero exit. ``hook`` subcommands never fail (see hooks.py)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from context_vigil import config


class CliError(Exception):
    """A user-facing error: printed as-is to stderr, exit 1."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="context-vigil",
        description="context-vigil — watch context %, hand over, /clear, resume.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    hook = sub.add_parser("hook", help="hook entrypoint (used by settings.json)")
    hook.add_argument("name")
    hook.set_defaults(func=_cmd_hook)
    cp = sub.add_parser("config", help="get or set a setting")
    csub = cp.add_subparsers(dest="action", required=True)
    cget = csub.add_parser("get")
    cget.add_argument("key")
    cset = csub.add_parser("set")
    cset.add_argument("key")
    cset.add_argument("value")
    cset.add_argument("--worktree", action="store_true",
                      help="set for this worktree only")
    cget.set_defaults(func=_cmd_config, worktree=False)
    cset.set_defaults(func=_cmd_config)
    return parser


def _cmd_config(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    try:
        if args.action == "set":
            config.set_value(cwd, args.key, args.value, worktree=args.worktree)
        if args.key not in config.DEFAULTS:
            raise config.ConfigError(
                f"unknown key {args.key!r}; known: {', '.join(config.KEYS)}"
            )
    except config.ConfigError as exc:
        raise CliError(str(exc)) from exc
    value, layer = config.resolve(cwd)[args.key]
    print(f"{args.key} = {value} ({layer})")
    return 0


def _cmd_hook(args: argparse.Namespace) -> int:
    return 0  # replaced in Task 7


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result: int = args.func(args)
        return result
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
