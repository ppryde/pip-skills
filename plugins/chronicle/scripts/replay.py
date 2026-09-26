"""One API call is one turn, however many transcript files repeat it.

Claude Code re-writes a long-lived agent's whole history into a NEW agent file
each time it is resumed (``<session>/subagents/agent-<id>.jsonl``), so the same
API call appears — same ``message.id``, same usage, same timestamp — in every
successive snapshot file. On the real archive the files of one such teammate
are nested: each file's assistant message ids are a strict subset of the next
file's. Forks and teammates seeded from a parent can likewise carry the
parent's earlier assistant messages. ``turns`` is keyed
``(session_id, agent_id, message_id)``, so without a rule every file that
repeats a call stored — and every report summed — its own copy: a session that
produced 64 snapshot files counted the same calls up to 64 times. Measured on a
real store, ~29% of all turns and tokens were such copies.

The rule, applied identically at ingest and by ``chronicle dedupe``: **one
``(session_id, message_id)`` is one row.**

1. The main agent's copy (``agent_id = ''``) wins whenever one exists — the
   main transcript is where the call was made.
2. Otherwise exactly one agent-file copy survives. Best is the most COMPLETE
   copy (most output tokens — a copy captured mid-stream carries a partial
   count — then one that has a stop reason); among equally complete copies, the
   one from the LONGEST snapshot (the agent file with the most bytes read, the
   latest snapshot of a resumed agent); the lowest agent id breaks a final tie.
   Which agent "owns" a replayed call is therefore arbitrary: it only moves the
   call within the per-agent breakdown and can never change a total.

Ranking on properties of the copies rather than on arrival order is what makes
the outcome independent of the order files are read in, so an incremental
ingest, a ``sync --full`` and ``chronicle dedupe`` all converge on the same
rows.

Everything keyed to a call — ``tool_calls``, ``artifacts``, ``file_edits`` —
follows the surviving copy's agent (``adopt``), so the per-agent views stay
coherent with the turn rows.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from scripts.transcript import MAIN_AGENT

_CHUNK = 500     # stays clear of SQLite's variable-count limit


@dataclass(frozen=True)
class Copy:
    """One stored (or incoming) copy of a call, reduced to what ranks it.
    ``snapshot_bytes`` is how much of the copy's agent file has been read —
    the proxy for "the longest / latest snapshot" that survives a transcript
    being deleted from disk (it lives in ``cursors``)."""
    agent_id: str
    output_tokens: int
    stop_reason: str | None
    snapshot_bytes: int = 0


def rank(copy: Copy) -> tuple[int, int, int, int, str]:
    """Sort key: the SMALLEST rank is the canonical copy."""
    return (
        0 if copy.agent_id == MAIN_AGENT else 1,
        -(copy.output_tokens or 0),
        0 if copy.stop_reason is not None else 1,
        -(copy.snapshot_bytes or 0),
        copy.agent_id,
    )


def canonical(copies: Iterable[Copy]) -> Copy:
    return min(copies, key=rank)


def stored_copies(conn: sqlite3.Connection, session_id: str,
                  message_ids: Sequence[str]) -> dict[str, list[Copy]]:
    """The rows already stored for these calls, ``{message_id: [copies]}``."""
    found: dict[str, list[Copy]] = {}
    ordered = sorted(set(message_ids))
    for start in range(0, len(ordered), _CHUNK):
        chunk = ordered[start:start + _CHUNK]
        marks = ",".join("?" * len(chunk))
        for message_id, agent_id, output_tokens, stop_reason, size in conn.execute(
            f"""SELECT t.message_id, t.agent_id, t.output_tokens, t.stop_reason,
                       COALESCE((SELECT MAX(c.byte_offset) FROM cursors c
                                 WHERE c.session_id = t.session_id AND c.agent_id = t.agent_id), 0)
                FROM turns t WHERE t.session_id = ? AND t.message_id IN ({marks})""",
            (session_id, *chunk),
        ):
            found.setdefault(message_id, []).append(
                Copy(agent_id, output_tokens, stop_reason, size))
    return found


def adopt(conn: sqlite3.Connection, session_id: str, message_id: str, agent_id: str) -> None:
    """Point everything keyed to this call at the agent whose turn row survives,
    and make that row's ``tool_calls`` the call's true count (the rows may have
    been written under a copy that has since been dropped)."""
    conn.execute(
        "UPDATE tool_calls SET agent_id = ? "
        "WHERE session_id = ? AND message_id = ? AND agent_id <> ?",
        (agent_id, session_id, message_id, agent_id),
    )
    owned = "SELECT tool_use_id FROM tool_calls WHERE session_id = ?1 AND message_id = ?2"
    for table in ("artifacts", "file_edits"):
        conn.execute(
            f"UPDATE {table} SET agent_id = ?3 WHERE session_id = ?1 AND agent_id <> ?3 "
            f"AND tool_use_id IN ({owned})",
            (session_id, message_id, agent_id),
        )
    conn.execute(
        "UPDATE turns SET tool_calls = (SELECT COUNT(*) FROM tool_calls "
        "WHERE session_id = turns.session_id AND message_id = turns.message_id) "
        "WHERE session_id = ? AND message_id = ? AND agent_id = ?",
        (session_id, message_id, agent_id),
    )


def drop_all_but(conn: sqlite3.Connection, session_id: str, message_id: str,
                 keep_agent: str) -> int:
    """Delete every stored copy of the call except ``keep_agent``'s."""
    return conn.execute(
        "DELETE FROM turns WHERE session_id = ? AND message_id = ? AND agent_id <> ?",
        (session_id, message_id, keep_agent),
    ).rowcount
