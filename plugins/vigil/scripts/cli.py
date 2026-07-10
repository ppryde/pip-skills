"""Vigil CLI — measure context and hand over. Pure stdlib."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct invocation: put plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import context as ctx  # noqa: E402
from scripts import state as st  # noqa: E402
from scripts.config import (  # noqa: E402
    ConfigError,
    get_config,
    load_config,
    set_config,
)
from typing import cast  # noqa: E402


def cmd_begin(args: argparse.Namespace) -> int:
    st.begin(args.root)
    mode = str(load_config(args.root)["context.mode"])
    auto = "auto" if os.environ.get("TMUX") else "manual"
    hint = (
        "the Stop hook will send /clear unattended"
        if auto == "auto"
        else "no tmux — checkpoint and ask the user to type /clear"
    )
    print(f"vigil active ({auto}, {mode} run mode) — {hint}")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    cfg = load_config(args.root)
    transcript = ctx.find_transcript(args.root.resolve(), Path.home())
    tokens = ctx.context_tokens(transcript) if transcript else None
    pct = (
        ctx.context_percent(tokens, cast(int, cfg["context.window"]))
        if tokens is not None
        else None
    )
    print(ctx.context_line(pct, cast(int, cfg["context.threshold"])))
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    if args.action == "get":
        print(get_config(args.root, args.key))
        return 0
    set_config(args.root, args.key, args.value)
    print(f"{args.key} = {get_config(args.root, args.key)}")
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    st.pause(args.root)
    print("auto-handover paused")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    st.resume(args.root)
    print("auto-handover resumed")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vigil", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("begin").set_defaults(func=cmd_begin)
    sub.add_parser("context").set_defaults(func=cmd_context)
    sub.add_parser("pause").set_defaults(func=cmd_pause)
    sub.add_parser("resume").set_defaults(func=cmd_resume)

    p = sub.add_parser("config")
    csub = p.add_subparsers(dest="action", required=True)
    cget = csub.add_parser("get")
    cget.add_argument("key")
    cset = csub.add_parser("set")
    cset.add_argument("key")
    cset.add_argument("value")
    p.set_defaults(func=cmd_config)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 0 if not exc.code else 1
    try:
        result: int = args.func(args)
        return result
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
