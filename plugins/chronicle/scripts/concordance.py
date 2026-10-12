"""Optional reader for concordance's replay numbers. chronicle never imports concordance: it
runs its CLI and stores the numeric rows it prints. No paths, patterns or content."""
from __future__ import annotations

import contextlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from scripts import report
from scripts.store import config_dir

FIELDS = ("tool_use_id", "agent_id", "kind", "estimator", "covered", "actual_tokens",
          "concordance_tokens", "latency_ms", "answerable", "drifted", "mode")
_INTS = ("actual_tokens", "concordance_tokens", "latency_ms")
_STRS = ("tool_use_id", "agent_id", "kind", "estimator", "answerable", "drifted", "mode")


def _valid(row: object) -> bool:
    return (isinstance(row, dict) and all(f in row for f in FIELDS)
            and all(isinstance(row[f], int) and not isinstance(row[f], bool) for f in _INTS)
            and all(isinstance(row[f], str) for f in _STRS)
            and isinstance(row["covered"], bool))


def store_rows(conn: sqlite3.Connection, session_id: str, rows: list[dict[str, object]]) -> int:
    """Replace the session's rows with the well-formed ones; return how many were stored."""
    # a repeated tool_use_id keeps its last row, so the count is what is stored
    good = list({r["tool_use_id"]: r for r in rows if _valid(r)}.values())
    with conn:
        conn.execute("DELETE FROM concordance_rows WHERE session_id = ?", (session_id,))
        conn.executemany(
            f"INSERT OR REPLACE INTO concordance_rows(session_id, {', '.join(FIELDS)}) "
            f"VALUES (?, {', '.join('?' for _ in FIELDS)})",
            [(session_id, *(r[f] for f in FIELDS)) for r in good])
    return len(good)


# The overseer dashboard runs `chronicle sync` under a 120 s timeout. The step must finish
# inside it: a replay starts only while its full REPLAY_TIMEOUT still fits in the budget, so
# the step never runs past STEP_BUDGET, nor sync past SYNC_CEILING; the remaining 30 s cover
# interpreter start-up, sync's teardown and the dashboard's spawn. A timeout is never
# shortened to fit, so a failure always means "needed more than REPLAY_TIMEOUT".
REPLAY_TIMEOUT = 30.0    # per session; a hung concordance costs at most this
STEP_BUDGET = 60.0       # whole step, replays included
SYNC_CEILING = 90.0      # sync + step, replays included
STARTED_TTL = 600.0      # a started marker this fresh means a replay may still be running


def step_budget(sync_elapsed: float) -> float:
    """Seconds the step may spend, replays included, given what sync already spent."""
    return max(0.0, min(STEP_BUDGET, SYNC_CEILING - sync_elapsed))


def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    """Run cmd in its own process group; on timeout kill the group, not just the child."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except BaseException:
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
        proc.kill()
        proc.communicate()
        raise
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


_exec: Callable[[list[str], float], subprocess.CompletedProcess[str]] = _run


def find_cli(env: Mapping[str, str] | None = None) -> Path | None:
    e = os.environ if env is None else env
    named = e.get("CONCORDANCE_CLI")
    if named:
        return Path(named) if Path(named).is_file() else None
    found = sorted((config_dir() / "plugins" / "cache").glob("*/concordance/*/scripts/cli.py"),
                   key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def run_replay(cli: Path, session_id: str, transcript: Path,
               timeout: float | None = None) -> list[dict[str, object]] | None:
    cmd = [sys.executable, str(cli), "replay", "--session", session_id,
           "--transcript", str(transcript), "--force"]  # chronicle already judged it finished
    try:
        proc = _exec(cmd, REPLAY_TIMEOUT if timeout is None else timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        rows = json.loads(proc.stdout)
    except ValueError:
        return None
    return rows if isinstance(rows, list) else None


def sync_step(conn: sqlite3.Connection, *, now: float | None = None, limit: int = 20,
              env: Mapping[str, str] | None = None,
              budget: float | None = None, sync_started: float | None = None,
              clock: Callable[[], float] = time.monotonic) -> dict[str, int]:
    """Replay finished sessions not yet replayed (or failed) at their current last activity.
    A failure is remembered per last_activity_at, so a session that keeps failing is
    skipped until it grows; a session whose replay started under STARTED_TTL ago and has no
    outcome is skipped too (chronicle may have been killed mid-replay). The budget is what
    the caller's timeout leaves after ``sync_started`` (a ``clock`` reading); a replay starts
    only while its full timeout still fits, and when not even one fits the step is skipped.
    Never raises."""
    out = {"replayed": 0, "failed": 0, "skipped": 0}
    e = os.environ if env is None else env
    if e.get("CHRONICLE_NO_CONCORDANCE") == "1":
        return out
    try:
        cli = find_cli(e)
        if cli is None:
            return out
        t = time.time() if now is None else now
        if budget is None:
            budget = step_budget(0.0 if sync_started is None else clock() - sync_started)
            if budget < REPLAY_TIMEOUT:   # not even one full replay fits
                out["skipped"] += 1
                return out
        # the marker is compared in Python: SQLite's REAL-to-TEXT cast differs from str(float)
        candidates = conn.execute(
            "SELECT s.session_id, s.last_activity_at, c.path, m.value, f.value, st.value "
            "FROM sessions s "
            "JOIN cursors c ON c.session_id = s.session_id AND c.agent_id = '' "
            "LEFT JOIN meta m ON m.key = 'concordance_replayed:' || s.session_id "
            "LEFT JOIN meta f ON f.key = 'concordance_failed:' || s.session_id "
            "LEFT JOIN meta st ON st.key = 'concordance_started:' || s.session_id "
            "WHERE s.last_activity_at IS NOT NULL AND s.last_activity_at < ? "
            "ORDER BY s.last_activity_at DESC",
            (t - report.LIVE_HORIZON_SECONDS,)).fetchall()
    except Exception as exc:  # noqa: BLE001 - optional reader: a bad store or lookup is a skip
        print(f"chronicle: concordance candidate lookup skipped: {exc!r}", file=sys.stderr)
        out["skipped"] += 1
        return out
    pending = [c for c in candidates if str(c[1]) not in (c[3], c[4])]
    todo = [c for c in pending if not _recently_started(c[5], t)]
    out["skipped"] += len(pending) - len(todo)
    spent_from = clock()
    for sid, last, path, _, _, _ in todo[:limit]:
        if clock() - spent_from + REPLAY_TIMEOUT > budget:   # a full replay must still fit
            break
        with contextlib.suppress(Exception), conn:  # best effort: it only guards against stacking
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                         (f"concordance_started:{sid}", str(t)))
        try:
            rows = run_replay(cli, sid, Path(path))
            if rows is not None:
                store_rows(conn, sid, rows)
        except Exception:  # noqa: BLE001 - one bad session never stops the rest
            rows = None
        key, outcome = (("concordance_replayed", "replayed") if rows is not None
                        else ("concordance_failed", "failed"))
        out[outcome] += 1
        with contextlib.suppress(Exception), conn:  # an unwritable marker only means a retry
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                         (f"{key}:{sid}", str(last)))
            conn.execute("DELETE FROM meta WHERE key = ?", (f"concordance_started:{sid}",))
    return out


def _recently_started(marker: object, now: float) -> bool:
    try:
        return 0 <= now - float(str(marker)) < STARTED_TTL
    except ValueError:
        return False
