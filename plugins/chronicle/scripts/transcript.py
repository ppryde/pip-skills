"""Pure parsing of Claude Code transcript JSONL into chronicle facts.

No I/O beyond what the caller hands in: ``fold`` consumes an iterable of raw
lines and returns the facts found in them. Every parse failure is skipped,
never raised — a hook must survive any transcript shape.

Transcript shape (observed, Claude Code 2.1.x):

- ``assistant`` records carry ``message.usage`` and ``message.id``. One API
  call is written as SEVERAL lines (one per content block — thinking, text,
  tool_use), all sharing ``message.id`` and the same ``usage``. Turns are
  therefore keyed by message id; naively summing every line double- or
  triple-counts every call.
- ``user`` records are either a human prompt (string content, or ``text``
  blocks) or a ``tool_result`` carrier. ``isMeta`` / ``isCompactSummary``
  records are synthetic and are not prompts.
- ``system`` records with ``subtype == "turn_duration"`` carry ``durationMs``
  — the wall time the model spent on one turn. ``compact_boundary`` marks a
  context compaction.
- ``ai-title`` records carry the auto-generated session title.
- Subagent transcripts (``<session>/subagents/agent-*.jsonl``) have the same
  shape with ``isSidechain: true`` and an ``agentId``.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

MAIN_AGENT = ""
SYNTHETIC_MODEL = "<synthetic>"



@dataclass
class Turn:
    message_id: str
    agent_id: str = MAIN_AGENT
    request_id: str | None = None
    ts: float | None = None
    model: str | None = None
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    stop_reason: str | None = None
    effort: str | None = None
    tool_uses: list[tuple[str, str]] = field(default_factory=list)  # (tool_use_id, name)

    @property
    def context_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_creation_tokens


@dataclass
class Event:
    uuid: str
    kind: str  # "prompt" | "compaction" | "turn_duration"
    agent_id: str = MAIN_AGENT
    ts: float | None = None
    value: int | None = None


@dataclass
class Facts:
    session_id: str | None = None
    cwd: str | None = None
    git_branch: str | None = None
    version: str | None = None
    entrypoint: str | None = None
    title: str | None = None
    first_ts: float | None = None
    last_ts: float | None = None
    turns: dict[tuple[str, str], Turn] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    lines: int = 0


def parse_ts(value: Any) -> float | None:
    """ISO-8601 (``...Z`` or offset) or epoch number -> epoch seconds; None if unusable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _opt_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _is_prompt(record: dict[str, Any], message: dict[str, Any]) -> bool:
    if record.get("isMeta") or record.get("isCompactSummary"):
        return False
    if "toolUseResult" in record:
        return False
    content = message.get("content")
    if isinstance(content, str):
        return bool(content.strip())
    if isinstance(content, list):
        kinds = {b.get("type") for b in content if isinstance(b, dict)}
        return "text" in kinds and "tool_result" not in kinds
    return False


def _touch_ts(facts: Facts, ts: float | None) -> None:
    if ts is None:
        return
    if facts.first_ts is None or ts < facts.first_ts:
        facts.first_ts = ts
    if facts.last_ts is None or ts > facts.last_ts:
        facts.last_ts = ts


def _fold_assistant(facts: Facts, record: dict[str, Any], agent_id: str) -> None:
    message = record.get("message")
    if not isinstance(message, dict):
        return
    message_id = message.get("id")
    if not isinstance(message_id, str) or not message_id:
        return
    if message.get("model") == SYNTHETIC_MODEL:
        # Claude Code writes locally generated stand-ins (error placeholders,
        # interrupted turns) as assistant records with model "<synthetic>" —
        # no API call happened, so they are not turns.
        return
    key = (agent_id, message_id)
    turn = facts.turns.get(key)
    if turn is None:
        raw_usage = message.get("usage")
        usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
        details = usage.get("output_tokens_details")
        thinking = _int(details.get("thinking_tokens")) if isinstance(details, dict) else 0
        turn = Turn(
            message_id=message_id,
            agent_id=agent_id,
            request_id=_opt_str(record.get("requestId")),
            ts=parse_ts(record.get("timestamp")),
            model=_opt_str(message.get("model")),
            input_tokens=_int(usage.get("input_tokens")),
            cache_read_tokens=_int(usage.get("cache_read_input_tokens")),
            cache_creation_tokens=_int(usage.get("cache_creation_input_tokens")),
            output_tokens=_int(usage.get("output_tokens")),
            thinking_tokens=thinking,
            stop_reason=_opt_str(message.get("stop_reason")),
            effort=_opt_str(record.get("effort")),
        )
        facts.turns[key] = turn
    else:
        # Later lines of the same message can carry a later stop_reason
        # (the final block) — keep the last non-null one.
        stop = message.get("stop_reason")
        if isinstance(stop, str):
            turn.stop_reason = stop
    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool_id = block.get("id")
            name = block.get("name")
            if (isinstance(tool_id, str) and isinstance(name, str)
                    and all(existing != tool_id for existing, _ in turn.tool_uses)):
                turn.tool_uses.append((tool_id, name))


def fold(lines: Iterable[str], *, default_agent: str = MAIN_AGENT) -> Facts:
    """Fold raw transcript lines into ``Facts``. Skips anything unparseable."""
    facts = Facts()
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        facts.lines += 1
        _fold_record(facts, record, default_agent)
    return facts


def _fold_record(facts: Facts, record: dict[str, Any], default_agent: str) -> None:
    kind = record.get("type")
    sid = record.get("sessionId") or record.get("session_id")
    if facts.session_id is None and isinstance(sid, str) and sid:
        facts.session_id = sid
    agent = record.get("agentId")
    agent_id = agent if isinstance(agent, str) and agent else default_agent

    if kind == "ai-title":
        title = record.get("aiTitle")
        if isinstance(title, str) and title.strip():
            facts.title = title.strip()
        return
    if kind == "summary":  # older transcripts: {"type":"summary","summary":"..."}
        summary = record.get("summary")
        if facts.title is None and isinstance(summary, str) and summary.strip():
            facts.title = summary.strip()
        return

    ts = parse_ts(record.get("timestamp"))
    if agent_id == MAIN_AGENT:
        _touch_ts(facts, ts)
        for key, attr in (("cwd", "cwd"), ("gitBranch", "git_branch"),
                          ("version", "version"), ("entrypoint", "entrypoint")):
            value = record.get(key)
            # Branch follows the LATEST record (a session can switch
            # branches); the rest are stable, first-wins.
            if (isinstance(value, str) and value
                    and (attr == "git_branch" or getattr(facts, attr) is None)):
                setattr(facts, attr, value)

    if kind == "assistant":
        _fold_assistant(facts, record, agent_id)
        return

    uuid = record.get("uuid")
    if not isinstance(uuid, str) or not uuid:
        return
    if kind == "user":
        message = record.get("message")
        if isinstance(message, dict) and _is_prompt(record, message):
            facts.events.append(Event(uuid=uuid, kind="prompt", agent_id=agent_id, ts=ts))
        elif record.get("isCompactSummary"):
            facts.events.append(Event(uuid=uuid, kind="compaction", agent_id=agent_id, ts=ts))
        return
    if kind == "system":
        subtype = record.get("subtype")
        if subtype == "turn_duration":
            facts.events.append(Event(uuid=uuid, kind="turn_duration", agent_id=agent_id,
                                      ts=ts, value=_int(record.get("durationMs"))))
        elif subtype == "compact_boundary":
            facts.events.append(Event(uuid=uuid, kind="compaction", agent_id=agent_id, ts=ts))
