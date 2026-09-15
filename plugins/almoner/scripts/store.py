"""Almoner store: one SQLite file that caches every gather and forgets nothing.

The store caches remote content (a deliberate reversal of the original
no-cache non-goal) so the page renders from the last gather and yesterday's
rows stay browsable. Retention is a VIEW: ``read_digest``'s ``days`` is a SQL
bound, and no table here is ever pruned. Growth is watched via ``log_runs``.

Judgements (asks, rank, because, topic) are deliberately NOT columns on
``item``: every gather replaces the item row, which would wipe them. They get
their own table keyed by (id, digest_hash) when the judging stage lands.
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts import paths
from scripts.model import digest_hash

STATES = ("new", "shown", "dismissed", "acted")
_HIDDEN = ("dismissed", "acted")
BUSY_TIMEOUT_S = 5.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watermark (
    source     TEXT PRIMARY KEY,
    cursor     TEXT,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS seen (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    first_seen  REAL NOT NULL,
    last_seen   REAL NOT NULL,
    shown_count INTEGER NOT NULL DEFAULT 0,
    digest_hash TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'new',
    state_at    REAL
);
CREATE TABLE IF NOT EXISTS item (
    id          TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    context     TEXT NOT NULL,
    title       TEXT,
    excerpt     TEXT,
    messages    TEXT,
    url         TEXT,
    who         TEXT,
    arrived     TEXT,
    arrived_ts  REAL,
    awaiting    INTEGER,
    gathered_at REAL NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS item_when ON item (COALESCE(arrived_ts, gathered_at));
CREATE TABLE IF NOT EXISTS suppressed (
    id     TEXT NOT NULL,
    source TEXT NOT NULL,
    rule   TEXT NOT NULL,
    at     REAL NOT NULL,
    PRIMARY KEY (id, rule)
);
CREATE TABLE IF NOT EXISTS run (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    started        REAL NOT NULL,
    finished       REAL NOT NULL,
    sources_ok     TEXT NOT NULL,
    sources_failed TEXT NOT NULL,
    items_in       INTEGER NOT NULL,
    items_out      INTEGER NOT NULL
);
"""


@contextlib.contextmanager
def _private_umask() -> Iterator[None]:
    """Narrow the process umask to 0o077 for the smallest window that covers
    file creation, so anything SQLite creates fresh (the db, and its -wal/-shm
    sidecars once WAL is on) is born 0600/0700 regardless of the ambient
    umask. The umask is process-global — always restore it, even on error."""
    previous = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


def _tighten(target: Path) -> None:
    """Chmod the db, its parent dir and any WAL/SHM sidecars to private,
    unconditionally. The umask only protects what this connect() creates
    fresh — a directory or db file that predates it (the README has callers
    create config.json under home/ first, so home/ usually pre-exists) is
    born with whatever mode its creator chose, and is never tightened by a
    later ``mkdir(exist_ok=True)``. Only the db's own parent is touched, never
    an arbitrary ancestor a caller chose via ALMONER_DB."""
    os.chmod(target.parent, 0o700)
    os.chmod(target, 0o600)
    for suffix in ("-wal", "-shm"):
        sidecar = target.with_name(target.name + suffix)
        if sidecar.exists():
            os.chmod(sidecar, 0o600)


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path if path is not None else paths.db_path()
    # Work content at rest: the home dir is 0700, the db/WAL/SHM files 0600 —
    # see cmd_status, which must never create either just by asking for status.
    with _private_umask():
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        conn = sqlite3.connect(str(target), timeout=BUSY_TIMEOUT_S)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
    _tighten(target)
    return conn


def connect_readonly(path: Path | None = None) -> sqlite3.Connection:
    """Open the store read-only, for callers (``status``) that must never
    create work-content storage just by asking about it. Creates and loosens
    nothing: the db itself and its parent dir are left exactly as found. A
    -wal/-shm sidecar is another matter — SQLite only materialises it lazily,
    on first access, and mirrors the *main db file's own mode* onto it (so
    the umask wrap alone does not help when that db predates this fix and is
    still loose). A harmless read forces it into existence here, on our
    terms, so it can be chmodded private before any caller sees the
    connection."""
    target = path if path is not None else paths.db_path()
    if not target.exists():
        raise FileNotFoundError(target)
    with _private_umask():
        conn = sqlite3.connect(f"{target.resolve().as_uri()}?mode=ro", uri=True,
                               timeout=BUSY_TIMEOUT_S)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA user_version")
    for suffix in ("-wal", "-shm"):
        sidecar = target.with_name(target.name + suffix)
        if sidecar.exists():
            os.chmod(sidecar, 0o600)
    return conn


def _epoch(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def upsert_items(conn: sqlite3.Connection, items: list[dict[str, Any]], now: float) -> None:
    with conn:
        for item in items:
            h = digest_hash(item)
            row = conn.execute("SELECT digest_hash, state FROM seen WHERE id = ?",
                               (item["id"],)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO seen (id, source, first_seen, last_seen, digest_hash, state)"
                    " VALUES (?, ?, ?, ?, ?, 'new')",
                    (item["id"], item["source"], now, now, h))
            elif row["state"] in _HIDDEN and row["digest_hash"] != h:
                conn.execute(
                    "UPDATE seen SET last_seen = ?, digest_hash = ?, state = 'new', state_at = ?"
                    " WHERE id = ?", (now, h, now, item["id"]))
            else:
                conn.execute("UPDATE seen SET last_seen = ?, digest_hash = ? WHERE id = ?",
                             (now, h, item["id"]))
            awaiting = item.get("awaiting")
            conn.execute(
                "INSERT OR REPLACE INTO item (id, source, context, title, excerpt, messages, url,"
                " who, arrived, arrived_ts, awaiting, gathered_at, payload)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (item["id"], item["source"], item["context"], item.get("title"),
                 item.get("excerpt"), json.dumps(item.get("messages")), item.get("url"),
                 item.get("who"), item.get("arrived"), _epoch(item.get("arrived")),
                 None if awaiting is None else int(bool(awaiting)), now, json.dumps(item)))


def read_digest(conn: sqlite3.Connection, *, days: int, now: float, context: str | None = None,
                source: str | None = None, new_only: bool = False,
                mark_shown: bool = True) -> list[dict[str, Any]]:
    # The window is a query bound, never a post-filter: see module docstring.
    sql = ("SELECT item.id, item.payload, item.gathered_at FROM item"
           " JOIN seen ON seen.id = item.id"
           " WHERE COALESCE(item.arrived_ts, item.gathered_at) >= ?"
           " AND seen.state NOT IN ('dismissed', 'acted')"
           # A page whose conversation was positively closed (all threads
           # resolved) leaves the digest even though its item row is still
           # cached — until a later gather re-emits it past the suppression.
           " AND NOT EXISTS (SELECT 1 FROM suppressed WHERE suppressed.id = item.id"
           " AND suppressed.rule = 'closed' AND suppressed.at > item.gathered_at)")
    params: list[Any] = [now - days * 86400]
    if context is not None:
        sql += " AND item.context = ?"
        params.append(context)
    if source is not None:
        sql += " AND item.source = ?"
        params.append(source)
    if new_only:
        sql += " AND seen.state = 'new'"
    sql += " ORDER BY COALESCE(item.arrived_ts, item.gathered_at) DESC, item.id"
    rows = conn.execute(sql, params).fetchall()
    if mark_shown:
        with conn:
            conn.executemany(
                "UPDATE seen SET shown_count = shown_count + 1,"
                " state = CASE WHEN state = 'new' THEN 'shown' ELSE state END WHERE id = ?",
                [(r["id"],) for r in rows])
    return [{**json.loads(r["payload"]), "gathered_at": r["gathered_at"]} for r in rows]


def set_state(conn: sqlite3.Connection, item_id: str, state: str, now: float) -> bool:
    if state not in _HIDDEN:
        raise ValueError(f"state must be one of {_HIDDEN}")
    with conn:
        cur = conn.execute("UPDATE seen SET state = ?, state_at = ? WHERE id = ?",
                           (state, now, item_id))
    return cur.rowcount > 0


def record_suppressed(conn: sqlite3.Connection, rows: list[tuple[str, str, str]],
                      now: float) -> None:
    with conn:
        conn.executemany(
            "INSERT INTO suppressed (id, source, rule, at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT (id, rule) DO UPDATE SET at = excluded.at",
            [(i, s, r, now) for i, s, r in rows])


def get_watermark(conn: sqlite3.Connection, source: str) -> float | None:
    row = conn.execute("SELECT fetched_at FROM watermark WHERE source = ?",
                       (source,)).fetchone()
    return None if row is None else float(row["fetched_at"])


def set_watermark(conn: sqlite3.Connection, source: str, fetched_at: float,
                  cursor: str | None = None) -> None:
    with conn:
        conn.execute(
            "INSERT INTO watermark (source, cursor, fetched_at) VALUES (?, ?, ?)"
            " ON CONFLICT (source) DO UPDATE SET cursor = excluded.cursor,"
            " fetched_at = excluded.fetched_at", (source, cursor, fetched_at))


def record_run(conn: sqlite3.Connection, *, started: float, finished: float,
               sources_ok: list[str], sources_failed: list[str], items_in: int,
               items_out: int) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO run (started, finished, sources_ok, sources_failed, items_in, items_out)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (started, finished, json.dumps(sources_ok), json.dumps(sources_failed),
             items_in, items_out))
    return int(cur.lastrowid or 0)


def log_runs(conn: sqlite3.Connection, limit: int = 20) -> dict[str, Any]:
    rows = conn.execute("SELECT * FROM run ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    return {
        "runs": [{**dict(r), "sources_ok": json.loads(r["sources_ok"]),
                  "sources_failed": json.loads(r["sources_failed"])} for r in rows],
        "store_bytes": int(page_count * page_size),
    }


def log_suppressed(conn: sqlite3.Connection, limit: int = 200) -> dict[str, Any]:
    rows = conn.execute("SELECT id, source, rule, at FROM suppressed ORDER BY at DESC LIMIT ?",
                        (limit,)).fetchall()
    return {"suppressed": [dict(r) for r in rows]}
