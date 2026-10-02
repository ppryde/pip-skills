"""context-vigil CLI. Every command prints one short human line; errors go to
stderr with a non-zero exit. ``hook`` subcommands never fail (see hooks.py)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from context_vigil import census, config, context, handover, hooks, paths, state, tmux


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
    hp = sub.add_parser("handover", help="validate notes, save the handover, arm /clear")
    hmode = hp.add_mutually_exclusive_group(required=True)
    hmode.add_argument("--file", help="notes following templates/handover.md")
    hmode.add_argument("--resume", action="store_true", help="load a waiting handover")
    hmode.add_argument("--discard", action="store_true", help="archive a waiting handover unread")
    hp.add_argument("--inline", action="append", default=[], help="embed a file (remote mode)")
    hp.add_argument("--no-snapshot", action="store_true")
    hp.set_defaults(func=_cmd_handover)
    sub.add_parser("ingest", help="record a status-line payload from stdin").set_defaults(
        func=_cmd_ingest)
    ctxp = sub.add_parser("context", help="print ctx NN%% for this session")
    ctxp.add_argument("--session-id", default=None)
    ctxp.set_defaults(func=_cmd_context)
    sub.add_parser("pause", help="stop nudges/auto-clear in this worktree").set_defaults(
        func=_cmd_pause)
    sub.add_parser("resume", help="re-enable this worktree").set_defaults(func=_cmd_resume)
    sub.add_parser("status", help="show install, mode and settings").set_defaults(
        func=_cmd_status)
    return parser


def _cmd_handover(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    scope = paths.scope_dir(cwd)
    if args.resume or args.discard:
        text = state.consume_handoff(scope)
        if text is None:
            raise CliError("no handover is waiting here")
        print(f"{handover.RESUME_PREAMBLE}\n\n{text}" if args.resume
              else "handover discarded (kept in the archive)")
        return 0
    try:
        notes = Path(args.file).read_text()
    except OSError as exc:
        raise CliError(f"--file unreadable: {exc}") from exc
    try:
        document = handover.assemble(
            notes, cwd, [Path(p) for p in args.inline], include_snapshot=not args.no_snapshot)
    except handover.HandoverError as exc:
        raise CliError(f"handover refused: {exc}") from exc
    result = state.request_clear(paths.scope_dir(cwd), document)
    if result == "paused":
        raise CliError("handover refused: paused here (`context-vigil resume` to re-enable)")
    if result == "cooldown":
        raise CliError("handover refused: a /clear just happened — cooldown active")
    if tmux.reachable():
        print("handover saved — /clear will be sent at the end of this turn")
    else:
        print("handover saved — type /clear to continue in a fresh context")
    return 0


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


def _cmd_ingest(args: argparse.Namespace) -> int:
    census.ingest(sys.stdin.read())
    return 0


def _cmd_context(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    pct = context.current_percent(cwd, args.session_id, None, config.window(cwd))
    print(context.context_line(pct, config.threshold(cwd)))
    return 0


def _cmd_pause(args: argparse.Namespace) -> int:
    state.pause(paths.scope_dir(Path.cwd()))
    print("context-vigil paused here — no nudges or auto-clear until `resume`")
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    state.resume(paths.scope_dir(Path.cwd()))
    print("context-vigil resumed here")
    return 0


def _mode_line() -> str:
    if tmux.reachable():
        return "mode: auto (inside tmux — /clear is sent for you)"
    if tmux.installed():
        return "mode: manual (not inside tmux — launch with claude-tmux for auto)"
    return "mode: manual (tmux not installed — you type /clear after a handover)"


def _cmd_status(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    scope = paths.scope_dir(cwd)
    record = paths.install_record_path()
    resolved = config.resolve(cwd)
    threshold, layer = resolved["context.threshold"]
    lines = [
        f"installed: {'yes' if record.exists() else 'no'}",
        _mode_line(),
        f"threshold: {threshold}% ({layer})",
        f"context.mode: {resolved['context.mode'][0]} ({resolved['context.mode'][1]})",
        f"paused here: {'yes' if state.is_paused(scope) else 'no'}",
        f"nudge gate: {'armed' if state.gate_active(scope) else 'clear'}",
        f"pending handover: {'yes' if state.read_handoff(scope) else 'no'}",
        f"data: {paths.data_root()}",
    ]
    print("\n".join(lines))
    return 0


def _cmd_hook(args: argparse.Namespace) -> int:
    out = hooks.run(args.name, sys.stdin.read())
    if out:
        print(out)
    return 0


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
