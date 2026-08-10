"""SQLite persistence for overseer cards. One board.db per repo, shared by all
its worktrees. Owns schema, card CRUD, atomic claiming, and the one-time
.workflow/ import. Sprints/usage/knowledge remain file-based this phase."""
from __future__ import annotations

import json
import os
import re as _re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

from scripts.models import Card, CardParseError
from scripts.store import derive_repo_root

SCHEMA_VERSION = 1
DB_ENV = "OVERSEER_DB"
_ID_RE = _re.compile(r"\AWF-(\d+)\Z")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS cards (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'planned',
    stage           TEXT,
    "order"         INTEGER NOT NULL DEFAULT 0,
    complexity      TEXT,
    priority        TEXT,
    jira            TEXT,
    linear          TEXT,
    sprint          TEXT,
    parent          TEXT,
    branch          TEXT,
    worktree        TEXT,
    pr              TEXT,
    touches         TEXT NOT NULL DEFAULT '[]',
    depends_on      TEXT NOT NULL DEFAULT '[]',
    budget_estimate INTEGER,
    budget_actual   INTEGER NOT NULL DEFAULT 0,
    created         TEXT NOT NULL DEFAULT '',
    updated         TEXT NOT NULL DEFAULT '',
    blocked_on      TEXT,
    checklist       TEXT NOT NULL DEFAULT '[]',
    repo            TEXT,
    claimed_by      TEXT,
    claimed_at      TEXT,
    claim_acked     INTEGER NOT NULL DEFAULT 0,
    claim_nudged    INTEGER NOT NULL DEFAULT 0,
    body            TEXT NOT NULL DEFAULT '',
    archived        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_cards_live  ON cards(archived, status);
CREATE INDEX IF NOT EXISTS idx_cards_claim ON cards(claimed_by);
"""


def board_db_path(repo_root: Path) -> Path:
    override = os.environ.get(DB_ENV)
    if override:
        return Path(override)
    from scripts.config import central_root
    return central_root(repo_root) / "board.db"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    if get_meta(conn, "schema_version") is None:
        set_meta(conn, "schema_version", str(SCHEMA_VERSION))
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> "str | None":
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def connect(repo_root: Path, *, migrate: bool = True) -> sqlite3.Connection:
    path = board_db_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    ensure_schema(conn)
    # Set-if-absent: record the repo's main root so the dashboard's `repos`
    # verb can enumerate one board per repo. Never overwrites an existing
    # value (stable identity even if this repo_root is ever unreachable on a
    # later connect), and only writes when `derive_repo_root` succeeds — a
    # no-op, no extra commit, on every connect that isn't the very first one.
    existing_root = get_meta(conn, "repo_root")
    if existing_root is None:
        root = derive_repo_root(repo_root)
        if root is not None:
            set_meta(conn, "repo_root", str(root))
            conn.commit()
    else:
        # Identity guard (finding I2): a board that already names a DIFFERENT
        # canonical root than the one connecting now means two repos are
        # sharing one board.db (a residual basename collision). Surface it
        # loudly on stderr; behaviour is otherwise unchanged (set-if-absent).
        this_root = derive_repo_root(repo_root)
        if this_root is not None and str(this_root) != existing_root:
            print(
                f"warning: overseer board at {path} was created for "
                f"{existing_root}; now connected from {this_root}",
                file=sys.stderr,
            )
    if migrate:
        _maybe_import(conn, repo_root)  # defined in Task 6; no-op stub until then
    if migrate and get_meta(conn, "workflow_fs_imported") is None:
        from scripts.store import migrate_workflow_to_central
        migrate_workflow_to_central(repo_root)
        set_meta(conn, "workflow_fs_imported", "1")
        conn.commit()
    return conn


def migrate_from_workflow(
    conn: sqlite3.Connection, repo_root: Path
) -> tuple[int, list[tuple[Path, str]]]:
    """Import live and archived cards from .workflow/ directory tree.

    Reads live cards from <repo>/.workflow/cards/*.md (archived=0) and
    archived cards from <repo>/.workflow/archive/cards/*.md (archived=1).
    Skips CardParseError, but records every skip (path + error message) in
    the returned ``skipped`` list rather than discarding it silently — see
    WF-056 (D1): with hundreds of legacy cards a silent skip goes unnoticed.
    Sets meta migrated_from_workflow=1.

    Sources from ``.workflow/`` (via ``workflow_root``) — the legacy,
    pre-central-storage on-disk location — NOT ``state_root``. Since Task 1,
    ``state_root`` resolves to the CENTRAL folder, which is empty on a
    legacy upgrade; reading from it here would import zero cards and then
    permanently stamp ``migrated_from_workflow=1``, stranding every legacy
    card forever. ``.workflow/`` is where legacy card markdown actually
    lives on disk, regardless of where the central folder points.

    The source root is the DB's OWN repo identity — ``derive_repo_root(repo_root)``
    (falling back to ``repo_root`` itself when derivation fails, e.g. no git) —
    not the raw connecting ``repo_root``. ``board_db_path`` keys one shared
    board.db per MAIN repo, but a worktree can be the FIRST caller to connect
    (and thus the first to trigger this one-time import). Reading straight
    from ``workflow_root(repo_root)`` in that case finds the worktree's own
    (typically empty) `.workflow/`, imports 0 cards, and permanently stamps
    ``migrated_from_workflow=1`` — stranding the main repo's cards forever
    since the import never retries. Resolving to the main root first makes
    the import read the MAIN repo's `.workflow/` no matter which worktree
    connects first.

    The whole import (all card writes + the marker) happens in a single
    transaction: intermediate rows are staged but never committed until
    every file has been processed. If anything goes wrong partway through
    (a crash, or a non-CardParseError exception such as UnicodeDecodeError
    or OSError while reading a file), the transaction is rolled back so the
    DB is left exactly as it was before the import — no partial cards, no
    marker — and the next connect() will retry the import from scratch.

    Returns ``(imported, skipped)``: the count of successfully imported
    cards, and a list of ``(path, reason)`` for every card that failed to
    parse — mirroring ``store.load_live_cards``'s ``quarantined`` list.
    """
    from scripts.store import workflow_root  # local import: avoid cycle
    source_root = derive_repo_root(repo_root) or repo_root
    root = workflow_root(source_root)
    imported = 0
    skipped: list[tuple[Path, str]] = []
    live_dir = root / "cards"
    arch_dir = root / "archive" / "cards"
    try:
        if live_dir.is_dir():
            for path in sorted(live_dir.glob("*.md")):
                try:
                    _upsert(conn, Card.from_text(path.read_text()), 0, commit=False)
                    imported += 1
                except CardParseError as exc:
                    skipped.append((path, str(exc)))
        if arch_dir.is_dir():
            for path in sorted(arch_dir.glob("*.md")):
                try:
                    _upsert(conn, Card.from_text(path.read_text()), 1, commit=False)
                    imported += 1
                except CardParseError as exc:
                    skipped.append((path, str(exc)))
        set_meta(conn, "migrated_from_workflow", "1")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return imported, skipped


def _maybe_import(conn: sqlite3.Connection, repo_root: Path) -> None:
    """Idempotent guard for one-time .workflow/ import.

    If already migrated (meta migrated_from_workflow == "1"), return.
    If DB already has cards, mark as migrated (pre-seeded) and return.
    Otherwise, run migrate_from_workflow.

    The "already has cards?" check queries the DB itself (shared by every
    repo_root that connects to it), so it's inherently consistent regardless
    of which worktree is calling — no separate main-root resolution needed
    here. The actual import fan-out to the MAIN repo's `.workflow/` happens
    inside `migrate_from_workflow`, which `repo_root` is simply passed
    through to unchanged.

    This is the only CLI-reachable seam that triggers the one-time import
    (via `connect()`), so any card skipped as a CardParseError is reported
    here — loudly, on stderr — the same way the repo-root identity guard
    above prints its warning directly rather than routing through a return
    value a caller might ignore (WF-056 / D1: a silent skip at hundreds of
    cards would otherwise never be noticed).
    """
    if get_meta(conn, "migrated_from_workflow") == "1":
        return
    already = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    if already:
        set_meta(conn, "migrated_from_workflow", "1")  # DB pre-seeded; don't double-import
        conn.commit()
        return
    _, skipped = migrate_from_workflow(conn, repo_root)
    for path, reason in skipped:
        print(f"warning: skipped {path} during workflow import: {reason}", file=sys.stderr)


def card_to_params(card: Card) -> dict:
    return {
        "id": card.id,
        "title": card.title,
        "status": card.status,
        "stage": card.stage,
        "order": card.order,
        "complexity": card.complexity,
        "priority": card.priority,
        "jira": card.jira,
        "linear": card.linear,
        "sprint": card.sprint,
        "parent": card.parent,
        "branch": card.branch,
        "worktree": card.worktree,
        "pr": card.pr,
        "touches": json.dumps(card.touches or []),
        "depends_on": json.dumps(card.depends_on or []),
        "budget_estimate": card.budget_estimate,
        "budget_actual": card.budget_actual,
        "created": card.created,
        "updated": card.updated,
        "blocked_on": card.blocked_on,
        "checklist": json.dumps(card.checklist or []),
        "repo": card.repo,
        "claimed_by": card.claimed_by,
        "claimed_at": card.claimed_at,
        "claim_acked": 1 if card.claim_acked else 0,
        "claim_nudged": 1 if card.claim_nudged else 0,
        "body": card.body,
    }


def _json_loads_column(row: sqlite3.Row, column: str) -> list:
    """``json.loads`` a card row's JSON-text column, quarantining a corrupt
    value as ``CardParseError`` instead of letting ``json.JSONDecodeError``
    escape — matches the file store's graceful-quarantine behaviour for a
    malformed row. ``cli.main`` catches ``CardParseError`` and exits 1 with
    a message; it does not catch ``json.JSONDecodeError``."""
    try:
        return json.loads(row[column] or "[]")
    except json.JSONDecodeError as exc:
        raise CardParseError(
            f"card {row['id']!r}: malformed JSON in column {column!r}: {exc}"
        ) from exc


def row_to_card(row: sqlite3.Row) -> Card:
    return Card(
        id=row["id"],
        title=row["title"],
        status=row["status"],
        stage=row["stage"],
        order=row["order"],
        complexity=row["complexity"],
        priority=row["priority"],
        jira=row["jira"],
        linear=row["linear"],
        sprint=row["sprint"],
        parent=row["parent"],
        branch=row["branch"],
        worktree=row["worktree"],
        pr=row["pr"],
        touches=_json_loads_column(row, "touches"),
        depends_on=_json_loads_column(row, "depends_on"),
        budget_estimate=row["budget_estimate"],
        budget_actual=row["budget_actual"] or 0,
        created=row["created"] or "",
        updated=row["updated"] or "",
        blocked_on=row["blocked_on"],
        checklist=_json_loads_column(row, "checklist"),
        repo=row["repo"],
        claimed_by=row["claimed_by"],
        claimed_at=row["claimed_at"],
        claim_acked=bool(row["claim_acked"]),
        claim_nudged=bool(row["claim_nudged"]),
        body=row["body"] or "",
    )


def _upsert(conn: sqlite3.Connection, card: Card, archived: int, *, commit: bool = True) -> None:
    params = card_to_params(card)
    params["archived"] = archived
    cols = ", ".join(f'"{c}"' for c in params)
    ph = ", ".join(f":{c}" for c in params)
    updates = ", ".join(f'"{c}" = excluded."{c}"' for c in params if c != "id")
    conn.execute(
        f"INSERT INTO cards ({cols}) VALUES ({ph}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}",
        params,
    )
    if commit:
        conn.commit()


def save_card(conn: sqlite3.Connection, card: Card) -> None:
    _upsert(conn, card, archived=0)


def create_card(conn: sqlite3.Connection, card: Card) -> None:
    """Insert-only create for a brand-new card id.

    Unlike ``save_card``'s ``INSERT ... ON CONFLICT(id) DO UPDATE`` (needed
    for its shared use editing existing cards), this is a plain ``INSERT``
    with no conflict clause: it raises ``sqlite3.IntegrityError`` if ``id``
    already exists in the table. Used by `new-card` so two concurrent mints
    of the same freshly-generated id can't silently overwrite one another —
    the loser gets a PK-violation error instead of a clobbered card.
    """
    params = card_to_params(card)
    params["archived"] = 0
    cols = ", ".join(f'"{c}"' for c in params)
    ph = ", ".join(f":{c}" for c in params)
    conn.execute(f"INSERT INTO cards ({cols}) VALUES ({ph})", params)
    conn.commit()


def archive_card(conn: sqlite3.Connection, card: Card) -> None:
    _upsert(conn, card, archived=1)


def load_card(conn: sqlite3.Connection, card_id: str) -> "Card | None":
    row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    return row_to_card(row) if row else None


def load_live_cards(conn: sqlite3.Connection) -> "tuple[list[Card], list[Path]]":
    rows = conn.execute("SELECT * FROM cards WHERE archived = 0 ORDER BY id").fetchall()
    return [row_to_card(r) for r in rows], []


def load_archived_cards(conn: sqlite3.Connection) -> "list[Card]":
    rows = conn.execute(
        "SELECT * FROM cards WHERE archived = 1 ORDER BY updated DESC"
    ).fetchall()
    return [row_to_card(r) for r in rows]


def mint_id(conn: sqlite3.Connection) -> str:
    highest = 0
    for (cid,) in conn.execute("SELECT id FROM cards"):
        m = _ID_RE.match(cid or "")
        if m:
            highest = max(highest, int(m.group(1)))
    return f"WF-{highest + 1:03d}"


def claim_card(conn: sqlite3.Connection, card_id: str, session_id: str, now: str, *, force: bool = False) -> bool:
    if force:
        sql = ("UPDATE cards SET claimed_by=?, claimed_at=?, claim_acked=0, "
               "claim_nudged=0, updated=? WHERE id=?")
        args = (session_id, now, now, card_id)
    else:
        sql = ("UPDATE cards SET claimed_by=?, claimed_at=?, claim_acked=0, "
               "claim_nudged=0, updated=? WHERE id=? AND claimed_by IS NULL")
        args = (session_id, now, now, card_id)
    cur = conn.execute(sql, args)
    conn.commit()
    return cur.rowcount == 1


def _parse_iso(value: "str | None") -> "datetime | None":
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def reclaim_stale(conn, live_session_ids, ttl_minutes: int, now: str) -> "list[str]":
    rows = conn.execute(
        "SELECT id, claimed_by, claimed_at FROM cards "
        "WHERE claimed_by IS NOT NULL AND archived = 0"
    ).fetchall()
    now_dt = _parse_iso(now)
    stale: list[str] = []
    for row in rows:
        if live_session_ids is not None:
            if row["claimed_by"] not in live_session_ids:
                stale.append(row["id"])
            continue
        # TTL fallback
        claimed_dt = _parse_iso(row["claimed_at"])
        if claimed_dt is None or now_dt is None:
            stale.append(row["id"])  # can't verify freshness -> reclaim
        elif now_dt - claimed_dt > timedelta(minutes=ttl_minutes):
            stale.append(row["id"])
    for cid in stale:
        conn.execute(
            "UPDATE cards SET claimed_by=NULL, claimed_at=NULL, claim_acked=0, "
            "claim_nudged=0, updated=? WHERE id=?",
            (now, cid),
        )
    conn.commit()
    return stale
