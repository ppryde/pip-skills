"""Hook entrypoints: session-start (inject + resume), stop (/clear), nudge.

Every function returns the hook's stdout text (or None) and never raises —
``run`` wraps them so a malformed payload or any internal error degrades to
"do nothing this turn". Stop never blocks: it only ever emits systemMessage.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Dict, Optional

from context_vigil import config, context, handover, paths, state, tmux

KICK_PROMPT = (
    "context-vigil: handover received — resume from the injected handover now, "
    "starting with its Next Step."
)
NUDGE_TEXT = (
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
    scope = paths.scope_dir(cwd)
    if state.is_paused(scope) or state.cooldown_active(scope) or state.gate_active(scope):
        return None
    threshold = config.threshold(cwd)
    pct = context.current_percent(
        cwd, _str(payload, "session_id"), _str(payload, "transcript_path"), config.window(cwd))
    if pct is None or pct < threshold:
        return None
    state.set_gate(scope)
    text = NUDGE_TEXT.format(pct=pct, threshold=threshold,
                             template=handover.template_path(), launcher=paths.launcher_path())
    if config.mode(cwd) == "remote":
        text += NUDGE_REMOTE
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": _str(payload, "hook_event_name") or "UserPromptSubmit",
        "additionalContext": text,
    }})


def stop(payload: Dict[str, object]) -> Optional[str]:
    scope = paths.scope_dir(_cwd(payload))
    if not state.clear_requested(scope):
        return None
    target = tmux.pane()
    if not tmux.reachable() or target is None:
        return json.dumps({"systemMessage": (
            "context-vigil: handover saved — type /clear to continue in a fresh "
            "context. (Run Claude inside tmux for hands-free handovers.)")})
    if state.consume_clear_flag(scope):
        delay = os.environ.get("CONTEXT_VIGIL_CLEAR_DELAY", "1")
        tmux.send_detached(target, [["/clear", "Enter"]], delay)
    return None


def session_start(payload: Dict[str, object]) -> Optional[str]:
    scope = paths.scope_dir(_cwd(payload))
    source = _str(payload, "source")
    out: Optional[str] = None
    if source == "clear":
        text = state.consume_handoff(scope)
        if text:
            out = json.dumps({"hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": f"{handover.RESUME_PREAMBLE}\n\n{text}",
            }})
            target = tmux.pane()
            if target is not None and tmux.reachable():
                delay = os.environ.get("CONTEXT_VIGIL_KICK_DELAY", "2")
                tmux.send_detached(target, [["-l", KICK_PROMPT], ["Enter"]], delay)
    else:
        waiting = state.read_handoff(scope)
        if waiting:
            summary = handover.summary(waiting, state.handoff_written_at(scope))
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
    state.begin_cycle(scope)
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
