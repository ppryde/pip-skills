"""Pending Learned facts (WF-113 5.5).

Agents report a ``learned`` array of ``{statement, tags}`` objects in their
``overseer-report`` JSON block (``scripts/schemas.py``); the report hook queues
each one here; the orchestrator adjudicates at a stage boundary -- accept
(becomes a real KB fact) or reject (kept, with a reason, so the same claim is
recognisable if re-proposed).

The queue lives in ``board.db`` (``pending_facts``): an add is one INSERT and an
adjudication one ``UPDATE ... WHERE status = 'pending'``, so parallel hooks and
a concurrent accept can no longer lose a row (the old JSONL rewrite could).
``knowledge/pending.jsonl`` is a regenerated view.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from scripts.db import commit_unless_txn, in_txn


@dataclass
class PendingFact:
    id: str
    card: str
    statement: str
    tags: list[str] = field(default_factory=list)
    source: str = ""
    status: str = "pending"
    reason: str = ""


def _row(row: sqlite3.Row) -> PendingFact:
    return PendingFact(
        id=row["id"], card=row["card"], statement=row["statement"],
        tags=json.loads(row["tags"] or "[]"), source=row["source"],
        status=row["status"], reason=row["reason"],
    )


def add_pending(
    conn: sqlite3.Connection, card: str, statement: str, tags: list[str], source: str
) -> PendingFact:
    fact = PendingFact(
        id=f"P-{uuid.uuid4().hex[:6]}", card=card, statement=statement, tags=tags, source=source
    )
    conn.execute(
        "INSERT INTO pending_facts(id, card, statement, tags, source, status, reason, created) "
        "VALUES (?,?,?,?,?,'pending','',?)",
        (fact.id, card, statement, json.dumps(tags), source,
         datetime.now().strftime("%Y-%m-%dT%H:%M")),
    )
    commit_unless_txn(conn)
    return fact


def load_pending(conn: sqlite3.Connection) -> list[PendingFact]:
    return [_row(r) for r in conn.execute("SELECT * FROM pending_facts ORDER BY rowid")]


def set_status(conn: sqlite3.Connection, fact_id: str, status: str, reason: str = "") -> PendingFact:
    """Adjudicate one pending fact. The UPDATE is conditional on ``pending``,
    so two racing adjudications cannot both win."""
    cur = conn.execute(
        "UPDATE pending_facts SET status = ?, reason = ? WHERE id = ? AND status = 'pending'",
        (status, reason, fact_id),
    )
    if cur.rowcount != 1:
        row = conn.execute("SELECT status FROM pending_facts WHERE id = ?", (fact_id,)).fetchone()
        if not in_txn(conn):
            conn.rollback()
        if row is None:
            raise FileNotFoundError(f"no pending fact with id {fact_id}")
        raise ValueError(f"{fact_id} is already {row['status']}")
    commit_unless_txn(conn)
    return _row(conn.execute("SELECT * FROM pending_facts WHERE id = ?", (fact_id,)).fetchone())
