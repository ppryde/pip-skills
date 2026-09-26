"""``chronicle dedupe`` — apply the one-call-one-row rule to an existing store.

Ingest applies ``scripts.replay``'s rule to everything it reads from now on, but
a store built before that holds every replayed call once per copy — and for
sessions whose transcripts have since been deleted from disk a re-sync can never
repair it. This verb does the same job in SQL, on the rows already stored:

* the canonical copy of each ``(session_id, message_id)`` is chosen by the same
  ``replay.rank`` ingest uses (main agent first, else the most complete, else the
  longest snapshot, else the lowest agent id);
* every other copy is deleted, and its tool rows follow the survivor;
* each affected session's rollup is recomputed by ``ingest.rollup`` — the very
  code an ingest uses — and no other session is touched.

Dry-run unless ``apply``: it reports what would go (rows, tokens, API-equivalent
cost, per account) and writes nothing. Applying runs in one write transaction
under the store's busy timeout, so it is safe beside a live dashboard sync, and
it is idempotent: a second run finds no duplicates.
"""
from __future__ import annotations

import sqlite3
import time
from collections import defaultdict
from typing import Any

from scripts import ingest, pricing, ratebook, replay

_DUPLICATED = """
    SELECT t.session_id, t.message_id, t.agent_id, t.model, t.input_tokens, t.cache_read_tokens,
           t.cache_creation_tokens, t.cache_5m_tokens, t.cache_1h_tokens, t.output_tokens,
           t.stop_reason, COALESCE(t.account_uuid, s.account_uuid),
           COALESCE((SELECT MAX(c.byte_offset) FROM cursors c
                     WHERE c.session_id = t.session_id AND c.agent_id = t.agent_id), 0),
           t.ts
    FROM turns t LEFT JOIN sessions s ON s.session_id = t.session_id
    WHERE (t.session_id, t.message_id) IN (
        SELECT session_id, message_id FROM turns GROUP BY session_id, message_id HAVING COUNT(*) > 1)
"""


def dedupe(conn: sqlite3.Connection, *, apply: bool = False,
           now: float | None = None) -> dict[str, Any]:
    """Collapse duplicated calls; return what was (``apply``) or would be removed."""
    if now is None:
        now = time.time()
    book = ratebook.load(conn)
    groups: dict[tuple[str, str], list[tuple[Any, ...]]] = defaultdict(list)
    for row in conn.execute(_DUPLICATED):
        groups[(row[0], row[1])].append(tuple(row))

    winners: list[tuple[str, str, str]] = []
    losers: list[tuple[str, str, str]] = []
    by_account: dict[str, dict[str, Any]] = {}
    tokens = 0
    cost = 0.0
    unpriced = 0
    for (session_id, message_id), rows in sorted(groups.items()):
        best = replay.canonical(replay.Copy(r[2], r[9], r[10], r[12]) for r in rows)
        winners.append((session_id, message_id, best.agent_id))
        for r in rows:
            if r[2] == best.agent_id:
                continue
            losers.append((session_id, r[2], message_id))
            row_tokens = r[4] + r[5] + r[6] + r[9]
            usd = pricing.turn_cost(
                r[3], input_tokens=r[4], cache_read_tokens=r[5], cache_creation_tokens=r[6],
                cache_5m_tokens=r[7], cache_1h_tokens=r[8], output_tokens=r[9],
                book=book, ts=r[13])
            tokens += row_tokens
            cost += usd or 0.0
            unpriced += usd is None
            bucket = by_account.setdefault(
                r[11] or "unknown", {"rows": 0, "tokens": 0, "cost_usd": 0.0})
            bucket["rows"] += 1
            bucket["tokens"] += row_tokens
            bucket["cost_usd"] += usd or 0.0

    sessions = sorted({session_id for session_id, _, _ in losers})
    if apply and losers:
        _apply(conn, winners, losers, sessions, now)
    return {
        "applied": bool(apply),
        "groups": len(groups),
        "rows_removed": len(losers),
        "sessions": len(sessions),
        "tokens_removed": tokens,
        "cost_usd_removed": round(cost, 2),
        "unpriced_rows_removed": unpriced,
        "pricing_as_of": book.pricing_as_of(),
        "by_account": {
            account: {**bucket, "cost_usd": round(bucket["cost_usd"], 2)}
            for account, bucket in sorted(by_account.items())
        },
    }


def _apply(conn: sqlite3.Connection, winners: list[tuple[str, str, str]],
           losers: list[tuple[str, str, str]], sessions: list[str], now: float) -> None:
    """One write transaction: delete the losing copies, re-home their tool
    rows, recompute each affected session. Nothing else is written."""
    conn.commit()                       # start from a clean slate, then own the write lock
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.executemany(
            "DELETE FROM turns WHERE session_id = ? AND agent_id = ? AND message_id = ?", losers)
        for session_id, message_id, agent_id in winners:
            replay.adopt(conn, session_id, message_id, agent_id)
        for session_id in sessions:
            _rollup_keeping_size(conn, session_id, now)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _rollup_keeping_size(conn: sqlite3.Connection, session_id: str, now: float) -> None:
    """``ingest.rollup``, except that a transcript no longer on disk keeps its
    last recorded ``transcript_bytes`` (rollup measures the file and would write
    0) — a dedupe repairs turn counts, it does not forget a session was large."""
    before = conn.execute(
        "SELECT transcript_bytes FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    ingest.rollup(conn, session_id, now=now)
    if before and before[0]:
        conn.execute(
            "UPDATE sessions SET transcript_bytes = ? WHERE session_id = ? AND transcript_bytes = 0",
            (before[0], session_id))
