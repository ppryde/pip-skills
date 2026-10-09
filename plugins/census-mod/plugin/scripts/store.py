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
    limits/<account key>.json    one per Claude ACCOUNT (not per folder), merged forward-only
        { "version": 2, "account": key, "org": ..., "org_name": ..., "billing": ...,
          "five_hour": {...}, "seven_day": {...}, <any other window>: {...},
          "updated_at": <epoch> }

``ingest`` takes no lock: a session writes only its own file (temp file +
``os.replace``), and limits only ever move forward, so racing writers cost at
most one refresh of a lower figure. ``read_all`` assembles the v1 view
(``{version: 1, limits, sessions}``) that ``census read`` prints. A legacy
``status.json`` (v1) is the old single-file store.
"""
from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from scripts import gitcache, resolve

STORE_ENV = "CENSUS_STORE"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
SCHEMA_VERSION = 2   # on-disk files (sessions/<sid>.json, limits.json)
VIEW_VERSION = 1     # the shape `census read` prints — unchanged from v1
SESSIONS_DIRNAME = "sessions"
LIMITS_DIRNAME = "limits"
LIMITS_FILENAME = "limits.json"   # the first v2 build's single file; migrated away
LEGACY_FILENAME = "status.json"
_SAFE_SID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")

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


def pointer_path() -> Path:
    """Where census publishes its own CLI location, for other tools to find."""
    return census_dir() / "cli.path"


def publish_location(cli: Path) -> None:
    """Record ``cli``'s resolved path in ``pointer_path()``, rewriting only on change.

    Atomic (temp file + ``os.replace``) so readers never see half a path. Never
    raises: a pointer that cannot be written must not disturb the status line.
    """
    try:
        target = pointer_path()
        wanted = str(cli.resolve()).encode("utf-8")
        try:
            if target.read_bytes() == wanted:
                return
        except OSError:
            pass
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), prefix=".cli.path.", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(wanted)
            os.replace(tmp, target)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:  # noqa: BLE001, S110 - best-effort pointer, never raises
        pass


def store_path() -> Path:
    """The LEGACY v1 single-file store; present only until migrated. A
    ``CENSUS_STORE`` ending ``.json`` names that file exactly (v1 honoured any name)."""
    override = os.environ.get(STORE_ENV)
    if override and Path(override).suffix == ".json":
        return Path(override)
    return census_dir() / LEGACY_FILENAME


def sessions_dir() -> Path:
    return census_dir() / SESSIONS_DIRNAME


_SAFE_KEY = _SAFE_SID
# The first six are identity, not limits: never served as a limit, never overwritten by one.
_LIMITS_META = ("version", "account", "org", "org_name", "billing")
_LIMITS_RESERVED = (*_LIMITS_META, "updated_at")

_ACCOUNTS: dict[str, dict[str, Any]] = {}


def reset_account_cache() -> None:
    """Forget resolved accounts (tests; a process normally resolves once)."""
    _ACCOUNTS.clear()


def _claude_json_path() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    return (Path(override) if override else Path.home()) / ".claude.json"


def _cfg_key() -> str:
    try:
        resolved = str(config_dir().resolve())
    except (OSError, RuntimeError):
        resolved = str(config_dir())
    return "cfg-" + hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]


def _text_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def account_info() -> dict[str, Any]:
    """The calling Claude account: ``{key, org, org_name, billing}``. Never raises.

    ``key`` is ``oauthAccount.accountUuid`` from the account's ``.claude.json``
    (``$CLAUDE_CONFIG_DIR/.claude.json``, else ``~/.claude.json``). Without one
    (a pure API key, a missing or malformed file, an unsafe value) it is
    ``cfg-`` + 12 hex of the SHA-256 of the resolved config dir. Cached per
    process, keyed by the file consulted.
    """
    try:
        path = _claude_json_path()
        cache_key = str(path)
    except Exception:  # noqa: BLE001 - e.g. no resolvable home
        return {"key": "cfg-unknown", "org": None, "org_name": None, "billing": None}
    cached = _ACCOUNTS.get(cache_key)
    if cached is not None:
        return cached
    info: dict[str, Any] = {"key": None, "org": None, "org_name": None, "billing": None}
    try:
        oauth = (_read_json(path) or {}).get("oauthAccount")
        uuid = oauth.get("accountUuid") if isinstance(oauth, dict) else None
        if isinstance(uuid, str) and _SAFE_KEY.fullmatch(uuid) and isinstance(oauth, dict):
            info = {
                "key": uuid,
                "org": _text_or_none(oauth.get("organizationUuid")),
                "org_name": _text_or_none(oauth.get("organizationName")),
                "billing": _text_or_none(oauth.get("billingType")),
            }
    except Exception:  # noqa: BLE001, S110 - fall back to the cfg- key
        pass
    if info["key"] is None:
        info["key"] = _cfg_key()
    _ACCOUNTS[cache_key] = info
    return info


def limits_dir() -> Path:
    return census_dir() / LIMITS_DIRNAME


def limits_path(key: str | None = None) -> Path:
    return limits_dir() / f"{key or account_info()['key']}.json"


def legacy_limits_path() -> Path:
    """The first v2 build's single ``limits.json``; present only until migrated."""
    return census_dir() / LIMITS_FILENAME


def safe_session_id(sid: object) -> str | None:
    """``sid`` when it is safe as a filename, else None (never a path escape)."""
    return sid if isinstance(sid, str) and _SAFE_SID.fullmatch(sid) else None


def session_path(sid: str) -> Path:
    return sessions_dir() / f"{sid}.json"


def _empty_store() -> dict[str, Any]:
    """An empty v1-shaped dict, the input to the pure ``merge``."""
    return {"version": VIEW_VERSION, "limits": None, "sessions": {}}


def _read_json(path: Path) -> dict[str, Any] | None:
    """A JSON object from ``path``, or None when missing, unreadable or not an object."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError, RecursionError):  # RecursionError: absurdly nested JSON
        return None
    return data if isinstance(data, dict) else None


_REPLACE_RETRIES = 3
_REPLACE_RETRY_SECONDS = 0.02


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` to ``path`` via a same-directory temp file and ``os.replace``.

    Atomic for readers on POSIX and Windows: they see the old file or the new one,
    never half of either. On Windows a replace can be briefly refused
    (PermissionError) while a reader has the target open, hence the short retry.
    Raises OSError for the caller to swallow.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle)
        for attempt in range(_REPLACE_RETRIES + 1):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == _REPLACE_RETRIES:
                    raise
                time.sleep(_REPLACE_RETRY_SECONDS)
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
    try:
        number = float(value)
    except OverflowError:  # an int too large for a float
        return None
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


_KNOWN_WINDOWS = ("five_hour", "seven_day")


def _is_window(value: Any, key: str | None = None) -> bool:
    """A rate-limit window: any object carrying ``used_percentage`` and ``resets_at``.

    The two windows v1 knew by name stay windows whatever they carry, so a
    half-formed reading is still gated and ordered, never stored verbatim."""
    if not isinstance(value, dict):
        return False
    return key in _KNOWN_WINDOWS or ("used_percentage" in value and "resets_at" in value)


def _live_limits(limits: Any, now: float, verbatim: bool = False) -> dict[str, Any] | None:
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

    Any key whose value is window-shaped is a window (``five_hour``, ``seven_day``,
    a future ``spend_limit``...). With ``verbatim`` an entry of any other shape is
    kept as is (its real shape is not known yet); identity keys never are.
    """
    if not isinstance(limits, dict):
        return None
    live: dict[str, Any] = {}
    for key, window in limits.items():
        if key in _LIMITS_RESERVED:
            continue
        if not _is_window(window, key):
            if verbatim and key not in _KNOWN_WINDOWS:
                live[key] = window
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


def _hoist_limits(
    store: dict[str, Any], incoming: dict[str, Any], now: float
) -> None:
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
    live = _live_limits(stored, now, verbatim=True) or {}
    merged = dict(live)

    changed = False
    for key, window in incoming.items():
        current = merged.get(key)
        if not _is_window(window, key):  # unknown shape: last write wins...
            if _is_window(current, key):
                continue  # ...but never over a live window
            if current != window or key not in merged:
                merged[key] = window
                changed = True
        elif not isinstance(current, dict) or _window_is_fresher(window, current):
            merged[key] = window
            changed = True

    # A window ``_live_limits`` just dropped (expired, or implausibly distant)
    # is a change to the account figure too.
    dropped = any(
        _is_window(value, key) and key not in live
        for key, value in stored.items()
        if key not in _LIMITS_RESERVED
    )

    # ``updated_at`` means "when the account figure last MOVED", not "when a
    # status line last rendered". A reading that loses the ordering leaves it
    # alone, so a latched figure cannot masquerade as a fresh observation.
    #
    # The v1 view serves it (``census read``), so it must tell the truth.
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


# The additive per-session ``git`` block: the git cache's fields, and the empty value of each.
_NO_GIT: dict[str, Any] = {
    "branch": None, "uncommitted": 0, "ahead": 0, "has_upstream": False, "detached": False,
}
GIT_FIELDS = tuple(_NO_GIT)


def _git_branch(worktree_cwd: str | None) -> str | None:
    """The current branch name at ``worktree_cwd``, or None on ANY failure.

    Read through the git cache (one ``git status`` pass per worktree per TTL,
    shared with the status-line drawer), so a warm ingest runs no git. Quarantine-
    safe by construction: a missing git binary, a non-repo cwd, a detached HEAD, or
    a slow/hanging git process must never raise or block — census's whole contract
    is to never break the status line.
    """
    return _branch_of(_git_state(worktree_cwd))


def _git_state(worktree_cwd: str | None) -> dict[str, Any]:
    """The git block for ``worktree_cwd`` from the git cache: exactly ``GIT_FIELDS``, null-safe
    (a missing cwd, a non-repo or a failed git is the empty block)."""
    if not worktree_cwd:
        return dict(_NO_GIT)
    state = gitcache.lookup(census_dir() / gitcache.DIRNAME, worktree_cwd)
    return {k: state.get(k, v) for k, v in _NO_GIT.items()}


def _branch_of(state: dict[str, Any]) -> str | None:
    """The top-level ``branch``: the block's branch, None on a detached HEAD."""
    return None if state.get("detached") else state.get("branch")


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _mod_git(payload: dict[str, Any]) -> dict[str, Any] | None:
    """The git block the census mod sent (``census_mod.git``), when every field has its
    proper type; None otherwise, so the cache fills the block instead."""
    mod = payload.get("census_mod")
    block = mod.get("git") if isinstance(mod, dict) else None
    if not isinstance(block, dict) or any(k not in block for k in _NO_GIT):
        return None
    branch = block["branch"]
    ok = (
        (branch is None or isinstance(branch, str))
        and _count(block["uncommitted"])
        and _count(block["ahead"])
        and isinstance(block["has_upstream"], bool)
        and isinstance(block["detached"], bool)
    )
    return {k: block[k] for k in _NO_GIT} if ok else None


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
    # The mod sends its own git state (census_mod.git) and needs no git here; otherwise one pass of the cache.
    git_block = _mod_git(payload) or _git_state(worktree)
    entry: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "worktree_cwd": worktree,
        "updated_at": now,
        "active_at": _active_at(previous, payload, now),
        "branch": _branch_of(git_block),
        "git": git_block,
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
    incoming = _live_limits(payload.get("rate_limits"), now, verbatim=True)
    if incoming:
        _hoist_limits(store, incoming, now)
    _prune(sessions, now)
    return store


def _stored_limits(key: str | None = None) -> dict[str, Any] | None:
    """An account's limits minus the file's identity fields (v1-compatible)."""
    data = _read_json(limits_path(key))
    if data is None:
        return None
    return {k: v for k, v in data.items() if k not in _LIMITS_META}


def _identity() -> dict[str, Any]:
    info = account_info()
    return {"account": info["key"], "org": info["org"],
            "org_name": info["org_name"], "billing": info["billing"]}


_LOCK_WAIT_SECONDS = 0.25   # how long a merge waits for another writer before going on without the lock
_LOCK_STALE_SECONDS = 5.0   # a lock older than this was left by a crashed writer
_MERGE_ATTEMPTS = 4


LOCK_HELD, LOCK_BUSY, LOCK_UNAVAILABLE = "held", "busy", "unavailable"


def _take_over_stale_lock(lock: Path) -> None:
    """Remove a lock left by a crashed writer, atomically. Rename it aside (only one waiter's rename can win the
    SAME file), then judge the file we actually hold: if it is not stale after all (a fresh lock took the name between
    our look and our rename) put it back with ``os.link``, which refuses to overwrite, instead of deleting it."""
    aside = lock.with_name(f"{lock.name}.stale.{os.getpid()}.{time.monotonic_ns()}")
    try:
        os.rename(lock, aside)
    except OSError:
        return   # someone else took it over first (or it was released)
    try:
        if time.time() - aside.stat().st_mtime > _LOCK_STALE_SECONDS:
            return
        try:
            os.link(aside, lock)   # a live lock we grabbed by mistake: give it back
        except OSError:
            pass
    except OSError:
        pass
    finally:
        _unlink(aside)


def _acquire_limits_lock(lock: Path) -> str:
    """Take the limits file's lock (``O_CREAT | O_EXCL``, portable).

    ``LOCK_HELD``: it is ours. ``LOCK_BUSY``: another live writer held it for the whole wait (``_LOCK_WAIT_SECONDS``):
    the caller must NOT write from a snapshot taken around then; it skips this merge and the session's next ingest
    carries the reading. ``LOCK_UNAVAILABLE``: the folder cannot hold a lock file at all, so the merge goes on without
    one and relies on re-reading before and after its write. The status line never blocks on any of this."""
    try:
        lock.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return LOCK_UNAVAILABLE
    deadline = time.monotonic() + _LOCK_WAIT_SECONDS
    while True:
        try:
            os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
            return LOCK_HELD
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > _LOCK_STALE_SECONDS:
                    _take_over_stale_lock(lock)
            except OSError:
                pass   # it vanished, or cannot be statted: either way the next pass looks again
            # every retry goes through the deadline and a short sleep, whatever happened above
            if time.monotonic() >= deadline:
                return LOCK_BUSY
            time.sleep(0.005)
        except OSError:
            return LOCK_UNAVAILABLE


def _release_limits_lock(lock: Path) -> None:
    _unlink(lock)


def _merged_limits_body(current: dict[str, Any], incoming: dict[str, Any], now: float) -> dict[str, Any]:
    holder: dict[str, Any] = {"limits": {k: v for k, v in current.items() if k not in _LIMITS_META}}
    _hoist_limits(holder, incoming, now)
    return {"version": SCHEMA_VERSION, **_identity(), **holder["limits"]}


def _keeps(after: dict[str, Any], body: dict[str, Any]) -> bool:
    """Does ``after`` hold every window of ``body`` or a fresher one? (Nothing of ours was clobbered by an older write.)"""
    for key, window in body.items():
        if key in _LIMITS_RESERVED or not _is_window(window, key):
            continue
        stored = after.get(key)
        if not isinstance(stored, dict) or _window_is_fresher(window, stored):
            return False
    return True


def _pending_files() -> list[Path]:
    """Readings queued by merges that had to skip (see ``_merge_limits_file``): one file per skipping writer, named
    ``<limits file>.pending.<pid>-<ns>`` so queueing needs no lock, and never ``*.json`` so no listing takes one for an account."""
    path = limits_path()
    try:
        return sorted(p for p in path.parent.iterdir() if p.name.startswith(f"{path.name}.pending.") and not p.name.endswith(".tmp"))
    except OSError:
        return []


def _queue_reading(incoming: dict[str, Any]) -> None:
    path = limits_path()
    try:
        _atomic_write(path.with_name(f"{path.name}.pending.{os.getpid()}-{time.monotonic_ns()}"), incoming)
    except OSError:
        pass   # best effort: the status line never fails on this


def _with_pending(incoming: dict[str, Any], files: list[Path]) -> dict[str, Any]:
    """``incoming`` plus every queued reading, window by window, the fresher of each pair (forward-only)."""
    merged = dict(incoming)
    for file in files:
        data = _read_json(file) or {}
        for key, window in data.items():
            if key in _LIMITS_RESERVED:
                continue
            if not _is_window(window, key):
                # unknown shape: kept verbatim as the main merge does (last write wins), never over a window
                if not _is_window(merged.get(key), key):
                    merged[key] = window
                continue
            current = merged.get(key)
            if not isinstance(current, dict) or _window_is_fresher(window, current):
                merged[key] = window
    return merged


def _merge_limits_file(incoming: dict[str, Any], now: float) -> None:
    """Forward-only merge into the calling account's limits file.

    Several sessions may merge at once, and a writer holding a stale snapshot must not replace a newer window. The
    merge runs under a short ``O_EXCL`` lock file (one per account file, never held across other work). A writer
    that waited out a live holder SKIPS its merge (the next ingest carries the reading) rather than write from a
    stale snapshot. Only where no lock file can be made at all does it go on unlocked: it looks again just before
    writing, merges onto what it finds, and checks afterwards that its figures survived, redoing the merge (bounded)
    if an older write landed on top. That unlocked path narrows the race but cannot close it. Written only on change.
    """
    path = limits_path()
    lock = path.with_name(path.name + ".lock")
    state = _acquire_limits_lock(lock)
    if state == LOCK_BUSY:
        # a live writer is mid-merge: do not write around it. Queue the reading in a file of its own; whichever
        # merge next gets the lock folds it in, even if that ingest carries no rate_limits at all.
        if incoming:
            _queue_reading(incoming)
        return
    held = state == LOCK_HELD
    queued = _pending_files()
    incoming = _with_pending(incoming, queued)
    try:
        confirmed = False
        for _ in range(_MERGE_ATTEMPTS):
            current = _read_json(path) or {}
            body = _merged_limits_body(current, incoming, now)
            if json.dumps(body, sort_keys=True) == json.dumps(current, sort_keys=True):
                confirmed = True   # already in the file
                break
            if (_read_json(path) or {}) != current:
                continue   # it changed since we read it: merge onto the new contents instead
            _atomic_write(path, body)
            if held or _keeps(_read_json(path) or {}, body):
                confirmed = True
                break
        if confirmed:   # only a merge we know landed lets the queue go; otherwise the next ingest tries again
            for file in queued:
                _unlink(file)
    finally:
        if held:
            _release_limits_lock(lock)


def _fold_old_limits(old: dict[str, Any], now: float) -> None:
    """Fold a pre-account limits dict (v1 ``status.json`` or v2 ``limits.json``) into
    the calling account's file through the forward-only merge."""
    old = {k: v for k, v in old.items() if k not in _LIMITS_META}
    path = limits_path()
    if not path.exists() and _create_limits_file(
        path, {"version": SCHEMA_VERSION, **_identity(), **old}
    ):
        return  # no account file existed: keep the legacy figures as they were
    # A file exists (or a fresh ingest just created it): merge, never overwrite.
    incoming = _live_limits(old, now, verbatim=True)
    if incoming:
        _merge_limits_file(incoming, now)


def _create_limits_file(path: Path, body: dict[str, Any]) -> bool:
    """Create ``path`` only if it does not exist (hard link is exclusive and atomic).
    False when it already exists, so a concurrent fresher file is never clobbered.
    Where hard links are refused (FAT/exFAT, some SMB/FUSE mounts) it falls back to an
    ``O_EXCL`` create: still exclusive, though a reader may briefly see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(body, handle)
        os.link(tmp, path)
        return True
    except FileExistsError:
        return False
    except OSError:
        return _create_exclusive(path, body)
    finally:
        _unlink(Path(tmp))


def _create_exclusive(path: Path, body: dict[str, Any]) -> bool:
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w") as handle:
        json.dump(body, handle)
    return True


def _migrate_limits_json(now: float) -> None:
    """Move the first v2 build's folder-wide ``limits.json`` to the calling account."""
    legacy = legacy_limits_path()
    if legacy == store_path():  # a v1 store a user named limits.json: the status-file migration owns it
        return
    if not legacy.exists():
        return
    old = _read_json(legacy)
    if old is not None:
        _fold_old_limits(old, now)
    _unlink(legacy)


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
        _migrate_limits_json(now)
    except Exception:  # noqa: BLE001, S110 - a reader must never fail on migration
        pass
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
            _fold_old_limits(old_limits, now)
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
    for folder in (sessions_dir(), limits_dir(), census_dir()):
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
    gitcache.prune(census_dir() / gitcache.DIRNAME, SESSION_TTL_SECONDS, wall)
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
    info = account_info()
    entry["account"] = info["key"]
    entry["org"] = info["org"]
    _atomic_write(path, entry)
    incoming = _live_limits(payload.get("rate_limits"), now, verbatim=True)
    if incoming or _pending_files():   # an earlier merge's skipped reading is delivered by whichever ingest comes next
        _merge_limits_file(incoming or {}, now)
    _sweep(now)


# --- Readers -------------------------------------------------------------------


def _registry_proc_start(pid: int, config: Path | None = None) -> str | None:
    """``procStart`` from Claude Code's session registry file
    ``<config dir>/sessions/<pid>.json``, or None when the file is missing, unreadable
    or carries none. ``config`` defaults to the account's config dir."""
    folder = config if config is not None else config_dir()
    data = _read_json(folder / "sessions" / f"{pid}.json")
    start = data.get("procStart") if data else None
    return start if isinstance(start, str) else None


def _windows_pid_alive(pid: int) -> bool | None:
    """Is a process with this pid still running (Windows)? True/False, or None when the OS cannot be asked.

    OpenProcess with the least right that lets GetExitCodeProcess answer; STILL_ACTIVE (259) means running.
    Never ``os.kill``: on Windows any signal but CTRL_C/CTRL_BREAK terminates the target."""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except (ImportError, AttributeError, OSError):
        return None
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    ERROR_ACCESS_DENIED = 5
    # Without signatures ctypes assumes C int for every argument and result, which truncates a 64-bit HANDLE.
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Access denied: it exists, it is just not ours. Anything else (invalid parameter): no such process.
        return kernel32.GetLastError() == ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return None
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _process_gone(mod: dict[str, Any], config: Path | None) -> bool:
    """Is the session process named by ``census_mod`` gone? Its pid must be a real int
    above 1; ``os.kill(pid, 0)`` failing with anything but EPERM means gone; and the
    registry file must exist with a ``procStart`` string equal to the recorded
    ``proc_start`` (registry files outlive crashes, and a pid can be reused). The two
    strings are compared as text only; never against ``ps``."""
    pid = mod.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        return True
    if os.name == "nt":
        # os.kill(pid, 0) would TERMINATE the process here; ask the OS without touching it.
        if _windows_pid_alive(pid) is False:
            return True
    else:
        try:
            os.kill(pid, 0)
        except OSError as exc:
            # Only EPERM means "it exists, it is just not ours". EACCES (also a PermissionError), ESRCH and
            # anything else leave no process we can vouch for: gone.
            if exc.errno != errno.EPERM:
                return True
    recorded = mod.get("proc_start")
    return not isinstance(recorded, str) or _registry_proc_start(pid, config) != recorded


def is_stale(entry: dict[str, Any], now: float, config: Path | None = None) -> bool:
    """Is this session entry dead or closed? Never raises.

    An entry whose payload carries a ``census_mod`` block (recorded by the census mod, which
    does not write on a timer) is stale iff ``census_mod.ended`` is set or its process is
    gone (see ``_process_gone``), however old ``updated_at`` is; with no ``pid`` yet (the mod
    could not find its registry entry) the process is unknown and the entry is live unless
    ended. Any other entry is stale
    when not rendered for ``STALE_HORIZON_SECONDS``. ``config`` is the Claude config dir
    holding ``sessions/<pid>.json`` (default: the account's)."""
    try:
        payload = entry.get("payload")
        mod = payload.get("census_mod") if isinstance(payload, dict) else None
        if isinstance(mod, dict):
            if mod.get("ended"):  # a clean exit is final, whatever the pid says
                return True
            if mod.get("pid") is None:  # the mod has not found its process yet: unknown, not dead
                return False
            return _process_gone(mod, config)
    except Exception:  # noqa: BLE001 - a reader must never raise; an unjudgeable process is gone
        return True
    updated = _number(entry.get("updated_at")) or 0.0
    return (now - updated) > STALE_HORIZON_SECONDS


def _with_meta(
    entry: dict[str, Any], limits: Any, now: float, config: Path | None = None
) -> dict[str, Any]:
    """Decorate an entry with reader-side flags.

    ``stale``: the session is dead or closed (``is_stale``: by its process when the census
    mod recorded one, else not rendered for ``STALE_HORIZON_SECONDS``). ``idle``: it is still
    open but its activity counters have not moved for ``IDLE_HORIZON_SECONDS`` (open TUI,
    nobody working). An entry from a pre-``active_at`` store falls back to ``updated_at``.
    """
    active = _entry_activity(entry)
    result = dict(entry)
    result["stale"] = is_stale(entry, now, config)
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
    """The whole store as the v1 view: ``{version: 1, limits, sessions}``, each session
    with one additive key, ``stale`` (``is_stale``)."""
    migrate()
    when = time.time() if now is None else now
    sessions = {sid: {**entry, "stale": is_stale(entry, when)} for sid, entry in _all_sessions().items()}
    return {"version": VIEW_VERSION, "limits": _stored_limits(), "sessions": sessions}


def read_view(
    *, session: str | None = None, worktree: str | None = None, limits_only: bool = False, every_account: bool = False
) -> Any:
    """What ``census read`` prints (before it is JSON): the one place that picks the view, shared by the CLI and by
    vitals, which reads census in-process instead of running it. ``limits_only`` wins, then ``session``, then
    ``worktree``, else the whole store."""
    if limits_only:
        return all_limits() if every_account else limits()
    if session:
        return for_session(session)
    if worktree:
        return latest_for_worktree(worktree)
    return read_all()


def limits(now: float | None = None) -> dict[str, Any] | None:
    """The account rate-limit windows that are still live (future ``resets_at``).

    A window whose reset time has passed since it was written is dropped, so a
    reader never sees a fossil reading even if no fresh write has replaced it yet.
    """
    migrate()
    if now is None:
        now = time.time()
    return _live_limits(_stored_limits(), now, verbatim=True)


def all_limits(now: float | None = None) -> dict[str, Any]:
    """Every account's limits file in this folder, keyed by account key (minus ``version``)."""
    migrate()
    if now is None:
        now = time.time()
    out: dict[str, Any] = {}
    try:
        names = sorted(os.listdir(limits_dir()))
    except OSError:
        return out
    for name in names:
        if name.startswith(".") or not name.endswith(".json"):
            continue
        data = _read_json(limits_dir() / name)
        if data is None:
            continue
        live = _live_limits(data, now, verbatim=True) or {}
        meta = {k: v for k, v in data.items() if k in _LIMITS_RESERVED and k != "version"}
        out[name[: -len(".json")]] = {**{k: meta[k] for k in meta if k != "updated_at"}, **live,
                                      **({"updated_at": meta["updated_at"]} if "updated_at" in meta else {})}
    return out


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
    return _with_meta(best, _live_limits(_stored_limits(), now, verbatim=True), now)


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
    return _with_meta(_view_entry(entry), _live_limits(_stored_limits(), now, verbatim=True), now)
