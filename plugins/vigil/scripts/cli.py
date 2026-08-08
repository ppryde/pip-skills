"""Vigil CLI — measure context and hand over. Pure stdlib."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
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


def _current_context_percent(
    root: Path, cfg: dict[str, object], session_id: str | None = None
) -> int | None:
    # census first: keyed by session id when we have one (this session's own
    # entry, never a sibling's — see census.context_percent), else the
    # worktree-correct newest-write scan. Falls back to transcript-slug
    # measurement when census has no live entry (not installed, no status
    # line, or stale) — preserving the old behaviour rather than regressing
    # to "ctx unknown".
    pct = census.context_percent(root, session_id=session_id)
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
    pct = _current_context_percent(args.root, cfg, session_id=args.session_id)
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


def _read_hook_payload() -> dict[str, object]:
    """Read and parse the hook's stdin JSON payload exactly once.

    Every hook invocation is a fresh process reading its own stdin once, so
    each ``cmd_*_hook`` calls this exactly once. Returns ``{}`` on unreadable
    or non-object stdin — callers fall back to defaults rather than raising.
    """
    try:
        payload = json.loads(sys.stdin.read())
    except (ValueError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _hook_root(payload: dict[str, object], args: argparse.Namespace) -> Path:
    cwd = payload.get("cwd")
    return Path(cast(str, cwd)) if isinstance(cwd, str) and cwd else args.root


def _hook_session_id(payload: dict[str, object], args: argparse.Namespace) -> str | None:
    """Session id for census keying: hook stdin's ``session_id`` field wins
    (every Claude Code hook payload carries one); falls back to the CLI's
    optional ``--session-id`` for scripted/manual invocations."""
    session_id = payload.get("session_id")
    if isinstance(session_id, str) and session_id:
        return session_id
    fallback: str | None = args.session_id
    return fallback


def cmd_stop_hook(args: argparse.Namespace) -> int:
    payload = _read_hook_payload()
    if st.consume_clear_flag(_hook_root(payload, args)):
        print("DISPATCH_CLEAR")
    return 0


def cmd_clear_armed_hook(args: argparse.Namespace) -> int:
    """Read-only Stop-hook helper: is a handover currently armed?

    Unlike ``stop-hook``, this never consumes ``clear-requested`` — the manual
    (no-tmux) path needs to know whether to print the loud instruction line
    without eating the flag the human's own /clear (and the SessionStart that
    follows it) still depends on.
    """
    payload = _read_hook_payload()
    if st.clear_requested(_hook_root(payload, args)):
        print("ARMED")
    return 0


def cmd_session_start_hook(args: argparse.Namespace) -> int:
    payload = _read_hook_payload()
    root = _hook_root(payload, args)
    if st.is_active(root):
        handoff = st.consume_handoff(root)
        if handoff:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": handoff,
                }
            }))
            # Injected additionalContext never starts a turn on its own — the
            # fresh session sits idle until a human types something. On a
            # `/clear`-triggered relaunch (never a plain `startup`/`resume`,
            # where a human just launched the CLI and should read the
            # handover first) type a resume prompt into the pane so unattended
            # runs restart hands-free. Best-effort and wrapped so it can never
            # raise or touch this hook's own stdout/stderr.
            _maybe_kick_resume(payload)
        # ANY session start on an active root begins a new cycle — clear the
        # gate and touch a fresh cooldown unconditionally, whether or not a
        # handover just landed. The cooldown covers census's stale-horizon lag
        # (a fresh session can still read the old session's high ctx%), so the
        # cleared gate cannot trigger an instant re-nudge → handover storm; and
        # a bare `/clear` with nothing armed no longer strands the gate.
        st.begin_cycle(root)
    return 0


_KICK_PROMPT = (
    "vigil: handover received — resume the work described in the injected handover now."
)


def _tmux_probe_reachable(tmux_bin: str) -> bool:
    """`tmux has-session` liveness probe, mirroring stop.sh's dead-server
    guard: `$TMUX` set only proves a client once existed, not that its server
    is still up. Never raises — FileNotFoundError (binary missing), a
    timeout, or any other subprocess failure all mean "not reachable"."""
    try:
        result = subprocess.run(
            [tmux_bin, "has-session"],
            timeout=5,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    return result.returncode == 0


def _dispatch_resume_kick(pane: str, tmux_bin: str, delay: str) -> None:
    """Fire-and-forget: type the resume prompt into the pane that just ran
    `/clear`, so an unattended session restarts itself hands-free. Spawned
    fully detached (own session group, every stream to DEVNULL) so the hook
    process returns immediately and the child can never corrupt the hook's
    own JSON stdout."""
    script = (
        f"sleep {shlex.quote(delay)}; "
        f"{shlex.quote(tmux_bin)} send-keys -t {shlex.quote(pane)} "
        f"-l {shlex.quote(_KICK_PROMPT)}; "
        f"{shlex.quote(tmux_bin)} send-keys -t {shlex.quote(pane)} Enter"
    )
    subprocess.Popen(
        ["bash", "-c", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _maybe_kick_resume(payload: dict[str, object]) -> None:
    """Fire the detached resume kick iff every precondition holds, checked in
    this order (cheapest/most-decisive first, so a non-qualifying session
    never even probes tmux):

    1. caller already confirmed a handoff was consumed this invocation
       (enforced by the sole call site, inside `if handoff:`);
    2. the hook payload's `source` is exactly `"clear"` — `startup`/`resume`/
       `compact`/missing all mean a human just launched the CLI and should
       read the handover, not have the session run off;
    3. `TMUX` is set AND `tmux has-session` succeeds (dead-server guard);
    4. `TMUX_PANE` is set and non-empty (needed to target the kick).

    Wrapped so this can NEVER raise or write to stdout/stderr: any failure
    silently degrades to today's manual-resume behaviour — the hook still
    exits 0 and the handover injection above is unaffected either way.

    `VIGIL_TMUX_BIN` (default `"tmux"`) is a test seam: E2E tests point it at
    a wrapper pinned to a private `tmux -L <socket>`, so no test can ever
    reach the developer's real tmux server.
    """
    try:
        if payload.get("source") != "clear":
            return
        if not os.environ.get("TMUX"):
            return
        tmux_bin = os.environ.get("VIGIL_TMUX_BIN", "tmux")
        if not _tmux_probe_reachable(tmux_bin):
            return
        pane = os.environ.get("TMUX_PANE")
        if not pane:
            return
        delay = os.environ.get("VIGIL_KICK_DELAY", "2")
        _dispatch_resume_kick(pane, tmux_bin, delay)
    except Exception:
        pass


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
    """UserPromptSubmit + PostToolUse hook backend: nudge once per
    over-threshold cycle.

    Registered on both events: UserPromptSubmit fires once per user turn, but
    unattended (auto-handover) runs receive no user prompts at all, so
    PostToolUse — which fires after every tool call inside the agentic loop —
    is the channel that actually reaches unattended sessions. The
    handover-gate (below) is what keeps the PostToolUse registration
    non-chatty: it nudges once per cycle regardless of how many times, or via
    which event, this hook is invoked afterward.

    All preconditions must hold: active, not paused, no cooldown, no live
    handover-gate, and a known ctx% at/over the configured threshold. Never
    raises — every check composes already quarantine-safe primitives.
    """
    payload = _read_hook_payload()
    root = _hook_root(payload, args)
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
    pct = _current_context_percent(root, cfg, session_id=_hook_session_id(payload, args))
    if pct is None or pct < threshold:
        return 0
    st.set_gate(root)
    mode = str(cfg["context.mode"])
    event_name = payload.get("hook_event_name")
    if not isinstance(event_name, str) or not event_name:
        event_name = "UserPromptSubmit"
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": _nudge_text(pct, threshold, mode),
        }
    }))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vigil", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--session-id", dest="session_id", default=None,
        help="census lookup key for this session (defaults to hook stdin's "
             "session_id when invoked as a hook; None for scripted/manual calls)",
    )
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
