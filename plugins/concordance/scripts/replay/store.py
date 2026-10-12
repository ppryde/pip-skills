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
                              "uncovered": 0, "by_kind": {}}
    if not path.exists():
        return out
    conn = _connect(path)
    try:
        rows = conn.execute(
            "SELECT session_id, kind, covered, actual_tokens, concordance_tokens, answerable, "
            "drifted FROM replay_rows WHERE replayed_at >= ?", (since,)).fetchall()
    finally:
        conn.close()
    # An uncovered call is one concordance would not have touched: its counterfactual is its
    # own actual tokens, so it contributes calls and size but never a saving.
    totals: dict[str, dict[str, int]] = {}
    answerable: dict[str, dict[str, int]] = {}
    split: dict[str, dict[str, dict[str, int]]] = {}
    for _sid, kind, cov, act, con, ans, drf in rows:
        counterfactual = int(con) if cov else int(act)
        t = totals.setdefault(kind, dict.fromkeys(
            ("calls", "covered", "uncovered", "actual_tokens", "concordance_tokens",
             "counterfactual_tokens", "drifted"), 0))
        t["calls"] += 1
        t["covered"] += int(cov)
        t["uncovered"] += int(not cov)
        t["actual_tokens"] += int(act)
        t["concordance_tokens"] += int(con) if cov else 0
        t["counterfactual_tokens"] += counterfactual
        t["drifted"] += drf == "yes"
        tally = answerable.setdefault(kind, {"yes": 0, "no": 0, "unknown": 0})
        tally[ans] = tally.get(ans, 0) + 1
        part = split.setdefault(kind, {}).setdefault(
            ans, {"calls": 0, "actual_tokens": 0, "counterfactual_tokens": 0})
        part["calls"] += 1
        part["actual_tokens"] += int(act)
        part["counterfactual_tokens"] += counterfactual
    by_kind = {k: {**t, "answerable": answerable[k], "by_answerable": split[k]}
               for k, t in totals.items()}
    out.update(sessions=len({r[0] for r in rows}), rows=len(rows), by_kind=by_kind,
               covered=sum(int(r[2]) for r in rows), uncovered=sum(int(not r[2]) for r in rows))
    return out
