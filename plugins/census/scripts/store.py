"""Census store: one worktree-indexed JSON file of status-line payloads.

Quarantine-safe: every public entry point swallows read / parse / lock / write
failures and never raises. A broken store must never break the status-line
render or the CLI command it piggybacks on.

Layout of ``~/.claude/census/status.json`` (override with ``CENSUS_STORE``)::

    {
      "version": 1,
      "limits": { "five_hour": {...}, "seven_day": {...}, "updated_at": <epoch> },
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

from scripts import resolve

STORE_ENV = "CENSUS_STORE"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
STORE_RELPATH = ("census", "status.json")
SCHEMA_VERSION = 1

SESSION_TTL_SECONDS = 24 * 3600      # prune entries older than this on write
STALE_HORIZON_SECONDS = 90           # readers flag entries older than this as stale
IDLE_HORIZON_SECONDS = 10 * 60       # readers flag sessions with no API activity for this long as idle
# Two readings whose reset boundaries are this close describe the SAME window.
# Observed boundaries are quantised to exactly 10 minutes and are bit-identical
# across concurrent sessions, and the closest two DISTINCT boundaries seen are
# 4h50m apart, so a minute of tolerance cannot merge two real windows.
_SAME_WINDOW_TOLERANCE_SECONDS = 60
# A reset further out than this is not a rate-limit window we know: the longest
# is seven days, so anything well beyond that is a corrupt or wrong-unit value
# (a millisecond epoch, say) and must not be served or allowed to win.
#
# Ten days rather than eight, to leave slack for a clock running BEHIND. The
# ceiling is measured against our own ``now``, so a machine two days slow would
# see a genuine seven-day window as nine days out and drop it, showing nothing
# where it could have shown something. The values this ceiling exists to reject
# are wrong by orders of magnitude, not by days, so the extra slack costs
# nothing: no real window falls in the eight-to-ten-day band, and no plausible
# corruption does either.
_MAX_WINDOW_HORIZON_SECONDS = 10 * 24 * 3600
_LOCK_ATTEMPTS = 50                  # 50 × 10ms = 0.5s bounded wait for the lock
_LOCK_DELAY_SECONDS = 0.01
_GIT_BRANCH_TIMEOUT_SECONDS = 2      # bounded wait; a hung/slow git must never hang the status line


def config_dir() -> Path:
    """The active Claude config dir — the account isolation boundary.

    Claude Code separates accounts by ``CLAUDE_CONFIG_DIR`` (e.g. a personal Max
    account under ``~/.claude-personal`` vs a default / work account under
    ``~/.claude``). The status line inherits this env var from the launching
    account, so rooting the store here keeps each account's sessions and rate
    limits in their own file — they never commingle across accounts.
    """
    override = os.environ.get(CONFIG_DIR_ENV)
    return Path(override) if override else Path.home() / ".claude"


def store_path() -> Path:
    override = os.environ.get(STORE_ENV)
    if override:
        return Path(override)
    return config_dir().joinpath(*STORE_RELPATH)


def _empty_store() -> dict[str, Any]:
    return {"version": SCHEMA_VERSION, "limits": None, "sessions": {}}


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
    if "limits" not in data:
        data["limits"] = None
    return data


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    # No evidence either way (an unrecognised payload shape): treat it as
    # activity rather than carrying an ageing timestamp toward "idle".
    if prior_fingerprint is None or fingerprint is None:
        return now
    if prior_fingerprint != fingerprint:
        return now
    return prior_active


_LIMIT_WINDOWS = ("five_hour", "seven_day")


def _live_limits(limits: Any, now: float) -> dict[str, Any] | None:
    """Keep only rate-limit windows whose reset time is still in the FUTURE.

    A window whose ``resets_at`` is in the past belongs to an EXPIRED window — a
    stale reading. The status line only refreshes ``rate_limits`` after an API
    response, so a dormant session (open TUI, no recent API call) keeps writing
    a fresh store entry whose ``rate_limits`` is frozen against a long-dead
    window. Hoisting or serving that reading makes the account-global figure
    flip-flop to whichever session wrote the file last. Gating on a future
    ``resets_at`` keeps only genuinely-current windows; an expired one is dropped.

    An implausibly distant ``resets_at`` is dropped too. Without that ceiling a
    single wrong-unit or corrupt value (a millisecond epoch reads as a reset
    tens of thousands of years out) would stay "live" forever and, being the
    latest window, would out-rank every honest reading indefinitely.
    """
    if not isinstance(limits, dict):
        return None
    live: dict[str, Any] = {}
    for key in _LIMIT_WINDOWS:
        window = limits.get(key)
        if not isinstance(window, dict):
            continue
        resets = _number(window.get("resets_at"))
        if resets is None:
            continue
        if now < resets <= now + _MAX_WINDOW_HORIZON_SECONDS:
            live[key] = window
    return live or None


def _window_is_fresher(incoming: dict[str, Any], stored: dict[str, Any]) -> bool:
    """Whether ``incoming`` supersedes ``stored`` for the same rate-limit window.

    Rate-limit usage is reported per window and only ever RISES until that
    window resets, so the two readings can be ordered without trusting any
    clock or any write order:

    - A meaningfully later ``resets_at`` is a NEWER window; its counter has
      restarted, so it wins outright however low its percentage.
    - A meaningfully earlier one belongs to a window already superseded, so it
      loses however high its percentage.
    - Boundaries within ``_SAME_WINDOW_TOLERANCE_SECONDS`` describe the same
      window and fall through to the usage comparison. Without that, two
      readings of one window differing by a second would invert the rule and
      let the lower percentage win.
    - Within the SAME window the higher percentage is the more recent reading.
      This is what stops a dormant session's frozen figure from winning: its
      percentage cannot exceed the one a working session has since reported.

    A reading with no usable percentage cannot be ordered, so it never displaces
    one that has a number, but it is taken when there is nothing to compare to.
    """
    incoming_resets = _number(incoming.get("resets_at"))
    stored_resets = _number(stored.get("resets_at"))
    if incoming_resets is None:
        return False
    if stored_resets is None:
        return True
    if incoming_resets > stored_resets + _SAME_WINDOW_TOLERANCE_SECONDS:
        return True
    if incoming_resets < stored_resets - _SAME_WINDOW_TOLERANCE_SECONDS:
        return False

    incoming_pct = _number(incoming.get("used_percentage"))
    stored_pct = _number(stored.get("used_percentage"))
    if incoming_pct is None:
        return False
    if stored_pct is None:
        return True
    return incoming_pct > stored_pct


def _hoist_limits(store: dict[str, Any], incoming: dict[str, Any], now: float) -> None:
    """Fold live rate-limit windows into top-level ``limits``, highest-usage-wins.

    ``resets_at`` gating alone is not enough. A dormant session's 5h window can
    still reset in the future while its ``used_percentage`` is frozen at
    whatever it was when that session last hit the API. Because the status line
    reruns on a timer, that session keeps rewriting the store, and a plain
    last-write-wins hoist lets its fossil percentage clobber a working
    session's current one — the account figure then flip-flops on every tick.

    So a window is only replaced by a reading that ``_window_is_fresher``
    orders above it. That ordering reads the readings themselves rather than
    any timestamp we assign, which makes it independent of write order AND of
    the system clock — a session whose clock has stepped cannot wedge a window,
    and no reading can become permanently unbeatable.
    """
    stored = store.get("limits")
    stored = stored if isinstance(stored, dict) else {}
    live = _live_limits(stored, now) or {}
    merged = dict(live)

    changed = False
    for key, window in incoming.items():
        current = merged.get(key)
        if not isinstance(current, dict) or _window_is_fresher(window, current):
            merged[key] = window
            changed = True

    # A window ``_live_limits`` just dropped (expired, or implausibly distant)
    # is a change to the account figure too.
    dropped = any(
        isinstance(stored.get(key), dict) and key not in live for key in _LIMIT_WINDOWS
    )

    # ``updated_at`` means "when the account figure last MOVED", not "when a
    # status line last rendered". A reading that loses the ordering leaves it
    # alone, so a latched figure cannot masquerade as a fresh observation.
    #
    # No reader is served this today: both ``_live_limits`` here and the
    # dashboard's own limits section whitelist the two window keys. The field
    # is written either way — it predates this ordering rule — so the choice is
    # not whether to have it but whether it tells the truth. Kept honest rather
    # than exposed: an API field nothing consumes would be dead surface.
    previous_updated = _number(stored.get("updated_at"))
    store["limits"] = {
        **merged,
        "updated_at": now if (changed or dropped or previous_updated is None) else previous_updated,
    }


def _prune(sessions: dict[str, Any], now: float) -> None:
    dead = [
        sid
        for sid, entry in sessions.items()
        if not isinstance(entry, dict)
        or now - float(entry.get("updated_at", 0) or 0) > SESSION_TTL_SECONDS
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


def merge(
    store: dict[str, Any],
    payload: dict[str, Any],
    worktree: str | None,
    tmux_pane: str | None,
    now: float,
) -> dict[str, Any]:
    """Fold one status-line payload into ``store`` in place; return ``store``.

    - Upserts the session entry keyed by ``session_id`` (no-op without one).
    - Preserves the prior context window when the incoming one is blank.
    - Stamps ``active_at`` only when the activity fingerprint moved, so a
      timer-driven rerun of the status line refreshes ``updated_at`` alone.
    - Hoists ``rate_limits`` to top-level ``limits``, but only LIVE windows
      (``resets_at`` in the future), and only when the incoming reading orders
      above the stored one — a frozen reading from a dormant session must not
      clobber the current account figure.
    - Prunes stale sessions.
    """
    sid = payload.get("session_id")
    if not isinstance(sid, str) or not sid:
        return store

    sessions = store["sessions"]
    previous = sessions.get(sid)

    if _context_is_blank(payload) and isinstance(previous, dict):
        prior_payload = previous.get("payload")
        if isinstance(prior_payload, dict) and isinstance(
            prior_payload.get("context_window"), dict
        ):
            payload = {**payload, "context_window": prior_payload["context_window"]}

    active = _active_at(previous, payload, now)
    sessions[sid] = {
        "worktree_cwd": worktree,
        "updated_at": now,
        "active_at": active,
        "branch": _git_branch(worktree),
        "payload": payload,
    }
    # Sibling fields (worktree_cwd, payload) are replaced wholesale on every
    # ingest, not merged with the previous entry — an untethered session (e.g.
    # one that has moved out of tmux) must not go on reporting a stale pane.
    # tmux_pane follows the same rule: present this ingest → stored; absent →
    # the key is left out of the freshly-built dict, so a repeat ingest
    # without TMUX_PANE drops any pane recorded by a prior ingest.
    if tmux_pane is not None:
        sessions[sid]["tmux_pane"] = tmux_pane

    incoming = _live_limits(payload.get("rate_limits"), now)
    if incoming:
        _hoist_limits(store, incoming, now)

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

    path = store_path()
    lock_path = path.with_name(path.name + ".lock")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w") as lock:
            if not _acquire(lock):
                return
            store = _load(path)
            # census-card-claim-design.md §2: ingest runs as a child of the
            # session process (the status-line pipeline), so TMUX_PANE is
            # already in its environment — no new plumbing needed to capture it.
            tmux_pane = os.environ.get("TMUX_PANE") or None
            merge(store, payload, resolve.worktree_cwd(payload), tmux_pane, now)
            _atomic_write(path, store)
    except OSError:
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


def _with_meta(entry: dict[str, Any], limits: Any, now: float) -> dict[str, Any]:
    """Decorate an entry with reader-side flags.

    ``stale``: the status line has not run for this session recently (dead or
    closed session). ``idle``: it is still rendering but its activity counters
    have not moved for ``IDLE_HORIZON_SECONDS`` (open TUI, nobody working).
    An entry from a pre-``active_at`` store falls back to ``updated_at``.
    """
    updated = _number(entry.get("updated_at")) or 0.0
    active = _number(entry.get("active_at"))
    if active is None:
        active = updated
    result = dict(entry)
    result["stale"] = (now - updated) > STALE_HORIZON_SECONDS
    result["idle"] = (now - active) > IDLE_HORIZON_SECONDS
    result["limits"] = limits
    return result


def read_all() -> dict[str, Any]:
    """The whole store, healed to a valid shape."""
    return _load(store_path())


def limits(now: float | None = None) -> dict[str, Any] | None:
    """The account rate-limit windows that are still live (future ``resets_at``).

    A window whose reset time has passed since it was written is dropped, so a
    reader never sees a fossil reading even if no fresh write has replaced it yet.
    """
    if now is None:
        now = time.time()
    return _live_limits(_load(store_path()).get("limits"), now)


def latest_for_worktree(cwd: str, now: float | None = None) -> dict[str, Any] | None:
    """The freshest session entry indexed to ``cwd``, plus top-level limits.

    Returns None when no session matches. The result carries a ``stale`` flag
    (True when older than the staleness horizon) so a consumer can distinguish a
    live reading from a frozen one left by a dead session.
    """
    if now is None:
        now = time.time()
    key = resolve.normalise(cwd)
    store = _load(store_path())

    best: dict[str, Any] | None = None
    best_ts = -1.0
    for entry in store.get("sessions", {}).values():
        if not isinstance(entry, dict) or entry.get("worktree_cwd") != key:
            continue
        ts = float(entry.get("updated_at", 0) or 0)
        if ts > best_ts:
            best_ts, best = ts, entry

    if best is None:
        return None
    return _with_meta(best, _live_limits(store.get("limits"), now), now)


def for_session(sid: str, now: float | None = None) -> dict[str, Any] | None:
    if now is None:
        now = time.time()
    store = _load(store_path())
    entry = store.get("sessions", {}).get(sid)
    if not isinstance(entry, dict):
        return None
    return _with_meta(entry, _live_limits(store.get("limits"), now), now)
