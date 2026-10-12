"""``chronicle permits``: what subagents were allowed, denied and asked, from the store.

Reads the outcome columns `scripts.permits` fills (``tool_calls.outcome`` and
friends, ``agents.agent_type`` and friends) and aggregates them per
(skill, agent type). Counts and fixed-vocabulary names only: no prompt, path,
argument or error text exists in the store to leak, and an agent type that is
neither a built-in nor ``<plugin>:<name>`` always prints as ``(ad-hoc)``.

The JSON this builds is the only interface to the proposal generator
(``tools/derive_agent_tools.py``), which reads it and writes nothing.
Pull only: it runs on demand, from a person or from a schedule the owner sets up.
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from typing import Any

from scripts import permits

# The first Claude Code that writes `permissionDecision` on tool results. A call
# from an older CLI never has one, so "no decision" is only drift past this.
DECISION_SINCE = (2, 1, 295)
UNATTRIBUTED = "(unattributed)"
UNKNOWN_TYPE = "?"
_OK = ("ok", "prompted:approved")
_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)")
MODES = ("interactive", "non-interactive", "unknown")


def _version_tuple(value: str | None) -> tuple[int, int, int] | None:
    match = _VERSION.match(value or "")
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None


def _mode(non_interactive: int | None) -> str:
    return MODES[2] if non_interactive is None else MODES[1] if non_interactive else MODES[0]


def _kind(outcome: str | None) -> str:
    if outcome is None:
        return "unknown"
    if outcome in _OK:
        return "ok"
    return outcome.split(":", 1)[0]


def _blank() -> dict[str, Any]:
    return {"calls": 0, "ok": 0, "errors": 0, "denied": 0, "prompts_rejected": 0,
            "prompts_approved": 0, "prompts_total": 0, "unknown": 0}


def _tally(into: dict[str, Any], outcome: str | None, prompted: int | None) -> None:
    into["calls"] += 1
    kind = _kind(outcome)
    if kind == "ok":
        into["ok"] += 1
    elif kind == "error":
        into["errors"] += 1
    elif kind == "denied":
        into["denied"] += 1
    elif kind == "prompted":
        into["prompts_rejected"] += 1       # approved ones are in _OK; the rest are refusals
    else:
        into["unknown"] += 1
    if outcome == "prompted:approved":
        into["prompts_approved"] += 1
    if prompted:
        into["prompts_total"] += 1


def _supported(conn: sqlite3.Connection) -> bool:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(tool_calls)")}
    agent_cols = {row[1] for row in conn.execute("PRAGMA table_info(agents)")}
    return "outcome" in cols and "agent_type" in agent_cols


def report(conn: sqlite3.Connection, *, since: float | None = None, skill: str | None = None,
           agent_type: str | None = None) -> dict[str, Any]:
    """The permissions report as a JSON-able dict (see the module doc).
    ``skill``/``agent_type`` filter groups (``agent_type`` against the FOLDED
    name). A store that predates the outcome columns reports ``supported:
    false`` and nothing else; ``chronicle sync`` migrates it."""
    if not _supported(conn):
        return {"supported": False,
                "note": "this store predates tool-call outcomes; run `chronicle sync` (then "
                        "`sync --full` to backfill older sessions)"}
    where = "WHERE tc.agent_id <> ''"
    params: list[Any] = []
    if since is not None:
        where += " AND tc.ts >= ?"
        params.append(since)
    rows = conn.execute(
        f"""SELECT tc.tool_name, tc.outcome, tc.reason, tc.decision, tc.prompted, tc.shape,
                   ag.agent_type, ag.skill, ag.non_interactive, s.version, tc.session_id,
                   tc.agent_id
            FROM tool_calls tc
            LEFT JOIN agents ag ON ag.session_id = tc.session_id AND ag.agent_id = tc.agent_id
            LEFT JOIN sessions s ON s.session_id = tc.session_id
            {where}""", params).fetchall()

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    tools: dict[tuple[str, str, str], dict[str, Any]] = {}
    flagged: dict[tuple[str, str, str], dict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter))
    agents_seen: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    agents_ni: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    flagged_temporary: Counter[tuple[tuple[str, str, str], str]] = Counter()
    flagged_reasons: dict[tuple[tuple[str, str, str], str], Counter[str]] = defaultdict(Counter)
    drift_decision: Counter[str] = Counter()
    total = other = unknown = 0

    for r in rows:
        folded = permits.fold_agent_type(r["agent_type"]) or UNKNOWN_TYPE
        skill_name = r["skill"] or UNATTRIBUTED
        if skill and skill_name != skill:
            continue
        if agent_type and folded != agent_type:
            continue
        key = (skill_name, folded)
        group = groups.setdefault(key, {
            "skill": skill_name, "agent_type": folded, "agents": 0, "non_interactive_agents": 0,
            **_blank(), "denied_by_cause": Counter(), "outcomes": Counter(),
            "by_mode": {m: _blank() for m in MODES}})
        _tally(group, r["outcome"], r["prompted"])
        _tally(group["by_mode"][_mode(r["non_interactive"])], r["outcome"], r["prompted"])
        agent_key = (r["session_id"], r["agent_id"])
        agents_seen[key].add(agent_key)
        if r["non_interactive"]:
            agents_ni[key].add(agent_key)
        outcome = r["outcome"]
        group["outcomes"][outcome or "unknown"] += 1
        if outcome and outcome.startswith("denied:"):
            group["denied_by_cause"][outcome.split(":", 1)[1]] += 1
        tool_key = (skill_name, folded, r["tool_name"])
        tool = tools.setdefault(tool_key, {
            "skill": skill_name, "agent_type": folded, "tool": r["tool_name"], **_blank(),
            "outcomes": Counter()})
        _tally(tool, outcome, r["prompted"])
        tool["outcomes"][outcome or "unknown"] += 1
        if r["shape"] and outcome and (outcome.startswith(("denied:", "prompted:"))
                                       or r["prompted"]):
            flagged[tool_key][r["shape"]][outcome] += 1
            if r["decision"] == "accept:user_temporary/-":
                flagged_temporary[(tool_key, r["shape"])] += 1
            if r["reason"]:
                flagged_reasons[(tool_key, r["shape"])][r["reason"]] += 1
        total += 1
        if outcome is None:
            unknown += 1
        elif outcome == "error:other":
            other += 1
        version = _version_tuple(r["version"])
        if outcome is not None and version is not None and version >= DECISION_SINCE:
            drift_decision["eligible"] += 1
            if r["decision"] is None:
                drift_decision["no_decision"] += 1

    for key, group in groups.items():
        group["agents"] = len(agents_seen[key])
        group["non_interactive_agents"] = len(agents_ni[key])
        group["denied_by_cause"] = dict(sorted(group["denied_by_cause"].items()))
        group["outcomes"] = dict(sorted(group["outcomes"].items()))
    tool_rows = []
    for tool_key, tool in sorted(tools.items()):
        tool["outcomes"] = dict(sorted(tool["outcomes"].items()))
        tool["flagged_shapes"] = [
            {"shape": shape, "outcomes": dict(sorted(counts.items())),
             "calls": sum(counts.values()),
             # approvals a person gave THIS time (not a permanent rule they already wrote)
             "approved_temporary": flagged_temporary[(tool_key, shape)],
             "reasons": dict(sorted(flagged_reasons[(tool_key, shape)].items()))}
            for shape, counts in sorted(flagged[tool_key].items(),
                                        key=lambda kv: -sum(kv[1].values()))]
        tool_rows.append(tool)

    def share(part: int, whole: int) -> float | None:
        return round(part / whole, 4) if whole else None

    eligible = drift_decision["eligible"]
    return {
        "supported": True,
        "since": since,
        "groups": sorted(groups.values(), key=lambda g: (-g["calls"], g["skill"], g["agent_type"])),
        "tools": tool_rows,
        "drift": {
            "calls": total,
            "error_other": other, "error_other_share": share(other, total),
            "unknown_outcome": unknown, "unknown_outcome_share": share(unknown, total),
            "decision_eligible": eligible,
            "no_decision": drift_decision["no_decision"],
            "no_decision_share": share(drift_decision["no_decision"], eligible),
            "decision_since_cli": ".".join(map(str, DECISION_SINCE)),
        },
    }


def render_text(out: dict[str, Any]) -> str:
    """The same report as aligned tables, for a person at a terminal."""
    if not out.get("supported"):
        return out["note"] + "\n"
    lines = ["PER SKILL / AGENT TYPE",
             _row(["skill", "agent type", "agents", "calls", "ok", "err", "denied", "prompts",
                   "denied by cause"])]
    for g in out["groups"]:
        causes = ", ".join(f"{c}={n}" for c, n in g["denied_by_cause"].items()) or "-"
        lines.append(_row([g["skill"], g["agent_type"], g["agents"], g["calls"], g["ok"],
                           g["errors"], g["denied"], g["prompts_total"], causes]))
    lines += ["", "FLAGGED SHAPES (denied or prompted)",
              _row(["skill", "agent type", "tool", "shape", "calls", "outcomes"])]
    for t in out["tools"]:
        for f in t["flagged_shapes"]:
            outcomes = ", ".join(f"{o}={n}" for o, n in f["outcomes"].items())
            lines.append(_row([t["skill"], t["agent_type"], t["tool"], f["shape"], f["calls"], outcomes]))
    d = out["drift"]
    lines += ["", "DRIFT"]
    lines.append(f"  calls {d['calls']}; error:other {d['error_other']} "
                 f"({_pct(d['error_other_share'])}); unknown outcome {d['unknown_outcome']} "
                 f"({_pct(d['unknown_outcome_share'])})")
    lines.append(f"  no permissionDecision among CLI >= {d['decision_since_cli']}: "
                 f"{d['no_decision']} of {d['decision_eligible']} ({_pct(d['no_decision_share'])})")
    return "\n".join(lines) + "\n"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _row(cells: list[Any]) -> str:
    return "  " + "  ".join(str(c) for c in cells)
