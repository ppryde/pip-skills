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

# The context windows Claude Code actually runs with. The transcript records
# how many tokens were IN the window, never how big the window was — so the
# window is inferred as the smallest standard size the observed peak fits in.
# Honest and stable: a session that peaked at 837k was plainly on a 1M window,
# and one that peaked at 190k on a 200k window. A session that never got near
# a boundary reads as 200k, the default for every current model.
STANDARD_WINDOWS = (200_000, 1_000_000)


def context_window_for(peak_tokens: int) -> int:
    """Smallest standard context window the observed peak fits inside."""
    for window in STANDARD_WINDOWS:
        if peak_tokens <= window:
            return window
    return STANDARD_WINDOWS[-1]


def peak_context_pct(peak_tokens: int) -> float | None:
    """Peak context as a share of its inferred window; None with no turns."""
    if peak_tokens <= 0:
        return None
    return peak_tokens / context_window_for(peak_tokens)


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


def cache_hit_rate(input_tokens: int, cache_read: int, cache_creation: int) -> float | None:
    """Share of a prompt's context served from cache; None when there was no context."""
    total = input_tokens + cache_read + cache_creation
    return cache_read / total if total > 0 else None


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
    out["cache_hit_rate"] = cache_hit_rate(
        out["input_tokens"], out["cache_read_tokens"], out["cache_creation_tokens"]
    )
    out["context_window"] = context_window_for(out["peak_context_tokens"])
    out["peak_context_pct"] = peak_context_pct(out["peak_context_tokens"])
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
    series: list[dict[str, Any]] = []
    previous_ts: float | None = None
    for r in conn.execute(
        "SELECT * FROM turns WHERE session_id = ? AND agent_id = '' ORDER BY ts, rowid",
        (session_id,),
    ):
        ts = r["ts"]
        gap = round(ts - previous_ts) if ts is not None and previous_ts is not None else None
        series.append({
            "ts": ts,
            "message_id": r["message_id"],
            "model": r["model"],
            "context_tokens": r["input_tokens"] + r["cache_read_tokens"] + r["cache_creation_tokens"],
            "input_tokens": r["input_tokens"],
            "cache_read_tokens": r["cache_read_tokens"],
            "cache_creation_tokens": r["cache_creation_tokens"],
            "cache_5m_tokens": r["cache_5m_tokens"],
            "cache_1h_tokens": r["cache_1h_tokens"],
            "output_tokens": r["output_tokens"],
            "thinking_tokens": r["thinking_tokens"],
            "tool_calls": r["tool_calls"],
            "stop_reason": r["stop_reason"],
            # Cold: more prefix written than read back. `gap_s` (seconds since
            # the previous call) says whether an idle stretch lapsed the TTL.
            "cold": r["cache_creation_tokens"] > r["cache_read_tokens"],
            "gap_s": gap,
        })
        if ts is not None:
            previous_ts = ts
    detail["turn_series"] = series
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
    detail["artifacts"] = artifacts_for(conn, session_id)
    tool_rows = conn.execute(
        """SELECT tool_name, message_id, result_chars, result_ts FROM tool_calls
           WHERE session_id = ? AND agent_id = ''""",
        (session_id,),
    ).fetchall()
    detail["biggest_jumps"] = biggest_jumps(series, tool_rows)
    return detail


# One row per PAGE: the latest publish of each url (a url-less publish — the
# result never landed — stands alone), with how many times it was published
# and when it first appeared.
_ARTIFACT_PAGE_SQL = """
    SELECT a.session_id, s.title AS session_title, a.ts, a.url, a.title,
           -- favicon/description are usually passed on the FIRST publish only
           -- (a redeploy keeps the icon it has), so take the earliest non-null.
           COALESCE(a.description, (SELECT d.description FROM artifacts d
               WHERE d.url = a.url AND d.session_id = a.session_id AND d.description IS NOT NULL
               ORDER BY d.ts LIMIT 1)) AS description,
           COALESCE(a.favicon, (SELECT i.favicon FROM artifacts i
               WHERE i.url = a.url AND i.session_id = a.session_id AND i.favicon IS NOT NULL
               ORDER BY i.ts LIMIT 1)) AS favicon,
           (SELECT COUNT(*) FROM artifacts p
             WHERE p.url = a.url AND p.session_id = a.session_id) AS publishes,
           (SELECT MIN(f.ts) FROM artifacts f
             WHERE f.url = a.url AND f.session_id = a.session_id) AS first_ts
    FROM artifacts a JOIN sessions s ON s.session_id = a.session_id
    WHERE (a.url IS NULL OR a.rowid = (
        SELECT q.rowid FROM artifacts q
        WHERE q.url = a.url AND q.session_id = a.session_id
        ORDER BY q.ts DESC, q.rowid DESC LIMIT 1))
"""


def _page_row(r: sqlite3.Row) -> dict[str, Any]:
    out = dict(r)
    if out["url"] is None:
        out["publishes"] = 1
        out["first_ts"] = out["ts"]
    return out


def artifacts_for(conn: sqlite3.Connection, session_id: str) -> list[dict[str, Any]]:
    return [
        _page_row(r) for r in conn.execute(
            # first_ts is NULL for a url-less row in SQL (patched in Python
            # below) — COALESCE keeps that row in time order rather than first.
            _ARTIFACT_PAGE_SQL + " AND a.session_id = ? ORDER BY COALESCE(first_ts, a.ts)",
            (session_id,),
        )
    ]


def artifacts(conn: sqlite3.Connection, *, repo_root: str | None = None,
              since: float | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Most recently published pages across the filtered sessions."""
    where, params = _session_filter(repo_root, since)
    clause = where.replace(" WHERE ", " AND ", 1) if where else ""
    return [
        _page_row(r) for r in conn.execute(
            _ARTIFACT_PAGE_SQL + clause + " ORDER BY a.ts DESC LIMIT ?", (*params, int(limit))
        )
    ]


def biggest_jumps(series: list[dict[str, Any]], tool_rows: list[sqlite3.Row],
                  limit: int = 8) -> list[dict[str, Any]]:
    """The turns that grew the context most SINCE THE PREVIOUS TURN, each
    attributed to what landed in between. (Ranking by absolute context would
    just list a session's last few turns — context only grows until a
    compaction — so the jump is the figure that says what happened.)

    ``series`` is the ordered main-agent turn series (``session_detail``'s
    ``turn_series``); ``tool_rows`` every main-agent tool call with its
    result size. A tool result is attributed to the first turn whose
    timestamp is at or after the result's — that is the call that had to
    read it. Results without a timestamp fall back to the turn that issued
    the call.
    """
    if not series:
        return []
    # index -> list of (tool_name, result_chars)
    landed: dict[int, list[tuple[str, int]]] = {}
    times = [t["ts"] for t in series]
    by_message = {t.get("message_id"): i for i, t in enumerate(series)}
    for row in tool_rows:
        chars = row["result_chars"]
        if chars is None:
            continue
        target: int | None = None
        rts = row["result_ts"]
        if rts is not None:
            for i, ts in enumerate(times):
                if ts is not None and ts >= rts:
                    target = i
                    break
        if target is None:
            issued = by_message.get(row["message_id"])
            target = issued + 1 if issued is not None and issued + 1 < len(series) else issued
        if target is None:
            continue
        landed.setdefault(target, []).append((row["tool_name"], int(chars)))

    ranked = []
    for i, turn in enumerate(series):
        previous = series[i - 1]["context_tokens"] if i > 0 else 0
        delta = turn["context_tokens"] - previous
        contributors = sorted(landed.get(i, []), key=lambda x: -x[1])[:3]
        ranked.append({
            "turn": i + 1,
            "ts": turn["ts"],
            "context_tokens": turn["context_tokens"],
            "delta_tokens": delta,
            "output_tokens": turn["output_tokens"],
            "cold": turn.get("cold", False),
            "tool_calls": turn["tool_calls"],
            "landed": [{"tool_name": n, "chars": c} for n, c in contributors],
            "landed_chars": sum(c for _, c in landed.get(i, [])),
        })
    ranked.sort(key=lambda r: (-r["delta_tokens"], r["turn"]))
    return ranked[:limit]


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
                   COALESCE(SUM(cold_turns), 0) AS cold_turns,
                   COALESCE(SUM(artifacts), 0) AS artifacts,
                   COALESCE(SUM(subagents), 0) AS subagents,
                   COALESCE(SUM(active_ms), 0) AS active_ms,
                   COALESCE(SUM(transcript_bytes), 0) AS transcript_bytes,
                   SUM(CASE WHEN ended_at IS NULL AND last_activity_at >= ? THEN 1 ELSE 0 END)
                       AS live
            FROM sessions s{where}""",
        (time.time() - LIVE_HORIZON_SECONDS, *params),
    ).fetchone()
    totals = dict(totals_row)
    totals["cache_hit_rate"] = cache_hit_rate(
        totals["input_tokens"], totals["cache_read_tokens"], totals["cache_creation_tokens"]
    )
    ttl = conn.execute(
        f"""SELECT COALESCE(SUM(t.cache_5m_tokens), 0), COALESCE(SUM(t.cache_1h_tokens), 0)
            FROM turns t JOIN sessions s ON s.session_id = t.session_id{where}""",
        params,
    ).fetchone()
    totals["cache_5m_tokens"], totals["cache_1h_tokens"] = int(ttl[0]), int(ttl[1])

    by_day = [
        dict(r) for r in conn.execute(
            f"""SELECT date(t.ts, 'unixepoch', 'localtime') AS day,
                       COUNT(DISTINCT t.session_id) AS sessions,
                       COUNT(*) AS turns,
                       SUM(t.input_tokens) AS input_tokens,
                       SUM(t.cache_read_tokens) AS cache_read_tokens,
                       SUM(t.cache_creation_tokens) AS cache_creation_tokens,
                       SUM(t.output_tokens) AS output_tokens,
                       SUM(CASE WHEN t.agent_id = '' AND t.cache_creation_tokens > t.cache_read_tokens
                                THEN 1 ELSE 0 END) AS cold_turns,
                       MAX(CASE WHEN t.agent_id = ''
                                THEN t.input_tokens + t.cache_read_tokens + t.cache_creation_tokens
                                ELSE 0 END) AS peak_context_tokens
                FROM turns t JOIN sessions s ON s.session_id = t.session_id
                {where}{' AND' if where else ' WHERE'} t.ts IS NOT NULL
                GROUP BY day ORDER BY day""",
            params,
        )
    ]
    for day in by_day:
        day["cache_hit_rate"] = cache_hit_rate(
            day["input_tokens"], day["cache_read_tokens"], day["cache_creation_tokens"]
        )
        day["peak_context_pct"] = peak_context_pct(day["peak_context_tokens"])
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
    peak_overall = max((int(r["peak_context_tokens"]) for r in shape_rows), default=0)
    totals["peak_context_tokens"] = peak_overall
    totals["peak_context_pct"] = peak_context_pct(peak_overall)
    totals["context_window"] = context_window_for(peak_overall)
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
        "artifacts": artifacts(conn, repo_root=repo_root, since=since),
    }
