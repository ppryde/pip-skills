"""replay_rows in usage.db: numbers only, replaced per (session_id, tool_use_id)."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from scripts.replay.core import ROW_FIELDS
from scripts.usage import DAY_S, usage_path

SCHEMA = """
CREATE TABLE IF NOT EXISTS replay_rows(
  session_id TEXT NOT NULL, tool_use_id TEXT NOT NULL, agent_id TEXT NOT NULL,
  kind TEXT NOT NULL, estimator TEXT NOT NULL, covered INTEGER NOT NULL,
  actual_tokens INTEGER NOT NULL, concordance_tokens INTEGER NOT NULL,
  latency_ms INTEGER NOT NULL, exit_code INTEGER NOT NULL, answerable TEXT NOT NULL,
  drifted TEXT NOT NULL, mode TEXT NOT NULL, replayed_at REAL NOT NULL,
  PRIMARY KEY (session_id, tool_use_id));
"""


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.executescript(SCHEMA)
    return conn


def save(rows: list[dict[str, object]], path: Path | None = None) -> None:
    conn = _connect(path or usage_path())
    now = time.time()
    try:
        with conn:
            for sid in {str(r["session_id"]) for r in rows}:
                conn.execute("DELETE FROM replay_rows WHERE session_id = ?", (sid,))
            conn.executemany(
                f"INSERT OR REPLACE INTO replay_rows({', '.join(ROW_FIELDS)}, replayed_at) "
                f"VALUES ({', '.join('?' for _ in ROW_FIELDS)}, ?)",
                [(*(int(v) if isinstance(v, bool) else v for v in (r[f] for f in ROW_FIELDS)), now)
                 for r in rows])
    finally:
        conn.close()


def summary(days: int = 30, path: Path | None = None,
            now: float | None = None) -> dict[str, object]:
    path = path or usage_path()
    since = (time.time() if now is None else now) - days * DAY_S
    out: dict[str, object] = {"days": days, "sessions": 0, "rows": 0, "covered": 0,
                              "by_kind": {}}
    if not path.exists():
        return out
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT session_id, kind, covered, actual_tokens, concordance_tokens, answerable, "
            "drifted FROM replay_rows WHERE replayed_at >= ?", (since,)).fetchall()
    finally:
        conn.close()
    calls: dict[str, int] = {}
    covered: dict[str, int] = {}
    actual: dict[str, int] = {}
    conc: dict[str, int] = {}
    drifted_n: dict[str, int] = {}
    answerable: dict[str, dict[str, int]] = {}
    for _sid, kind, cov, act, con, ans, drf in rows:
        calls[kind] = calls.get(kind, 0) + 1
        covered[kind] = covered.get(kind, 0) + int(cov)
        actual[kind] = actual.get(kind, 0) + int(act)
        conc[kind] = conc.get(kind, 0) + int(con)
        drifted_n[kind] = drifted_n.get(kind, 0) + (drf == "yes")
        tally = answerable.setdefault(kind, {"yes": 0, "no": 0, "unknown": 0})
        tally[ans] = tally.get(ans, 0) + 1
    by_kind = {k: {"calls": calls[k], "covered": covered[k], "actual_tokens": actual[k],
                   "concordance_tokens": conc[k], "answerable": answerable[k],
                   "drifted": drifted_n[k]} for k in calls}
    out.update(sessions=len({r[0] for r in rows}), rows=len(rows),
               covered=sum(int(r[2]) for r in rows), by_kind=by_kind)
    return out
