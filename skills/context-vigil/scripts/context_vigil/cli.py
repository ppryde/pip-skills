"""context-vigil CLI. Every command prints one short human line; errors go to
stderr with a non-zero exit. ``hook`` subcommands never fail (see hooks.py)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from context_vigil import (
    census,
    config,
    context,
    handover,
    hooks,
    install,
    launcher,
    paths,
    session,
    state,
    tmux,
)

_LAUNCH_CHOICES = ("on-demand", "always", "not-now")


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
    sub.add_parser("pause", help="stop nudges/auto-clear for this session").set_defaults(
        func=_cmd_pause)
    sub.add_parser("resume", help="re-enable nudges/auto-clear for this session").set_defaults(
        func=_cmd_resume)
    sub.add_parser("status", help="show install, mode and settings").set_defaults(
        func=_cmd_status)
    ip = sub.add_parser("install", help="wire hooks + status line (dry run without --yes)")
    ip.add_argument("--yes", action="store_true")
    ip.add_argument("--threshold", type=int, default=None)
    ip.add_argument("--launcher", choices=_LAUNCH_CHOICES, default=None)
    ip.add_argument("--confirm-always", action="store_true")
    ip.set_defaults(func=_cmd_install)
    lp = sub.add_parser("launcher", help="choose how Claude launches (tmux)")
    lp.add_argument("choice", nargs="?", choices=launcher.CHOICES)
    lp.add_argument("--yes", action="store_true")
    lp.add_argument("--confirm-always", action="store_true")
    lp.set_defaults(func=_cmd_launcher)
    up = sub.add_parser("uninstall", help="remove exactly what install added")
    up.add_argument("--yes", action="store_true")
    up.set_defaults(func=_cmd_uninstall)
    return parser


def _cmd_handover(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    scope = _scope(cwd)
    kept = session.handoff_scope(cwd, _env_session_id())
    if args.resume or args.discard:
        text = state.consume_handoff(kept)
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
            notes, cwd, [Path(p) for p in args.inline], include_snapshot=not args.no_snapshot,
            max_tokens=config.handover_max_tokens(cwd))
    except handover.HandoverError as exc:
        raise CliError(f"handover refused: {exc}") from exc
    headless = session.is_headless(_env_session_id())
    if headless:
        # no /clear is sent to a headless run: leave the handoff where the next run looks
        if state.is_paused(scope):
            raise CliError("handover refused: paused here (`context-vigil resume` to re-enable)")
        state.write_handoff(kept, document)
        print(f"handover saved to {state.handoff_path(kept)} — the next headless run in this "
              "worktree can `handover --resume` it")
        return 0
    result = state.request_clear(scope, document)
    if result == "paused":
        raise CliError("handover refused: paused here (`context-vigil resume` to re-enable)")
    if tmux.reachable():
        print("handover saved — /clear will be sent at the end of this turn")
    else:
        print("handover saved — type /clear, then send any message (e.g. \"go\") "
              "to start the resumed turn")
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


def _env_session_id() -> Optional[str]:
    return os.environ.get("CLAUDE_SESSION_ID") or None


def _scope(cwd: Path) -> Path:
    """Same scope the hooks resolve for this session (headless children get their own)."""
    return session.scope(cwd, _env_session_id())


def _cmd_context(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    reading = context.current_reading(
        cwd, args.session_id or _env_session_id(), None, config.window(cwd))
    print(context.context_line(reading.pct, config.threshold(cwd), reading.confident))
    return 0


def _cmd_pause(args: argparse.Namespace) -> int:
    state.pause(_scope(Path.cwd()))
    print("context-vigil paused here — no nudges or auto-clear until `resume`")
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    state.resume(_scope(Path.cwd()))
    print("context-vigil resumed here")
    return 0


def _mode_line() -> str:
    if session.is_headless(_env_session_id()):
        return ("mode: headless (no /clear is sent; `handover --file` saves it "
                "for the next run to `--resume`)")
    if tmux.reachable():
        return "mode: auto (inside tmux — /clear is sent for you)"
    if tmux.installed():
        return "mode: manual (not inside tmux — launch with claude-tmux for auto)"
    return "mode: manual (tmux not installed — you type /clear after a handover)"


def _cmd_status(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    scope = _scope(cwd)
    record = paths.install_record_path()
    resolved = config.resolve(cwd)
    threshold, layer = resolved["context.threshold"]
    reading = context.current_reading(cwd, _env_session_id(), None, config.window(cwd))
    pending = state.read_handoff(session.handoff_scope(cwd, _env_session_id()))
    lines = [
        f"installed: {'yes' if record.exists() else 'no'}",
        _mode_line(),
        f"{context.context_line(reading.pct, int(str(threshold)), reading.confident)}",
        f"threshold: {threshold}% ({layer})",
        f"window: {resolved['context.window'][0]} ({resolved['context.window'][1]})",
        f"context.mode: {resolved['context.mode'][0]} ({resolved['context.mode'][1]})",
        f"nudge.repeat_step: {resolved['nudge.repeat_step'][0]}% "
        f"({resolved['nudge.repeat_step'][1]})",
        f"handover.max_tokens: {resolved['handover.max_tokens'][0]} "
        f"({resolved['handover.max_tokens'][1]})",
        f"handover.cooldown_seconds: {resolved['handover.cooldown_seconds'][0]} "
        f"({resolved['handover.cooldown_seconds'][1]})",
        f"paused here: {'yes' if state.is_paused(scope) else 'no'}",
        f"nudge gate: {'armed' if state.gate_active(scope) else 'clear'}",
        f"pending handover: {'yes' if pending else 'no'}",
        f"data: {paths.data_root()}",
    ]
    print("\n".join(lines))
    return 0


def _cmd_install(args: argparse.Namespace) -> int:
    try:
        plan = install.plan_install(args.threshold, args.launcher)
    except (install.InstallError, config.ConfigError, OSError, UnicodeError) as exc:
        raise CliError(str(exc)) from exc
    diffs = [c.diff() for c in plan.changes if c.before != c.after]
    if not args.yes:
        print("context-vigil install — DRY RUN, nothing changed yet.\n")
        print("\n".join(diffs) if diffs else "Hooks and status line already wired.")
        for line in plan.manual:
            print(f"\nMANUAL STEP: {line}")
        for line in plan.notes:
            print(f"\n{line}")
        current = args.threshold if args.threshold is not None else config.threshold(Path.cwd())
        verb = "will be set" if args.threshold is not None else "current"
        print(f"\nThreshold ({verb}): nudge at {current}% context (default 35). Lower hands over "
              "sooner with a leaner context; higher means fewer handovers but more "
              "degradation before each.")
        print("\n" + launcher.walkthrough_text())
        print(f"\nIf choosing Always, confirm: {launcher.ALWAYS_CONFIRM}")
        print("\nApply with:  context-vigil install --yes [--threshold N] "
              "[--launcher on-demand|always|not-now]")
        return 0
    if args.launcher == "always" and not args.confirm_always:
        raise CliError("--launcher always also needs --confirm-always "
                       "(it takes over the claude command)")
    # Show what is about to change BEFORE changing it, so the record of the
    # edit (the rc file included) is on screen even if apply fails part-way.
    print("\n".join(diffs) if diffs else "Hooks and status line already wired.")
    for line in plan.manual:
        print(f"\nMANUAL STEP: {line}")
    for line in plan.notes:
        print(f"\n{line}")
    sys.stdout.flush()
    try:
        install.apply(plan)
    except OSError as exc:
        raise CliError(f"install failed part-way ({exc}); re-run, or `uninstall --yes`") from exc
    print(f"\ncontext-vigil installed. {_mode_line()}. "
          "Hooks and the status line take effect in new sessions.")
    return 0


def _record_launcher(choice: str, rc: Path) -> None:
    """Keep an existing install.json in step; never create one from `launcher` alone."""
    record_path = paths.install_record_path()
    try:
        record = json.loads(record_path.read_text())
    except (OSError, ValueError):
        return
    if not isinstance(record, dict):
        return
    record["launcher"] = choice
    record["rc_path"] = str(rc)
    install.write_atomic(record_path, json.dumps(record, indent=2) + "\n")


def _cmd_launcher(args: argparse.Namespace) -> int:
    if args.choice is None:
        print(launcher.walkthrough_text())
        return 0
    if args.choice == "always" and args.yes and not args.confirm_always:
        raise CliError("`always` takes over the claude command — re-run with --confirm-always")
    try:
        change = launcher.plan_rc(args.choice)
    except (install.InstallError, OSError, UnicodeError) as exc:
        raise CliError(str(exc)) from exc
    if change is None:
        line = launcher.alias_line(args.choice)
        print(f"Unknown shell — add this to your shell rc yourself:\n  {line}" if line
              else "Nothing to change.")
        return 0
    print(change.diff() or "Already set.")
    if not args.yes:
        print("\nDRY RUN — apply with:  context-vigil launcher "
              f"{args.choice} --yes" + (" --confirm-always" if args.choice == "always" else ""))
        return 0
    try:
        install.apply(install.Plan(changes=[change]))
        _record_launcher(args.choice, change.path)
    except OSError as exc:
        raise CliError(f"launcher change failed ({exc}); nothing more was changed") from exc
    print(f"\nDone. Open a new shell (or `source {change.path}`) for it to take effect.")
    return 0


def _cmd_uninstall(args: argparse.Namespace) -> int:
    try:
        plan = install.plan_uninstall()
    except (install.InstallError, OSError, UnicodeError) as exc:
        raise CliError(str(exc)) from exc
    diffs = [c.diff() for c in plan.changes if c.before != c.after]
    print("\n".join(diffs) if diffs else "Nothing of context-vigil's is installed.")
    for line in plan.manual:
        print(f"\nNOTE: {line}")
    if not args.yes:
        print("\nDRY RUN — apply with:  context-vigil uninstall --yes")
        return 0
    try:
        install.apply(plan)
    except OSError as exc:
        raise CliError(f"uninstall failed ({exc}); nothing more was changed") from exc
    print(f"\ncontext-vigil uninstalled. Data left at {paths.data_root()} (delete it by hand).")
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
