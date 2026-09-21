"""Read-side queries over the chronicle store — the JSON the CLI and the
overseer dashboard consume. Every function takes an open connection and
returns plain dicts/lists (JSON-ready); filtering is by main repo root and a
``since`` epoch so a dashboard can scope to one repo and a time window.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from scripts import pricing, transcript

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


def _slug(name: str) -> str:
    """A server name as Claude Code writes it into a tool name: every
    character outside ``[A-Za-z0-9-]`` becomes an underscore. So
    ``claude.ai Snowflake`` -> ``claude_ai_Snowflake`` and
    ``plugin:linear:linear`` -> ``plugin_linear_linear``."""
    return re.sub(r"[^A-Za-z0-9-]", "_", name)


def mcp_server_names(conn: sqlite3.Connection) -> dict[str, str]:
    """Slug -> the server's real name, from the attribution on turns.

    The MCP breakdown is derived from tool names, which carry only the slug
    (`mcp__claude_ai_Snowflake__sql_exec_tool`), so it could show nothing
    better than `claude_ai_Snowflake`. Claude Code also stamps the server's
    actual name on the TURN — `claude.ai Snowflake` — and `_slug` is exactly
    the transform between them, so this is a join rather than a guess.

    Built from the WHOLE store, not the filtered window: a name is a label,
    not a measure, so a wider lookup skews no denominator, and a window whose
    own turns happen to carry no attribution still gets the good label.

    Two different names slugging to one key would make the label ambiguous;
    that key is dropped and the slug stands, since a coarse name is honest
    and a wrong one is not.
    """
    have = {row[1] for row in conn.execute("PRAGMA table_info(turns)")}
    if "mcp_server" not in have:
        return {}
    names: dict[str, set[str]] = {}
    for (name,) in conn.execute(
        "SELECT DISTINCT mcp_server FROM turns WHERE mcp_server IS NOT NULL"
    ):
        if name:
            names.setdefault(_slug(name), set()).add(name)
    return {slug: next(iter(v)) for slug, v in names.items() if len(v) == 1}


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


def _qualifier_sql(conn: sqlite3.Connection, prefix: str = "") -> str:
    """The SQL expression for a row's `qualifier`, or a NULL literal when the
    column is not there yet.

    `qualifier` was added to `tool_calls` after the table shipped, and
    `store.connect(readonly=True)` — the ONLY path the CLI's report verbs
    take — returns before `_migrate` can add it. So a store upgraded but not
    yet synced still lacks the column, and naming it unconditionally raises
    `OperationalError` for every read: `chronicle summary` exits non-zero,
    `run_chronicle` soft-degrades that to None, and the dashboard reports an
    empty account to someone with a thousand transcripts.

    Substituting NULL degrades to "no plugin skills recorded", which is what
    an un-backfilled store honestly holds. MCP is unaffected either way — it
    is derived from `tool_name`, which was never missing."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tool_calls)")}
    return f"{prefix}qualifier" if "qualifier" in columns else "NULL"


def _result_chars_sql(conn: sqlite3.Connection, prefix: str = "") -> str:
    """The SQL expression for a call's `result_chars`, or NULL where the
    column is not there yet — the same read-only migration trap
    `_qualifier_sql` documents, on the column right beside it.

    `result_chars` was in every usage query unguarded, so an upgraded-but-
    never-synced store raised `OperationalError` on the whole summary, not
    just on the sizes. NULL folds to 0 in `_usage_blocks` and to an empty
    block in `_context_growth`, which is what such a store honestly holds.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(tool_calls)")}
    return f"{prefix}result_chars" if "result_chars" in columns else "NULL"


def _median(values: list[float]) -> float | None:
    """Median, because the mean of a tool's wall time is a fiction: an
    `AskUserQuestion` that waited 60 hours for a human, or a `Bash` left
    running for half a day, drags it somewhere no call ever was. The middle
    call is the one that describes the tool."""
    if not values:
        return None
    values.sort()
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


_ATTRIBUTION_COLUMNS = ("skill", "plugin", "agent_type", "mcp_server", "mcp_tool")

_EMPTY_ATTRIBUTION: dict[str, Any] = {
    "turns": 0, "attributed_turns": 0, "cost_usd": 0.0, "unattributed_cost_usd": 0.0,
    "plugins": [], "skills": [], "agents": [], "mcp": [],
}


def _attribution(conn: sqlite3.Connection, where: str, params: list[Any], *,
                 limit: int = 50) -> dict[str, Any]:
    """Turns, tokens and cost grouped by what was in scope.

    Claude Code stamps `attributionSkill` / `attributionPlugin` /
    `attributionAgent` / `attributionMcpServer` onto ASSISTANT records, so
    these land on turns — which carry usage. That is the difference between
    "superpowers was invoked 80 times" and "superpowers cost 427M context
    tokens across 2,987 turns", and it is why this is grouped here rather
    than folded into the tool-call breakdowns.

    `plugin` is NULL for a built-in skill: the transcript states that, so a
    built-in is counted among skills and attributed to no plugin, rather than
    being guessed at from whether its name contains a colon.

    A turn with nothing in scope is in no bucket — most turns, correctly.
    """
    have = {row[1] for row in conn.execute("PRAGMA table_info(turns)")}
    if not any(c in have for c in _ATTRIBUTION_COLUMNS):
        return {**_EMPTY_ATTRIBUTION, "turns": _attributed_totals(conn, where, params)[0]}

    def _group(column: str, extra: str = "") -> list[dict[str, Any]]:
        # Per-column, not just "any column present". The five attribution
        # columns arrived as five separate ALTERs and the report verbs open
        # the store READ-ONLY (see `_qualifier_sql`), so a store can genuinely
        # hold some and not others — an interrupted `_migrate`, or one touched
        # by an intermediate build. Naming an absent column raised
        # `OperationalError` out of the whole summary; an absent column simply
        # has nothing attributed to it, which is what the store honestly says.
        if column not in have:
            return []
        rows = conn.execute(
            f"""SELECT t.{column} AS name, COUNT(*) AS turns,
                       SUM(t.input_tokens + t.cache_read_tokens + t.cache_creation_tokens)
                           AS context_tokens,
                       SUM(t.output_tokens) AS output_tokens,
                       COUNT(DISTINCT t.session_id) AS sessions{extra}
                FROM turns t JOIN sessions s ON s.session_id = t.session_id{where}
                {'AND' if where else 'WHERE'} t.{column} IS NOT NULL
                GROUP BY t.{column}
                ORDER BY context_tokens DESC, name
                LIMIT {int(limit)}""",
            params,
        ).fetchall()
        costs = _costs_by(conn, f"t.{column}", where, params, extra=f"t.{column} IS NOT NULL")
        out = []
        for r in rows:
            item = dict(r)
            _attach_cost(item, costs, r["name"])
            out.append(item)
        return out

    # Cost of turns with ANYTHING in scope, counted once. Summing the plugin
    # and agent lists would bill a plugin skill running inside a subagent
    # twice, since it sets both.
    any_set = " OR ".join(f"t.{c} IS NOT NULL" for c in _ATTRIBUTION_COLUMNS if c in have)
    attributed_costs = _costs_by(conn, "1", where, params, extra=any_set)
    attributed_cost = sum(c["cost_usd"] for c in attributed_costs.values())
    all_costs = _costs_by(conn, "1", where, params)
    total_cost = sum(c["cost_usd"] for c in all_costs.values())

    # The `extra` sub-selects name a column OTHER than the one being grouped,
    # so each is guarded on its own: a store with `plugin` but no `skill` can
    # still report plugins, just without the distinct-skill count.
    plugins = _group("plugin",
                     extra=", COUNT(DISTINCT t.skill) AS skills" if "skill" in have else "")
    skills = _group("skill",
                    extra=", MAX(t.plugin) AS plugin" if "plugin" in have else "")
    total_turns, attributed = _attributed_totals(conn, where, params)
    return {
        "turns": total_turns,
        "attributed_turns": attributed,
        "cost_usd": round(attributed_cost, 6),
        "unattributed_cost_usd": round(total_cost - attributed_cost, 6),
        "plugins": plugins,
        "skills": skills,
        "agents": _group("agent_type"),
        "mcp": _group("mcp_server"),
    }


def _attributed_totals(conn: sqlite3.Connection, where: str,
                       params: list[Any]) -> tuple[int, int]:
    """(all turns, turns with anything in scope) — the denominator that keeps
    a plugin's share honest."""
    have = {row[1] for row in conn.execute("PRAGMA table_info(turns)")}
    cols = [c for c in _ATTRIBUTION_COLUMNS if c in have]
    any_set = " OR ".join(f"t.{c} IS NOT NULL" for c in cols) if cols else "0"
    row = conn.execute(
        f"""SELECT COUNT(*), COALESCE(SUM(CASE WHEN {any_set} THEN 1 ELSE 0 END), 0)
            FROM turns t JOIN sessions s ON s.session_id = t.session_id{where}""",
        params,
    ).fetchone()
    return int(row[0]), int(row[1])


def _delegation(conn: sqlite3.Connection, where: str, params: list[Any]) -> dict[str, Any]:
    """What subagents DO against what they PRODUCE.

    Kept as raw pairs rather than percentages so the caller can render either,
    and so a zero denominator is the caller's problem to display rather than
    a None to unpick. Counted from `agent_id`, which every turn and tool call
    carries — unlike attribution, this covers the whole store.
    """
    turns = conn.execute(
        f"""SELECT COUNT(*), COALESCE(SUM(CASE WHEN t.agent_id <> '' THEN 1 ELSE 0 END), 0),
                   COALESCE(SUM(t.output_tokens), 0),
                   COALESCE(SUM(CASE WHEN t.agent_id <> '' THEN t.output_tokens ELSE 0 END), 0)
            FROM turns t JOIN sessions s ON s.session_id = t.session_id{where}""",
        params,
    ).fetchone()
    calls = conn.execute(
        f"""SELECT COUNT(*), COALESCE(SUM(CASE WHEN c.agent_id <> '' THEN 1 ELSE 0 END), 0)
            FROM tool_calls c JOIN sessions s ON s.session_id = c.session_id{where}""",
        params,
    ).fetchone()
    return {
        "turns": int(turns[0]), "subagent_turns": int(turns[1]),
        "output_tokens": int(turns[2]), "subagent_output_tokens": int(turns[3]),
        "tool_calls": int(calls[0]), "subagent_tool_calls": int(calls[1]),
    }


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    """Whether the store has `name` yet. The report verbs open the store
    READ-ONLY, a path that returns before `_migrate` runs, so a store upgraded
    but not yet synced can be missing a table this code names — see
    `_qualifier_sql` for the same trap on a column."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone() is not None


def _agent_type_sql(conn: sqlite3.Connection, prefix: str = "") -> str:
    """`MAX(<prefix>agent_type)`, or NULL when the column is not there yet.
    Same read-only migration trap as `_qualifier_sql`: the report verbs open
    the store on a path that returns before `_migrate` runs."""
    have = {row[1] for row in conn.execute("PRAGMA table_info(turns)")}
    return f"MAX({prefix}agent_type)" if "agent_type" in have else "NULL"


def _agents_join(conn: sqlite3.Connection, prefix: str = "t.") -> str:
    """LEFT JOIN onto `agents` when the table exists, else nothing — the task
    is a label, and a store that predates it must still list its agents."""
    if not _has_table(conn, "agents"):
        return ""
    return (f" LEFT JOIN agents ag ON ag.session_id = {prefix}session_id"
            f" AND ag.agent_id = {prefix}agent_id")


def _task_sql(conn: sqlite3.Connection) -> str:
    return "MAX(ag.task)" if _has_table(conn, "agents") else "NULL"


def _agent_description_sql(conn: sqlite3.Connection) -> str:
    """The agent's short label. NULL where the column predates the store, so a
    store not yet resynced degrades to the task prompt rather than erroring —
    the same guard `qualifier` needed, for the same reason: report verbs open
    the store READ-ONLY, a path that returns before `_migrate` can add it."""
    if not _has_table(conn, "agents"):
        return "NULL"
    columns = {row[1] for row in conn.execute("PRAGMA table_info(agents)")}
    return "MAX(ag.description)" if "description" in columns else "NULL"


_EMPTY_CHURN: dict[str, Any] = {
    "lines_added": 0, "lines_removed": 0, "files": 0, "edits": 0, "files_by_churn": [],
    "sessions": 0, "output_tokens": 0, "by_day": [],
}


def _churn(conn: sqlite3.Connection, where: str, params: list[Any], *,
           limit: int = 50, agent: str | None = None) -> dict[str, Any]:
    """Lines added/removed and the files that moved most, from `file_edits`.

    A measure of editing DONE, not of lines surviving in the repo: ten edits
    to one line are ten edits, and a later revert still counts. For "what
    shipped" git is the truthful source; this answers "how much editing
    happened", which is a different question.

    ``where`` is a SESSIONS-side filter (``s.``-prefixed) in every caller, so
    every query here can share it — each joins `sessions s`.

    ``agent`` narrows to one subagent's edits. It is applied to the FILE-side
    queries only: the per-session denominator below counts sessions, which an
    agent-side clause cannot filter and would not mean anything for.
    """
    if not _has_table(conn, "file_edits"):
        return dict(_EMPTY_CHURN)
    scope = f"{where}{' AND' if where else ' WHERE'} f.agent_id = ?" if agent else where
    scoped = [*params, agent] if agent else params
    join = f"FROM file_edits f JOIN sessions s ON s.session_id = f.session_id{scope}"
    total = conn.execute(
        f"""SELECT COALESCE(SUM(f.lines_added), 0), COALESCE(SUM(f.lines_removed), 0),
                   COUNT(DISTINCT f.file_path), COUNT(*) {join}""",
        scoped,
    ).fetchone()
    files = [
        {
            "file_path": r["file_path"],
            "edits": r["edits"],
            "lines_added": r["lines_added"],
            "lines_removed": r["lines_removed"],
            "operations": sorted(set((r["operations"] or "").split(","))),
            "sessions": r["sessions"],
        }
        for r in conn.execute(
            f"""SELECT f.file_path AS file_path, COUNT(*) AS edits,
                       SUM(f.lines_added) AS lines_added,
                       SUM(f.lines_removed) AS lines_removed,
                       GROUP_CONCAT(DISTINCT f.operation) AS operations,
                       COUNT(DISTINCT f.session_id) AS sessions
                {join}
                GROUP BY f.file_path
                ORDER BY SUM(f.lines_added + f.lines_removed) DESC, f.file_path
                LIMIT {int(limit)}""",
            scoped,
        )
    ]
    # Sessions that actually changed a file, and the output they produced —
    # the ONLY honest denominators for a per-session or per-line average.
    # Sessions with no file edits would otherwise halve every such figure.
    per_session = conn.execute(
        f"""SELECT COUNT(*), COALESCE(SUM(s.output_tokens), 0)
            FROM sessions s{where}{' AND' if where else ' WHERE'} s.files_touched > 0""",
        params,
    ).fetchone()
    by_day = [
        {"day": r["day"], "lines_added": int(r["lines_added"]),
         "lines_removed": int(r["lines_removed"]), "edits": int(r["edits"])}
        for r in conn.execute(
            f"""SELECT date(f.ts, 'unixepoch', 'localtime') AS day,
                       SUM(f.lines_added) AS lines_added,
                       SUM(f.lines_removed) AS lines_removed,
                       COUNT(*) AS edits
                {join}{' AND' if scope else ' WHERE'} f.ts IS NOT NULL
                GROUP BY day ORDER BY day""",
            scoped,
        )
    ]
    return {
        "lines_added": int(total[0]), "lines_removed": int(total[1]),
        "files": int(total[2]), "edits": int(total[3]), "files_by_churn": files,
        "sessions": int(per_session[0]), "output_tokens": int(per_session[1]),
        "by_day": by_day,
    }


def _usage_blocks(rows: Iterable[sqlite3.Row], *, with_sessions: bool,
                  limit: int = 50, tool_limit: int = 400,
                  server_names: dict[str, str] | None = None,
                  ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Fold classified tool-call rows into the `tools`, `mcp` and `plugins`
    breakdowns the Usage callout reads.

    Rows need `tool_name`, `qualifier`, `result_chars`, `ts`, `result_ts`,
    `agent_id` and (when `with_sessions`) `session_id`. Every bucket carries
    the same four measures, so the three tabs are directly comparable:

    - `calls`         how often it ran
    - `result_chars`  how much it poured back into the context — the reason a
                      cheap-looking tool can be the expensive one
    - `median_s`      wall time of the middle call (see `_median`)
    - `subagent_calls` how much of it was delegated rather than run inline

    A plugin-provided MCP server lands in BOTH the mcp and plugins blocks: the
    two answer different questions — what MCP costs, and which plugins get
    used — so the overlap is the point, not a bug.

    `with_sessions` is False for a single-session read, where every count
    would be 1 and the key is noise.

    `server_names` (see `mcp_server_names`) supplies each MCP server's real
    name for display. `server` stays the slug — it is the key everything
    joins on — and `name` falls back to it for a server attribution never
    named.
    """
    names = server_names or {}
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    durations: dict[tuple[str, str], list[float]] = {}
    seen: dict[tuple[str, str], set[str]] = {}
    server_tools: dict[str, set[str]] = {}
    provenance: dict[str, int] = {}
    mcp_calls = mcp_chars = plugin_calls = 0
    mcp_sessions: set[str] = set()
    plugin_sessions: set[str] = set()

    def _add(kind: str, key: str, fields: dict[str, Any], row: sqlite3.Row,
             session_id: str | None) -> dict[str, Any]:
        bucket = buckets.setdefault((kind, key), {**fields, "calls": 0, "result_chars": 0,
                                                  "subagent_calls": 0})
        bucket["calls"] += 1
        bucket["result_chars"] += int(row["result_chars"] or 0)
        if row["agent_id"]:
            bucket["subagent_calls"] += 1
        ts, result_ts = row["ts"], row["result_ts"]
        if ts is not None and result_ts is not None and result_ts >= ts:
            durations.setdefault((kind, key), []).append(float(result_ts) - float(ts))
        if with_sessions and session_id is not None:
            ids = seen.setdefault((kind, key), set())
            ids.add(session_id)
            bucket["sessions"] = len(ids)
        return bucket

    for row in rows:
        c = classify(row["tool_name"], row["qualifier"])
        session_id = row["session_id"] if with_sessions else None
        _add("tool", row["tool_name"], {"tool_name": row["tool_name"]}, row, session_id)
        if c.mcp is not None:
            mcp_calls += 1
            mcp_chars += int(row["result_chars"] or 0)
            provenance[c.mcp.provenance] = provenance.get(c.mcp.provenance, 0) + 1
            server_tools.setdefault(c.mcp.server, set()).add(c.mcp.tool)
            bucket = _add("mcp", c.mcp.server,
                          {"server": c.mcp.server,
                           "name": names.get(c.mcp.server, c.mcp.server),
                           "provenance": c.mcp.provenance, "tools": 0},
                          row, session_id)
            bucket["tools"] = len(server_tools[c.mcp.server])
            # Per-TOOL granularity too: the callout ranks servers, but "which
            # of playwright's 17 tools" is a different and useful question.
            _add("mcptool", f"{c.mcp.server}/{c.mcp.tool}",
                 {"server": c.mcp.server, "name": names.get(c.mcp.server, c.mcp.server),
                  "tool": c.mcp.tool}, row, session_id)
            if session_id is not None:
                mcp_sessions.add(session_id)
        if c.plugin is not None:
            plugin_calls += 1
            kind = "mcp" if c.mcp is not None else "skill"
            _add("plugin", f"{c.plugin}/{kind}", {"plugin": c.plugin, "kind": kind},
                 row, session_id)
            if session_id is not None:
                plugin_sessions.add(session_id)

    for key, bucket in buckets.items():
        median = _median(durations.get(key, []))
        bucket["median_s"] = None if median is None else round(median, 2)

    def _ranked(kind: str, cap: int | None = None) -> list[dict[str, Any]]:
        # Calls descending, then name ascending so equal counts are stable.
        values = [b for (k, _), b in buckets.items() if k == kind]
        values.sort(key=lambda d: (-d["calls"],
                                   d.get("tool_name") or d.get("plugin")
                                   or f"{d.get('server')}/{d.get('tool', '')}"))
        return values[:limit if cap is None else cap]

    mcp_block: dict[str, Any] = {
        "calls": mcp_calls,
        "result_chars": mcp_chars,
        "by_provenance": provenance,
        "servers": _ranked("mcp"),
        # A per-SERVER cap in disguise: `limit` ranks the whole flat list, so
        # at 50 a store with a dozen servers loses the quiet ones entirely and
        # the UI's server picker offers a name with no rows behind it. This
        # list is read one server at a time, not as a top-N, so it gets a cap
        # that clears the sum of every server's tool count instead.
        "tools": _ranked("mcptool", tool_limit),
    }
    plugins_block: dict[str, Any] = {"calls": plugin_calls, "items": _ranked("plugin")}
    if with_sessions:
        mcp_block["sessions"] = len(mcp_sessions)
        plugins_block["sessions"] = len(plugin_sessions)
    return _ranked("tool"), mcp_block, plugins_block


_EMPTY_CONTEXT_GROWTH: dict[str, Any] = {
    "result_chars": 0, "calls": 0, "measured_calls": 0, "tools_total": 0, "tools": [],
}


def _context_growth(conn: sqlite3.Connection, where: str, params: list[Any], *,
                    limit: int = 50, agent: str | None = None) -> dict[str, Any]:
    """What actually grew the context, per tool, from `tool_calls.result_chars`.

    Deliberately NOT "cost by tool". A turn's cost is the prompt it carried,
    and that was paid before any of its tools ran — a turn that calls five
    tools did not pay five times, so splitting its dollars across them would
    be invention. The other direction IS sound: a tool RESULT is text that
    enters the context, and every turn after it carries that text again. So
    this ranks tools by how much they poured in, which is the part a reader
    can actually act on.

    Shares are of characters returned, never of dollars, for the same reason:
    a result re-sent at cache-read rates costs a fraction of one at creation
    rates, and a compaction drops some of it entirely. A per-tool $ figure
    would overclaim by a factor nobody could see.

    `calls` counts every call in the window; `measured_calls` only those that
    recorded a result size. `avg_chars` divides by the latter — dividing by
    the former would understate a tool whose results went unrecorded, and it
    is the average that carries the finding: a tool called rarely and
    returning enormously beats a chatty one that returns almost nothing.

    `tools_total` is how many distinct tools the window holds, so a truncated
    list can say what it is a truncation of. `where` is the same
    sessions-side filter every other block takes; `agent` narrows to one
    subagent's calls.
    """
    # `result_chars` was added to `tool_calls` after the table shipped, and
    # the report verbs open the store READ-ONLY — a path that returns before
    # `_migrate` runs. See `_qualifier_sql` for the full trap: naming a
    # missing column here would report an EMPTY account to someone with a
    # thousand transcripts.
    if _result_chars_sql(conn) == "NULL":
        return dict(_EMPTY_CONTEXT_GROWTH)

    scope = f"{where}{' AND' if where else ' WHERE'} c.agent_id = ?" if agent else where
    scoped = [*params, agent] if agent else params
    rows = conn.execute(
        f"""SELECT c.tool_name AS tool_name, COUNT(*) AS calls,
                   COUNT(c.result_chars) AS measured_calls,
                   COALESCE(SUM(c.result_chars), 0) AS result_chars
            FROM tool_calls c JOIN sessions s ON s.session_id = c.session_id{scope}
            GROUP BY c.tool_name
            ORDER BY COALESCE(SUM(c.result_chars), 0) DESC, c.tool_name""",
        scoped,
    ).fetchall()
    total_chars = sum(int(r["result_chars"]) for r in rows)
    return {
        "result_chars": total_chars,
        "calls": sum(int(r["calls"]) for r in rows),
        "measured_calls": sum(int(r["measured_calls"]) for r in rows),
        "tools_total": len(rows),
        "tools": [
            {
                "tool_name": r["tool_name"],
                "calls": int(r["calls"]),
                "measured_calls": int(r["measured_calls"]),
                "result_chars": int(r["result_chars"]),
                "share": round(int(r["result_chars"]) / total_chars, 6) if total_chars else 0.0,
                # None, not 0, where nothing was measured: "we don't know" and
                # "it returned nothing" are different claims.
                "avg_chars": (round(int(r["result_chars"]) / int(r["measured_calls"]))
                              if r["measured_calls"] else None),
            }
            for r in rows[:limit]
        ],
    }


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
                    alias: str = "s", branch: str | None = None,
                    account: str | None = None,
                    conn: sqlite3.Connection | None = None) -> tuple[str, list[Any]]:
    """The WHERE clause every session-scoped read shares. ``branch`` is a
    session-level filter: a session records the LAST branch it was seen on
    (a session can check out several), so a branch-scoped read attributes
    each session wholly to where it ended up. Turns carry no branch.

    ``account`` is likewise session-level — a session belongs to whichever
    account was logged in when it was first ingested (see
    ``ingest._upsert_session_identity``). ``conn`` is needed only to guard
    it: `account_uuid` is a migrated column, and the report verbs open the
    store READ-ONLY — a path that returns before `_migrate` can add it (the
    same trap `_qualifier_sql` documents). Without the guard, an
    account-filtered read against a store not yet resynced since this shipped
    would raise `OperationalError` for a store with a thousand sessions in
    it; with it, the filter is silently dropped (a store with no such column
    has recorded no account for anything, so there is nothing to match).
    """
    clauses: list[str] = []
    params: list[Any] = []
    if repo_root:
        clauses.append(f"{alias}.repo_root = ?")
        params.append(repo_root)
    if branch:
        clauses.append(f"{alias}.git_branch = ?")
        params.append(branch)
    if account and (conn is None
                    or "account_uuid" in {row[1] for row in conn.execute(
                        "PRAGMA table_info(sessions)")}):
        clauses.append(f"{alias}.account_uuid = ?")
        params.append(account)
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
    # Parenthesised, always. `extra` is caller-supplied SQL and `_attribution`
    # passes a multi-clause `a OR b OR c` — spliced bare after the window's own
    # `s.repo_root = ?` that degrades to `(repo_root = ? AND a) OR b OR c`,
    # because SQL binds AND tighter than OR, and every attributed turn in the
    # WHOLE store gets priced into one repo's figure (18x on a real store).
    # The parens cost nothing for the single-clause callers and make the
    # multi-clause ones correct by construction.
    clause = f"{where}{' AND' if where else ' WHERE'} ({extra})" if extra else where
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
             branch: str | None = None, account: str | None = None) -> list[dict[str, Any]]:
    where, params = _session_filter(repo_root, since, branch=branch, account=account, conn=conn)
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


def accounts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """One row per account uuid seen on a session: session count, and when it
    was last active. Read straight off ``sessions.account_uuid`` — what a
    session was actually attributed to at ingest — rather than the
    ``accounts`` table, which only records identity for a config dir that was
    readable AT INGEST TIME and carries no session count of its own.

    Same read-only migration trap as `repos`' column-guarded siblings: naming
    `account_uuid` unconditionally would raise on a store not yet resynced
    since the column shipped."""
    have = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
    if "account_uuid" not in have:
        return []
    rows = conn.execute(
        """SELECT account_uuid, COUNT(*) AS sessions,
                  MAX(COALESCE(last_activity_at, started_at)) AS last_activity_at
           FROM sessions WHERE account_uuid IS NOT NULL
           GROUP BY account_uuid ORDER BY sessions DESC"""
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
    # The rail's rows. `task` is the only legible name an agent has — its id
    # is a hash — and `agent_type` says what KIND it was; both are LEFT-joined
    # so an agent predating either still lists, unnamed.
    subagent_rows = [
        dict(r) for r in conn.execute(
            f"""SELECT t.agent_id AS agent_id, COUNT(*) AS turns,
                      SUM(t.input_tokens + t.cache_read_tokens + t.cache_creation_tokens)
                          AS context_tokens,
                      SUM(t.output_tokens) AS output_tokens, SUM(t.tool_calls) AS tool_calls,
                      MIN(t.ts) AS first_ts, MAX(t.ts) AS last_ts,
                      {_agent_type_sql(conn, 't.')} AS agent_type, {_task_sql(conn)} AS task,
                      {_agent_description_sql(conn)} AS description
               FROM turns t{_agents_join(conn)}
               WHERE t.session_id = ? AND t.agent_id <> ''
               GROUP BY t.agent_id ORDER BY first_ts""",
            (session_id,),
        )
    ]
    # Cost per agent, from the same per-model rate table every other cost on
    # the page uses. The rail listed turns, context, output and tools but not
    # money — so the one question the list is actually scanned for ("which of
    # these was expensive?") could only be answered by opening all of them in
    # turn. `unpriced_turns` rides along so a row on a model the pricing table
    # does not know reads as unknown rather than as free.
    agent_costs = _costs_by(conn, "t.agent_id", " WHERE s.session_id = ?",
                            [session_id], extra="t.agent_id <> ''")
    for row in subagent_rows:
        _attach_cost(row, agent_costs, row["agent_id"])
    detail["subagents"] = subagent_rows

    detail["churn"] = _churn(conn, " WHERE s.session_id = ?", [session_id])
    detail["context_growth"] = _context_growth(
        conn, " WHERE s.session_id = ?", [session_id])
    # The same two blocks the page computes for a whole window, narrowed to
    # this session: which plugins, skills, agent types and MCP servers its
    # tokens went to, and how much of it ran inside a subagent. Both take a
    # sessions-side filter, so nothing here is a special case.
    detail["attribution"] = _attribution(conn, " WHERE s.session_id = ?", [session_id])
    detail["delegation"] = _delegation(conn, " WHERE s.session_id = ?", [session_id])
    detail["tools"], detail["mcp"], detail["plugins"] = _usage_blocks(
        conn.execute(
            f"""SELECT session_id, tool_name, {_qualifier_sql(conn)} AS qualifier,
                       {_result_chars_sql(conn)} AS result_chars,
                       ts, result_ts, agent_id FROM tool_calls
                WHERE session_id = ?""",
            (session_id,),
        ).fetchall(),
        with_sessions=False,
        server_names=mcp_server_names(conn),
    )
    detail["compactions_at"] = [
        r[0] for r in conn.execute(
            "SELECT ts FROM events WHERE session_id = ? AND kind = 'compaction' ORDER BY ts",
            (session_id,),
        )
    ]
    detail["artifacts"] = artifacts_for(conn, session_id)
    tool_rows = conn.execute(
        f"""SELECT tool_name, message_id, {_result_chars_sql(conn)} AS result_chars,
                   result_ts FROM tool_calls
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


def agent_detail(conn: sqlite3.Connection, session_id: str,
                 agent_id: str) -> dict[str, Any] | None:
    """One subagent in detail, or None when the session never ran it.

    The same questions `session_detail` answers, narrowed to an agent: its own
    turns, its own tool calls, its own edits, its own cost. Every fact table
    carries `agent_id`, so each is a WHERE clause on the query that already
    existed rather than a new join.

    Deliberately NOT folded into `session_detail`: a session with eight agents
    at a hundred turns each would triple that payload for a drawer usually
    left unopened, so the caller fetches this only when one is.
    """
    row = conn.execute(
        f"""SELECT t.agent_id AS agent_id, COUNT(*) AS turns,
                   SUM(t.input_tokens + t.cache_read_tokens + t.cache_creation_tokens)
                       AS context_tokens,
                   SUM(t.input_tokens) AS input_tokens,
                   SUM(t.cache_read_tokens) AS cache_read_tokens,
                   SUM(t.cache_creation_tokens) AS cache_creation_tokens,
                   SUM(t.output_tokens) AS output_tokens,
                   SUM(t.thinking_tokens) AS thinking_tokens,
                   SUM(t.tool_calls) AS tool_calls,
                   MIN(t.ts) AS first_ts, MAX(t.ts) AS last_ts,
                   {_agent_type_sql(conn, 't.')} AS agent_type, {_task_sql(conn)} AS task
            FROM turns t{_agents_join(conn)}
            WHERE t.session_id = ? AND t.agent_id = ?""",
        (session_id, agent_id),
    ).fetchone()
    # An agent that ran no turn has no row to show. COUNT(*) makes the
    # aggregate return one line regardless, so the emptiness is read off
    # `turns` rather than off the row's existence.
    if row is None or not row["turns"]:
        return None

    detail = dict(row)
    detail["session_id"] = session_id
    started, last = detail["first_ts"], detail["last_ts"]
    detail["duration_s"] = (
        round(last - started) if started and last and last >= started else None)
    detail["cache_hit_rate"] = cache_hit_rate(
        detail["input_tokens"], detail["cache_read_tokens"], detail["cache_creation_tokens"])
    where, params = " WHERE t.session_id = ? AND t.agent_id = ?", [session_id, agent_id]
    _attach_cost(detail, _costs_by(conn, "t.agent_id", where, params), agent_id)

    series: list[dict[str, Any]] = []
    previous_ts: float | None = None
    for r in conn.execute(
        "SELECT * FROM turns WHERE session_id = ? AND agent_id = ? ORDER BY ts, rowid",
        (session_id, agent_id),
    ):
        ts = r["ts"]
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
            "cold": r["cache_creation_tokens"] > r["cache_read_tokens"],
            "gap_s": round(ts - previous_ts) if ts is not None and previous_ts is not None else None,
            "cost_usd": _cost_of(r),
        })
        if ts is not None:
            previous_ts = ts
    detail["turn_series"] = series
    detail["peak_context_tokens"] = max((t["context_tokens"] for t in series), default=0)

    detail["tools"], detail["mcp"], detail["plugins"] = _usage_blocks(
        conn.execute(
            f"""SELECT session_id, tool_name, {_qualifier_sql(conn)} AS qualifier,
                       {_result_chars_sql(conn)} AS result_chars,
                       ts, result_ts, agent_id FROM tool_calls
                WHERE session_id = ? AND agent_id = ?""",
            (session_id, agent_id),
        ).fetchall(),
        with_sessions=False,
        server_names=mcp_server_names(conn),
    )
    detail["churn"] = _churn(conn, " WHERE s.session_id = ?", [session_id], agent=agent_id)
    detail["context_growth"] = _context_growth(
        conn, " WHERE s.session_id = ?", [session_id], agent=agent_id)
    detail["artifacts"] = [
        _page_row(r) for r in conn.execute(
            _ARTIFACT_PAGE_SQL + " AND a.session_id = ? AND a.agent_id = ?"
            " ORDER BY COALESCE(first_ts, a.ts)",
            (session_id, agent_id),
        )
    ]
    return detail


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
              branch: str | None = None, account: str | None = None) -> list[dict[str, Any]]:
    """Most recently published pages across the filtered sessions.

    ``_ARTIFACT_PAGE_SQL`` already folds a url's republishes WITHIN one
    session into its latest row; a page resumed into another session is a
    SEPARATE row from that query, one per session it was published from, so
    those are merged here by url — otherwise one artifact republished across
    two sessions would count, and list, as two.
    """
    where, params = _session_filter(repo_root, since, branch=branch, account=account, conn=conn)
    clause = where.replace(" WHERE ", " AND ", 1) if where else ""
    pages: list[dict[str, Any]] = []
    by_url: dict[str, dict[str, Any]] = {}
    for r in conn.execute(_ARTIFACT_PAGE_SQL + clause + " ORDER BY a.ts DESC", params):
        row = _page_row(r)
        earlier = by_url.get(row["url"]) if row["url"] else None
        if earlier is None:
            pages.append(row)
            if row["url"]:
                by_url[row["url"]] = row
            continue
        earlier["publishes"] += row["publishes"]
        earlier["first_ts"] = min(earlier["first_ts"], row["first_ts"])
        earlier["favicon"] = earlier["favicon"] or row["favicon"]
        earlier["description"] = earlier["description"] or row["description"]
    return pages[:limit]


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


def _within(days: list[dict[str, Any]], since: float | None) -> list[dict[str, Any]]:
    """Day buckets at or after ``since``.

    ``since`` is a SESSION-level filter (see ``_session_filter``): a session
    counts wholly once any of its activity falls inside the window, so its
    totals keep turns from before it. A day TREND is a different read — a day
    the window excludes must not appear on the chart just because the session
    that touched it also touched a later day that is inside.
    """
    if since is None:
        return days
    first = time.strftime("%Y-%m-%d", time.localtime(since))
    return [d for d in days if d["day"] >= first]


# How close together two hits with no parseable reset time must be to count
# as the SAME event (see `_limit_group_key`).
_LIMIT_BUCKET_SECONDS = 600


def _limit_bucket(ts: float | None) -> int | None:
    return int(ts // _LIMIT_BUCKET_SECONDS) * _LIMIT_BUCKET_SECONDS if ts is not None else None


def _limit_group_key(row: sqlite3.Row) -> tuple[Any, ...]:
    """One real-world hit, however many sessions logged it. `resets_at` is
    the STABLE identity when it parsed — every session hitting the same
    limit at the same moment states the same reset — so it is preferred over
    the hit's own timestamp, which drifts by whenever each session happened
    to retry. Only a hit with no reset time at all falls back to bucketing
    ITS OWN timestamp, which is coarser and can in principle split one real
    event that happened to log with and without a parseable reset time; that
    has not been observed in practice (see the ingest worker's report).

    Deliberately the RAW stored `resets_at`, never a window-inferred one
    (see `_session_windows`/`_weekly_anchor` below) — inference depends on
    the account's OTHER activity, which is a report-time computation and
    must not change what counts as "the same event"."""
    resets_at = row["resets_at"]
    marker = ("resets_at", resets_at) if resets_at is not None else ("bucket", _limit_bucket(row["ts"]))
    return (row["account_uuid"], row["kind"], row["model"], marker)


# --- usage-limit windows -----------------------------------------------------
# The banner states only a RESET time, never when the account's usage window
# OPENED — and the two limits that carry a documented period don't share one
# shape:
#
# - A 5-hour SESSION window is ACTIVITY-anchored: Claude Code opens one on the
#   account's first turn after the previous window's close, and it runs
#   exactly 5h from THAT turn — not from a clock boundary, and not stretched
#   by continued activity. So its start is a fact about when the account
#   worked, recovered here by walking every turn the account ever made (see
#   `_session_windows`), not by subtracting 5h from the reset.
# - A WEEKLY window is the opposite: a FIXED weekly clock boundary (a weekday
#   + local time) that repeats regardless of activity. Its start IS simply
#   `resets_at - 7d`; the only thing worth inferring is the reset itself, for
#   a hit whose own banner didn't parse one (see `_weekly_anchor`).
#
# Monthly-spend and per-model limits have no documented window at all, so
# neither gets one here.

_SESSION_WINDOW_SECONDS = 5 * 3600
_WEEKLY_WINDOW_SECONDS = 7 * 86400


def _session_windows_from_ts(timestamps: Iterable[float]) -> list[tuple[float, float]]:
    """Every 5-hour SESSION window an account opened, from its own turn
    timestamps in ASCENDING order.

    A window opens at the first timestamp at or after the previous window's
    close (`open + 5h`) — including the very first timestamp seen at all,
    which makes that first window best-effort: nothing here can know
    whether activity preceded the data. Activity inside an open window never
    extends it — the close is fixed the instant the window opens, which is
    what "activity-anchored, not clock-anchored" means: WHEN it opens
    depends on activity, how LONG it lasts does not.
    """
    windows: list[tuple[float, float]] = []
    close: float | None = None
    for ts in timestamps:
        if close is None or ts >= close:
            close = ts + _SESSION_WINDOW_SECONDS
            windows.append((ts, close))
    return windows


def _session_windows(conn: sqlite3.Connection, account_uuid: str) -> list[tuple[float, float]]:
    """`_session_windows_from_ts` over one account's own turns — every
    session and subagent it owns, across the account's WHOLE history (a
    window can open on a turn from long before the current report's `since`
    filter, so this is deliberately unfiltered by it)."""
    rows = conn.execute(
        """SELECT t.ts FROM turns t JOIN sessions s ON s.session_id = t.session_id
           WHERE s.account_uuid = ? AND t.ts IS NOT NULL ORDER BY t.ts""",
        (account_uuid,),
    )
    return _session_windows_from_ts(r[0] for r in rows)


def _window_for_hit(windows: list[tuple[float, float]], hit_ts: float) -> tuple[float, float] | None:
    """The session window open when `hit_ts` landed: the last one opened at
    or before it. `windows` is ascending by open, so this is a linear scan
    that stops at the first window opened AFTER the hit. None if the hit
    precedes every known window (turns before it are unknowable) or the
    account has none."""
    found: tuple[float, float] | None = None
    for open_at, close_at in windows:
        if open_at > hit_ts:
            break
        found = (open_at, close_at)
    return found


@dataclass(frozen=True)
class WeeklyAnchor:
    """A weekly reset's fixed schedule: a weekday (Monday=0 .. Sunday=6) and
    a local time, in a named zone. Deliberately NOT hardcoded anywhere in
    this module — every account or organisation can run a different
    schedule, and this is a public repo — so it is always inferred from an
    OBSERVED reset (see `_weekly_anchor`)."""
    weekday: int
    hour: int
    minute: int
    tz: str


def _weekly_anchor_from_reset(resets_at: float, reset_raw: str | None) -> WeeklyAnchor:
    """A `WeeklyAnchor` read off one observed weekly reset. The zone comes
    from the banner's own text when it parsed (`reset_raw`); an unstated or
    unrecognised zone falls back to UTC — still a fixed, well-defined
    schedule, just not verified against the account's own stated zone."""
    zone_name = transcript.reset_zone_name(reset_raw) or "UTC"
    try:
        tz: Any = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError:
        tz, zone_name = timezone.utc, "UTC"
    dt = datetime.fromtimestamp(resets_at, tz=tz)
    return WeeklyAnchor(weekday=dt.weekday(), hour=dt.hour, minute=dt.minute, tz=zone_name)


def _weekly_anchor(conn: sqlite3.Connection, account_uuid: str) -> WeeklyAnchor | None:
    """The account's weekly schedule, inferred from its MOST RECENT weekly
    hit that carried a readable reset — the schedule an org is on now, if it
    has ever changed. None when the account has no such hit to infer from."""
    row = conn.execute(
        """SELECT h.resets_at, h.reset_raw FROM limit_hits h JOIN sessions s ON s.session_id = h.session_id
           WHERE s.account_uuid = ? AND h.kind = 'weekly' AND h.resets_at IS NOT NULL
           ORDER BY h.ts DESC LIMIT 1""",
        (account_uuid,),
    ).fetchone()
    return None if row is None else _weekly_anchor_from_reset(row[0], row[1])


def _nearest_weekly_reset(anchor: WeeklyAnchor, hit_ts: float) -> float:
    """The anchor's next occurrence at or after `hit_ts` — used to infer a
    weekly hit's own reset when its banner's text carried none."""
    tz = ZoneInfo(anchor.tz)
    dt = datetime.fromtimestamp(hit_ts, tz=tz)
    days_ahead = (anchor.weekday - dt.weekday()) % 7
    candidate = (dt + timedelta(days=days_ahead)).replace(
        hour=anchor.hour, minute=anchor.minute, second=0, microsecond=0)
    if candidate < dt:
        candidate += timedelta(days=7)
    return candidate.timestamp()


def _sum_account_tokens(conn: sqlite3.Connection, account_uuid: str,
                        window_start: float, window_end: float) -> dict[str, Any]:
    """Token usage (and cost) an account burned — across ALL its sessions and
    subagents — in `[window_start, window_end]`. The shared arithmetic behind
    every `tokens_to_limit` figure; callers derive the window bounds
    themselves (see `_session_windows`/`_weekly_anchor` above), since a
    session and a weekly limit derive theirs completely differently.
    """
    totals: dict[str, Any] = {"input_tokens": 0, "cache_read_tokens": 0,
                              "cache_creation_tokens": 0, "output_tokens": 0}
    cost = 0.0
    unpriced_turns = 0
    for r in conn.execute(
        """SELECT t.model AS model, COUNT(*) AS turns,
                  COALESCE(SUM(t.input_tokens), 0) AS input_tokens,
                  COALESCE(SUM(t.cache_read_tokens), 0) AS cache_read_tokens,
                  COALESCE(SUM(t.cache_creation_tokens), 0) AS cache_creation_tokens,
                  COALESCE(SUM(t.cache_5m_tokens), 0) AS cache_5m_tokens,
                  COALESCE(SUM(t.cache_1h_tokens), 0) AS cache_1h_tokens,
                  COALESCE(SUM(t.output_tokens), 0) AS output_tokens
           FROM turns t JOIN sessions s ON s.session_id = t.session_id
           WHERE s.account_uuid = ? AND t.ts >= ? AND t.ts <= ?
           GROUP BY t.model""",
        (account_uuid, window_start, window_end),
    ):
        for key in ("input_tokens", "cache_read_tokens", "cache_creation_tokens", "output_tokens"):
            totals[key] += int(r[key])
        priced = _cost_of(r)
        if priced is None:
            unpriced_turns += int(r["turns"])
        else:
            cost += priced
    totals["total_tokens"] = sum(totals.values())
    totals["cost_usd"] = round(cost, 6)
    totals["unpriced_turns"] = unpriced_turns
    totals["window_start"] = window_start
    return totals


def _limit_window_and_tokens(
    conn: sqlite3.Connection, *, kind: str, account_uuid: str | None, hit_at: float | None,
    resets_at: float | None, session_windows: dict[str, list[tuple[float, float]]],
    weekly_anchors: dict[str, WeeklyAnchor | None],
) -> tuple[float | None, bool, dict[str, Any] | None]:
    """`(resets_at, resets_at_inferred, tokens_to_limit)` for one deduped
    event. `session_windows`/`weekly_anchors` are per-account caches the
    caller (`limits`) fills lazily and reuses across every event of one
    account — deriving either is one query over that account's whole turn
    history, and a window with several events sharing one reset must not
    pay for it more than once.

    SESSION: the window containing the hit is looked up (never recomputed
    from the reset), and tokens are summed from its OPEN. A message's own
    stated reset is trusted for DISPLAY exactly as parsed — Claude Code's
    banner and this account's window can disagree by the ~10-minute
    quantisation census has observed on real five-hour boundaries, and that
    is expected, not an error to raise over.

    WEEKLY: the reset itself IS the window's end (`- 7d` is its start), so
    there is nothing to "look up" — only to infer when the banner's own text
    carried none, from the account's other weekly hits.
    """
    if not account_uuid or hit_at is None:
        return resets_at, False, None
    if kind == "session":
        windows = session_windows.setdefault(account_uuid, _session_windows(conn, account_uuid))
        window = _window_for_hit(windows, hit_at)
        if window is None:
            return resets_at, False, None
        inferred = resets_at is None
        effective_resets_at = window[1] if inferred else resets_at
        return effective_resets_at, inferred, _sum_account_tokens(conn, account_uuid, window[0], hit_at)
    if kind == "weekly":
        inferred = False
        if resets_at is None:
            if account_uuid not in weekly_anchors:
                weekly_anchors[account_uuid] = _weekly_anchor(conn, account_uuid)
            anchor = weekly_anchors[account_uuid]
            if anchor is None:
                return None, False, None
            resets_at = _nearest_weekly_reset(anchor, hit_at)
            inferred = True
        tokens = _sum_account_tokens(conn, account_uuid, resets_at - _WEEKLY_WINDOW_SECONDS, hit_at)
        return resets_at, inferred, tokens
    return resets_at, False, None


def limits(conn: sqlite3.Connection, *, repo_root: str | None = None, since: float | None = None,
           branch: str | None = None, account: str | None = None) -> dict[str, Any]:
    """Deduplicated usage-limit hits, most recent first, plus a per-kind count.

    Claude Code writes the SAME real-world hit into every session and
    subagent running at the time (see `transcript.LimitHit`), so the rows in
    `limit_hits` are grouped here into distinct EVENTS — one per
    (account, kind, model, reset) — each carrying how many sessions saw it
    and, when the window is known, the tokens burned reaching it (see
    `_limit_window_and_tokens`).

    Entirely DB-reads: nothing here re-opens a transcript. Window derivation
    for a SESSION event walks the account's own `turns` (indexed on `ts`;
    `sessions.account_uuid` is what makes "the account's turns" a query
    rather than a re-parse), so it costs one ordered scan per DISTINCT
    account across this whole call (cached below), not one per event.

    The filters are session-scoped like every other read here (`repo_root`,
    `branch`, `account` narrow WHICH SESSIONS' hits are considered; `since`
    narrows to hits themselves, like a day trend elsewhere in this module,
    since a hit long before a session's later, in-window activity must not
    count as inside it).
    """
    if not _has_table(conn, "limit_hits"):
        return {"events": [], "by_kind": {}}
    where, params = _session_filter(repo_root, since, branch=branch, account=account, conn=conn)
    rows = conn.execute(
        f"""SELECT h.session_id AS session_id, h.ts AS ts, h.kind AS kind, h.model AS model,
                   h.reset_raw AS reset_raw, h.resets_at AS resets_at, h.raw_text AS raw_text,
                   s.account_uuid AS account_uuid
            FROM limit_hits h JOIN sessions s ON s.session_id = h.session_id
            {where}""",
        params,
    ).fetchall()

    groups: dict[tuple[Any, ...], dict[str, Any]] = {}
    for r in rows:
        g = groups.setdefault(_limit_group_key(r), {
            "account_uuid": r["account_uuid"], "kind": r["kind"], "model": r["model"],
            "resets_at": r["resets_at"], "reset_raw": r["reset_raw"], "raw_text": r["raw_text"],
            "first_ts": None, "last_ts": None, "sessions": set(),
        })
        ts = r["ts"]
        if ts is not None:
            g["first_ts"] = ts if g["first_ts"] is None else min(g["first_ts"], ts)
            g["last_ts"] = ts if g["last_ts"] is None else max(g["last_ts"], ts)
        g["sessions"].add(r["session_id"])

    # Per-account caches so a window/anchor derivation — one ordered scan of
    # that account's whole turn history — is paid at most once per account
    # for this whole call, however many of its events need it.
    session_windows: dict[str, list[tuple[float, float]]] = {}
    weekly_anchors: dict[str, WeeklyAnchor | None] = {}

    events = []
    for g in groups.values():
        resets_at, inferred, tokens = _limit_window_and_tokens(
            conn, kind=g["kind"], account_uuid=g["account_uuid"], hit_at=g["first_ts"],
            resets_at=g["resets_at"], session_windows=session_windows, weekly_anchors=weekly_anchors,
        )
        events.append({
            "account_uuid": g["account_uuid"],
            "kind": g["kind"],
            "model": g["model"],
            "hit_at": g["first_ts"],
            "last_seen_at": g["last_ts"],
            "resets_at": resets_at,
            # True when the banner's own text (or `quotaLimits`) carried no
            # reset at all and this is instead the account's derived window
            # close / weekly anchor — an honest label for a display value
            # this call computed rather than one Claude Code stated.
            "resets_at_inferred": inferred,
            "reset_raw": g["reset_raw"],
            "raw_text": g["raw_text"],
            "sessions": len(g["sessions"]),
            "tokens_to_limit": tokens,
        })
    # `since` is session-scoped in `_session_filter` above (a session with
    # ANY in-window activity keeps every hit it ever logged); this narrows to
    # hits actually inside the window, the same fix `_within` applies to a
    # day trend elsewhere in this module.
    if since is not None:
        events = [e for e in events if e["hit_at"] is not None and e["hit_at"] >= since]
    events.sort(key=lambda e: e["hit_at"] if e["hit_at"] is not None else -1, reverse=True)
    by_kind: dict[str, int] = {}
    for e in events:
        by_kind[e["kind"]] = by_kind.get(e["kind"], 0) + 1
    return {"events": events, "by_kind": by_kind}


def summary(conn: sqlite3.Connection, *, repo_root: str | None = None,
            since: float | None = None, branch: str | None = None,
            account: str | None = None) -> dict[str, Any]:
    where, params = _session_filter(repo_root, since, branch=branch, account=account, conn=conn)
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
    by_day = _within(by_day, since)
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
    usage_rows = conn.execute(
        f"""SELECT c.session_id AS session_id, c.tool_name AS tool_name,
                   {_qualifier_sql(conn, "c.")} AS qualifier,
                   {_result_chars_sql(conn, "c.")} AS result_chars,
                   c.ts AS ts, c.result_ts AS result_ts,
                   c.agent_id AS agent_id
            FROM tool_calls c JOIN sessions s ON s.session_id = c.session_id{where}""",
        params,
    ).fetchall()
    tools, mcp_block, plugins_block = _usage_blocks(
        usage_rows, with_sessions=True, server_names=mcp_server_names(conn))
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
    churn = _churn(conn, where, params)
    churn["by_day"] = _within(churn["by_day"], since)
    return {
        "totals": totals,
        "by_day": by_day,
        "by_model": by_model,
        "tools": tools,
        "context_growth": _context_growth(conn, where, params),
        "churn": churn,
        "attribution": _attribution(conn, where, params),
        "delegation": _delegation(conn, where, params),
        "mcp": mcp_block,
        "plugins": plugins_block,
        "shape": shape,
        "artifacts": artifacts(conn, repo_root=repo_root, since=since, branch=branch,
                              account=account),
    }
