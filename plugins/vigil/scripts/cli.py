"""Vigil CLI — measure context and hand over. Pure stdlib."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct invocation: put plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import census  # noqa: E402
from scripts import context as ctx  # noqa: E402
from scripts import snapshot as snap  # noqa: E402
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


def _current_context_percent(root: Path, cfg: dict[str, object]) -> int | None:
    # census first: worktree-correct and windowed against the session's real
    # context size. Falls back to transcript-slug measurement when census has no
    # live entry (not installed, no status line, or stale) — preserving the old
    # behaviour rather than regressing to "ctx unknown".
    pct = census.context_percent(root)
    if pct is None:
        transcript = ctx.find_transcript(root.resolve(), Path.home())
        tokens = ctx.context_tokens(transcript) if transcript else None
        pct = (
            ctx.context_percent(tokens, cast(int, cfg["context.window"]))
            if tokens is not None
            else None
        )
    return pct


def cmd_context(args: argparse.Namespace) -> int:
    cfg = load_config(args.root)
    pct = _current_context_percent(args.root, cfg)
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


def _assemble_handover(args: argparse.Namespace) -> str | None:
    parts: list[str] = []
    if not args.no_snapshot:
        parts.append(snap.session_snapshot(args.root.resolve()))
    if args.content_file:
        if args.content_file == "-":
            raw = sys.stdin.read()
        else:
            try:
                raw = Path(args.content_file).read_text()
            except OSError as exc:
                raise ValueError(f"--content-file unreadable: {exc}") from exc
        if raw.strip():
            parts.append(raw.strip())
    for inline_path in args.inline or []:
        try:
            raw = Path(inline_path).read_text()
        except OSError as exc:
            raise ValueError(f"--inline unreadable: {inline_path}: {exc}") from exc
        if raw.strip():
            parts.append(f"## Inlined: `{inline_path}`\n\n```\n{raw.strip()}\n```")
    if args.notes:
        parts.append(f"## Notes\n\n{args.notes.strip()}")
    document = "\n\n".join(p.strip() for p in parts if p.strip())
    return document or None


def cmd_handover(args: argparse.Namespace) -> int:
    document = _assemble_handover(args)
    if document is None:
        print("handover refused: nothing to hand over "
              "(pass --notes/--content-file, or drop --no-snapshot)", file=sys.stderr)
        return 1
    result = st.request_clear(args.root, document)
    if result == "armed":
        if os.environ.get("TMUX"):
            print("handover armed — auto (/clear via tmux at end of turn)")
        else:
            print("handover armed — manual (no tmux): type /clear to complete")
        return 0
    reason = {
        "inactive": "not watching here — run `vigil begin` first",
        "paused": "auto-handover is paused (`vigil resume` to re-enable)",
        "cooldown": "just cleared — cooldown active, nothing to do",
    }[result]
    print(f"handover refused: {reason}", file=sys.stderr)
    return 1


def _hook_root(args: argparse.Namespace) -> Path:
    try:
        payload = json.loads(sys.stdin.read())
        cwd = payload.get("cwd") if isinstance(payload, dict) else None
    except (ValueError, OSError):
        cwd = None
    return Path(cwd) if cwd else args.root


def cmd_stop_hook(args: argparse.Namespace) -> int:
    if st.consume_clear_flag(_hook_root(args)):
        print("DISPATCH_CLEAR")
    return 0


def cmd_clear_armed_hook(args: argparse.Namespace) -> int:
    """Read-only Stop-hook helper: is a handover currently armed?

    Unlike ``stop-hook``, this never consumes ``clear-requested`` — the manual
    (no-tmux) path needs to know whether to print the loud instruction line
    without eating the flag the human's own /clear (and the SessionStart that
    follows it) still depends on.
    """
    if st.clear_requested(_hook_root(args)):
        print("ARMED")
    return 0


def cmd_session_start_hook(args: argparse.Namespace) -> int:
    root = _hook_root(args)
    if st.is_active(root):
        handoff = st.consume_handoff(root)
        if handoff:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": handoff,
                }
            }))
            # Completion = the handover actually landed in this fresh session —
            # not merely "clear was requested" — so the gate only clears here.
            st.clear_gate(root)
        st.arm_ready(root)
    return 0


_NUDGE_BODY = (
    "**vigil: context at {pct}% — over the {threshold}% threshold.** "
    "At your next reasonable stopping point:\n"
    "(1) wait for running subagents to finish, or ask them to stop and confirm;\n"
    "(2) judge whether this is a sane place to pause — if mid-critical-step, "
    "finish that step first;\n"
    "(3) write a rich handover (what you were doing, what's next, gotchas) and run "
    "`vigil handover --content-file <doc>` / `--notes`. The clear will dispatch "
    "automatically (or you'll be told to ask the user to type /clear)."
)

_NUDGE_REMOTE_SUFFIX = (
    "\n\nThis session is remote — the next session cannot open referenced file "
    "paths. Inline what it must read into the handover body with repeatable "
    "`vigil handover --inline <path>` rather than leaving it as a reference."
)


def _nudge_text(pct: int, threshold: int, mode: str) -> str:
    text = _NUDGE_BODY.format(pct=pct, threshold=threshold)
    if mode == "remote":
        text += _NUDGE_REMOTE_SUFFIX
    return text


def cmd_nudge_hook(args: argparse.Namespace) -> int:
    """UserPromptSubmit hook backend: nudge once per over-threshold cycle.

    All preconditions must hold: active, not paused, no cooldown, no live
    handover-gate, and a known ctx% at/over the configured threshold. Never
    raises — every check composes already quarantine-safe primitives.
    """
    root = _hook_root(args)
    if not st.is_active(root):
        return 0
    if st.is_paused(root):
        return 0
    if st.cooldown_active(root):
        return 0
    if st.gate_active(root):
        return 0
    cfg = load_config(root)
    threshold = cast(int, cfg["context.threshold"])
    pct = _current_context_percent(root, cfg)
    if pct is None or pct < threshold:
        return 0
    st.set_gate(root)
    mode = str(cfg["context.mode"])
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": _nudge_text(pct, threshold, mode),
        }
    }))
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

    p = sub.add_parser("handover")
    p.add_argument("--notes")
    p.add_argument("--content-file", dest="content_file")
    p.add_argument("--no-snapshot", dest="no_snapshot", action="store_true")
    p.add_argument("--inline", dest="inline", action="append", default=[])
    p.set_defaults(func=cmd_handover)

    sub.add_parser("stop-hook").set_defaults(func=cmd_stop_hook)
    sub.add_parser("clear-armed-hook").set_defaults(func=cmd_clear_armed_hook)
    sub.add_parser("session-start-hook").set_defaults(func=cmd_session_start_hook)
    sub.add_parser("nudge-hook").set_defaults(func=cmd_nudge_hook)

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
    except ValueError as exc:
        print(f"handover refused: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
