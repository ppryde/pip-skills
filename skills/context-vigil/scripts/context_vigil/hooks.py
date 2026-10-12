"""Hook entrypoints: session-start (inject + resume), stop (/clear), nudge.

Every function returns the hook's stdout text (or None) and never raises —
``run`` wraps them so a malformed payload or any internal error degrades to
"do nothing this turn". Stop never blocks: it only ever emits systemMessage.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Callable, Dict, Optional

from context_vigil import (
    config,
    context,
    handover,
    last_light,
    messages,
    pane,
    paths,
    session,
    state,
    tmux,
)

KICK_PROMPT = (
    "context-vigil: handover received — resume from the injected handover now, "
    "starting with its Next Step."
)
NOTES_STEP = (
    "run `\"{launcher}\" notes-path`: it prints a private notes file outside the "
    "repository, pre-filled from the template. Fill that file in (Failed Attempts and "
    "exactly one Next Step are required; never write handover notes inside the "
    "repository, never paste a secret into them), then run:\n"
    "   `\"{launcher}\" handover --file <the path notes-path printed>`"
)
NUDGE_ATTENDED = (
    "**context-vigil: context at {pct}% — over the {threshold}% threshold.** "
    "A person just typed to you. Answer the user's message first. Then tell them "
    "context is at {pct}% and ASK whether to hand over now. Do not run `handover` "
    "until they agree. If they do, " + NOTES_STEP
)
NUDGE_UNATTENDED = (
    "**context-vigil: context at {pct}% — over the {threshold}% threshold.** "
    "At your next sensible stopping point:\n"
    "1. If any subagent or background command you started has not reported back, "
    "wait for it (or stop it) first — handing over abandons its result.\n"
    "2. If the user is mid-discussion with you, finish that exchange first; never "
    "clear a conversation out from under a live human.\n"
    "3. Hand over: " + NOTES_STEP + "\n"
    "It will tell you whether /clear is automatic or the user must type it."
)
NUDGE_NOTICED = (
    "**context-vigil: context at {pct}% — over the {threshold}% threshold.** "
    "The user has already been shown this on screen. If their message asks you to "
    "hand over, do it now: " + NOTES_STEP + "\nOtherwise answer their message normally "
    "and do not bring the handover up."
)
NUDGE_REMOTE = (
    "\n\nThis session is remote: the next session cannot open file paths. Embed "
    "anything it must read with repeatable `--inline <path>`. Never inline secrets or "
    "env files (.env, keys, credentials, shell rc): they are refused, and a handover "
    "is printed back into the next session's transcript."
)


def _cwd(payload: Dict[str, object]) -> Path:
    cwd = payload.get("cwd")
    return Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()


def _str(payload: Dict[str, object], key: str) -> Optional[str]:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


_BACKGROUND_PREFIX = "<task-notification>"


def classify_prompt(payload: Dict[str, object]) -> str:
    """``ours`` (last light's prompt, or our resume kick), ``background`` (a finished
    background task starting a turn), else ``human``."""
    text = payload.get("prompt")
    text = text.lstrip() if isinstance(text, str) else ""
    if text.startswith(last_light.MARKER) or text.startswith(KICK_PROMPT):
        return "ours"
    if text.startswith(_BACKGROUND_PREFIX):
        return "background"
    return "human"


def _on_human_prompt(cwd: Path, session_id: Optional[str], scope: Path) -> None:
    """Lock 1 arms; a prepared handover is stale once the person carries on."""
    if session_id:
        with session.locked(session_id) as got:
            if got:
                record = session.load(session_id)
                record["last_light_armed"] = True
                session.save(session_id, record)
    state.discard_prepared(scope, config.archive_keep(cwd))


def nudge(payload: Dict[str, object]) -> Optional[str]:
    cwd = _cwd(payload)
    session_id = _str(payload, "session_id")
    transcript_path = _str(payload, "transcript_path")

    def quiet(where: Path) -> bool:
        return (state.is_paused(where) or state.clear_requested(where)
                or state.cooldown_active(where, config.cooldown_seconds(cwd)))

    scope = session.scope(cwd, session_id, transcript_path)   # headless known before choosing
    event = _str(payload, "hook_event_name")
    kind = classify_prompt(payload) if event == "UserPromptSubmit" else None
    if kind == "ours":
        return None
    if kind == "human":
        _on_human_prompt(cwd, session_id, scope)
    if quiet(scope):
        return None
    threshold = config.threshold(cwd)
    reading = context.current_reading(cwd, session_id, transcript_path, config.window(cwd))
    pct = reading.pct
    after = session.scope(cwd, session_id, transcript_path)   # the measurement may have learnt more
    if after != scope:
        scope = after
        if quiet(scope):
            return None
    if pct is None or pct < threshold:
        return None
    if not reading.confident and reading.headless is not True:
        # the window is only the configured guess and an interactive session's
        # status line will soon tell the truth: a quiet turn, no gate, no last %
        return None
    # Re-nudge every repeat_step % past the last nudge. The gate marks "nudged
    # this cycle" (SessionStart / resume clear it, which resets the sequence);
    # the last nudged % lives in the session record. Without a session id there
    # is nowhere to keep it, so the gate alone holds: one nudge per cycle. The
    # check-and-set runs under the record's lock so parallel hooks cannot both
    # nudge; a lock that cannot be had means a quiet turn.
    record = None
    key = session_id or "scope-" + hashlib.sha1(str(scope).encode()).hexdigest()[:16]
    with session.locked(key) as got:
        if not got:
            return None
        record = session.load(session_id) if session_id else None
        if state.gate_active(scope):
            last = record["last_nudged_pct"] if record is not None else None
            # pct below the last nudge means the context shrank (compaction, /clear):
            # a new cycle, so nudge again instead of waiting to climb back past it
            shrank = isinstance(last, int) and pct < last
            if not shrank and (not isinstance(last, int)
                               or pct < last + config.repeat_step(cwd)):
                return None
        state.set_gate(scope)
        if session_id and record is not None:
            record["last_nudged_pct"] = pct
            session.save(session_id, record)
    noticed = (session_id is not None and record is not None
               and isinstance(record.get("last_noticed_pct"), int))
    if event == "UserPromptSubmit" and kind == "human":
        template = NUDGE_NOTICED if noticed else NUDGE_ATTENDED
    else:
        template = NUDGE_UNATTENDED
    text = template.format(pct=pct, threshold=threshold, launcher=paths.launcher_path())
    if config.mode(cwd) == "remote":
        text += NUDGE_REMOTE
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": event or "UserPromptSubmit",
        "additionalContext": text,
    }})


def _notice(payload: Dict[str, object], scope: Path) -> Optional[str]:
    """The end-of-turn notice (spec section 2): shown to the user, never to the model;
    first crossing, then every repeat step. One JSON object or nothing."""
    session_id = _str(payload, "session_id")
    if not session_id or state.is_paused(scope):
        return None
    cwd = _cwd(payload)
    reading = context.current_reading(cwd, session_id, _str(payload, "transcript_path"),
                                      config.window(cwd))
    if reading.pct is None or not reading.confident:
        return None
    pct, threshold, step = int(reading.pct), config.threshold(cwd), config.repeat_step(cwd)
    if pct < threshold:
        return None
    with session.locked(session_id) as got:
        if not got:
            return None
        record = session.load(session_id)
        last = record["last_noticed_pct"]
        if isinstance(last, int) and pct < last + step:
            return None
        record["last_noticed_pct"] = pct
        session.save(session_id, record)
    template = messages.NOTICE_FIRST if not isinstance(last, int) else messages.NOTICE_REPEAT
    return messages.system_message(template.format(pct=pct, threshold=threshold))


def stop(payload: Dict[str, object]) -> Optional[str]:
    if payload.get("stop_hook_active") is True:
        return None
    session_id = _str(payload, "session_id")
    transcript_path = _str(payload, "transcript_path")
    if session.is_headless(session_id, transcript_path):
        return None   # a headless session never types into a pane, inherited or not
    scope = session.scope(_cwd(payload), session_id, transcript_path)
    if state.drop_orphan_clear(scope):
        return None   # its handover was resumed or discarded elsewhere: nothing to /clear for
    if not state.clear_requested(scope):
        return _notice(payload, scope)
    target = tmux.pane()
    if not tmux.reachable() or target is None:
        return messages.system_message(messages.SAVED_TYPE_CLEAR)
    if not pane.pane_safe(target):
        # a dialog (or the person's own typing) holds the box: typing /clear + Enter
        # would answer it. Leave the flag armed; the manual /clear still loads it.
        return messages.system_message(messages.SAVED_DIALOG_OPEN)
    if state.consume_clear_flag(scope):
        delay = os.environ.get("CONTEXT_VIGIL_CLEAR_DELAY", "2")
        tmux.send_detached(target, [["/clear", "Enter"]], delay)
    return None


def session_start(payload: Dict[str, object]) -> Optional[str]:
    session_id = _str(payload, "session_id")
    cwd = _cwd(payload)
    transcript_path = _str(payload, "transcript_path")
    headless = session.is_headless(session_id, transcript_path)   # before choosing a scope
    scope = session.scope(cwd, session_id, transcript_path)
    kept = session.handoff_scope(cwd, session_id, transcript_path)
    source = _str(payload, "source")
    out: Optional[str] = None
    loaded = False
    if source == "clear":
        text = state.consume_handoff(kept, config.archive_keep(cwd))
        if text:
            loaded = True
            text = handover.cap_for_injection(text, config.handover_max_tokens(cwd))
            out = json.dumps({"hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": f"{handover.RESUME_PREAMBLE}\n\n{text}",
            }})
            target = None if headless else tmux.pane()
            if target is not None and tmux.reachable() and pane.pane_safe(target):
                delay = os.environ.get("CONTEXT_VIGIL_KICK_DELAY", "2")
                tmux.send_detached(target, [["-l", KICK_PROMPT], ["Enter"]], delay)
    else:
        # A per-session (tmux) scope with nothing of its own also offers the
        # worktree-level handover a plain `claude` left here — never loads it.
        fallback = session.fallback_handoff_scope(cwd, session_id, transcript_path)
        if fallback is not None:
            state.drop_orphan_clear(fallback, older_than=time.time())
        where = session.waiting_handoff_scope(cwd, session_id, transcript_path)
        waiting = state.read_handoff(where) if where is not None else None
        if where is not None and waiting:
            summary = handover.summary(waiting, state.handoff_written_at(where))
            out = json.dumps({
                "systemMessage": f"context-vigil: {summary}. Say \"resume the handover\" "
                                 "to load it, or \"discard the handover\" to drop it.",
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": (
                        f"context-vigil: {summary}. It has NOT been loaded. Only if the user "
                        f"asks, run `\"{paths.launcher_path()}\" handover --resume` (load) "
                        "or `handover --discard` (drop)."),
                },
            })
    state.begin_cycle(scope, cooldown=loaded)
    return out


_HOOKS: Dict[str, Callable[[Dict[str, object]], Optional[str]]] = {
    "nudge": nudge, "stop": stop, "session-start": session_start,
}


def run(name: str, raw: str) -> Optional[str]:
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or name not in _HOOKS:
            return None
        return _HOOKS[name](payload)
    except Exception:
        return None
