"""Replay one session: every tool call becomes one numeric row."""
from __future__ import annotations

from scripts.render import est_tokens
from scripts.replay import drift, estimators
from scripts.replay.transcript import Session, ToolCall

ROW_FIELDS = ("session_id", "tool_use_id", "agent_id", "kind", "estimator", "covered",
              "actual_tokens", "concordance_tokens", "latency_ms", "exit_code",
              "answerable", "drifted", "mode")


def replay_session(session: Session, mode: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    by_agent: dict[str, list[ToolCall]] = {}
    for call in session.calls:
        by_agent.setdefault(call.agent_id, []).append(call)
    for call in session.calls:
        mine = by_agent[call.agent_id]
        query = estimators.match(call)
        kind = query.kind if query else call.name.lower()
        est = estimators.NOT_COVERED
        drifted = "unknown"
        try:  # one odd call must not abort the whole replay: it becomes an uncovered row
            if query:
                est = estimators.estimate(query, call, [c for c in mine if c.seq > call.seq])
            if call.name == "Read" and isinstance(call.input.get("file_path"), str):
                drifted = drift.drifted([c for c in mine if c.seq <= call.seq],
                                        str(call.input["file_path"]), call.cwd)
        except Exception:  # noqa: BLE001
            est, drifted = estimators.NOT_COVERED, "unknown"
        rows.append({
            "session_id": session.session_id, "tool_use_id": call.tool_use_id,
            "agent_id": call.agent_id, "kind": kind,
            "estimator": query.estimator if query else "", "covered": est.covered,
            "actual_tokens": est_tokens(call.result_text),
            "concordance_tokens": est.concordance_tokens, "latency_ms": est.latency_ms,
            "exit_code": est.exit_code, "answerable": est.answerable, "drifted": drifted,
            "mode": mode})
    return rows
