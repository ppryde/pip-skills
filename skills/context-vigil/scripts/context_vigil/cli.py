"""context-vigil CLI. Every command prints one short human line; errors go to
stderr with a non-zero exit. ``hook`` subcommands never fail (see hooks.py)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import List, Optional

from context_vigil import (
    cards,
    census,
    config,
    context,
    handover,
    hooks,
    install,
    last_light,
    launcher,
    messages,
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
    hp.add_argument("--inline", action="append", default=[],
                    help="embed a file (remote mode only; secret-bearing files are refused)")
    hp.add_argument("--no-snapshot", action="store_true")
    hp.add_argument("--prepared", action="store_true",
                    help="last light: save without arming /clear (carry on, or /clear to resume)")
    hp.set_defaults(func=_cmd_handover)
    sub.add_parser("notes-path", help="print (creating it from the template) the private "
                   "file to write handover notes in").set_defaults(func=_cmd_notes_path)
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
    ip.add_argument("--questions-json", action="store_true",
                    help="print the install questions as AskUserQuestion cards")
    ip.add_argument("--last-light", choices=("on", "off"), default=None)
    ip.add_argument("--last-light-threshold", type=int, default=None)
    ip.add_argument("--bar", choices=("on", "off"), default=None)
    ip.set_defaults(func=_cmd_install)
    lp = sub.add_parser("launcher", help="choose how Claude launches (tmux)")
    lp.add_argument("choice", nargs="?", choices=launcher.CHOICES)
    lp.add_argument("--yes", action="store_true")
    lp.add_argument("--confirm-always", action="store_true")
    lp.set_defaults(func=_cmd_launcher)
    llp = sub.add_parser("last-light", help="prepare a handover before an idle cache goes cold")
    llp.add_argument("choice", nargs="?", choices=("on", "off"))
    llp.add_argument("--threshold", type=int, default=None)
    llp.add_argument("--yes", action="store_true")
    llp.set_defaults(func=_cmd_last_light)
    up = sub.add_parser("uninstall", help="remove exactly what install added")
    up.add_argument("--yes", action="store_true")
    up.set_defaults(func=_cmd_uninstall)
    return parser


def _cmd_handover(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    scope = _scope(cwd)
    kept = session.handoff_scope(cwd, _env_session_id())
    if args.resume or args.discard:
        keep = config.archive_keep(cwd)
        # own scope first, then the worktree-level one a plain `claude` left here
        where = session.waiting_handoff_scope(cwd, _env_session_id())
        text = state.consume_handoff(where, keep) if where is not None else None
        if where is None or text is None:
            raise CliError("no handover is waiting here")
        if where != kept:
            state.drop_orphan_clear(where)   # its /clear request went with it
        print(f"{handover.RESUME_PREAMBLE}\n\n"
              f"{handover.cap_for_injection(text, config.handover_max_tokens(cwd))}"
              if args.resume
              else "handover discarded" + (" (kept in the archive)" if keep else ""))
        return 0
    notes_file = Path(args.file)
    try:
        notes = notes_file.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise CliError(f"--file is not UTF-8 text: {notes_file}") from exc
    except OSError as exc:
        raise CliError(f"--file unreadable: {notes_file} "
                       f"({exc.strerror or type(exc).__name__})") from exc
    if args.inline and config.mode(cwd) != "remote":
        raise CliError("--inline is for remote mode only (context.mode is not `remote`): "
                       "reference files by path in the notes instead")
    try:
        document = handover.assemble(
            notes, cwd, [Path(p) for p in args.inline], include_snapshot=not args.no_snapshot,
            max_tokens=config.handover_max_tokens(cwd))
    except handover.HandoverError as exc:
        raise CliError(f"handover refused: {exc}") from exc
    if args.prepared:
        if session.is_headless(_env_session_id()):
            raise CliError("--prepared is for interactive sessions")
        if state.is_paused(scope):
            raise CliError("handover refused: paused here (`context-vigil resume` to re-enable)")
        if state.handoff_path(scope).exists() and not state.is_prepared(scope):
            raise CliError("a handover is already pending — --prepared will not replace it")
        state.write_prepared(scope, document, config.archive_keep(cwd))
        _tidy_notes(notes_file, [scope, kept])
        print(messages.LAST_LIGHT_PREPARED)
        return 0
    headless = session.is_headless(_env_session_id())
    if headless:
        # no /clear is sent to a headless run: leave the handoff where the next run looks
        if state.is_paused(scope):
            raise CliError("handover refused: paused here (`context-vigil resume` to re-enable)")
        state.write_handoff(kept, document, config.archive_keep(cwd))
        _tidy_notes(notes_file, [scope, kept])
        print(f"handover saved to {state.handoff_path(kept)} — the next headless run in this "
              "worktree can `handover --resume` it")
        return 0
    result = state.request_clear(scope, document, config.archive_keep(cwd))
    if result == "paused":
        raise CliError("handover refused: paused here (`context-vigil resume` to re-enable)")
    _tidy_notes(notes_file, [scope, kept])
    if tmux.reachable():
        print("handover saved — /clear will be sent at the end of this turn")
    else:
        print("handover saved — type /clear, then send any message (e.g. \"go\") "
              "to start the resumed turn")
    return 0


def _tidy_notes(notes_file: Path, scopes: List[Path]) -> None:
    """After a saved handover: delete the notes file ``notes-path`` handed out (its job
    is done, and it need not linger) and nothing else — any other file, under the data
    root or not, is left where it is; warn, by path only, about notes inside a git
    worktree — untracked and unignored, one `git add -A` from history."""
    real = os.path.realpath(str(notes_file))
    if any(real == os.path.realpath(str(state.notes_path(s))) for s in scopes):
        if paths.owned(Path(real).parent):
            try:
                os.unlink(str(notes_file))
            except OSError:
                pass
        return
    root = Path(os.path.realpath(str(paths.data_root())))
    if root in Path(real).parents:
        return
    repo = paths.enclosing_repo(Path(real))
    if repo is not None:
        print(f"WARNING: the notes file {notes_file} is inside a git repository ({repo}) and "
              "is not ignored — delete it. Next time write notes in the file "
              "`context-vigil notes-path` prints (private, outside every repository).",
              file=sys.stderr)


def _cmd_notes_path(args: argparse.Namespace) -> int:
    scope = _scope(Path.cwd())
    try:
        template = handover.template_path().read_text(encoding="utf-8")
        path = state.ensure_notes(scope, template)
    except paths.UnsafeDataRoot:
        raise
    except OSError as exc:
        raise CliError(f"cannot prepare the notes file under {scope} "
                       f"({exc.strerror or type(exc).__name__})") from exc
    print(path)
    return 0


def _data_root_warning() -> Optional[str]:
    """A data root inside a git worktree (a dotfiles-managed config dir, usually):
    it ignores itself, but say so — paths only."""
    root = paths.data_root()
    repo = paths.enclosing_repo(root)
    if repo is None:
        return None
    return (f"WARNING: the data root {root} is inside a git repository ({repo}). It ignores "
            "itself (a .gitignore of `*`), but handovers belong outside repositories: set "
            "CONTEXT_VIGIL_HOME to an absolute path outside it.")


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
    raw = sys.stdin.read()
    census.ingest(raw)
    try:   # the status line must never fail: last light is best-effort
        payload = json.loads(raw)
        if isinstance(payload, dict):
            last_light.tick(payload)
    except Exception:
        pass
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


ALL_HOOKS = len(install.HOOKS)
FEED_GRACE_SECONDS = 120   # a session this old with no status-line reading is not feeding us
LIVE_NOW = ("Hooks and the status line are live in this session on current Claude Code: "
            "`/hooks` should list the four context-vigil entries. If they are missing, "
            "restart Claude (older Claude Code builds load hooks only at startup).")


def _record_launcher_choice() -> Optional[str]:
    try:
        record = json.loads(paths.read_private(paths.install_record_path()))
    except (OSError, ValueError):
        return None
    choice = record.get("launcher") if isinstance(record, dict) else None
    return choice if isinstance(choice, str) else None


def _mode_line(hooks_live: bool) -> str:
    """Auto is claimed only when our hooks are in settings.json, and then only
    conditionally on this session having loaded them."""
    if session.is_headless(_env_session_id()):
        return ("mode: headless (no /clear is sent; `handover --file` saves it "
                "for the next run to `--resume`)")
    if tmux.reachable():
        if hooks_live:
            return ("mode: auto (inside tmux — /clear is sent for you once `/hooks` "
                    "lists context-vigil in this session)")
        return "mode: none yet (inside tmux, but context-vigil's hooks are not installed)"
    if tmux.installed():
        choice = _record_launcher_choice()
        if choice in ("on-demand", "always"):
            command = "claude-tmux" if choice == "on-demand" else "claude"
            return (f"mode: manual (not inside tmux — a new session started with "
                    f"`{command}` from a new shell runs in auto mode)")
        if hooks_live:
            return ("mode: manual (not inside tmux — `context-vigil launcher` adds a "
                    "`claude-tmux` command for auto)")
        return "mode: manual (not inside tmux; `install` adds a `claude-tmux` launcher)"
    return "mode: manual (tmux not installed — you type /clear after a handover)"


def _python_line() -> str:
    return (f"python: {sys.executable} (as run here; hooks use the python3 on the PATH "
            "Claude was started with)")


def _ago(then: float) -> str:
    return f"{max(0, int(time.time() - then))}s ago"


def _feed_lines(cwd: Path, scope: Path, live: install.LiveState) -> List[str]:
    """Status-line truth: what feeds us, when it last did, and a warning when an
    installed context-vigil is not being fed (then interactive sessions never nudge)."""
    seen = census.last_seen(cwd, _env_session_id())
    lines = [f"status line: {live.statusline}",
             "last status-line reading for this worktree: "
             + (_ago(seen) if seen is not None else "none yet")]
    if not live.hooks or session.is_headless(_env_session_id()):
        return lines
    started = state.started_at(scope)
    if live.statusline == "missing":
        lines.append("WARNING: status line not feeding context-vigil — interactive sessions "
                     "are never nudged until the MANUAL STEP line from `install` is in your "
                     "status-line script (re-run `install` to see it).")
    elif (started is not None and time.time() - started > FEED_GRACE_SECONDS
          and (seen is None or seen < started)):
        lines.append(f"WARNING: status line not feeding context-vigil — this session started "
                     f"{_ago(started)} and no status-line reading has arrived, so it is never "
                     "nudged. Check the status line is wired (above) and that the workspace "
                     "trust dialog was accepted (hooks and the status line wait for it).")
    return lines


def _cmd_status(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    paths.guard_read(paths.data_root())   # a root that is not ours: say so, not "no hooks"
    scope = _scope(cwd)
    record = paths.install_record_path()
    resolved = config.resolve(cwd)
    threshold, layer = resolved["context.threshold"]
    reading = context.current_reading(cwd, _env_session_id(), None, config.window(cwd))
    pending = session.waiting_handoff_scope(cwd, _env_session_id())
    pending_text = ("no" if pending is None
                    else "yes" if pending == session.handoff_scope(cwd, _env_session_id())
                    else "yes (left by a plain `claude` in this worktree)")
    live = install.live_state()
    settings = install.settings_path()
    if live.hooks is None:
        installed = "unknown"
        hooks_line = (f"hooks: unreadable — {settings} could not be parsed (invalid JSON, "
                      "duplicate keys or not UTF-8)")
    else:
        installed = ("yes" if live.hooks == ALL_HOOKS
                     else "partial" if live.hooks else "no")
        hooks_line = f"hooks: {live.hooks}/{ALL_HOOKS} in {settings}"
        if live.hooks < ALL_HOOKS and (live.hooks or record.exists()):
            hooks_line += " — MISSING — re-run install"
    lines = [
        f"installed: {installed}",
        hooks_line,
        *_feed_lines(cwd, scope, live),
        _mode_line(live.hooks == ALL_HOOKS),
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
        f"handover.archive_keep: {resolved['handover.archive_keep'][0]} "
        f"({resolved['handover.archive_keep'][1]})",
        f"paused here: {'yes' if state.is_paused(scope) else 'no'}",
        f"nudge gate: {'armed' if state.gate_active(scope) else 'clear'}",
        _last_light_line(cwd) + (
            f", lead {config.last_light_lead_seconds(cwd)} s — this session: "
            f"{last_light.session_state(cwd, _env_session_id())}"
            if config.last_light_enabled(cwd) else ""),
        _bar_line(),
        f"pending handover: {pending_text}",
        f"data: {paths.data_root()}",
        _python_line(),
    ]
    warning = _data_root_warning()
    if warning:
        lines.append(warning)
    print("\n".join(lines))
    return 0


def _summaries(plan: install.Plan) -> List[str]:
    """What each planned edit does, in context-vigil's own lines only — never a
    diff: rc files, settings.json and status-line scripts hold secrets, and this
    output reaches the terminal and the agent's transcript."""
    return [c.describe() for c in plan.changes if c.before != c.after]


def _cmd_install(args: argparse.Namespace) -> int:
    if args.questions_json:
        print(json.dumps(cards.install_cards(install.claude_supports_mods()),
                         ensure_ascii=False, indent=2))
        return 0
    flag = {"on": True, "off": False, None: None}
    try:
        plan = install.plan_install(args.threshold, args.launcher, flag[args.last_light],
                                    args.last_light_threshold, flag[args.bar])
    except (install.InstallError, config.ConfigError, OSError, UnicodeError) as exc:
        raise CliError(str(exc)) from exc
    summaries = _summaries(plan)
    warning = _data_root_warning()
    if warning:
        print(warning + "\n")
    if not args.yes:
        print("context-vigil install — DRY RUN, nothing changed yet.\n")
        print("\n".join(summaries) if summaries else "Hooks and status line already wired.")
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
              "[--launcher on-demand|always|not-now] [--last-light on|off] "
              "[--last-light-threshold N] [--bar on|off]")
        return 0
    if args.launcher == "always" and not args.confirm_always:
        raise CliError("--launcher always also needs --confirm-always "
                       "(it takes over the claude command)")
    # Show what is about to change BEFORE changing it, so the record of the
    # edit (the rc file included) is on screen even if apply fails part-way.
    print("\n".join(summaries) if summaries else "Hooks and status line already wired.")
    for line in plan.manual:
        print(f"\nMANUAL STEP: {line}")
    for line in plan.notes:
        print(f"\n{line}")
    sys.stdout.flush()
    try:
        install.apply(plan)
    except OSError as exc:
        raise CliError(f"install failed part-way ({exc}); re-run, or `uninstall --yes`") from exc
    print("\n".join(_installed_lines(plan)))
    return 0


def _last_light_line(cwd: Path) -> str:
    if not config.last_light_enabled(cwd):
        return "🌅 last light: off"
    return f"🌅 last light: on ({config.last_light_threshold(cwd)}%)"


def _bar_line() -> str:
    try:
        record = json.loads(paths.read_private(paths.install_record_path()))
    except (OSError, ValueError):
        record = {}
    if not (isinstance(record, dict) and record.get("bar")):
        return "🎛️ vigil bar: off"
    note = "" if install.claude_supports_mods() else " — but this Claude Code build has no mods"
    return f"🎛️ vigil bar: on{note}"


def _cmd_last_light(args: argparse.Namespace) -> int:
    cwd = Path.cwd()
    try:
        if args.choice == "off":
            config.set_value(cwd, "last_light.enabled", "off")
        elif args.choice == "on" and not args.yes:
            print(json.dumps(cards.last_light_card(), ensure_ascii=False, indent=2))
            print("\nApply with:  context-vigil last-light on --yes [--threshold N]")
            return 0
        elif args.choice == "on":
            if args.threshold is not None:
                config.set_value(cwd, "last_light.threshold", str(args.threshold))
            config.set_value(cwd, "last_light.enabled", "on")
    except config.ConfigError as exc:
        raise CliError(str(exc)) from exc
    print(_last_light_line(cwd))
    return 0


def _installed_lines(plan: install.Plan) -> List[str]:
    """The closing report: what is live now, what needs a new shell or a new session."""
    hooks_live = install.live_state().hooks == ALL_HOOKS
    lines = [f"\ncontext-vigil installed. {_mode_line(hooks_live)}.", LIVE_NOW]
    choice, rc = plan.record.get("launcher"), plan.record.get("rc_path")
    command = {"on-demand": "claude-tmux", "always": "claude"}.get(str(choice))
    if command and rc:
        lines.append(f"The `{command}` alias needs a new shell: open a new terminal (or "
                     f"`source {rc}`). The agent cannot run `{command}` itself — its shell "
                     "read the rc when this session started.")
    headless = session.is_headless(_env_session_id())
    if not headless and tmux.reachable():
        lines.append("You are inside tmux: auto mode works in this session once `/hooks` "
                     "lists context-vigil (no restart needed on current Claude Code).")
    elif not headless and command and tmux.installed():
        lines.append(f"This session stays manual. For auto mode, start a new session with "
                     f"`{command}` from a new shell (carry this work over with a handover).")
    lines.append(_python_line())
    return lines


def _record_launcher(choice: str, rc: Path) -> None:
    """Keep an existing install.json in step; never create one from `launcher` alone."""
    record_path = paths.install_record_path()
    try:
        record = json.loads(paths.read_private(record_path))
    except (OSError, ValueError):
        return
    if not isinstance(record, dict):
        return
    record["launcher"] = choice
    record["rc_path"] = str(rc)
    paths.write_private(record_path, json.dumps(record, indent=2) + "\n")


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
    print(change.describe() if change.before != change.after else "Already set.")
    for line in change.notes:
        print(f"\nMANUAL STEP: {line}")
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
    summaries = _summaries(plan)
    print("\n".join(summaries) if summaries else "Nothing of context-vigil's is installed.")
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


DEBUG_ENV = "CONTEXT_VIGIL_DEBUG"


def _unexpected(exc: BaseException) -> None:
    """One line naming the exception CLASS only: its message could quote a file or an
    environment value, and this output reaches the agent's transcript. An OSError also
    names its reason (``strerror``) and path(s) — the detail a user needs to fix it,
    never its free-form message. With CONTEXT_VIGIL_DEBUG=1, also the frames (file,
    line, function) — still never the message, a source line, a local or the
    environment."""
    if isinstance(exc, OSError) and (exc.strerror or exc.filename):
        where = " -> ".join(str(f) for f in (exc.filename, exc.filename2) if f is not None)
        print(f"error: unexpected {type(exc).__name__}: {exc.strerror or 'failed'}"
              + (f": {where}" if where else "")
              + f" — re-run with {DEBUG_ENV}=1 for details", file=sys.stderr)
    else:
        print(f"error: unexpected {type(exc).__name__} (details withheld: they could quote "
              f"a file) — re-run with {DEBUG_ENV}=1 for details", file=sys.stderr)
    if os.environ.get(DEBUG_ENV):
        for frame in traceback.extract_tb(exc.__traceback__):
            print(f"  at {frame.filename}:{frame.lineno} in {frame.name}", file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result: int = args.func(args)
        return result
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (paths.DataRootError, paths.UnsafeDataRoot) as exc:
        print(f"error: {exc}", file=sys.stderr)   # our own words and a path
        return 1
    except KeyboardInterrupt:
        return 130
    except Exception as exc:   # noqa: BLE001 — the last line of defence, by design
        _unexpected(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
