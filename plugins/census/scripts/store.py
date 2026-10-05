"""Census store: lock-free per-session files plus one forward-merged limits file.

Quarantine-safe: every public entry point swallows read / parse / write
failures and never raises. A broken store must never break the status-line
render or the CLI command it piggybacks on.

Layout of ``~/.claude/census/`` (override with ``CENSUS_STORE``)::

    sessions/<session_id>.json   one file per session, written only by that session
        {
          "version": 2,
          "worktree_cwd": "<abs path>",
          "updated_at": <epoch - last time the status line ran for this session>,
          "active_at": <epoch - last time the session's activity counters moved>,
          "branch": "<current git branch, null when unresolvable/detached>",
          "tmux_pane": "<%N, absent when the session isn't running inside tmux>",
          "payload": { ...full status-line payload verbatim... }
        }
    limits.json                  account rate-limit windows, merged forward-only
        { "version": 2, "five_hour": {...}, "seven_day": {...}, "updated_at": <epoch> }

``ingest`` takes no lock: a session writes only its own file (temp file +
``os.replace``), and limits only ever move forward, so racing writers cost at
most one refresh of a lower figure. ``read_all`` assembles the v1 view
(``{version: 1, limits, sessions}``) that ``census read`` prints. A legacy
``status.json`` (v1) is the old single-file store.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from scripts import resolve

STORE_ENV = "CENSUS_STORE"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
SCHEMA_VERSION = 2   # on-disk files (sessions/<sid>.json, limits.json)
VIEW_VERSION = 1     # the shape `census read` prints — unchanged from v1
SESSIONS_DIRNAME = "sessions"
LIMITS_FILENAME = "limits.json"
LEGACY_FILENAME = "status.json"
_SAFE_SID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

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


def census_dir() -> Path:
    """This account's census directory.

    ``CENSUS_STORE`` overrides it. In v1 that variable named the ``status.json``
    file itself, so a value ending ``.json`` still means "its parent directory".
    """
    override = os.environ.get(STORE_ENV)
    if override:
        path = Path(override)
        return path.parent if path.suffix == ".json" else path
    return config_dir() / "census"


def store_path() -> Path:
    """The LEGACY v1 single-file store; present only until migrated."""
    return census_dir() / LEGACY_FILENAME


def sessions_dir() -> Path:
    return census_dir() / SESSIONS_DIRNAME


def limits_path() -> Path:
    return census_dir() / LIMITS_FILENAME


def safe_session_id(sid: object) -> str | None:
    """``sid`` when it is safe as a filename, else None (never a path escape)."""
    return sid if isinstance(sid, str) and _SAFE_SID.match(sid) else None


def session_path(sid: str) -> Path:
    return sessions_dir() / f"{sid}.json"


def _empty_store() -> dict[str, Any]:
    """An empty v1-shaped dict, the input to the pure ``merge``."""
    return {"version": VIEW_VERSION, "limits": None, "sessions": {}}


def _read_json(path: Path) -> dict[str, Any] | None:
    """A JSON object from ``path``, or None when missing, unreadable or not an object."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` to ``path`` via a same-directory temp file and ``os.replace``.

    ``os.replace`` is atomic on POSIX and Windows, so a reader sees the old file or
    the new one, never half of either. Raises OSError for the caller to swallow.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _unlink(path: Path) -> None:
    try:
        path.unlink()
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
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    if not branch or branch == "HEAD":  # blank, or detached HEAD
        return None
    return branch


def build_entry(
    previous: Any,
    payload: dict[str, Any],
    worktree: str | None,
    tmux_pane: str | None,
    now: float,
) -> dict[str, Any]:
    """The v2 session file body for one ingest (v1's per-session rules, unchanged)."""
    if _context_is_blank(payload) and isinstance(previous, dict):
        prior_payload = previous.get("payload")
        if isinstance(prior_payload, dict) and isinstance(
            prior_payload.get("context_window"), dict
        ):
            payload = {**payload, "context_window": prior_payload["context_window"]}
    entry: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "worktree_cwd": worktree,
        "updated_at": now,
        "active_at": _active_at(previous, payload, now),
        "branch": _git_branch(worktree),
        "payload": payload,
    }
    # Replaced wholesale each ingest: a session that left tmux must not keep a pane.
    if tmux_pane is not None:
        entry["tmux_pane"] = tmux_pane
    return entry


def merge(
    store: dict[str, Any],
    payload: dict[str, Any],
    worktree: str | None,
    tmux_pane: str | None,
    now: float,
) -> dict[str, Any]:
    """Fold one payload into a v1-shaped dict in place; return it. Pure (no I/O
    beyond git); kept for unit tests of the per-session and limits rules."""
    sid = payload.get("session_id")
    if not isinstance(sid, str) or not sid:
        return store
    sessions = store["sessions"]
    entry = build_entry(sessions.get(sid), payload, worktree, tmux_pane, now)
    entry.pop("version", None)
    sessions[sid] = entry
    incoming = _live_limits(payload.get("rate_limits"), now)
    if incoming:
        _hoist_limits(store, incoming, now)
    _prune(sessions, now)
    return store


def _stored_limits() -> dict[str, Any] | None:
    data = _read_json(limits_path())
    if data is None:
        return None
    data = dict(data)
    data.pop("version", None)
    return data


def _merge_limits_file(incoming: dict[str, Any], now: float) -> None:
    """Forward-only merge of live windows into ``limits.json``; no lock.

    Two sessions may race here. The ordering (``_window_is_fresher``) only moves
    forward, so the loser of a race costs one refresh of a lower figure, and the
    next write from the working session restores it. Written only on change.
    """
    stored = _stored_limits() or {}
    holder: dict[str, Any] = {"limits": stored}
    before = json.dumps(stored, sort_keys=True)
    _hoist_limits(holder, incoming, now)
    if json.dumps(holder["limits"], sort_keys=True) != before:
        _atomic_write(limits_path(), {"version": SCHEMA_VERSION, **holder["limits"]})


def _session_files() -> list[Path]:
    try:
        names = os.listdir(sessions_dir())
    except OSError:
        return []
    return [
        sessions_dir() / name
        for name in sorted(names)
        if not name.startswith(".") and name.endswith(".json")
    ]


_STRAY_TMP_SECONDS = 3600


MIGRATED_SUFFIX = ".v1-migrated"
MIGRATED_KEEP_SECONDS = 7 * 24 * 3600
_MIGRATE_LOCK = ".migrate.lock"
_MIGRATE_LOCK_STALE_SECONDS = 60


def migrate(now: float | None = None) -> bool:
    """Split a v1 ``status.json`` into v2 files, then retire it. Never raises.

    One migrator per account at a time: ``O_CREAT | O_EXCL`` on ``.migrate.lock``
    (portable, unlike flock). A lock older than a minute is a crashed migrator's
    and is broken. Returns True only when this call migrated.
    """
    if now is None:
        now = time.time()
    lock: Path | None = None
    try:
        legacy = store_path()
        if not legacy.exists():
            return False
        lock = census_dir() / _MIGRATE_LOCK
        # Lock age is wall-clock time.time() on purpose (mtime is wall-clock), unlike `now`.
        if lock.exists() and time.time() - lock.stat().st_mtime > _MIGRATE_LOCK_STALE_SECONDS:
            _unlink(lock)
        os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except Exception:  # noqa: BLE001 - a reader must never fail on migration
        return False
    try:
        data = _read_json(legacy) or {}
        sessions = data.get("sessions")
        for sid, entry in (sessions.items() if isinstance(sessions, dict) else []):
            safe = safe_session_id(sid)
            if safe is None or not isinstance(entry, dict):
                continue
            current = _read_json(session_path(safe))
            if current is not None and (_number(current.get("updated_at")) or 0.0) >= (
                _number(entry.get("updated_at")) or 0.0
            ):
                continue
            _atomic_write(session_path(safe), {"version": SCHEMA_VERSION, **entry})
        old_limits = data.get("limits")
        if isinstance(old_limits, dict):
            if not limits_path().exists():
                _atomic_write(limits_path(), {"version": SCHEMA_VERSION, **old_limits})
            else:
                incoming = _live_limits(old_limits, now)
                if incoming:
                    _merge_limits_file(incoming, now)
        os.replace(legacy, legacy.with_name(legacy.name + MIGRATED_SUFFIX))
        _unlink(legacy.with_name(legacy.name + ".lock"))
        for stray in census_dir().glob(".status.*.tmp"):
            _unlink(stray)
        return True
    except Exception:  # noqa: BLE001 - never raise from a reader
        return False
    finally:
        _unlink(lock)


def _sweep(now: float) -> None:
    """Ingest-side housekeeping: prune session files past the TTL (by their own
    ``updated_at`` against this ingest's ``now``, as v1 did) and delete stray temp
    files older than an hour (by mtime)."""
    for path in _session_files():
        entry = _read_json(path)
        if entry is None:
            # Unparseable: age it by mtime so a corrupt file cannot live forever.
            try:
                if time.time() - path.stat().st_mtime > SESSION_TTL_SECONDS:
                    _unlink(path)
            except OSError:
                pass
            continue
        if now - (_number(entry.get("updated_at")) or 0.0) > SESSION_TTL_SECONDS:
            _unlink(path)
    wall = time.time()
    for folder in (sessions_dir(), census_dir()):
        try:
            strays = [
                p for p in folder.iterdir() if p.name.startswith(".") and p.name.endswith(".tmp")
            ]
        except OSError:
            continue
        for stray in strays:
            try:
                if wall - stray.stat().st_mtime > _STRAY_TMP_SECONDS:
                    _unlink(stray)
            except OSError:
                pass
    retired = store_path().with_name(store_path().name + MIGRATED_SUFFIX)
    try:
        if wall - retired.stat().st_mtime > MIGRATED_KEEP_SECONDS:
            _unlink(retired)
    except OSError:
        pass


def ingest(raw: str, now: float | None = None) -> None:
    """Parse a status-line payload from ``raw`` and record it. Never raises.

    No lock: this session writes only its own file; limits merge forward-only.
    """
    try:
        _ingest(raw, time.time() if now is None else now)
    except Exception:  # noqa: BLE001 - quarantine: a broken store must never break the status line
        return


def _ingest(raw: str, now: float) -> None:
    migrate(now)
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        return
    sid = safe_session_id(payload.get("session_id"))
    if sid is None:
        return
    path = session_path(sid)
    # census-card-claim-design.md section 2: ingest runs inside the session's
    # status line, so TMUX_PANE is already in its environment.
    tmux_pane = os.environ.get("TMUX_PANE") or None
    entry = build_entry(_read_json(path), payload, resolve.worktree_cwd(payload), tmux_pane, now)
    _atomic_write(path, entry)
    incoming = _live_limits(payload.get("rate_limits"), now)
    if incoming:
        _merge_limits_file(incoming, now)
    _sweep(now)


# --- Readers -------------------------------------------------------------------


def _with_meta(entry: dict[str, Any], limits: Any, now: float) -> dict[str, Any]:
    """Decorate an entry with reader-side flags.

    ``stale``: the status line has not run for this session recently (dead or
    closed session). ``idle``: it is still rendering but its activity counters
    have not moved for ``IDLE_HORIZON_SECONDS`` (open TUI, nobody working).
    An entry from a pre-``active_at`` store falls back to ``updated_at``.
    """
    updated = _number(entry.get("updated_at")) or 0.0
    active = _entry_activity(entry)
    result = dict(entry)
    result["stale"] = (now - updated) > STALE_HORIZON_SECONDS
    result["idle"] = (now - active) > IDLE_HORIZON_SECONDS
    result["limits"] = limits
    return result


def _view_entry(entry: dict[str, Any]) -> dict[str, Any]:
    out = dict(entry)
    out.pop("version", None)
    return out


def _all_sessions() -> dict[str, dict[str, Any]]:
    sessions: dict[str, dict[str, Any]] = {}
    for path in _session_files():
        entry = _read_json(path)
        if entry is not None:
            sessions[path.name[: -len(".json")]] = _view_entry(entry)
    return sessions


def read_all(now: float | None = None) -> dict[str, Any]:
    """The whole store as the v1 view: ``{version: 1, limits, sessions}``."""
    migrate()
    return {"version": VIEW_VERSION, "limits": _stored_limits(), "sessions": _all_sessions()}


def limits(now: float | None = None) -> dict[str, Any] | None:
    """The account rate-limit windows that are still live (future ``resets_at``).

    A window whose reset time has passed since it was written is dropped, so a
    reader never sees a fossil reading even if no fresh write has replaced it yet.
    """
    migrate()
    if now is None:
        now = time.time()
    return _live_limits(_stored_limits(), now)


def latest_for_worktree(cwd: str, now: float | None = None) -> dict[str, Any] | None:
    """The most recently ACTIVE session entry indexed to ``cwd``, plus limits.

    Freshest means last active, not last rendered. Ranking on ``updated_at``
    would hand a worktree's answer to whichever of its sessions rendered most
    recently, and since the status line reruns on a timer that is routinely a
    dormant TUI rather than the session doing the work. Ties (equal activity,
    or entries predating ``active_at``) fall back to ``updated_at``.

    Returns None when no session matches. The result carries ``stale`` and
    ``idle`` flags so a consumer can distinguish a live reading from one frozen
    by a dead session, and a working session from a dozing one.
    """
    migrate()
    if now is None:
        now = time.time()
    key = resolve.normalise(cwd)

    best: dict[str, Any] | None = None
    best_rank = (-1.0, -1.0)
    for entry in _all_sessions().values():
        if entry.get("worktree_cwd") != key:
            continue
        rank = (_entry_activity(entry), _number(entry.get("updated_at")) or 0.0)
        if rank > best_rank:
            best_rank, best = rank, entry

    if best is None:
        return None
    return _with_meta(best, _live_limits(_stored_limits(), now), now)


def for_session(sid: str, now: float | None = None) -> dict[str, Any] | None:
    migrate()
    if now is None:
        now = time.time()
    safe = safe_session_id(sid)
    if safe is None:
        return None
    entry = _read_json(session_path(safe))
    if entry is None:
        return None
    return _with_meta(_view_entry(entry), _live_limits(_stored_limits(), now), now)
