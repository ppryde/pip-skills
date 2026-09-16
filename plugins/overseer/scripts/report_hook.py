"""SubagentStop report hook (WF-113 §5.4).

Turns an overseer agent's one-line reply into ledger records without spending
an agent or orchestrator turn: parse the line, total real usage from the
agent's transcript, write the card and usage.jsonl, queue Learned lines.

Record-only by design. A Stop/SubagentStop hook that blocks makes the agent
continue, which costs a turn at the agent's full context and risks a loop —
so a malformed or over-long reply is *recorded* (``unparsed``/``overrun``),
never bounced. The cap is stated in the dispatch instead.
"""
from __future__ import annotations

from pathlib import Path

from scripts import db
from scripts.dispatch import (
    REPLY_WORD_CAP,
    Reply,
    ReplyError,
    parse_reply,
    reply_words,
    role_of,
)
from scripts.models import Card
from scripts.pending import add_pending, parse_learned
from scripts.store import state_root
from scripts.transcript_usage import budget_tokens, raw_total, sum_usage, zero_usage
from scripts.usage import append_usage


def _record(card: Card, reply: Reply, detail: str, spend: int, now: str) -> None:
    """Budget semantics are unchanged from telemetry.md: implementer and fixer
    spend feeds ``budget_actual``; planner/reviewer/verifier spend is
    measurement only (usage.jsonl)."""
    if reply.role == "reviewer":
        card.record_review(reply.stage, reply.round or 0, reply.slot or "?", reply.line, now)
    elif reply.role == "fixer":
        card.log_progress(f"{reply.stage} r{reply.round} fix — {reply.line}", spend, now)
    elif reply.role == "implementer":
        card.log_progress(f"chunk {reply.chunk} — {reply.line}", spend, now)
    elif reply.role == "planner":
        if reply.status == "DONE" and detail.strip():
            card.set_section("## Plan", detail, now)
    elif reply.role == "verifier" and detail.strip():
        card.set_section("## Verification", detail, now)


def handle(payload: dict[str, object], repo_root: Path, now: str) -> dict[str, object] | None:
    role = role_of(payload.get("agent_type"))
    if role is None:
        return None
    message = payload.get("last_assistant_message")
    text = message if isinstance(message, str) else ""
    transcript = payload.get("agent_transcript_path")
    totals = sum_usage(Path(transcript)) if isinstance(transcript, str) and transcript else zero_usage()
    words = reply_words(text)
    root = state_root(repo_root)
    entry: dict[str, object] = {
        "ts": now, "card": None, "role": role, "stage": None, "round": None,
        "tokens": raw_total(totals), **totals, "budget_tokens": budget_tokens(totals),
        "reply_words": words, "overrun": words > REPLY_WORD_CAP,
        "agent_id": payload.get("agent_id"), "source": "hook",
    }
    try:
        reply = parse_reply(role, text)
        if not reply.path.resolve().is_relative_to((root / "dispatch").resolve()):
            raise ReplyError("reply path is outside this repo's dispatch directory")
    except ReplyError as exc:
        entry.update(unparsed=text[:500], error=str(exc))
        append_usage(root, entry)
        return entry
    entry.update(card=reply.card, stage=reply.stage, round=reply.round)
    try:
        detail = reply.path.read_text()
    except OSError:
        detail = ""
        entry["error"] = "detail file missing"
    spend = budget_tokens(totals)
    conn = db.connect(repo_root)
    try:
        card = db.mutate_card(conn, reply.card, lambda c: _record(c, reply, detail, spend, now))
    finally:
        conn.close()
    if card is None:
        entry["error"] = f"no card {reply.card}"
    else:
        for statement, tags in parse_learned(detail):
            add_pending(repo_root, reply.card, statement, tags, str(reply.path))
        if card.tripwire_breached:
            entry["tripwire"] = True
    append_usage(root, entry)
    return entry
