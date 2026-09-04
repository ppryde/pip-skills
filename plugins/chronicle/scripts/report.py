"""Read-side queries over the chronicle store — the JSON the CLI and the
overseer dashboard consume. Every function takes an open connection and
returns plain dicts/lists (JSON-ready); filtering is by main repo root and a
``since`` epoch so a dashboard can scope to one repo and a time window.
"""
from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

# A session with no recorded end (backfilled transcripts never see a
# SessionEnd hook) counts as live only while it has been active this recently.
LIVE_HORIZON_SECONDS = 15 * 60


def _session_filter(repo_root: str | None, since: float | None,
                    alias: str = "s") -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if repo_root:
        clauses.append(f"{alias}.repo_root = ?")
        params.append(repo_root)
    if since is not None:
        clauses.append(f"COALESCE({alias}.last_activity_at, {alias}.started_at, 0) >= ?")
        params.append(since)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def is_live(ended_at: float | None, last_activity_at: float | None, now: float) -> bool:
    if ended_at is not None:
        return False
    return last_activity_at is not None and (now - last_activity_at) <= LIVE_HORIZON_SECONDS


def _row_to_session(row: sqlite3.Row, now: float | None = None) -> dict[str, Any]:
    if now is None:
        now = time.time()
    out = dict(row)
    try:
        out["models"] = json.loads(out.get("models") or "[]")
    except ValueError:
        out["models"] = []
    started = out.get("started_at")
    last = out.get("last_activity_at")
    out["duration_s"] = round(last - started) if started and last and last >= started else None
    out["context_tokens"] = (
        out["input_tokens"] + out["cache_read_tokens"] + out["cache_creation_tokens"]
    )
    out["live"] = is_live(out.get("ended_at"), out.get("last_activity_at"), now)
    return out


def status(conn: sqlite3.Connection) -> dict[str, Any]:
    sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    turns = conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0]
    last = conn.execute("SELECT MAX(updated_at) FROM cursors").fetchone()[0]
    repos = conn.execute(
        "SELECT COUNT(DISTINCT repo_root) FROM sessions WHERE repo_root IS NOT NULL"
    ).fetchone()[0]
    synced = conn.execute("SELECT value FROM meta WHERE key = 'synced_at'").fetchone()
    try:
        synced_at = float(synced[0]) if synced and synced[0] is not None else None
    except (TypeError, ValueError):
        synced_at = None
    return {
        "sessions": sessions, "turns": turns, "repos": repos,
        "last_ingest_at": last, "synced_at": synced_at,
    }


def sessions(conn: sqlite3.Connection, *, repo_root: str | None = None,
             since: float | None = None, limit: int = 200) -> list[dict[str, Any]]:
    where, params = _session_filter(repo_root, since)
    rows = conn.execute(
        f"SELECT * FROM sessions s{where} "
        "ORDER BY COALESCE(s.last_activity_at, s.started_at, 0) DESC LIMIT ?",
        (*params, int(limit)),
    ).fetchall()
    now = time.time()
    return [_row_to_session(r, now) for r in rows]


def repos(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT repo_root, COUNT(*) AS sessions,
                  SUM(input_tokens + cache_read_tokens + cache_creation_tokens + output_tokens)
                      AS total_tokens
           FROM sessions WHERE repo_root IS NOT NULL
           GROUP BY repo_root ORDER BY sessions DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def session_detail(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    detail = _row_to_session(row)
    detail["turn_series"] = [
        {
            "ts": r["ts"],
            "model": r["model"],
            "context_tokens": r["input_tokens"] + r["cache_read_tokens"] + r["cache_creation_tokens"],
            "input_tokens": r["input_tokens"],
            "cache_read_tokens": r["cache_read_tokens"],
            "cache_creation_tokens": r["cache_creation_tokens"],
            "output_tokens": r["output_tokens"],
            "thinking_tokens": r["thinking_tokens"],
            "tool_calls": r["tool_calls"],
            "stop_reason": r["stop_reason"],
        }
        for r in conn.execute(
            "SELECT * FROM turns WHERE session_id = ? AND agent_id = '' ORDER BY ts, rowid",
            (session_id,),
        )
    ]
    detail["subagents"] = [
        dict(r) for r in conn.execute(
            """SELECT agent_id, COUNT(*) AS turns,
                      SUM(input_tokens + cache_read_tokens + cache_creation_tokens) AS context_tokens,
                      SUM(output_tokens) AS output_tokens, SUM(tool_calls) AS tool_calls,
                      MIN(ts) AS first_ts, MAX(ts) AS last_ts
               FROM turns WHERE session_id = ? AND agent_id <> ''
               GROUP BY agent_id ORDER BY first_ts""",
            (session_id,),
        )
    ]
    detail["tools"] = [
        dict(r) for r in conn.execute(
            """SELECT tool_name, COUNT(*) AS calls FROM tool_calls
               WHERE session_id = ? GROUP BY tool_name ORDER BY calls DESC, tool_name""",
            (session_id,),
        )
    ]
    detail["compactions_at"] = [
        r[0] for r in conn.execute(
            "SELECT ts FROM events WHERE session_id = ? AND kind = 'compaction' ORDER BY ts",
            (session_id,),
        )
    ]
    return detail


def _quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"p50": None, "p90": None, "max": None, "mean": None}
    ordered = sorted(values)

    def q(p: float) -> float:
        idx = min(len(ordered) - 1, max(0, round(p * (len(ordered) - 1))))
        return ordered[idx]

    return {
        "p50": q(0.5), "p90": q(0.9), "max": ordered[-1],
        "mean": sum(ordered) / len(ordered),
    }


def summary(conn: sqlite3.Connection, *, repo_root: str | None = None,
            since: float | None = None) -> dict[str, Any]:
    where, params = _session_filter(repo_root, since)
    totals_row = conn.execute(
        f"""SELECT COUNT(*) AS sessions,
                   COALESCE(SUM(turns), 0) AS turns,
                   COALESCE(SUM(prompts), 0) AS prompts,
                   COALESCE(SUM(tool_calls), 0) AS tool_calls,
                   COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
                   COALESCE(SUM(cache_creation_tokens), 0) AS cache_creation_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(thinking_tokens), 0) AS thinking_tokens,
                   COALESCE(SUM(compactions), 0) AS compactions,
                   COALESCE(SUM(subagents), 0) AS subagents,
                   COALESCE(SUM(active_ms), 0) AS active_ms,
                   COALESCE(SUM(transcript_bytes), 0) AS transcript_bytes,
                   SUM(CASE WHEN ended_at IS NULL AND last_activity_at >= ? THEN 1 ELSE 0 END)
                       AS live
            FROM sessions s{where}""",
        (time.time() - LIVE_HORIZON_SECONDS, *params),
    ).fetchone()
    totals = dict(totals_row)

    by_day = [
        dict(r) for r in conn.execute(
            f"""SELECT date(t.ts, 'unixepoch', 'localtime') AS day,
                       COUNT(DISTINCT t.session_id) AS sessions,
                       COUNT(*) AS turns,
                       SUM(t.input_tokens) AS input_tokens,
                       SUM(t.cache_read_tokens) AS cache_read_tokens,
                       SUM(t.cache_creation_tokens) AS cache_creation_tokens,
                       SUM(t.output_tokens) AS output_tokens
                FROM turns t JOIN sessions s ON s.session_id = t.session_id
                {where}{' AND' if where else ' WHERE'} t.ts IS NOT NULL
                GROUP BY day ORDER BY day""",
            params,
        )
    ]
    by_model = [
        dict(r) for r in conn.execute(
            f"""SELECT t.model AS model, COUNT(*) AS turns,
                       COUNT(DISTINCT t.session_id) AS sessions,
                       SUM(t.input_tokens) AS input_tokens,
                       SUM(t.cache_read_tokens) AS cache_read_tokens,
                       SUM(t.cache_creation_tokens) AS cache_creation_tokens,
                       SUM(t.output_tokens) AS output_tokens
                FROM turns t JOIN sessions s ON s.session_id = t.session_id
                {where}{' AND' if where else ' WHERE'} t.model IS NOT NULL
                GROUP BY t.model ORDER BY turns DESC""",
            params,
        )
    ]
    tools = [
        dict(r) for r in conn.execute(
            f"""SELECT c.tool_name AS tool_name, COUNT(*) AS calls,
                       COUNT(DISTINCT c.session_id) AS sessions
                FROM tool_calls c JOIN sessions s ON s.session_id = c.session_id
                {where}
                GROUP BY c.tool_name ORDER BY calls DESC LIMIT 20""",
            params,
        )
    ]
    shape_rows = conn.execute(
        f"""SELECT turns, prompts, transcript_bytes, peak_context_tokens, started_at,
                   last_activity_at
            FROM sessions s{where}""",
        params,
    ).fetchall()
    durations = [
        float(r["last_activity_at"] - r["started_at"])
        for r in shape_rows
        if r["started_at"] and r["last_activity_at"] and r["last_activity_at"] >= r["started_at"]
    ]
    shape = {
        "turns": _quantiles([float(r["turns"]) for r in shape_rows]),
        "prompts": _quantiles([float(r["prompts"]) for r in shape_rows]),
        "duration_s": _quantiles(durations),
        "transcript_bytes": _quantiles([float(r["transcript_bytes"]) for r in shape_rows]),
        "peak_context_tokens": _quantiles([float(r["peak_context_tokens"]) for r in shape_rows]),
    }
    return {
        "totals": totals,
        "by_day": by_day,
        "by_model": by_model,
        "tools": tools,
        "shape": shape,
    }
