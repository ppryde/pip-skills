"""Census store: one worktree-indexed JSON file of status-line payloads.

Quarantine-safe: every public entry point swallows read / parse / lock / write
failures and never raises. A broken store must never break the status-line
render or the CLI command it piggybacks on.

Layout of ``<data root>/census.json`` (see ``paths.census_path``)::

    {
      "version": 1,
      "sessions": {
        "<session_id>": {
          "worktree_cwd": "<abs path>",
          "updated_at": <epoch — last time the status line ran for this session>,
          "active_at": <epoch — last time the session's activity counters moved>,
          "branch": "<current git branch, null when unresolvable/detached>",
          "tmux_pane": "<%N, absent when the session isn't running inside tmux>",
          "payload": { ...full status-line payload verbatim... }
        }
      }
    }
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from context_vigil import paths, session

SCHEMA_VERSION = 1

SESSION_TTL_SECONDS = 24 * 3600      # prune entries older than this on write
STALE_HORIZON_SECONDS = 90           # readers ignore entries older than this
_LOCK_ATTEMPTS = 50                  # 50 × 10ms = 0.5s bounded wait for the lock
_LOCK_DELAY_SECONDS = 0.01
_GIT_BRANCH_TIMEOUT_SECONDS = 2      # bounded wait; a hung/slow git must never hang the status line


def store_path() -> Path:
    return paths.census_path()


def normalise(path: str) -> str:
    """Collapse symlinks and trailing-slash / `.` variants to one canonical key."""
    return os.path.realpath(path)


def worktree_cwd(payload: dict[str, Any]) -> str | None:
    """The worktree-level directory to index this session by.

    First present wins:
      1. ``worktree.path``          — ``--worktree`` sessions
      2. ``workspace.current_dir``  — ``git worktree add`` sessions and the plain case
      3. ``cwd``                    — last resort

    Returns a normalised absolute path, or None if the payload carries no usable
    directory.
    """
    worktree = payload.get("worktree")
    if isinstance(worktree, dict):
        path = worktree.get("path")
        if isinstance(path, str) and path:
            return normalise(path)

    workspace = payload.get("workspace")
    if isinstance(workspace, dict):
        current = workspace.get("current_dir")
        if isinstance(current, str) and current:
            return normalise(current)

    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        return normalise(cwd)

    return None


def _empty_store() -> dict[str, Any]:
    return {"version": SCHEMA_VERSION, "sessions": {}}


def _load(path: Path) -> dict[str, Any]:
    """Load the store, healing any missing/corrupt shape into a valid skeleton."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return _empty_store()
    if not isinstance(data, dict):
        return _empty_store()
    data.setdefault("version", SCHEMA_VERSION)
    if not isinstance(data.get("sessions"), dict):
        data["sessions"] = {}
    return data


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    paths.ensure_dir(path.parent)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".status.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _context_is_blank(payload: dict[str, Any]) -> bool:
    """True when the payload carries no live context figure.

    This is the post-``/compact`` and pre-first-API-call gap: ``current_usage``
    and ``used_percentage`` are both null/absent. We must not overwrite a good
    prior reading with this.
    """
    window = payload.get("context_window")
    if not isinstance(window, dict):
        return True
    return window.get("current_usage") is None and window.get("used_percentage") is None


def _number(value: Any) -> float | None:
    """``value`` as a finite float, or None if it is not a usable number.

    Rejects ``bool`` (an int subclass), NaN and the infinities. NaN matters
    specifically: ``json`` both emits and re-reads a bare ``NaN``, so one that
    reaches the store survives every round trip, and every comparison against
    it is false — a naive ``>=`` gate would then wedge permanently.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None  # rejects NaN and ±inf


def _section(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _activity_fingerprint(payload: dict[str, Any]) -> tuple[Any, ...] | None:
    """The payload facts that move ONLY when the session does real work.

    The status line reruns on a timer (``refreshInterval``) as well as after
    every API response, and the store is rewritten on both. ``updated_at`` thus
    says "last rendered", not "last active". These counters are advanced by
    Claude Code only on an API round-trip or a new user prompt, so an identical
    fingerprint across two ingests means nothing happened in between.

    KNOWN LIMIT: these are API-traffic facts, so a session that is busy WITHOUT
    talking to the API — a long tool call, a subagent whose usage does not reach
    the parent's counters — looks dormant. ``idle`` therefore means "no API
    traffic for a while", which is a good proxy for "nobody working" but not the
    same claim. Consumers should treat it as a dimming cue, never as grounds to
    reclaim or interrupt a session.

    Returns None when the payload carries NONE of these facts. Absent data is
    not the same as absent activity: without evidence we must not claim a
    session is idle, or a payload shape we do not recognise would report every
    session dormant forever.
    """
    cost = _section(payload, "cost")
    window = _section(payload, "context_window")
    cache = _section(payload, "prompt_cache")
    fingerprint = (
        payload.get("prompt_id"),
        cost.get("total_cost_usd"),
        cost.get("total_api_duration_ms"),
        window.get("total_input_tokens"),
        window.get("total_output_tokens"),
        cache.get("requests"),
    )
    return fingerprint if any(field is not None for field in fingerprint) else None


def _active_at(previous: Any, payload: dict[str, Any], now: float) -> float:
    """``now`` when the activity fingerprint moved (or on first sight), else the
    prior ``active_at`` carried forward. A prior entry without one (pre-upgrade
    store) starts the clock at ``now``."""
    if not isinstance(previous, dict):
        return now
    prior_payload = previous.get("payload")
    prior_active = _number(previous.get("active_at"))
    if not isinstance(prior_payload, dict) or prior_active is None:
        return now
    # A timestamp from the future is not trustworthy (a clock step, or a
    # hand-edited store): start the clock again rather than carry it forward
    # and report the session idle-free until wall clock catches up.
    if prior_active > now:
        return now
    prior_fingerprint = _activity_fingerprint(prior_payload)
    fingerprint = _activity_fingerprint(payload)
    if prior_fingerprint is None and fingerprint is None:
        # Evidence-free on BOTH sides, so nothing observable changed. Carry the
        # prior stamp: a TUI opened and never prompted carries no fingerprint
        # fields at all, and it is the archetypal idle session — returning
        # ``now`` here would make it permanently non-idle, which is the feature
        # failing silently in exactly the case it exists for.
        return prior_active
    if prior_fingerprint is None or fingerprint is None:
        # Evidence appeared or vanished between ingests. That is a change we
        # cannot interpret, so treat it as activity rather than guess.
        return now
    if prior_fingerprint != fingerprint:
        return now
    return prior_active


def _entry_activity(entry: dict[str, Any]) -> float:
    """When this entry last showed real activity, for RANKING entries.

    ``active_at`` when the entry has a usable one, else ``updated_at``, else 0.

    Every reader that picks "the freshest session" must rank on this rather than
    on ``updated_at``. The status line reruns on a timer, so ``updated_at``
    ranks a dormant TUI above a session that is actually working — which is the
    whole ambiguity this module exists to remove.
    """
    active = _number(entry.get("active_at"))
    if active is not None:
        return active
    return _number(entry.get("updated_at")) or 0.0


def _prune(sessions: dict[str, Any], now: float) -> None:
    dead = [
        sid
        for sid, entry in sessions.items()
        if not isinstance(entry, dict)
        or now - (_number(entry.get("updated_at")) or 0.0) > SESSION_TTL_SECONDS
    ]
    for sid in dead:
        sessions.pop(sid, None)


def _git_branch(worktree_cwd: str | None) -> str | None:
    """The current branch name at ``worktree_cwd``, or None on ANY failure.

    Quarantine-safe by construction: a missing git binary, a non-repo cwd, a
    detached HEAD, or a slow/hanging git process must never raise or block —
    census's whole contract is to never break the status line. Bounded by a
    short timeout so a stalled git process cannot hang the caller.
    """
    if not worktree_cwd:
        return None
    try:
        result = subprocess.run(
            ["git", "-C", worktree_cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=_GIT_BRANCH_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    if not branch or branch == "HEAD":  # blank, or detached HEAD
        return None
    return branch


_COMPUTE: Any = object()   # merge(): look the branch up itself


def merge(
    store: dict[str, Any],
    payload: dict[str, Any],
    worktree: str | None,
    tmux_pane: str | None,
    now: float,
    branch: Any = _COMPUTE,
) -> dict[str, Any]:
    """Fold one status-line payload into ``store`` in place; return ``store``.

    - Upserts the session entry keyed by ``session_id`` (no-op without one).
    - Preserves the prior context window when the incoming one is blank.
    - Stamps ``active_at`` only when the activity fingerprint moved, so a
      timer-driven rerun of the status line refreshes ``updated_at`` alone.
    - Prunes stale sessions.

    ``branch`` is the already-looked-up branch name (a subprocess, so ``ingest``
    computes it before taking the lock); left out, it is looked up here.
    """
    sid = payload.get("session_id")
    if not isinstance(sid, str) or not sid:
        return store

    sessions = store["sessions"]
    previous = sessions.get(sid)

    carried = False
    if _context_is_blank(payload) and isinstance(previous, dict):
        prior_payload = previous.get("payload")
        if isinstance(prior_payload, dict) and isinstance(
            prior_payload.get("context_window"), dict
        ):
            payload = {**payload, "context_window": prior_payload["context_window"]}
            carried = True   # the reading is the previous one, not a fresh one

    active = _active_at(previous, payload, now)
    sessions[sid] = {
        "worktree_cwd": worktree,
        "updated_at": now,
        "active_at": active,
        "branch": _git_branch(worktree) if branch is _COMPUTE else branch,
        "payload": payload,
    }
    if carried:
        sessions[sid]["carried"] = True
    # Sibling fields (worktree_cwd, payload) are replaced wholesale on every
    # ingest, not merged with the previous entry — an untethered session (e.g.
    # one that has moved out of tmux) must not go on reporting a stale pane.
    # tmux_pane follows the same rule: present this ingest → stored; absent →
    # the key is left out of the freshly-built dict, so a repeat ingest
    # without TMUX_PANE drops any pane recorded by a prior ingest.
    if tmux_pane is not None:
        sessions[sid]["tmux_pane"] = tmux_pane

    _prune(sessions, now)
    return store


def ingest(raw: str, now: float | None = None) -> None:
    """Parse a status-line payload from ``raw`` and record it. Never raises.

    Holds an exclusive ``fcntl.flock`` for the read-modify-write so concurrent
    per-turn writers from every session cannot lose each other's entries.
    """
    if now is None:
        now = time.time()
    try:
        payload = json.loads(raw)
    except ValueError:
        return
    if not isinstance(payload, dict) or not payload.get("session_id"):
        return

    worktree = worktree_cwd(payload)
    branch = _git_branch(worktree)   # a subprocess: never inside the census lock
    path = store_path()
    lock_path = path.with_name(path.name + ".lock")
    try:
        with os.fdopen(paths.open_private(lock_path, os.O_WRONLY | os.O_CREAT), "w") as lock:
            if not _acquire(lock):
                return
            store = _load(path)
            # census-card-claim-design.md §2: ingest runs as a child of the
            # session process (the status-line pipeline), so TMUX_PANE is
            # already in its environment — no new plumbing needed to capture it.
            tmux_pane = os.environ.get("TMUX_PANE") or None
            merge(store, payload, worktree, tmux_pane, now, branch)
            _atomic_write(path, store)
    except OSError:
        return
    _note_session(payload)   # independent of the store write: never under the census lock


def _note_session(payload: dict[str, Any]) -> None:
    """Side records for the context reader: this session has a status line, and
    which window this model has — learned, not configured. Never raises."""
    try:
        session.mark_statusline(str(payload["session_id"]))
        session.learn_from_payload(payload)
    except Exception:
        return


def _acquire(lock: Any) -> bool:
    for _ in range(_LOCK_ATTEMPTS):
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            time.sleep(_LOCK_DELAY_SECONDS)
    return False


# --- Readers -------------------------------------------------------------------


def for_session(sid: str) -> dict[str, Any] | None:
    """The stored entry for one session id, or None."""
    entry = _load(store_path()).get("sessions", {}).get(sid)
    return dict(entry) if isinstance(entry, dict) else None


def last_seen(cwd: Path, session_id: str | None = None) -> float | None:
    """When the status line last reported for ``session_id``, or (without one) for
    any session in ``cwd``'s worktree (same repository root); None if never.
    For ``status`` only: no staleness horizon, just the newest ``updated_at``."""
    sessions = _load(store_path()).get("sessions")
    if not isinstance(sessions, dict):
        return None
    if session_id is not None:
        own = sessions.get(session_id)
        return (_entry_ts(own) or None) if isinstance(own, dict) else None
    key = paths.worktree_key(cwd)
    newest: float | None = None
    for entry in sessions.values():
        where = entry.get("worktree_cwd") if isinstance(entry, dict) else None
        if not isinstance(where, str) or not where:
            continue
        ts = _entry_ts(entry)
        if ts and (newest is None or ts > newest) and paths.worktree_key(Path(where)) == key:
            newest = ts
    return newest


def _entry_ts(entry: dict) -> float:
    """The entry's ``updated_at`` as a float; malformed/missing reads as 0.0
    (i.e. beyond any staleness horizon) — quarantine-safe, never raises."""
    try:
        return float(entry.get("updated_at", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _fresh_entry(root: Path, now: float, session_id: str | None = None) -> dict | None:
    sessions = _load(store_path()).get("sessions")
    if not isinstance(sessions, dict):
        sessions = {}

    if session_id is not None:
        own = sessions.get(session_id)
        if isinstance(own, dict):
            # A session-id match IS this session — no worktree check needed,
            # and (crucially) no falling back to a sibling's entry if ours is
            # stale: that would resurrect the misattribution this guards
            # against. Stale own entry -> unavailable, full stop.
            ts = _entry_ts(own)
            if now - ts <= STALE_HORIZON_SECONDS:
                return own
            return None
        # Not in the store: unknown, never a sibling's reading in its place.
        return None

    key = normalise(str(root))
    best: dict | None = None
    best_rank = (-1.0, -1.0)
    for entry in sessions.values():
        if not isinstance(entry, dict) or entry.get("worktree_cwd") != key:
            continue
        if now - _entry_ts(entry) > STALE_HORIZON_SECONDS:
            continue    # horizon BEFORE ranking: a dormant sibling must not hide a live one
        # rank on activity (see _entry_activity), not on timer-driven updated_at
        rank = (_entry_activity(entry), _entry_ts(entry))
        if rank > best_rank:
            best_rank, best = rank, entry
    return best


def context_percent(
    root: Path, now: float | None = None, session_id: str | None = None
) -> int | None:
    """Live context % for ``root`` from census, or None if unavailable/stale.

    Uses census's pre-computed ``used_percentage``, which already divides by the
    session's real window size (200k or the extended 1M) — so this is correct
    without vigil knowing the window.

    When ``session_id`` is given and the store has an entry for it, that entry
    is used directly (still subject to the staleness horizon) — this is what
    keeps two live sessions sharing a worktree from reading each other's
    context %. A ``session_id`` the store has no entry for yields None (never a
    sibling's reading); the worktree scan, ranked by activity, serves only a
    call with no ``session_id``. A carried-forward reading yields None.
    """
    if now is None:
        now = time.time()
    entry = _fresh_entry(root, now, session_id)
    if entry is None or entry.get("carried"):
        return None
    return entry_percent(entry)


def entry_percent(entry: dict[str, Any]) -> int | None:
    """``used_percentage`` of one census entry, rounded; None when absent or unreadable."""
    payload = entry.get("payload")
    window = payload.get("context_window") if isinstance(payload, dict) else None
    pct = window.get("used_percentage") if isinstance(window, dict) else None
    if pct is None:
        return None
    try:
        return round(float(pct))
    except (TypeError, ValueError, OverflowError):
        return None
