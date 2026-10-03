"""Hook entrypoints: session-start (inject + resume), stop (/clear), nudge.

Every function returns the hook's stdout text (or None) and never raises —
``run`` wraps them so a malformed payload or any internal error degrades to
"do nothing this turn". Stop never blocks: it only ever emits systemMessage.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Dict, Optional

from context_vigil import config, context, handover, paths, session, state, tmux

KICK_PROMPT = (
    "context-vigil: handover received — resume from the injected handover now, "
    "starting with its Next Step."
)
NUDGE_ATTENDED = (
    "**context-vigil: context at {pct}% — over the {threshold}% threshold.** "
    "A person just typed to you. Answer the user's message first. Then tell them "
    "context is at {pct}% and ASK whether to hand over now. Do not run `handover` "
    "until they agree. If they do, write handover notes following `{template}` "
    "(Failed Attempts and exactly one Next Step are required) and run:\n"
    "   `\"{launcher}\" handover --file <your notes file>`"
)
NUDGE_UNATTENDED = (
    "**context-vigil: context at {pct}% — over the {threshold}% threshold.** "
    "At your next sensible stopping point:\n"
    "1. If any subagent or background command you started has not reported back, "
    "wait for it (or stop it) first — handing over abandons its result.\n"
    "2. If the user is mid-discussion with you, finish that exchange first; never "
    "clear a conversation out from under a live human.\n"
    "3. Write handover notes following `{template}` — Failed Attempts and exactly "
    "one Next Step are required — then run:\n"
    "   `\"{launcher}\" handover --file <your notes file>`\n"
    "It will tell you whether /clear is automatic or the user must type it."
)
NUDGE_REMOTE = (
    "\n\nThis session is remote: the next session cannot open file paths. Embed "
    "anything it must read with repeatable `--inline <path>`."
)


def _cwd(payload: Dict[str, object]) -> Path:
    cwd = payload.get("cwd")
    return Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()


def _str(payload: Dict[str, object], key: str) -> Optional[str]:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def nudge(payload: Dict[str, object]) -> Optional[str]:
    cwd = _cwd(payload)
    session_id = _str(payload, "session_id")
    transcript_path = _str(payload, "transcript_path")

    def quiet(where: Path) -> bool:
        return (state.is_paused(where) or state.clear_requested(where)
                or state.cooldown_active(where, config.cooldown_seconds(cwd)))

    scope = session.scope(cwd, session_id, transcript_path)   # headless known before choosing
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
    key = session_id or "scope-" + hashlib.sha1(str(scope).encode()).hexdigest()[:16]
    with session.locked(key) as got:
        if not got:
            return None
        record = session.load(session_id) if session_id else None
        if state.gate_active(scope):
            last = record["last_nudged_pct"] if record is not None else None
            if not isinstance(last, int) or pct < last + config.repeat_step(cwd):
                return None
        state.set_gate(scope)
        if session_id and record is not None:
            record["last_nudged_pct"] = pct
            session.save(session_id, record)
    event = _str(payload, "hook_event_name")
    template = NUDGE_ATTENDED if event == "UserPromptSubmit" else NUDGE_UNATTENDED
    text = template.format(pct=pct, threshold=threshold,
                           template=handover.template_path(), launcher=paths.launcher_path())
    if config.mode(cwd) == "remote":
        text += NUDGE_REMOTE
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": event or "UserPromptSubmit",
        "additionalContext": text,
    }})


def stop(payload: Dict[str, object]) -> Optional[str]:
    session_id = _str(payload, "session_id")
    transcript_path = _str(payload, "transcript_path")
    if session.is_headless(session_id, transcript_path):
        return None   # a headless session never types into a pane, inherited or not
    scope = session.scope(_cwd(payload), session_id, transcript_path)
    if not state.clear_requested(scope):
        return None
    target = tmux.pane()
    if not tmux.reachable() or target is None:
        return json.dumps({"systemMessage": (
            "context-vigil: handover saved — type /clear, then send any message "
            "(e.g. \"go\") to start the resumed turn. (Run Claude inside tmux "
            "for hands-free handovers.)")})
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
        text = state.consume_handoff(kept)
        if text:
            loaded = True
            out = json.dumps({"hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": f"{handover.RESUME_PREAMBLE}\n\n{text}",
            }})
            target = None if headless else tmux.pane()
            if target is not None and tmux.reachable():
                delay = os.environ.get("CONTEXT_VIGIL_KICK_DELAY", "2")
                tmux.send_detached(target, [["-l", KICK_PROMPT], ["Enter"]], delay)
    else:
        waiting = state.read_handoff(kept)
        if waiting:
            summary = handover.summary(waiting, state.handoff_written_at(kept))
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
