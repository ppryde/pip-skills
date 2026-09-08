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
- ``assistant`` records may carry ``attributionSkill`` / ``attributionPlugin``
  / ``attributionAgent`` / ``attributionMcpServer`` / ``attributionMcpTool``,
  naming what was in scope for that call. They nest (a plugin skill running
  inside a subagent sets three), and are absent on an ordinary turn with
  nothing in scope.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

MAIN_AGENT = ""
SYNTHETIC_MODEL = "<synthetic>"
ARTIFACT_TOOL = "Artifact"
_ARTIFACT_URL_RE = re.compile(r"https://claude\.ai/code/artifact/[A-Za-z0-9-]+")



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
    cache_5m_tokens: int = 0
    cache_1h_tokens: int = 0
    stop_reason: str | None = None
    effort: str | None = None
    # What was in scope for this call, as Claude Code stamps it on the record.
    # On the TURN rather than the tool call, so these account for tokens —
    # "what did superpowers cost" — not merely how often it was invoked.
    # `plugin` is None for a BUILT-IN skill (`code-review`): the transcript
    # says so outright rather than leaving it to be guessed from the name.
    skill: str | None = None
    plugin: str | None = None
    agent_type: str | None = None
    mcp_server: str | None = None
    mcp_tool: str | None = None
    # (tool_use_id, name, qualifier) — see `_qualifier`.
    tool_uses: list[tuple[str, str, str | None]] = field(default_factory=list)
    # Artifact publishes issued in this turn, keyed by tool_use_id.
    artifacts: dict[str, ArtifactUse] = field(default_factory=dict)

    @property
    def context_tokens(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_creation_tokens

    @property
    def cold(self) -> bool:
        """A cold turn had to (re)write more of its prefix than it read back —
        the first call of a session, the first after a cache TTL lapsed, or
        the first after the prefix changed (a compaction)."""
        return self.cache_creation_tokens > self.cache_read_tokens


@dataclass
class ArtifactUse:
    """An ``Artifact`` tool call that creates or redeploys a page. Reads,
    lists, comments and the rest are not creations and are not recorded."""
    tool_use_id: str
    title: str | None = None
    description: str | None = None
    favicon: str | None = None
    redeploy: bool = False
    url: str | None = None  # filled from the tool_result, when it lands


@dataclass
class FileEdit:
    """One file change, from the unified diff Claude Code writes alongside
    every Edit/Write result (`toolUseResult.structuredPatch`)."""
    tool_use_id: str
    file_path: str
    operation: str  # "edit" | "create" | "update"
    lines_added: int = 0
    lines_removed: int = 0
    ts: float | None = None
    # Who made the edit. `tool_calls`, `artifacts` and `events` all record
    # this; `file_edits` did not carry it at all and the insert wrote the main
    # agent for every row, so no subagent could ever own an edit — which made
    # `agent_detail`'s churn permanently empty and inflated the main agent's
    # by every subagent's work.
    agent_id: str = MAIN_AGENT


@dataclass
class ToolResult:
    tool_use_id: str
    chars: int
    ts: float | None
    # The published URL when this is an Artifact publish's result — kept here
    # so an ingest that sees the result but not the call can still fill it.
    artifact_url: str | None = None


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
    # tool_result blocks seen, by tool_use_id (results usually follow their
    # call within the same file, but may land in a later ingest).
    results: dict[str, ToolResult] = field(default_factory=dict)
    # File changes seen, by tool_use_id (see `_file_edit`).
    file_edits: dict[str, FileEdit] = field(default_factory=dict)
    # A SUBAGENT file's opening prompt: the task it was handed (see
    # `_subagent_task`). None on a main transcript, whose first prompt is the
    # user talking rather than an instruction handed down.
    task: str | None = None
    # From a `bridge-session` record: the account and organisation that owns
    # the bridge. NOT written on every session — only ones bridged from
    # claude.ai — so it is a sparse link, absent on most older transcripts.
    # Named for what the record literally says rather than "the billed
    # account", which is an interpretation the data does not state.
    owner_account_uuid: str | None = None
    owner_organization_uuid: str | None = None
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


# How much of a task line to keep. Long enough for the first clause of a
# real instruction, short enough for one row of a drawer's rail.
TASK_CHARS = 200

# Agent-team prompts arrive wrapped by the orchestrator, and the wrapper's
# `summary` attribute is already the short label a rail wants — the raw text
# beneath it opens with markup and says nothing in its first 200 characters.
_TEAMMATE_SUMMARY_RE = re.compile(r'<teammate-message\b[^>]*\bsummary="([^"]*)"')


def _prompt_text(content: Any) -> str:
    """The prose of a user message, whether it arrived as a bare string or as
    content blocks. Non-text blocks contribute nothing."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _subagent_task(content: Any) -> str | None:
    """One line naming what a subagent was asked to do.

    Verbatim and truncated, never summarised — no model runs during ingest,
    and a paraphrase of an instruction is a different claim from the
    instruction. The wrapper's own summary wins when there is one.
    """
    text = " ".join(_prompt_text(content).split())
    if not text:
        return None
    wrapped = _TEAMMATE_SUMMARY_RE.search(text)
    if wrapped and wrapped.group(1).strip():
        return wrapped.group(1).strip()[:TASK_CHARS]
    return text[:TASK_CHARS] + "…" if len(text) > TASK_CHARS else text


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
        creation = usage.get("cache_creation")
        creation = creation if isinstance(creation, dict) else {}
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
            cache_5m_tokens=_int(creation.get("ephemeral_5m_input_tokens")),
            cache_1h_tokens=_int(creation.get("ephemeral_1h_input_tokens")),
            stop_reason=_opt_str(message.get("stop_reason")),
            effort=_opt_str(record.get("effort")),
            skill=_opt_str(record.get("attributionSkill")),
            plugin=_opt_str(record.get("attributionPlugin")),
            agent_type=_opt_str(record.get("attributionAgent")),
            mcp_server=_opt_str(record.get("attributionMcpServer")),
            mcp_tool=_opt_str(record.get("attributionMcpTool")),
        )
        facts.turns[key] = turn
    else:
        # Later lines of the same message can carry a later stop_reason
        # (the final block) — keep the last non-null one.
        stop = message.get("stop_reason")
        if isinstance(stop, str):
            turn.stop_reason = stop
        # ...and a later, LARGER output count. Claude Code writes one line per
        # content block as the response streams, all sharing the message id,
        # and the usage on the early lines is a partial snapshot: a real
        # subagent message read [3, 1337] across its two lines. Freezing the
        # first under-counted that agent's output by 21x (222 recorded against
        # 4,702 actual), and every subagent in the store the same way.
        #
        # MAX, not last: line order is not guaranteed, and a partial snapshot
        # arriving after the total must never lower it. The input side needs
        # no such handling — `input_tokens`/`cache_read`/`cache_creation`
        # describe the prompt, which is settled before the first token is
        # streamed and is identical on every line of the message.
        raw_later = message.get("usage")
        if isinstance(raw_later, dict):
            turn.output_tokens = max(turn.output_tokens, _int(raw_later.get("output_tokens")))
            later_details = raw_later.get("output_tokens_details")
            if isinstance(later_details, dict):
                turn.thinking_tokens = max(
                    turn.thinking_tokens, _int(later_details.get("thinking_tokens"))
                )
    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool_id = block.get("id")
            name = block.get("name")
            if (isinstance(tool_id, str) and isinstance(name, str)
                    and all(existing != tool_id for existing, _, _ in turn.tool_uses)):
                turn.tool_uses.append((tool_id, name, _qualifier(name, block.get("input"))))
                if name == ARTIFACT_TOOL:
                    artifact = _artifact_use(tool_id, block.get("input"))
                    if artifact is not None:
                        turn.artifacts[tool_id] = artifact


def _artifact_use(tool_id: str, raw: Any) -> ArtifactUse | None:
    """An ``Artifact`` call that publishes (the default action) — None for
    every other action (read, list, comments, db, assets, ...)."""
    inp: dict[str, Any] = raw if isinstance(raw, dict) else {}
    action = inp.get("action") or "publish"
    file_path = _opt_str(inp.get("file_path"))
    if action != "publish" or not file_path:
        return None
    # The harness names a page from its <title> tag, and only reads the
    # `title` parameter when that is absent — so most publishes carry no
    # title here. The file's stem is the harness's own last resort, and the
    # best name the transcript can give us.
    title = _opt_str(inp.get("title")) or file_path.rsplit("/", 1)[-1].rsplit(".", 1)[0] or None
    return ArtifactUse(
        tool_use_id=tool_id,
        title=title,
        description=_opt_str(inp.get("description")),
        favicon=_opt_str(inp.get("favicon")),
        redeploy=bool(inp.get("url")),
    )


# Tools whose identity is in their input, and the input key that carries it.
# Kept deliberately narrow: the transcript is the durable record and chronicle
# is a projection over it, so copying arbitrary inputs (an Agent's full prompt,
# a Write's file body) would make the store a second copy of the conversation.
QUALIFIED_TOOLS: dict[str, str] = {"Skill": "skill", "Agent": "subagent_type"}


def _qualifier(name: str, raw: Any) -> str | None:
    """The short identifier distinguishing one `Skill`/`Agent` call from
    another — `tribunal:reckoning`, `Explore`. None for every other tool."""
    key = QUALIFIED_TOOLS.get(name)
    if key is None or not isinstance(raw, dict):
        return None
    return _opt_str(raw.get(key))


def _fold_tool_results(facts: Facts, record: dict[str, Any], message: dict[str, Any],
                       ts: float | None, agent_id: str = MAIN_AGENT) -> None:
    content = message.get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        tool_id = block.get("tool_use_id")
        if not isinstance(tool_id, str) or not tool_id:
            continue
        payload = block.get("content")
        text = payload if isinstance(payload, str) else json.dumps(payload) if payload is not None else ""
        url = artifact_url(text)
        facts.results[tool_id] = ToolResult(tool_use_id=tool_id, chars=len(text), ts=ts,
                                            artifact_url=url)
        edit = _file_edit(tool_id, record.get("toolUseResult"), ts, agent_id)
        if edit is not None:
            facts.file_edits[tool_id] = edit
        if url:
            for turn in facts.turns.values():
                artifact = turn.artifacts.get(tool_id)
                if artifact is not None:
                    artifact.url = url


# Git's marker for a missing trailing newline, which is not a change.
#
# The ---/+++ file headers a unified diff opens with USED to be listed here
# too, and that was a bug: `structuredPatch` hunks carry only +/-/space-
# prefixed CONTENT, never those headers, so the guard caught nothing it was
# aimed at — while a removed line whose own text begins `--` arrives as
# `-` + `--flag` = `---flag` and was silently dropped. Deleting `--flag` from
# a shell script, or adding `++i;`, undercounted the churn feeding the Rework
# tile and the Files ranking.
_DIFF_HEADERS = ("\\",)


def _file_edit(tool_id: str, raw: Any, ts: float | None,
               agent_id: str = MAIN_AGENT) -> FileEdit | None:
    """The file change carried by one `toolUseResult`, or None if it carries
    no diff (a Bash result, a Read, a tool that touched nothing).

    Both Edit and Write produce a `structuredPatch`; `type` distinguishes a
    creation from an in-place change. Counting the +/- lines of the hunks is
    the whole measurement — the diff CONTENT is deliberately not kept, so the
    store stays counts and ids rather than a second copy of the source.
    """
    if not isinstance(raw, dict):
        return None
    patch = raw.get("structuredPatch")
    file_path = _opt_str(raw.get("filePath"))
    if not isinstance(patch, list) or not file_path:
        return None
    added = removed = 0
    for hunk in patch:
        if not isinstance(hunk, dict):
            continue
        for line in hunk.get("lines") or []:
            if not isinstance(line, str) or line.startswith(_DIFF_HEADERS):
                continue
            if line.startswith("+"):
                added += 1
            elif line.startswith("-"):
                removed += 1
    return FileEdit(
        tool_use_id=tool_id,
        file_path=file_path,
        agent_id=agent_id,
        operation=_opt_str(raw.get("type")) or "edit",
        lines_added=added,
        lines_removed=removed,
        ts=ts,
    )


def artifact_url(text: str) -> str | None:
    match = _ARTIFACT_URL_RE.search(text)
    return match.group(0) if match else None


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
    if kind == "bridge-session":
        for key, attr in (("ownerAccountUuid", "owner_account_uuid"),
                          ("ownerOrganizationUuid", "owner_organization_uuid")):
            value = record.get(key)
            if isinstance(value, str) and value and getattr(facts, attr) is None:
                setattr(facts, attr, value)
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
            # A subagent's FIRST prompt is the task it was handed. Later ones
            # are the conversation, and the main agent's are the user talking.
            if agent_id != MAIN_AGENT and facts.task is None:
                facts.task = _subagent_task(message.get("content"))
        elif record.get("isCompactSummary"):
            facts.events.append(Event(uuid=uuid, kind="compaction", agent_id=agent_id, ts=ts))
        elif isinstance(message, dict):
            _fold_tool_results(facts, record, message, ts, agent_id)
        return
    if kind == "system":
        subtype = record.get("subtype")
        if subtype == "turn_duration":
            facts.events.append(Event(uuid=uuid, kind="turn_duration", agent_id=agent_id,
                                      ts=ts, value=_int(record.get("durationMs"))))
        elif subtype == "compact_boundary":
            facts.events.append(Event(uuid=uuid, kind="compaction", agent_id=agent_id, ts=ts))
