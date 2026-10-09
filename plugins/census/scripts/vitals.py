#!/usr/bin/env python3
"""/census:vitals — an on-demand readout of this session's vital signs.

Gathers from three read-only sources and renders one of three styles:

- **census** (``census read``): the status-line payload (context window, model, cost,
  duration, prompt cache, the account's rate-limit windows), the session's ``git`` block
  (branch, uncommitted, ahead, upstream) and the payload's ``pr`` (number, url, review state).
  Read through this plugin's own ``cli.py`` first; ``CENSUS_CLI`` overrides it.
- **git**: only when the census entry has no ``git`` block (a record from before it): one
  ``git status --porcelain=2 --branch -uno``. Never ``gh``: the PR comes from the payload.
- **the transcript** (``transcript_path`` from the payload): tool calls by name and subagent
  spawns.

Every source is optional and fail-safe: a missing one leaves its lines out,
it never raises. Pure stdlib.

Styles are sized for a phone (no line wider than 44 columns; free text such as
branch, session and tool names is clipped to fit):
``compact`` (six lines), ``detailed`` (sections, pace forecasts, tool
breakdown), ``playful`` (the Witchfinder's reading).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import shlex
import shutil
import subprocess
import tempfile
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # run as a script: put the plugin root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import gitcache, store

STALE_SECONDS = 90  # census: not rendered for 90s (idle without refreshInterval, or closed)
MAX_RESET_SECONDS = 10 * 86400  # census's own ceiling: further out is a corrupt/ms value
TIMEOUT_SECONDS = 4
WINDOW_SECONDS = {"five_hour": 5 * 3600, "seven_day": 7 * 86400}
WINDOW_LABEL = {"five_hour": "5h", "seven_day": "7d"}
AGENT_TOOLS = {"Agent", "Task"}
STYLES = ("compact", "detailed", "playful")
ALIASES = {
    "lean": "compact",
    "brief": "compact",
    "full": "detailed",
    "trend": "detailed",
    "drama": "playful",
    "witchfinder": "playful",
}


# --------------------------------------------------------------------------- data


@dataclass
class Window:
    """One rate-limit window: percent used and when it resets (epoch secs)."""

    key: str
    used: float
    resets_at: float

    @property
    def label(self) -> str:
        return WINDOW_LABEL.get(self.key) or clip(self.key.replace("_", " "), 12)

    def pace(self, now: float) -> float | None:
        """Projected percent at reset if usage continues at the rate so far
        this window. None for an unknown window length or too early to tell
        (under 5% of the window elapsed)."""
        length = WINDOW_SECONDS.get(self.key)
        if length is None:
            return None
        elapsed = length - (self.resets_at - now)
        if elapsed < length * 0.05:
            return None
        return self.used * length / elapsed


@dataclass
class Vitals:
    """Everything a style can show. Any field may be absent (None / empty)."""

    now: float
    session_id: str | None = None
    session_name: str | None = None
    stale: bool = False
    idle: bool = False
    age: float | None = None  # seconds since census last recorded this session (status-line render or mod event)
    borrowed: bool = False  # reading is another session's (worktree fallback)
    has_reading: bool = False
    model: str | None = None
    effort: str | None = None
    ctx_pct: float | None = None
    ctx_tokens: int | None = None
    ctx_size: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    api_ms: int | None = None
    lines_added: int | None = None
    lines_removed: int | None = None
    cache_hit: float | None = None
    cache_expires_at: float | None = None
    windows: list[Window] = field(default_factory=list)
    branch: str | None = None
    dirty: int | None = None
    ahead: int | None = None  # None without an upstream: there is nothing to be ahead of
    pr_number: int | None = None
    pr_state: str | None = None
    tools: Counter[str] = field(default_factory=Counter)
    prompts: int | None = None

    @property
    def tool_calls(self) -> int:
        return sum(self.tools.values())

    @property
    def agents(self) -> int:
        return sum(self.tools[name] for name in AGENT_TOOLS)


# ------------------------------------------------------------------------ helpers


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if math.isfinite(f) else None


def _int(value: Any) -> int | None:
    n = _num(value)
    return None if n is None else int(n)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _ok(result: subprocess.CompletedProcess[str]) -> str | None:
    return result.stdout if result.returncode == 0 else None


def _git(*args: str, cwd: str | None = None) -> str | None:
    """stdout of ``git <args>``, or None on any failure. Never raises."""
    try:
        return _ok(
            subprocess.run(
                ["git", "--no-optional-locks", *args],
                cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False,
            )
        )
    except (OSError, subprocess.SubprocessError):
        return None


# ------------------------------------------------------------------------- census


def _runnable(text: str) -> Path | None:
    """``text`` as ONE path (never split, never shell-interpreted, so an env value
    cannot smuggle arguments): returned only if it is absolute, a regular file, and
    a Python script (run under this interpreter) or an executable."""
    if not text or "\0" in text or "\n" in text:
        return None
    path = Path(text)
    if not path.is_absolute() or not path.is_file():
        return None
    return path if path.suffix == ".py" or os.access(path, os.X_OK) else None


def census_cli() -> Path | None:
    """Where census's CLI is. ``CENSUS_CLI`` is authoritative when set (and refused, not
    skipped past, when it is not runnable). Otherwise this plugin's own ``cli.py`` beside
    this file, then census's ``cli.path`` pointer, then ``census`` on PATH. Whatever it
    names must pass ``_runnable``."""
    override = os.environ.get("CENSUS_CLI")
    if override:
        return _runnable(override)
    if (own := _runnable(str(Path(__file__).resolve().with_name("cli.py")))) is not None:
        return own
    # census's own rule for where cli.path lives (a CENSUS_STORE ending .json is the legacy file: its parent holds it)
    folder = store.census_dir()
    try:
        recorded = _runnable((folder / "cli.path").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        recorded = None
    if recorded:
        return recorded
    found = shutil.which("census")
    return _runnable(found) if found else None


def _one_arg(text: str) -> str:
    """``text`` as exactly one argv element: quoted for a shell, then split back, so it is provably a single
    token (list-form argv never reaches a shell anyway)."""
    (token,) = shlex.split(shlex.quote(text))
    return token


def _census_read(args: list[str]) -> dict[str, Any] | None:
    cli = census_cli()
    if cli is None:
        return None
    program, extra = _one_arg(str(cli)), [_one_arg(a) for a in args]
    try:
        if cli.suffix == ".py":
            done = subprocess.run(
                [sys.executable, program, "read", *extra],
                capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False,
            )
        else:
            done = subprocess.run(
                [program, "read", *extra],
                capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False,
            )
    except (OSError, subprocess.SubprocessError):
        return None
    out = _ok(done)
    if not out:
        return None
    try:
        data = json.loads(out)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data else None


def census_entry(session_id: str | None, cwd: str) -> dict[str, Any] | None:
    """This session's census entry; the freshest for the worktree when the
    session has none (or no id was given). A fallback entry may belong to a
    sibling session -- ``apply_census`` flags that as ``borrowed``."""
    if session_id:
        own = _census_read(["--session", session_id])
        if own:
            return own
    return _census_read(["--worktree", os.path.realpath(cwd)])


def apply_census(v: Vitals, entry: dict[str, Any]) -> None:
    """Fold a census entry (``census read`` v1 shape) into ``v``."""
    payload = _dict(entry.get("payload"))
    v.has_reading = True
    updated = _num(entry.get("updated_at"))
    if updated is not None:
        v.age = max(0.0, v.now - updated)
    # census judges liveness itself (by process for a census-mod session, which does not
    # write on a timer); only an entry with no verdict falls back to the age rule
    verdict = entry.get("stale")
    if isinstance(verdict, bool):
        v.stale = verdict
    else:
        v.stale = v.age is not None and v.age > STALE_SECONDS
    v.idle = bool(entry.get("idle"))
    owner = payload.get("session_id")
    if v.session_id and isinstance(owner, str) and owner != v.session_id:
        v.borrowed = True
    v.session_id = v.session_id or (owner if isinstance(owner, str) else None)
    v.session_name = payload.get("session_name") or None
    v.branch = v.branch or entry.get("branch") or None
    pr = _dict(payload.get("pr"))  # the status line's own PR facts: never a `gh` call
    v.pr_number = _int(pr.get("number")) or None
    state = pr.get("review_state")
    v.pr_state = str(state).lower() if isinstance(state, str) and state else None

    model = _dict(payload.get("model"))
    v.model = model.get("display_name") or model.get("id") or None
    v.effort = _dict(payload.get("effort")).get("level") or None

    ctx = _dict(payload.get("context_window"))
    v.ctx_pct = _num(ctx.get("used_percentage"))
    v.ctx_size = _int(ctx.get("context_window_size"))
    usage = _dict(ctx.get("current_usage"))
    parts = [
        _int(usage.get(k))
        for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    ]
    if any(p is not None for p in parts):
        v.ctx_tokens = sum(p or 0 for p in parts)
    if v.ctx_pct is None and v.ctx_tokens is not None and v.ctx_size:
        v.ctx_pct = 100 * v.ctx_tokens / v.ctx_size
    v.tokens_in = _int(ctx.get("total_input_tokens"))
    v.tokens_out = _int(ctx.get("total_output_tokens"))

    cost = _dict(payload.get("cost"))
    v.cost_usd = _num(cost.get("total_cost_usd"))
    v.duration_ms = _int(cost.get("total_duration_ms"))
    v.api_ms = _int(cost.get("total_api_duration_ms"))
    v.lines_added = _int(cost.get("total_lines_added"))
    v.lines_removed = _int(cost.get("total_lines_removed"))

    cache = _dict(payload.get("prompt_cache"))
    v.cache_hit = _num(cache.get("hit_ratio"))
    v.cache_expires_at = _num(cache.get("expires_at"))

    # The account's merged limits are authoritative; the payload's own copy is
    # this session's last sighting and may lag behind a busier sibling.
    limits = _dict(entry.get("limits")) or _dict(payload.get("rate_limits"))
    for key in sorted(limits, key=lambda k: (k not in WINDOW_SECONDS, WINDOW_SECONDS.get(k, 0))):
        win = _dict(limits[key])
        used, resets = _num(win.get("used_percentage")), _num(win.get("resets_at"))
        if used is not None and resets is not None and 0 < resets - v.now <= MAX_RESET_SECONDS:
            v.windows.append(Window(key, used, resets))


# ---------------------------------------------------------------------------- git


def _git_block(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    """The entry's census ``git`` block when it has the right shape, else None."""
    block = entry.get("git") if isinstance(entry, dict) else None
    if not isinstance(block, dict):
        return None
    branch, dirty, ahead = block.get("branch"), _int(block.get("uncommitted")), _int(block.get("ahead"))
    if (branch is not None and not isinstance(branch, str)) or dirty is None or ahead is None:
        return None
    if not isinstance(block.get("has_upstream"), bool):
        return None
    return block


def apply_git(v: Vitals, entry: dict[str, Any] | None, cwd: str) -> None:
    """Branch, uncommitted files and ahead from the session's census ``git`` block. Only an
    entry with none (written before the block existed) makes vitals ask git itself, once:
    ``git status --porcelain=2 --branch -uno`` in the worktree."""
    block = _git_block(entry)
    if block is None:
        recorded = (entry or {}).get("worktree_cwd")
        status = _git("status", "--porcelain=2", "--branch", "-uno", cwd=recorded if isinstance(recorded, str) else cwd)
        if status is None:
            return
        block = gitcache.parse_status(status)
    v.branch = block.get("branch") or v.branch
    v.dirty = _int(block.get("uncommitted"))
    v.ahead = _int(block.get("ahead")) if block.get("has_upstream") else None


# --------------------------------------------------------------------- transcript


def _is_prompt(rec: dict[str, Any], content: Any) -> bool:
    """A prompt the user typed: string content, or blocks with text (an image
    prompt). Not meta records, compaction summaries, command/caveat wrappers
    (``<...``), tool results or interruption markers."""
    if rec.get("isMeta") or rec.get("isCompactSummary"):
        return False
    if isinstance(content, str):
        return not content.startswith(("<", "[Request interrupted"))
    if isinstance(content, list):
        texts = [b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return any(
            isinstance(t, str) and not t.startswith(("<", "[Request interrupted")) for t in texts
        )
    return False


def apply_transcript(v: Vitals, path: Any) -> None:
    """Count tool calls by name and real user prompts. Streams the file and
    only parses lines that can matter, so a long transcript stays cheap."""
    if not isinstance(path, str) or not path:
        return
    tools: Counter[str] = Counter()
    prompts = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                is_tool = '"tool_use"' in line
                is_user = '"type":"user"' in line or '"type": "user"' in line
                if not (is_tool or is_user):
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(rec, dict) or rec.get("isSidechain"):
                    continue
                content = _dict(rec.get("message")).get("content")
                if rec.get("type") == "user":
                    prompts += _is_prompt(rec, content)
                    continue
                if rec.get("type") == "assistant" and isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tools[str(block.get("name") or "?")] += 1
    except (OSError, ValueError):  # ValueError: e.g. a NUL byte in the path
        return
    v.tools = tools
    v.prompts = prompts


# -------------------------------------------------------------------- formatting


def fmt_tokens(n: int | None) -> str:
    if n is None:
        return "?"
    if n >= 999_500:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1000:
        return f"{n / 1000:.1f}k".replace(".0k", "k") if n < 10_000 else f"{round(n / 1000)}k"
    return str(n)


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    m = s // 60
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h}h{m:02d}m" if m else f"{h}h"
    d, h = divmod(h, 24)
    return f"{d}d{h}h" if h else f"{d}d"


def fmt_reset(resets_at: float, now: float) -> str:
    """'in 2h18m (14:32)' within a day, else 'Sun 20:00'."""
    when = datetime.fromtimestamp(resets_at).astimezone()  # local wall clock
    if resets_at - now < 86400:
        return f"in {fmt_duration(resets_at - now)} ({when:%H:%M})"
    return f"{when:%a %H:%M}"


def fmt_cost(usd: float | None) -> str:
    return "?" if usd is None else f"${usd:.2f}"


def bar(pct: float | None, width: int = 10, full: str = "▰", empty: str = "▱") -> str:
    if pct is None:
        return empty * width
    filled = min(width, max(0, round(pct / 100 * width)))
    return full * filled + empty * (width - filled)


def gauge(pct: float | None) -> str:
    """Traffic-light emoji for a percent-used figure."""
    if pct is None:
        return "⚪"
    if pct >= 80:
        return "🔴"
    if pct >= 50:
        return "🟡"
    return "🟢"


def _columns(char: str) -> int:
    """Terminal columns one character takes: 2 for East Asian wide/fullwidth, 0 for combining."""
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def clip(text: str, limit: int) -> str:
    """``text`` cut to ``limit`` terminal columns, ending in an ellipsis if cut."""
    if sum(map(_columns, text)) <= limit:
        return text
    kept, used = [], 0
    for char in text:
        if used + _columns(char) > limit - 1:
            break
        kept.append(char)
        used += _columns(char)
    return "".join(kept) + "…" if limit > 0 else ""


def tool_label(name: str) -> str:
    """An MCP tool's own name (``mcp__server__ctx_search`` -> ``ctx_search``),
    clipped so a breakdown line fits a phone."""
    if name.startswith("mcp__"):
        name = name.rsplit("__", 1)[-1]
    return clip(name, 14)


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def pct(value: float | None) -> str:
    return "?%" if value is None else f"{round(value)}%"


def repo_line(v: Vitals, budget: int = 40) -> str | None:
    """Branch, then PR; the branch is clipped so the PR always shows."""
    if v.branch is None and v.pr_number is None:
        return None
    pr = ""
    if v.pr_number:
        pr = f" · PR #{v.pr_number}" + (f" {v.pr_state}" if v.pr_state else "")
    return clip(v.branch or "detached", budget - len(pr)) + pr


def sync_line(v: Vitals) -> str | None:
    if v.dirty is None:
        return None
    parts = ["clean" if v.dirty == 0 else f"{v.dirty} dirty"]
    if v.ahead is not None:
        parts.append(f"↑{v.ahead}")
    return " · ".join(parts)


def liveness(v: Vitals) -> str | None:
    """Why the figures may not be this session's live ones, or None."""
    if v.borrowed:
        return "another session's reading"
    if v.stale and v.age is not None:
        return f"reading is {fmt_duration(v.age)} old"
    if v.stale:
        return "reading may be stale"
    return None


# ------------------------------------------------------------------------- styles


def render_compact(v: Vitals) -> str:
    lines = []
    ctx = f"⚡ ctx {pct(v.ctx_pct)} {bar(v.ctx_pct)}"
    if v.ctx_tokens is not None:
        ctx += f" {fmt_tokens(v.ctx_tokens)}"
        if v.ctx_size:
            ctx += f"/{fmt_tokens(v.ctx_size)}"
    lines.append(ctx)
    mind = [clip(v.model or "model ?", 18)]
    if v.effort:
        mind.append(v.effort)
    if v.cost_usd is not None:
        mind.append(fmt_cost(v.cost_usd))
    lines.append("🧠 " + " · ".join(mind))
    if (repo := repo_line(v)) is not None:
        lines.append(f"🌿 {repo}")
    if (sync := sync_line(v)) is not None:
        lines.append(f"✎  {sync}")
    if any(w.key in WINDOW_SECONDS for w in v.windows):
        lines.append(
            "⏳ "
            + " · ".join(
                f"{w.label} {pct(w.used)} {gauge(w.used)} {fmt_duration(w.resets_at - v.now)}"
                for w in [w for w in v.windows if w.key in WINDOW_SECONDS][:2]
            )
        )
    clock = [fmt_duration((v.duration_ms or 0) / 1000) if v.duration_ms is not None else None]
    if v.tools:
        clock.append(f"{v.tool_calls} tools")
    if v.agents:
        clock.append(plural(v.agents, "agent"))
    if any(clock):
        lines.append("⏱  " + " · ".join(c for c in clock if c))
    if (live := liveness(v)) is not None:
        lines.append(f"⚠️  {live}")
    return "\n".join(lines)


def render_detailed(v: Vitals) -> str:
    out: list[str] = ["SESSION VITALS", "══════════════"]
    if v.session_name:
        out.append(f"“{clip(v.session_name, 40)}”")
    if (live := liveness(v)) is not None:
        out.append(f"⚠️  {live}")

    out += ["", f"💾 Context {pct(v.ctx_pct)} {bar(v.ctx_pct, 12)}"]
    if v.ctx_tokens is not None:
        size = f" of {fmt_tokens(v.ctx_size)}" if v.ctx_size else ""
        out.append(f"   ↳ {fmt_tokens(v.ctx_tokens)}{size} in window")
        if v.ctx_size:
            out.append(f"   ↳ {fmt_tokens(max(0, v.ctx_size - v.ctx_tokens))} headroom")
    if v.cache_hit is not None:
        cache = f"   ↳ cache hit {round(v.cache_hit * 100)}%"
        if v.cache_expires_at is not None:
            left = v.cache_expires_at - v.now
            cache += f" · warm {fmt_duration(left)}" if left > 0 else " · cold"
        out.append(cache)

    model = clip(v.model or "model ?", 22)
    out += ["", f"🧠 {model}" + (f" · effort {v.effort}" if v.effort else "")]
    if v.cost_usd is not None:
        out.append(f"   ↳ cost {fmt_cost(v.cost_usd)}")
    if v.tokens_in is not None or v.tokens_out is not None:
        out.append(f"   ↳ in {fmt_tokens(v.tokens_in)} · out {fmt_tokens(v.tokens_out)}")

    if (repo := repo_line(v)) is not None:
        out += ["", f"🌳 {repo}"]
        if (sync := sync_line(v)) is not None:
            out.append(f"   ↳ {sync}")
    if v.lines_added is not None:
        if repo_line(v) is None:
            out += ["", "🌳 not a git repo"]
        out.append(f"   ↳ +{v.lines_added} / -{v.lines_removed or 0} lines this session")

    if v.duration_ms is not None or v.tools:
        head = f"⏱  {fmt_duration(v.duration_ms / 1000)}" if v.duration_ms is not None else "⏱"
        if v.api_ms is not None:
            head += f" · API {fmt_duration(v.api_ms / 1000)}"
        out += ["", head]
        if v.prompts is not None:
            out.append(f"   ↳ {plural(v.prompts, 'prompt')} · {plural(v.tool_calls, 'tool call')}")
        if v.tools:
            top = [f"{tool_label(name)} {n}" for name, n in v.tools.most_common(6)]
            for i in range(0, len(top), 2):
                out.append(("   ↳ " if i == 0 else "     ") + " · ".join(top[i : i + 2]))
        if v.agents:
            out.append(f"   ↳ {plural(v.agents, 'subagent')} spawned")

    for w in v.windows:
        out += ["", f"📊 {w.label} limit {pct(w.used)} {gauge(w.used)} {bar(w.used, 12)}"]
        out.append(f"   ↳ resets {fmt_reset(w.resets_at, v.now)}")
        if (pace := w.pace(v.now)) is not None:
            verdict = "over the limit" if pace > 100 else "within"
            out.append(f"   ↳ pace → {pct(pace)} at reset ({verdict})")
    return "\n".join(out)


def _ctx_verse(p: float | None) -> str:
    if p is None:
        return "The breath cannot be measured."
    if p >= 80:
        return "The breath grows short. Hand over."
    if p >= 50:
        return "Half the breath is spent."
    return "The lungs are full and clear."


def _limit_verse(w: Window, now: float) -> str:
    pace = w.pace(now)
    if w.used >= 90:
        return "the gate is all but shut"
    if pace is not None and pace > 100:
        return "the pace offends the gate"
    if w.used >= 50:
        return "the ward holds, but strains"
    return "the gate stands open"


def _verdict(v: Vitals) -> str:
    worst_limit = max((w.used for w in v.windows), default=0.0)
    if not v.has_reading:
        return "The signs are hidden.\n   No census reading to judge."
    if (v.ctx_pct or 0) >= 80 or worst_limit >= 90:
        return "Found wanting.\n   Seek absolution: hand over."
    if (v.ctx_pct or 0) >= 50 or worst_limit >= 70 or (v.dirty or 0) > 20:
        return "Venial sins accrue.\n   Proceed with care."
    return "The soul is clean.\n   Continue with righteous purpose."


def render_playful(v: Vitals) -> str:
    out = ["🔮 THE SANCTUM'S VITAL SIGNS 🔮", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"]

    out += ["", "⚡ THE BREATH (context)", f"   {bar(v.ctx_pct, 16, '█', '░')} {pct(v.ctx_pct)}"]
    if v.ctx_tokens is not None and v.ctx_size:
        out.append(
            f"   {fmt_tokens(v.ctx_tokens)} drawn · {fmt_tokens(max(0, v.ctx_size - v.ctx_tokens))}"
            " remain"
        )
    out.append(f"   {_ctx_verse(v.ctx_pct)}")

    out += ["", "🧠 THE MIND", f"   {clip(v.model or 'an unknown spirit', 38)}"]
    if v.cost_usd is not None:
        out.append(f"   {fmt_cost(v.cost_usd)} tithed this session")
    if v.tokens_out is not None:
        out.append(f"   {fmt_tokens(v.tokens_out)} tokens of prophecy")

    if repo_line(v) is not None:
        out += ["", "📜 THE SANCTUM", f"   {repo_line(v, 38)}"]
        if v.dirty is not None:
            out.append(
                "   unblemished — nothing uncommitted"
                if v.dirty == 0
                else f"   {plural(v.dirty, 'file')} await penance"
            )
        if v.ahead:
            out.append(f"   {plural(v.ahead, 'commit')} unconfessed to the remote")

    if v.duration_ms is not None or v.tools:
        out += ["", "⏳ THE VIGIL"]
        if v.duration_ms is not None:
            out.append(f"   {fmt_duration(v.duration_ms / 1000)} in meditation")
        if v.tools:
            out.append(f"   {plural(v.tool_calls, 'act')} of devotion")
        if v.agents:
            out.append(f"   {plural(v.agents, 'spirit')} summoned")

    if v.windows:
        out += ["", "🚪 THE GATES (rate limits)"]
        for w in v.windows:
            out.append(f"   {gauge(w.used)} {w.label} {pct(w.used)}")
            out.append(f"      {_limit_verse(w, v.now)}")
            out.append(f"      reopens {fmt_reset(w.resets_at, v.now)}")

    out += ["", f"✨ {_verdict(v)}"]
    if (live := liveness(v)) is not None:
        out.append(f"   (⚠️  {live})")
    return "\n".join(out)


RENDERERS = {"compact": render_compact, "detailed": render_detailed, "playful": render_playful}


# --------------------------------------------------------------------------- main


def gather(session_id: str | None, cwd: str, *, now: float | None = None) -> Vitals:
    v = Vitals(now=time.time() if now is None else now, session_id=session_id)
    # Each source is independent: one failing (odd input we did not foresee)
    # must not hide the others.
    entry: dict[str, Any] | None = None
    with contextlib.suppress(Exception):
        entry = census_entry(session_id, cwd)
        if entry:
            apply_census(v, entry)
    with contextlib.suppress(Exception):
        apply_git(v, entry, cwd)
    if entry:
        with contextlib.suppress(Exception):
            apply_transcript(v, _dict(entry.get("payload")).get("transcript_path"))
    return v


def _clean_session(value: str | None) -> str | None:
    """An unexpanded ``${CLAUDE_SESSION_ID}`` (or blank) means 'unknown'."""
    if not value or value.startswith("$") or "{" in value:
        return None
    return value


def style_named(words: list[str]) -> str | None:
    """The first word naming a style or alias, as a style; None when none does."""
    for word in " ".join(words).split():
        w = word.lower()
        if w in STYLES:
            return w
        if w in ALIASES:
            return ALIASES[w]
    return None


def resolve_style(words: list[str]) -> str:
    """The first word naming a style or alias wins; otherwise compact."""
    return style_named(words) or "compact"


# ------------------------------------------------------------------- the saved default

PREF_FILE = "vitals.json"
NO_DEFAULT_MARKER = "(vitals: no default style chosen yet)"


def pref_path() -> Path:
    """Per account: beside the sessions, in the census dir (census's own rule, so a ``.json`` store works too)."""
    return store.census_dir() / PREF_FILE


def read_default() -> str | None:
    """The saved default style, or None when there is none or the file is unreadable or odd. Never raises."""
    try:
        data = json.loads(pref_path().read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return None
    style = data.get("default_style") if isinstance(data, dict) else None
    return style if isinstance(style, str) and style in STYLES else None


def write_default(style: str) -> None:
    """Save ``style`` atomically (same-directory temp file, then replace). Raises OSError."""
    path = pref_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{PREF_FILE}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"default_style": style}, handle)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _emit(text: str) -> None:
    """One line to stdout as UTF-8 bytes whatever the console's encoding says (every renderer prints emoji and box
    glyphs; a legacy Windows code page would raise on them). Same as ``cli._emit``."""
    data = (text + "\n").encode("utf-8")
    try:
        buffer = getattr(sys.stdout, "buffer", None)
        if buffer is not None:
            sys.stdout.flush()
            buffer.write(data)
            buffer.flush()
            return
    except (OSError, ValueError):
        pass
    sys.stdout.write(data.decode("utf-8", "replace") + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vitals", description=__doc__.splitlines()[0])
    parser.add_argument("words", nargs="*", help="style name or alias (from /census:vitals arguments)")
    parser.add_argument("--style", choices=STYLES)
    parser.add_argument("--set-default", metavar="STYLE", help="save the default style (lean|detailed|playful or an alias), then show it")
    parser.add_argument("--session", help="session id (default: freshest for the worktree)")
    parser.add_argument("--cwd", default=os.getcwd())
    args = parser.parse_args(argv)
    session = _clean_session(args.session) or _clean_session(os.environ.get("CLAUDE_SESSION_ID"))
    explicit = args.style or style_named(args.words)
    if args.set_default is not None:
        # exactly one name or alias, nothing else: "lean; ls" or "lean detailed" is not a style
        word = args.set_default.strip().lower()
        chosen = word if word in STYLES else ALIASES.get(word)
        if chosen is None:
            print(f"vitals: {args.set_default!r} is not a style; use lean, detailed or playful", file=sys.stderr)
            return 2
        try:
            write_default(chosen)
        except OSError as exc:
            _emit(f"(vitals could not save the default style: {type(exc).__name__}: {exc})")
            return 1
        _emit(f"(vitals: default style saved: {chosen})")
        explicit = chosen
    saved = None if explicit else read_default()
    style = explicit or saved or "compact"
    try:
        vitals = gather(session, args.cwd)
        reading = RENDERERS[style](vitals)
    except Exception as exc:  # noqa: BLE001 -- last line of defence: never dump a traceback
        _emit(f"(vitals could not read this session: {type(exc).__name__}: {exc})")
        return 0
    if not vitals.has_reading:
        _emit("(no census reading yet — census's status-line hook or the census-mod mod feeds it)")
    _emit(reading)
    if not explicit and saved is None:
        _emit(NO_DEFAULT_MARKER)  # the command asks the person once, then runs --set-default
    return 0


if __name__ == "__main__":
    sys.exit(main())
