"""Usage-only redaction of Claude Code transcript records (stdlib only).

This module runs ON A REMOTE BOX, on whatever ``python3`` it has, fed over
ssh's stdin (see ``remote_agent``): it must stay Python 3.8-compatible source
(no walrus, no ``match``, no ``dataclass(slots)``, no runtime-evaluated
``X | None``: annotations are deferred by ``from __future__ import annotations``),
and must import nothing from the rest of chronicle. A test parses it under the
3.8 grammar.

The point of it: transcripts can hold PRODUCTION DATA in tool results, prompts
and thinking. Redaction happens here, before a byte leaves the box, so message
content never crosses the wire. ``slim`` is a pure function of one record.

Fidelity levels (each is a strict superset of the one before):

``minimal``      exactly what cost accounting needs — ids, timestamps, cwd,
                 branch, model, the API ``usage`` block, stop_reason, tool NAMES
                 (no inputs), account bridge records, turn durations.
                 LOST: effort, skill/plugin/mcp/agent_type attribution, skill
                 and agent-type qualifiers, tool result sizes, titles, file
                 edits and line churn, artifacts, limit hits, subagent tasks.
``attribution``  ALSO keeps the low-risk minimum needed for the attribution
                 views: ``effort``, the ``attribution*`` stamps, the ``Skill``
                 name and ``Agent`` subagent_type (identifier-shaped values
                 only), each tool result's LENGTH (``_len``, a number — never
                 its text), file path + added/removed line COUNTS of every
                 Edit/Write (``toolUseResult._lines``), Artifact publish
                 facts (action, file path, favicon, the published URL),
                 usage-limit banners (Anthropic-authored text, recognised by
                 prefix), ``isCompactSummary``. Still NEVER kept: prompts,
                 assistant text, thinking, tool inputs, tool result text,
                 titles, agent tasks and descriptions.
``titles``       ALSO keeps session titles (``ai-title``/``custom-title``/
                 ``summary``), Artifact title/description, subagent task lines
                 and agent descriptions — each truncated to 80 characters.
                 These are model- or user-written prose and CAN CONTAIN
                 CUSTOMER OR PRODUCTION DETAIL. Opt in knowingly.
"""
# Annotations are never evaluated at runtime (this import), so the modern
# spellings below cost the remote's 3.8 nothing; it is why ruff's pyupgrade
# rules can stay on for this file.
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

FIDELITIES = ("minimal", "attribution", "titles")
_LEVEL = {name: index for index, name in enumerate(FIDELITIES)}

# Longest string kept for a "short" prose field at the `titles` level.
SHORT_CHARS = 80
# Longest single line the agent will parse (a bigger one is skipped, unread).
MAX_LINE_BYTES = 32 * 1024 * 1024
_STRING_CAP = 2000

KEEP_TOP = ("type", "uuid", "parentUuid", "sessionId", "timestamp", "isSidechain", "agentId",
            "requestId", "cwd", "gitBranch", "version", "entrypoint", "isApiErrorMessage", "error",
            "apiErrorStatus", "isMeta",
            # A boolean marker: without it a compaction summary (whose text is
            # dropped) would read as an ordinary prompt and inflate the count.
            "isCompactSummary")
KEEP_MSG = ("id", "model", "role", "stop_reason")
# The only STRING values `usage` is allowed to carry (everything else in it is a
# number): tier and region labels, never prose.
_USAGE_STRINGS = ("service_tier", "inference_geo", "speed")
KEEP_SYSTEM = ("subtype", "durationMs", "level")
ACCOUNT_KEYS = ("ownerAccountUuid", "ownerOrganizationUuid", "bridgeSessionId",
                "vetoedAgainstAccountUuid", "cause", "ts")
# Assistant-record stamps the attribution views read (see chronicle's
# transcript.py). Values must look like identifiers; anything else is dropped.
ATTRIBUTION_KEYS = ("effort", "effortLevel", "attributionSkill", "attributionPlugin",
                    "attributionAgent", "attributionMcpServer", "attributionMcpTool")
# tool name -> the ONE input key whose value identifies the call.
QUALIFIER_KEYS = {"Skill": "skill", "Agent": "subagent_type", "Task": "subagent_type"}
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")

_IDENT_RE = re.compile(r"^[A-Za-z0-9_.:/@+\- ]{1,100}$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.:/@+\- ]{1,200}$")
_ARTIFACT_URL_RE = re.compile(r"https://claude\.ai/code/artifact/[A-Za-z0-9-]+")
_LIMIT_PREFIXES = ("You've hit your session limit", "You've hit your weekly limit",
                   "You've hit your monthly spend limit")
_MODEL_LIMIT_RE = re.compile(r"^You've reached your .+? limit\b")
_TEAMMATE_SUMMARY_RE = re.compile(r'<teammate-message\b[^>]*\bsummary="([^"]*)"')
REDACTED = "[redacted]"


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _copy_scalars(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    """The named keys of ``source`` whose values are plain scalars. A key that
    holds a container (or a string longer than any real id) is dropped: the
    whitelist names FIELDS, and a field that changed shape is not the field."""
    out: dict[str, Any] = {}
    for key in keys:
        if key not in source:
            continue
        value = source[key]
        if not _scalar(value):
            continue
        if isinstance(value, str) and len(value) > _STRING_CAP:
            continue
        out[key] = value
    return out


def _usage(value: Any, depth: int = 0) -> Any:
    """``message.usage`` as numbers (recursively), plus the few named label
    strings. A field of any other type is not usage, so it is not kept."""
    if isinstance(value, (bool, int, float)):
        return value
    if depth > 4:
        return None
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 64:
                continue
            if isinstance(item, str):
                if key in _USAGE_STRINGS and _IDENT_RE.match(item):
                    out[key] = item
                continue
            kept = _usage(item, depth + 1)
            if kept is not None:
                out[key] = kept
        return out
    if isinstance(value, list):
        return [k for k in (_usage(item, depth + 1) for item in value[:16]) if k is not None]
    return None


def _ident(value: Any) -> str | None:
    return value if isinstance(value, str) and _IDENT_RE.match(value) else None


def _short(value: Any) -> str | None:
    """One whitespace-collapsed line, at most ``SHORT_CHARS`` long."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text[:SHORT_CHARS] if text else None


def result_text(payload: Any) -> str:
    """The text chronicle measures a tool result by (``transcript.py`` does the
    same computation, so a length taken here equals one taken there)."""
    if isinstance(payload, str):
        return payload
    return json.dumps(payload) if payload is not None else ""


def _int_pair(value: Any) -> tuple[int, int] | None:
    if (isinstance(value, list) and len(value) == 2
            and all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in value)):
        return value[0], value[1]
    return None


def _line_counts(tool_use_result: Any) -> dict[str, Any] | None:
    """``{filePath, type, _lines: [added, removed]}`` from an Edit/Write's
    ``toolUseResult`` — the diff's +/- line COUNTS, never its content. None
    when the result carries no diff."""
    if not isinstance(tool_use_result, dict):
        return None
    patch = tool_use_result.get("structuredPatch")
    file_path = tool_use_result.get("filePath")
    if not isinstance(patch, list) or not isinstance(file_path, str) or not file_path:
        return None
    added = removed = 0
    for hunk in patch:
        if not isinstance(hunk, dict):
            continue
        lines = hunk.get("lines")
        for line in lines if isinstance(lines, list) else ():
            if not isinstance(line, str) or line.startswith("\\"):
                continue
            if line.startswith("+"):
                added += 1
            elif line.startswith("-"):
                removed += 1
    out: dict[str, Any] = {"filePath": file_path[:_STRING_CAP], "_lines": [added, removed]}
    kind = tool_use_result.get("type")
    if isinstance(kind, str) and _IDENT_RE.match(kind):
        out["type"] = kind
    return out


def _tool_input(name: str, raw: Any, level: int) -> dict[str, Any]:
    """A tool call's input, cut down to what attribution needs (nothing at all
    at ``minimal``)."""
    if level < 1 or not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    key = QUALIFIER_KEYS.get(name)
    if key is not None:
        value = _ident(raw.get(key))
        if value is not None:
            out[key] = value
    elif name in EDIT_TOOLS:
        # The bodies (old_string/new_string/content) are exactly what must not
        # leave. Churn is carried by the RESULT's `_lines`, not by the input.
        for path_key in ("file_path", "notebook_path"):
            value = raw.get(path_key)
            if isinstance(value, str) and value:
                out[path_key] = value[:_STRING_CAP]
    elif name == "Artifact":
        action = _ident(raw.get("action"))
        if action is not None:
            out["action"] = action
        value = raw.get("file_path")
        if isinstance(value, str) and value:
            out["file_path"] = value[:_STRING_CAP]
        favicon = raw.get("favicon")
        if isinstance(favicon, str) and 0 < len(favicon) <= 40:
            out["favicon"] = favicon
        url = raw.get("url")
        if isinstance(url, str) and url:
            match = _ARTIFACT_URL_RE.search(url)
            out["url"] = match.group(0) if match else "x"
        if level >= 2:
            for text_key in ("title", "description"):
                short = _short(raw.get(text_key))
                if short is not None:
                    out[text_key] = short
    return out


def _limit_banner(record: dict[str, Any]) -> bool:
    return record.get("isApiErrorMessage") is True and record.get("error") == "rate_limit"


def _banner_text(text: Any) -> str:
    """A usage-limit banner's text, kept ONLY when it opens with one of the
    clauses Claude Code itself writes; anything else is content we cannot vouch
    for and becomes empty."""
    if not isinstance(text, str):
        return ""
    if text.startswith(_LIMIT_PREFIXES) or _MODEL_LIMIT_RE.match(text):
        return text[:600]
    return ""


def _assistant(record: dict[str, Any], out: dict[str, Any], level: int) -> None:
    raw_msg = record.get("message")
    msg = raw_msg if isinstance(raw_msg, dict) else {}
    kept = _copy_scalars(msg, KEEP_MSG)
    if isinstance(msg.get("usage"), dict):
        kept["usage"] = _usage(msg["usage"])
    banner = level >= 1 and _limit_banner(record)
    blocks: list[dict[str, Any]] = []
    content = msg.get("content")
    for block in content if isinstance(content, list) else ():
        if not isinstance(block, dict):
            continue
        kind = block.get("type", "text")
        if kind == "tool_use":
            name = block.get("name")
            if not isinstance(name, str) or not _NAME_RE.match(name):
                name = "unknown"
            tool_id = block.get("id")
            blocks.append({"type": "tool_use", "id": tool_id if _scalar(tool_id) else None,
                           "name": name, "input": _tool_input(name, block.get("input"), level)})
        else:
            text = _banner_text(block.get("text")) if banner and kind == "text" else ""
            blocks.append({"type": kind if isinstance(kind, str) else "text", "text": text})
    kept["content"] = blocks
    out["message"] = kept
    if level >= 1:
        for key in ATTRIBUTION_KEYS:
            value = _ident(record.get(key))
            if value is not None:
                out[key] = value
        quota = record.get("quotaLimits")
        if banner and isinstance(quota, dict):
            resets = quota.get("resetsAt")
            if isinstance(resets, (int, float)) and not isinstance(resets, bool):
                out["quotaLimits"] = {"resetsAt": resets}


def _task_line(content: Any) -> str | None:
    """A subagent's opening prompt as one short line — the agent-team wrapper's
    own ``summary`` when it has one (as chronicle's ``_subagent_task`` prefers),
    else the first ``SHORT_CHARS`` characters of the prose."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = " ".join(b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text"
                        and isinstance(b.get("text"), str))
    else:
        return None
    text = " ".join(text.split())
    wrapped = _TEAMMATE_SUMMARY_RE.search(text)
    if wrapped and wrapped.group(1).strip():
        return _short(wrapped.group(1))
    return _short(text)


def _tool_result_block(block: dict[str, Any], level: int) -> dict[str, Any]:
    tool_use_id = block.get("tool_use_id")
    out = {"type": "tool_result", "tool_use_id": tool_use_id if _scalar(tool_use_id) else None,
           "content": ""}
    if level < 1:
        return out
    text = result_text(block.get("content"))
    out["_len"] = len(text)
    if block.get("is_error") is True:
        out["is_error"] = True
    else:
        match = _ARTIFACT_URL_RE.search(text)
        if match:
            out["content"] = match.group(0)
    return out


def _user(record: dict[str, Any], out: dict[str, Any], level: int) -> None:
    raw_msg = record.get("message")
    content = raw_msg.get("content") if isinstance(raw_msg, dict) else None
    if (isinstance(content, list) and len(content) > 0
            and all(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)):
        out["message"] = {"role": "user",
                          "content": [_tool_result_block(b, level) for b in content]}
        if level >= 1:
            counts = _line_counts(record.get("toolUseResult"))
            if counts is not None:
                out["toolUseResult"] = counts
        return
    body = REDACTED
    if level >= 2 and (record.get("isSidechain") or record.get("agentId")):
        body = _task_line(content) or REDACTED
    out["message"] = {"role": "user", "content": body}
    # chronicle refuses to count a record carrying `toolUseResult` as a prompt;
    # keep the KEY (empty) so that survives, without any of its content.
    if "toolUseResult" in record:
        out["toolUseResult"] = {}


def slim(record: Any, fidelity: str = "minimal") -> dict[str, Any] | None:
    """One transcript record cut down to ``fidelity`` (see the module doc), or
    None for a record type that carries nothing usage-related. Pure: the input
    is not modified. A ``fidelity`` not in ``FIDELITIES`` is a ValueError."""
    if fidelity not in _LEVEL:
        raise ValueError(f"unknown fidelity: {fidelity!r}")
    level = _LEVEL[fidelity]
    if not isinstance(record, dict):
        return None
    kind = record.get("type")
    if level >= 2 and kind in ("ai-title", "custom-title", "summary"):
        title_key = {"ai-title": "aiTitle", "custom-title": "customTitle", "summary": "summary"}[kind]
        title = _short(record.get(title_key))
        if title is None:
            return None
        out = _copy_scalars(record, ("type", "sessionId"))
        out[title_key] = title
        return out
    out = _copy_scalars(record, KEEP_TOP)
    if kind == "assistant":
        _assistant(record, out, level)
    elif kind == "user":
        _user(record, out, level)
    elif kind == "system":
        out.update(_copy_scalars(record, KEEP_SYSTEM))
    elif kind in ("bridge-session", "history-suppression"):
        out.update(_copy_scalars(record, ACCOUNT_KEYS))
    elif kind == "cost-state":
        for key in ("totalCostUSD", "startTime", "modelUsage"):
            if key in record:
                out[key] = record[key]
    else:
        return None
    return out


def slim_meta(text: str, fidelity: str) -> str | None:
    """An ``agent-<id>.meta.json``'s text cut down: only the ``titles`` level
    keeps anything (the short ``description`` label). None means: send nothing."""
    if _LEVEL.get(fidelity, 0) < 2:
        return None
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return None
    description = _short(data.get("description")) if isinstance(data, dict) else None
    if description is None:
        return None
    return json.dumps({"description": description}, separators=(",", ":"))


def slim_line(raw: bytes, fidelity: str) -> str | None:
    """One raw transcript line -> one compact redacted JSON line (no newline),
    or None to drop it (unparseable, non-UTF8 beyond repair, or nothing to
    keep). Never raises on hostile input."""
    try:
        record = json.loads(raw.decode("utf-8", errors="replace"))
        slimmed = slim(record, fidelity)
    except (ValueError, RecursionError):
        return None
    if slimmed is None:
        return None
    return json.dumps(slimmed, separators=(",", ":"))


def iter_complete_lines(handle: Any, start: int, limit: int, expired: Any,
                        block: int = 1 << 20) -> Iterator[tuple[bytes | None, int]]:
    """COMPLETE lines of a binary file object from byte ``start``, as
    ``(line_bytes, end_offset)`` where ``end_offset`` is the offset just past
    the line's newline. A trailing partial line (a writer mid-line) is never
    yielded, so the caller's offset only ever advances over whole lines.

    Stops once ``limit`` bytes have been consumed (finishing the line in
    hand: one line is always delivered) or ``expired()`` says the time budget
    is spent. A line longer than ``MAX_LINE_BYTES`` is skipped without being
    held: ``(None, end_offset)`` is yielded in its place, so a huge line costs
    memory of one block, not of itself."""
    handle.seek(start)
    pos = start
    consumed = 0
    buf = b""
    skipping = False
    while True:
        chunk = handle.read(block)
        if not chunk:
            return
        buf += chunk
        while True:
            newline = buf.find(b"\n")
            if newline < 0:
                break
            line, buf = buf[:newline], buf[newline + 1:]
            end = pos + newline + 1
            pos = end
            consumed += newline + 1
            if skipping:
                skipping = False
                yield None, end
            elif len(line) > MAX_LINE_BYTES:
                yield None, end
            else:
                yield line, end
            if consumed >= limit or expired():
                return
        if len(buf) > MAX_LINE_BYTES:
            # An oversized line in progress: drop what is held, remember why.
            pos += len(buf)
            consumed += len(buf)
            buf = b""
            skipping = True
