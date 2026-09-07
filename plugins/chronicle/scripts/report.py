"""Read-side queries over the chronicle store — the JSON the CLI and the
overseer dashboard consume. Every function takes an open connection and
returns plain dicts/lists (JSON-ready); filtering is by main repo root and a
``since`` epoch so a dashboard can scope to one repo and a time window.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from scripts import pricing

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

MCP_PREFIX = "mcp__"
# Tools whose identity lives in their input rather than their name. The value
# is the input key ingest keeps as the row's `qualifier` (see transcript.py).
QUALIFIED_TOOLS: dict[str, str] = {"Skill": "skill", "Agent": "subagent_type"}


@dataclass(frozen=True)
class McpRef:
    server: str
    tool: str
    provenance: str  # "plugin" | "connector" | "local"


@dataclass(frozen=True)
class Classified:
    """What one tool call contributes to each box. The fields are independent,
    not a single `kind`: a plugin-provided MCP server populates BOTH `mcp` and
    `plugin`, which is the overlap the two panels deliberately show."""
    mcp: McpRef | None = None
    plugin: str | None = None
    skill: str | None = None


def _plugin_of_server(server: str) -> str | None:
    """The plugin supplying an MCP server, from Claude Code's own naming:
    ``plugin_<plugin>_<server>``. Split on the LAST underscore, so
    ``plugin_agent-ui-telemetry_agent-ui`` yields ``agent-ui-telemetry``.

    A heuristic, because a plugin whose own name contains an underscore is
    indistinguishable from the server suffix. It degrades to naming the whole
    remainder rather than guessing wrong halves — attribution can be coarse,
    never fabricated."""
    if not server.startswith("plugin_"):
        return None
    rest = server[len("plugin_"):]
    plugin, _, suffix = rest.rpartition("_")
    return plugin if plugin and suffix else rest or None


def classify(tool_name: str, qualifier: str | None) -> Classified:
    """Attribute one tool call to the MCP and/or plugin boxes."""
    if tool_name.startswith(MCP_PREFIX):
        rest = tool_name[len(MCP_PREFIX):]
        server, sep, tool = rest.partition("__")
        if not sep or not server or not tool:
            # Unsplittable: attribute the row to itself rather than dropping it.
            server = tool = tool_name
            provenance = "local"
        elif server.startswith("plugin_"):
            provenance = "plugin"
        elif server.startswith("claude_ai_"):
            provenance = "connector"
        else:
            provenance = "local"
        return Classified(
            mcp=McpRef(server=server, tool=tool, provenance=provenance),
            plugin=_plugin_of_server(server),
        )
    if tool_name in QUALIFIED_TOOLS and qualifier:
        plugin, sep, _ = qualifier.partition(":")
        return Classified(
            plugin=plugin if sep and plugin else None,
            skill=qualifier if tool_name == "Skill" else None,
        )
    return Classified()


def _usage_blocks(rows: Iterable[sqlite3.Row], *,
                  with_sessions: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fold classified tool-call rows into the `mcp` and `plugins` blocks.

    Rows need `tool_name`, `qualifier`, `result_chars` and (when
    `with_sessions`) `session_id`. A plugin-provided MCP server lands in BOTH
    blocks: the two answer different questions — what MCP costs, and which
    plugins get used — so the overlap is the point, not a bug.

    `with_sessions` is False for a single-session read, where every count
    would be 1 and the key is noise.
    """
    servers: dict[str, dict[str, Any]] = {}
    tools: dict[tuple[str, str], dict[str, Any]] = {}
    plugins: dict[tuple[str, str], dict[str, Any]] = {}
    server_tools: dict[str, set[str]] = {}
    seen: dict[str, set[str]] = {}  # bucket key -> session ids, for `sessions`
    provenance: dict[str, int] = {}
    mcp_calls = mcp_chars = plugin_calls = 0

    def _touch(bucket: dict[str, Any], key: str, session_id: str | None) -> None:
        if with_sessions and session_id is not None:
            ids = seen.setdefault(key, set())
            ids.add(session_id)
            bucket["sessions"] = len(ids)

    for row in rows:
        c = classify(row["tool_name"], row["qualifier"])
        chars = int(row["result_chars"] or 0)
        session_id = row["session_id"] if with_sessions else None
        if c.mcp is not None:
            mcp_calls += 1
            mcp_chars += chars
            provenance[c.mcp.provenance] = provenance.get(c.mcp.provenance, 0) + 1
            server_tools.setdefault(c.mcp.server, set()).add(c.mcp.tool)
            s = servers.setdefault(c.mcp.server, {
                "server": c.mcp.server, "provenance": c.mcp.provenance,
                "tools": 0, "calls": 0, "result_chars": 0,
            })
            s["calls"] += 1
            s["result_chars"] += chars
            s["tools"] = len(server_tools[c.mcp.server])
            _touch(s, f"server:{c.mcp.server}", session_id)

            t = tools.setdefault((c.mcp.server, c.mcp.tool), {
                "server": c.mcp.server, "tool": c.mcp.tool,
                "calls": 0, "result_chars": 0,
            })
            t["calls"] += 1
            t["result_chars"] += chars
            _touch(t, f"tool:{c.mcp.server}/{c.mcp.tool}", session_id)
        if c.plugin is not None:
            plugin_calls += 1
            kind = "mcp" if c.mcp is not None else "skill"
            p = plugins.setdefault((c.plugin, kind), {
                "plugin": c.plugin, "kind": kind, "calls": 0,
            })
            p["calls"] += 1
            _touch(p, f"plugin:{c.plugin}/{kind}", session_id)

    def _ranked(values: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        # Calls descending, then name ascending so equal counts are stable.
        return sorted(values, key=lambda d: (-d["calls"],
                                             d.get("server") or d.get("plugin") or ""))

    mcp_block: dict[str, Any] = {
        "calls": mcp_calls,
        "result_chars": mcp_chars,
        "by_provenance": provenance,
        "servers": _ranked(servers.values()),
        "tools": _ranked(tools.values()),
    }
    plugins_block: dict[str, Any] = {"calls": plugin_calls, "items": _ranked(plugins.values())}
    if with_sessions:
        mcp_block["sessions"] = len(
            {sid for key, ids in seen.items() if key.startswith("server:") for sid in ids}
        )
        plugins_block["sessions"] = len(
            {sid for key, ids in seen.items() if key.startswith("plugin:") for sid in ids}
        )
    return mcp_block, plugins_block


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
                    alias: str = "s", branch: str | None = None) -> tuple[str, list[Any]]:
    """The WHERE clause every session-scoped read shares. ``branch`` is a
    session-level filter: a session records the LAST branch it was seen on
    (a session can check out several), so a branch-scoped read attributes
    each session wholly to where it ended up. Turns carry no branch."""
    clauses: list[str] = []
    params: list[Any] = []
    if repo_root:
        clauses.append(f"{alias}.repo_root = ?")
        params.append(repo_root)
    if branch:
        clauses.append(f"{alias}.git_branch = ?")
        params.append(branch)
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


_COST_COLUMNS = """COUNT(*) AS turns,
              COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
              COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
              COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
              COALESCE(SUM(t.cache_5m_tokens), 0) AS cache_5m_tokens,
              COALESCE(SUM(t.cache_1h_tokens), 0) AS cache_1h_tokens,
              COALESCE(SUM(t.output_tokens), 0) AS output_tokens"""


def _cost_of(row: sqlite3.Row | dict[str, Any]) -> float | None:
    return pricing.turn_cost(
        row["model"],
        input_tokens=row["input_tokens"], cache_read_tokens=row["cache_read_tokens"],
        cache_creation_tokens=row["cache_creation_tokens"],
        cache_5m_tokens=row["cache_5m_tokens"], cache_1h_tokens=row["cache_1h_tokens"],
        output_tokens=row["output_tokens"],
    )


def _costs_by(conn: sqlite3.Connection, key_sql: str, where: str, params: list[Any],
              extra: str = "") -> dict[Any, dict[str, Any]]:
    """API-equivalent cost grouped by ``key_sql`` (a turns/sessions expression).

    Cost is a per-model rate times per-model token counts, so the query
    groups by (key, model) and the table sums the priced models in Python;
    turns on a model the pricing table does not know are counted in
    ``unpriced_turns`` rather than priced as something else. Subagent turns
    are included — they cost the same money as the main agent's.
    """
    clause = f"{where}{' AND' if where else ' WHERE'} {extra}" if extra else where
    out: dict[Any, dict[str, Any]] = {}
    for r in conn.execute(
        f"""SELECT {key_sql} AS key, t.model AS model, {_COST_COLUMNS}
            FROM turns t JOIN sessions s ON s.session_id = t.session_id{clause}
            GROUP BY key, t.model""",
        params,
    ):
        entry = out.setdefault(r["key"], {"cost_usd": 0.0, "unpriced_turns": 0})
        cost = _cost_of(r)
        if cost is None:
            entry["unpriced_turns"] += int(r["turns"])
        else:
            entry["cost_usd"] += cost
    return out


def _attach_cost(row: dict[str, Any], costs: dict[Any, dict[str, Any]], key: Any) -> None:
    entry = costs.get(key, {"cost_usd": 0.0, "unpriced_turns": 0})
    row["cost_usd"] = round(entry["cost_usd"], 6)
    row["unpriced_turns"] = entry["unpriced_turns"]


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
             since: float | None = None, limit: int = 200,
             branch: str | None = None) -> list[dict[str, Any]]:
    where, params = _session_filter(repo_root, since, branch=branch)
    rows = conn.execute(
        f"SELECT * FROM sessions s{where} "
        "ORDER BY COALESCE(s.last_activity_at, s.started_at, 0) DESC LIMIT ?",
        (*params, int(limit)),
    ).fetchall()
    now = time.time()
    out = [_row_to_session(r, now) for r in rows]
    if out:
        ids = [r["session_id"] for r in out]
        marks = ",".join("?" * len(ids))
        costs = _costs_by(conn, "t.session_id", f" WHERE t.session_id IN ({marks})", ids)
        for r in out:
            _attach_cost(r, costs, r["session_id"])
    return out


def repos(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """One row per repo root: session count, total tokens, and when it was
    last active (the newest session activity). Listed busiest first (most
    sessions); the dashboard re-orders its repo selector by
    ``last_activity_at``, most recent first."""
    rows = conn.execute(
        """SELECT repo_root, COUNT(*) AS sessions,
                  SUM(input_tokens + cache_read_tokens + cache_creation_tokens + output_tokens)
                      AS total_tokens,
                  MAX(COALESCE(last_activity_at, started_at)) AS last_activity_at
           FROM sessions WHERE repo_root IS NOT NULL
           GROUP BY repo_root ORDER BY sessions DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def session_detail(conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    detail = _row_to_session(row)
    _attach_cost(detail, _costs_by(conn, "t.session_id", " WHERE t.session_id = ?", [session_id]),
                 session_id)
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
            "cost_usd": _cost_of(r),
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
    detail["mcp"], detail["plugins"] = _usage_blocks(
        conn.execute(
            """SELECT session_id, tool_name, qualifier, result_chars FROM tool_calls
               WHERE session_id = ?""",
            (session_id,),
        ).fetchall(),
        with_sessions=False,
    )
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
              since: float | None = None, limit: int = 50,
              branch: str | None = None) -> list[dict[str, Any]]:
    """Most recently published pages across the filtered sessions."""
    where, params = _session_filter(repo_root, since, branch=branch)
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
            since: float | None = None, branch: str | None = None) -> dict[str, Any]:
    where, params = _session_filter(repo_root, since, branch=branch)
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
    session_costs = _costs_by(conn, "t.session_id", where, params)
    totals["cost_usd"] = round(sum(c["cost_usd"] for c in session_costs.values()), 6)
    totals["unpriced_turns"] = sum(c["unpriced_turns"] for c in session_costs.values())
    totals["pricing_as_of"] = pricing.PRICING_AS_OF

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
    day_costs = _costs_by(conn, "date(t.ts, 'unixepoch', 'localtime')", where, params,
                          extra="t.ts IS NOT NULL")
    for day in by_day:
        day["cache_hit_rate"] = cache_hit_rate(
            day["input_tokens"], day["cache_read_tokens"], day["cache_creation_tokens"]
        )
        day["peak_context_pct"] = peak_context_pct(day["peak_context_tokens"])
        _attach_cost(day, day_costs, day["day"])
    by_model = [
        dict(r) for r in conn.execute(
            f"""SELECT t.model AS model, COUNT(*) AS turns,
                       COUNT(DISTINCT t.session_id) AS sessions,
                       SUM(t.input_tokens) AS input_tokens,
                       SUM(t.cache_read_tokens) AS cache_read_tokens,
                       SUM(t.cache_creation_tokens) AS cache_creation_tokens,
                       SUM(t.cache_5m_tokens) AS cache_5m_tokens,
                       SUM(t.cache_1h_tokens) AS cache_1h_tokens,
                       SUM(t.output_tokens) AS output_tokens
                FROM turns t JOIN sessions s ON s.session_id = t.session_id
                {where}{' AND' if where else ' WHERE'} t.model IS NOT NULL
                GROUP BY t.model ORDER BY turns DESC""",
            params,
        )
    ]
    for m in by_model:
        cost = _cost_of(m)
        m["cost_usd"] = None if cost is None else round(cost, 6)
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
    usage_rows = conn.execute(
        f"""SELECT c.session_id AS session_id, c.tool_name AS tool_name,
                   c.qualifier AS qualifier, c.result_chars AS result_chars
            FROM tool_calls c JOIN sessions s ON s.session_id = c.session_id{where}""",
        params,
    ).fetchall()
    mcp_block, plugins_block = _usage_blocks(usage_rows, with_sessions=True)
    shape_rows = conn.execute(
        f"""SELECT session_id, turns, prompts, transcript_bytes, peak_context_tokens, started_at,
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
        # A session priced entirely on unpriced models sums to 0.0 — that is
        # "unknown", not a genuine free session, so it is excluded here
        # rather than dragging the typical-cost quantiles toward zero. A
        # PARTIALLY unpriced session still contributes its priced portion.
        "cost_usd": _quantiles([
            entry["cost_usd"]
            for entry in (
                session_costs.get(r["session_id"], {"cost_usd": 0.0, "unpriced_turns": 0})
                for r in shape_rows
            )
            if not (entry["cost_usd"] == 0.0 and entry["unpriced_turns"] > 0)
        ]),
    }
    return {
        "totals": totals,
        "by_day": by_day,
        "by_model": by_model,
        "tools": tools,
        "mcp": mcp_block,
        "plugins": plugins_block,
        "shape": shape,
        "artifacts": artifacts(conn, repo_root=repo_root, since=since, branch=branch),
    }
