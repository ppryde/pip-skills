"""Last light: before an idle session's 1-hour prompt cache goes cold, ask the agent
to *prepare* a handover. Nothing is cleared. Spec §1."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Dict, Optional

from context_vigil import census, config, pane, paths, session, state, tmux

MARKER = "[context-vigil:last-light]"

PROMPT = (
    MARKER + " The prompt cache expires in about {minutes} minutes and this session is "
    "idle. Prepare a handover: run `\"{launcher}\" notes-path`, fill in the file it "
    "prints, then run `\"{launcher}\" handover --file <the path notes-path printed> "
    "--prepared`. Then reply with exactly the line that command prints and stop. Do not "
    "/clear and do not continue the task."
)


def _expires_at(payload: Dict[str, object]) -> Optional[float]:
    cache = payload.get("prompt_cache")
    if not isinstance(cache, dict):
        return None
    expires = cache.get("expires_at")
    if cache.get("ttl") != "1h" or cache.get("warm") is not True:
        return None
    if isinstance(expires, bool) or not isinstance(expires, (int, float)):
        return None
    return float(expires)


def _pct(payload: Dict[str, object]) -> Optional[float]:
    window = payload.get("context_window")
    value = window.get("used_percentage") if isinstance(window, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _blocked(scope: Path) -> Optional[str]:
    if state.is_prepared(scope):
        return "prepared"                      # lock 2
    if state.handoff_path(scope).exists() or state.clear_requested(scope):
        return "pending"
    if state.is_paused(scope):
        return "paused"
    return None


def tick(payload: Dict[str, object], now: Optional[float] = None) -> str:
    """One status-line tick. Returns why it did or did not fire; never raises."""
    now = time.time() if now is None else now
    where = census.worktree_cwd(payload)        # str | None
    raw_cwd = payload.get("cwd")
    cwd = Path(where) if where else Path(raw_cwd) if isinstance(raw_cwd, str) and raw_cwd \
        else Path.cwd()
    if not config.last_light_enabled(cwd):
        return "off"
    expires = _expires_at(payload)
    if expires is None:
        return "no-cache"
    left = expires - now
    lead = config.last_light_lead_seconds(cwd)
    if not 0 < left <= lead:
        return "not-near"
    pct = _pct(payload)
    if pct is None or pct < config.last_light_threshold(cwd):
        return "below"
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return "no-session"
    if session.load(session_id)["last_light_armed"] is not True:
        return "disarmed"                      # lock 1
    transcript = payload.get("transcript_path")
    scope = session.scope(cwd, session_id, transcript if isinstance(transcript, str) else None)
    blocked = _blocked(scope)
    if blocked:
        return blocked
    target = tmux.pane()
    if target is None or not tmux.reachable():
        return "no-tmux"
    if not pane.pane_safe(target):
        return "unsafe"
    with session.locked(session_id) as got:
        if not got:
            return "locked"
        record = session.load(session_id)
        if record["last_light_armed"] is not True:
            return "disarmed"
        blocked = _blocked(scope)
        if blocked:
            return blocked
        record["last_light_armed"] = False
        session.save(session_id, record)
        text = PROMPT.format(minutes=max(1, int(left // 60)), launcher=paths.launcher_path())
        tmux.send_detached(target, [["-l", text], ["Enter"]], "0")
    return "fired"


def session_state(cwd: Path, session_id: Optional[str]) -> str:
    """One word or phrase for `status`: why last light is or is not ready."""
    if not config.last_light_enabled(cwd):
        return "off"
    if not session_id:
        return "no session"
    scope = session.scope(cwd, session_id)
    if state.is_prepared(scope):
        return "prepared handover waiting"
    if tmux.pane() is None or not tmux.reachable():
        return "inactive: not tmux"
    entry = census.for_session(session_id) or {}
    payload = entry.get("payload")
    cache = payload.get("prompt_cache") if isinstance(payload, dict) else None
    if not isinstance(cache, dict):
        return "inactive: no prompt_cache in status line"
    if cache.get("ttl") != "1h":
        return f"inactive: cache TTL {cache.get('ttl')}"
    return "armed" if session.load(session_id)["last_light_armed"] is True else "disarmed"
