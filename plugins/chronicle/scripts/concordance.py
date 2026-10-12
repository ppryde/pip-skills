"""Optional reader for concordance's replay numbers. chronicle never imports concordance: it
runs its CLI and stores the numeric rows it prints. No paths, patterns or content."""
from __future__ import annotations

import sqlite3

FIELDS = ("tool_use_id", "agent_id", "kind", "estimator", "covered", "actual_tokens",
          "concordance_tokens", "latency_ms", "answerable", "drifted", "mode")
_INTS = ("actual_tokens", "concordance_tokens", "latency_ms")
_STRS = ("tool_use_id", "agent_id", "kind", "estimator", "answerable", "drifted", "mode")


def _valid(row: object) -> bool:
    return (isinstance(row, dict) and all(f in row for f in FIELDS)
            and all(isinstance(row[f], int) and not isinstance(row[f], bool) for f in _INTS)
            and all(isinstance(row[f], str) for f in _STRS)
            and isinstance(row["covered"], bool))


def store_rows(conn: sqlite3.Connection, session_id: str, rows: list[dict[str, object]]) -> int:
    """Replace the session's rows with the well-formed ones; return how many were stored."""
    # a repeated tool_use_id keeps its last row, so the count is what is stored
    good = list({r["tool_use_id"]: r for r in rows if _valid(r)}.values())
    with conn:
        conn.execute("DELETE FROM concordance_rows WHERE session_id = ?", (session_id,))
        conn.executemany(
            f"INSERT OR REPLACE INTO concordance_rows(session_id, {', '.join(FIELDS)}) "
            f"VALUES (?, {', '.join('?' for _ in FIELDS)})",
            [(session_id, *(r[f] for f in FIELDS)) for r in good])
    return len(good)
