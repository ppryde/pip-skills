"""One row per conversation, and the rule that says whether it waits on you.

Both halves live here, shared by every adapter, so two transports for one
source (``via: agent`` and ``via: api``) cannot drift apart in behaviour.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class InMessage:
    text: str
    at: datetime
    who: str | None = None
    url: str | None = None
    # True: the reader wrote it. False: someone else did. None: cannot tell.
    mine: bool | None = None
    # Which sub-conversation this message belongs to (e.g. a Notion discussion
    # id). Never serialised — it only steers the awaiting rule below.
    thread: str | None = None


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def conversation(*, id: str, source: str, context: str, title: str,
                 messages: list[InMessage], url: str | None = None) -> dict[str, Any]:
    if not messages:
        raise ValueError("a conversation needs at least one message")
    ordered = sorted(messages, key=lambda m: m.at)
    newest = ordered[-1]
    inbound = [m for m in ordered if m.mine is not True]
    headline = inbound[-1] if inbound else newest

    item: dict[str, Any] = {
        "id": id,
        "source": source,
        "context": context,
        "title": title,
        "excerpt": headline.text,
        "count": len(ordered),
        "messages": [_serialise(m) for m in ordered],
        "arrived": iso(headline.at),
        "bundled": False,
        "asks": None,
        "seen_in": [source],
        "rank": None,
        "because": None,
    }
    if headline.who is not None:
        item["who"] = headline.who
    if url is not None:
        item["url"] = url
    # The last-speaker rule. Unknown stays ABSENT: absence must not read as urgency.
    # On a multi-thread row (any message carries a thread id) the rule applies
    # PER THREAD, so an unanswered question in one thread cannot be hidden by
    # the reader answering a different thread on the same page.
    if any(m.thread is not None for m in ordered):
        groups: dict[str | None, list[InMessage]] = {}
        for m in ordered:
            groups.setdefault(m.thread, []).append(m)
        newest_per_group = [max(msgs, key=lambda m: m.at) for msgs in groups.values()]
        if any(g.mine is False for g in newest_per_group):
            item["awaiting"] = True
        elif all(g.mine is True for g in newest_per_group):
            item["awaiting"] = False
        # else: some group's newest is unknown and none is False — omit.
    elif newest.mine is not None:
        item["awaiting"] = newest.mine is False
    return item


def _serialise(m: InMessage) -> dict[str, Any]:
    out: dict[str, Any] = {"text": m.text, "at": iso(m.at)}
    if m.who is not None:
        out["who"] = m.who
    if m.url is not None:
        out["url"] = m.url
    return out


def digest_hash(item: dict[str, Any]) -> str:
    """Hash of what would change your mind about a dismissal.

    Dismissing means "not as it currently stands": when this moves, the row
    comes back as new.
    """
    last = (item.get("messages") or [{}])[-1]
    basis = {
        "title": item.get("title"),
        "count": item.get("count"),
        "awaiting": item.get("awaiting"),
        "last_at": last.get("at"),
        "last_text": last.get("text"),
    }
    return hashlib.sha256(json.dumps(basis, sort_keys=True).encode()).hexdigest()[:16]
