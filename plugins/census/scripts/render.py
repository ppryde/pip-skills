"""Draw the status line: Pac-Man gauges and git state, emoji and plain Unicode only.

A port of the owner's ``statusline-command.sh`` rules into one stdlib process
(no ``jq``, no ``awk``, no bash), with the account's census limits and the git
cache folded in. ``draw`` is pure; ``statusline`` is the entry point that gathers
limits and git, then draws.

Configuration is read from the environment so it can live in ``settings.json``
``env``: ``CENSUS_STATUSLINE_SEGMENTS``, ``CENSUS_STATUSLINE_COLOR``,
``CENSUS_STATUSLINE_MASCOT``, ``CLAUDE_COST_BUDGET`` (and the git TTL, in
``gitcache``).
"""
from __future__ import annotations

import math
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

SEGMENTS_ENV = "CENSUS_STATUSLINE_SEGMENTS"
COLOR_ENV = "CENSUS_STATUSLINE_COLOR"
MASCOT_ENV = "CENSUS_STATUSLINE_MASCOT"
BUDGET_ENV = "CLAUDE_COST_BUDGET"
DEFAULT_SEGMENTS = "context,cache,limits,cost/model,git,dir,changes,pr"
DEFAULT_BUDGET = 20.0
BAR_WIDTH = 10

_CODES = {
    "reset": "0",
    "grey": "90",
    "cyan": "36",
    "green": "32",
    "yellow": "33",
    "magenta": "35",
    "pac": "93",  # bright yellow Pac-Man
    "white": "97",  # bright white: the track ahead of Pac-Man
    "red": "31",
    "orange": "38;5;208",
    "claude": "1;38;2;217;119;87",  # bold #D97757, the asterisk's own orange (truecolor)
}

# A canned payload for `census statusline --preview`.
PREVIEW_PAYLOAD: dict[str, Any] = {
    "session_id": "preview",
    "model": {"display_name": "Opus 5.5"},
    "workspace": {"current_dir": ""},  # filled with the working directory at draw time
    "context_window": {"used_percentage": 42},
    "cost": {"total_cost_usd": 3.10, "total_duration_ms": 6_480_000},
    "prompt_cache": {"hit_ratio": 0.93, "requests": 12, "warm": True, "expires_at": None, "misses": 0},
}


class Palette:
    """ANSI colour wrapper; with colour off every method is the identity."""

    def __init__(self, on: bool) -> None:
        self.on = on

    def code(self, name: str) -> str:
        return f"\x1b[{_CODES[name]}m" if self.on else ""

    def paint(self, name: str, text: str) -> str:
        return f"{self.code(name)}{text}{self.code('reset')}" if self.on else text


def level_colour_name(pct: float) -> str:
    """green below 75, orange from 75, red from 90."""
    if pct >= 90:
        return "red"
    if pct >= 75:
        return "orange"
    return "green"


def level_colour_inv_name(pct: float) -> str:
    """The inverted ramp, for gauges where HIGH is good: green from 90, orange from 75."""
    if pct >= 90:
        return "green"
    if pct >= 75:
        return "orange"
    return "red"


def level_colour(pct: float) -> str:
    return f"\x1b[{_CODES[level_colour_name(pct)]}m"


def level_colour_inv(pct: float) -> str:
    return f"\x1b[{_CODES[level_colour_inv_name(pct)]}m"


def _round(value: float) -> int:
    """printf "%.0f": round half to even."""
    return int(f"{value:.0f}")


def pac_bar(
    pct: float, width: int = BAR_WIDTH, glyph: str = "•", ahead: str | None = None, color: bool = True
) -> str:
    """A Pac-Man bar (no label). Pac-Man eats left to right; each eaten cell is
    coloured by its own slot (green, then orange, then red toward the right edge)
    and the track ahead is white. ``ahead`` is the glyph to the right (default
    ``glyph``): the cost gauge passes ``$``, so Pac-Man eats the dollars."""
    pal = Palette(color)
    ahead = glyph if ahead is None else ahead
    filled = int((pct / 100) * width + 0.5)
    filled = max(0, min(filled, width))
    paci = min(filled, width - 1)
    out = []
    for j in range(width):
        if j < paci:
            out.append(pal.paint(level_colour_name((j + 1) * 100 // width), glyph))
        elif j == paci:
            out.append(pal.paint("pac", "ᗧ"))
        else:
            out.append(pal.paint("white", ahead))
    return "".join(out)


def fmt_reset(target: float, now: float) -> str:
    """Compact time until ``target`` (epoch seconds): 2h10m, 45m, 3d4h."""
    diff = max(0, int(target - now))
    if diff >= 86400:
        return f"{diff // 86400}d{(diff % 86400) // 3600}h"
    if diff >= 3600:
        return f"{diff // 3600}h{(diff % 3600) // 60}m"
    return f"{diff // 60}m"


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _section(payload: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


# --- Segments: each returns a list of parts; every part is joined by the grey bar ---


class Ctx:
    def __init__(
        self,
        payload: Mapping[str, Any],
        env: Mapping[str, str],
        now: float,
        limits: Mapping[str, Any] | None,
        git: Mapping[str, Any],
    ) -> None:
        self.payload, self.env, self.now, self.limits, self.git = payload, env, now, limits, git
        self.pal = Palette(color_enabled(env))

    def cwd(self) -> str:
        workspace = _section(self.payload, "workspace")
        worktree = _section(self.payload, "worktree")
        for value in (worktree.get("path"), workspace.get("current_dir"), self.payload.get("cwd")):
            if isinstance(value, str) and value:
                return value
        return os.getcwd()


def _context_pct(payload: Mapping[str, Any]) -> float | None:
    window = _section(payload, "context_window")
    used = _num(window.get("used_percentage"))
    if used is not None:
        return used
    size = _num(window.get("context_window_size"))
    usage = window.get("current_usage")
    if size and isinstance(usage, dict):
        total = sum(
            _num(usage.get(k)) or 0.0
            for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        )
        return total / size * 100
    return None


def seg_context(c: Ctx) -> list[str]:
    pct = _context_pct(c.payload)
    if pct is None:
        bar = f"{c.pal.paint('pac', 'ᗧ')}{c.pal.paint('white', '•' * (BAR_WIDTH - 1))} {c.pal.paint('grey', '--%')}"
    else:
        shown = _round(pct)
        bar = f"{pac_bar(pct, color=c.pal.on)} {c.pal.paint(level_colour_name(shown), f'{shown}%')}"
    return [f"{c.pal.paint('grey', '🧠')} {bar}"]


def seg_cache(c: Ctx) -> list[str]:
    cache = _section(c.payload, "prompt_cache")
    ratio, requests = _num(cache.get("hit_ratio")), _num(cache.get("requests"))
    if ratio is None or not requests or requests <= 0:
        return []
    pct = _round(max(0.0, min(100.0, ratio * 100)))
    warm = cache.get("warm") is True
    pal = c.pal
    seg = f"{pal.paint('grey', '🎯' if warm else '🧊')} {pal.paint(level_colour_inv_name(pct), f'{pct}%')}"
    expires = _num(cache.get("expires_at"))
    if warm and expires is not None:
        seg += f" {pal.paint('grey', '⟳ ' + fmt_reset(expires, c.now))}"
    misses = _num(cache.get("misses"))
    if misses and misses > 0:
        seg += f" {pal.paint('red', f'✗{int(misses)}')}"
    return [seg]


def _usage_bar(c: Ctx, window: Any) -> str | None:
    if not isinstance(window, dict):
        return None
    pct = _num(window.get("used_percentage"))
    if pct is None:
        return None
    shown = _round(pct)
    out = f"{pac_bar(pct, color=c.pal.on)} {c.pal.paint(level_colour_name(shown), f'{shown}%')}"
    resets = _num(window.get("resets_at"))
    if resets is not None:
        out += f" {c.pal.paint('grey', '⟳ ' + fmt_reset(resets, c.now))}"
    return out


def seg_limits(c: Ctx) -> list[str]:
    parts = []
    for key, emoji in (("five_hour", "⏳"), ("seven_day", "📅")):
        window = (c.limits or {}).get(key)
        resets = _num(window.get("resets_at")) if isinstance(window, dict) else None
        if resets is not None and resets <= c.now:  # an expired window is a fossil
            continue
        bar = _usage_bar(c, window)
        if bar:
            parts.append(f"{c.pal.paint('grey', emoji)} {bar}")
    return parts


def _budget(env: Mapping[str, str]) -> float:
    try:
        value = float(env.get(BUDGET_ENV, ""))
    except ValueError:
        return DEFAULT_BUDGET
    return value if math.isfinite(value) else DEFAULT_BUDGET


def seg_cost(c: Ctx) -> list[str]:
    cost_data = _section(c.payload, "cost")
    cost = _num(cost_data.get("total_cost_usd"))
    if cost is None:
        return []
    budget = _budget(c.env)
    pct = 0 if budget <= 0 else max(0, _round(cost / budget * 100))
    bar = pac_bar(min(pct, 100), glyph="•", ahead="$", color=c.pal.on)  # colour on the uncapped pct below
    amount = c.pal.paint(level_colour_name(pct), f"${cost:.2f}")
    parts = [f"{c.pal.paint('grey', '💸')} {bar} {amount}"]
    duration = _num(cost_data.get("total_duration_ms"))
    if duration is not None and duration > 0:
        burn = cost / (duration / 3_600_000)
        burn_i = _round(burn)
        if burn_i >= 20:
            colour, emoji = "red", "🚀"
        elif burn_i >= 8:
            colour, emoji = "orange", "🔥"
        else:
            colour, emoji = "green", "🐌"
        value = str(burn_i) if burn_i >= 100 else f"{burn:.2f}"
        parts.append(f"{emoji} {c.pal.paint(colour, f'${value}/hr')}")
    return parts


def detect_account(env: Mapping[str, str]) -> str:
    """Which Claude config is active: CLAUDE_PROFILE, then CLAUDE_CONFIG_DIR, else work."""
    profile = env.get("CLAUDE_PROFILE")
    if profile:
        return "personal" if profile in ("personal", "home", "p") else "work"
    config = env.get("CLAUDE_CONFIG_DIR")
    if config:
        return "personal" if "personal" in config else "work"
    return "work"


DEFAULT_MASCOT = "✻"


def mascot(env: Mapping[str, str]) -> str:
    """The glyph before the model name: ``CENSUS_STATUSLINE_MASCOT`` (any string), else ✻."""
    return env.get(MASCOT_ENV) or DEFAULT_MASCOT


def _model(payload: Mapping[str, Any]) -> str:
    name = _section(payload, "model").get("display_name")
    return name if isinstance(name, str) and name else "Claude"


def seg_model(c: Ctx) -> list[str]:
    custom = c.env.get(MASCOT_ENV)
    # The default takes a two-column slot like an emoji (the ✻ plus one extra space), so the model name lines
    # up with the emoji-led segments above it; an override is drawn as given.
    glyph = custom if custom else c.pal.paint("claude", DEFAULT_MASCOT) + " "
    return [f"{glyph} {c.pal.paint('cyan', _model(c.payload))}"]


def seg_git(c: Ctx) -> list[str]:
    branch = c.git.get("branch")
    return [c.pal.paint("green", f"🌿 {branch}")] if branch else []


def seg_dir(c: Ctx) -> list[str]:
    cwd = c.cwd()
    parts = re.split(r"[\\/]", cwd)  # both separators: a Windows path is drawn like a POSIX one
    shown = cwd if len(parts) <= 3 else "…" + "".join("/" + p for p in parts[-3:])
    return [c.pal.paint("magenta", f"📁 {shown}")]


def seg_changes(c: Ctx) -> list[str]:
    if not c.git.get("branch"):
        return []
    seg = c.pal.paint("yellow", f"✏️ {int(c.git.get('uncommitted') or 0)}")
    ahead = int(c.git.get("ahead") or 0)
    if ahead > 0 and c.git.get("has_upstream"):
        seg += "  " + c.pal.paint("yellow", f"⬆️ {ahead}")
    return [seg]


_REVIEW_TONE = {"approved": "green", "pending": "yellow", "changes_requested": "red"}


def seg_pr(c: Ctx) -> list[str]:
    """The branch's open PR from the payload (never a ``gh`` call): ``🔀 #12 approved``. Hidden without one."""
    pr = _section(c.payload, "pr")
    number = pr.get("number")
    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        return []
    seg = f"🔀 #{number}"
    state = pr.get("review_state")
    if isinstance(state, str) and state:
        seg += " " + c.pal.paint(_REVIEW_TONE.get(state, "grey"), state)
    return [seg]


SEGMENTS: dict[str, Callable[[Ctx], list[str]]] = {
    "context": seg_context,
    "cache": seg_cache,
    "limits": seg_limits,
    "cost": seg_cost,
    "model": seg_model,
    "git": seg_git,
    "dir": seg_dir,
    "changes": seg_changes,
    "pr": seg_pr,
}


def color_enabled(env: Mapping[str, str]) -> bool:
    """``auto`` (default) is on unless NO_COLOR is set — stdout is a pipe under
    Claude Code, so there is no tty to test; ``always`` forces it, ``never`` strips it."""
    mode = env.get(COLOR_ENV, "auto").strip().lower()
    if mode == "never":
        return False
    if mode == "always":
        return True
    return not env.get("NO_COLOR")


def layout(env: Mapping[str, str]) -> list[list[str]]:
    """The configured segments as lines of segment names; unknown names are dropped."""
    spec = (env.get(SEGMENTS_ENV) or "").strip() or DEFAULT_SEGMENTS
    return [[n for n in (s.strip() for s in line.split(",")) if n in SEGMENTS] for line in spec.split("/")]


def draw(
    payload: Mapping[str, Any],
    env: Mapping[str, str],
    now: float,
    limits: Mapping[str, Any] | None,
    git: Mapping[str, Any],
) -> str:
    """The status line for ``payload``: one or two lines joined by newline, no trailing newline."""
    c = Ctx(payload, env, now, limits, git)
    sep = c.pal.paint("grey", " │ ")
    out = []
    for names in layout(env):
        parts = [part for name in names for part in SEGMENTS[name](c)]
        if parts:
            out.append(sep.join(parts))
    return "\n".join(out)


def fallback(payload: Mapping[str, Any] | None) -> str:
    return f"🤖 {_model(payload) if isinstance(payload, dict) else 'Claude'}"


def _resolve(value: Any) -> Any:
    return value() if callable(value) else value


def safe_draw(
    payload: Mapping[str, Any],
    env: Mapping[str, str],
    now: float,
    limits: Any,
    git: Any,
) -> str:
    """``draw`` that never raises: any error prints the one-line fallback.
    ``limits`` and ``git`` may be values or zero-argument callables."""
    try:
        return draw(payload, env, now, _resolve(limits), _resolve(git))
    except Exception:  # noqa: BLE001 - a status line must never print a traceback
        return fallback(payload)


def statusline(payload: Mapping[str, Any], env: Mapping[str, str] | None = None, now: float | None = None) -> str:
    """Gather the account's live limits and the cached git state, then draw."""
    from scripts import gitcache, resolve
    from scripts import store as st

    env = os.environ if env is None else env
    now = time.time() if now is None else now

    def git() -> dict[str, Any]:
        worktree = resolve.worktree_cwd(dict(payload)) or os.getcwd()
        return gitcache.lookup(st.census_dir() / gitcache.DIRNAME, worktree, now)

    return safe_draw(payload, env, now, lambda: st.limits(now), git)


def preview_payload(now: float | None = None) -> dict[str, Any]:
    """The canned payload with its working directory and cache expiry filled in."""
    now = time.time() if now is None else now
    payload = {k: (dict(v) if isinstance(v, dict) else v) for k, v in PREVIEW_PAYLOAD.items()}
    payload["workspace"] = {"current_dir": str(Path.cwd())}
    payload["prompt_cache"]["expires_at"] = now + 50 * 60
    return payload


_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def write_side_channel(raw: str, payload: Any, directory: str) -> None:
    """Stash the raw payload at ``<directory>/<session_id>.json`` (temp then replace)
    for the agent-ui watcher. Never raises."""
    try:
        sid = payload.get("session_id") if isinstance(payload, dict) else None
        if not isinstance(sid, str) or not _SAFE_FILENAME.match(sid):
            return
        folder = Path(directory)
        folder.mkdir(parents=True, exist_ok=True)
        # a unique, exclusively created temp: a predictable name could be a planted symlink
        fd, tmp = tempfile.mkstemp(dir=str(folder), prefix=f".{sid}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(raw)
            os.replace(tmp, folder / f"{sid}.json")
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:  # noqa: BLE001, S110 - best-effort, must never break the line
        pass
