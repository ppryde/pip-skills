"""SQLite persistence for overseer. One board.db per repo, shared by all its
worktrees. Owns schema, card CRUD, atomic claiming, the transaction helper and
the one-time .workflow/ import.

Schema v2 (WF-265 PR D1) also holds sprints, knowledge facts, pending facts
and stage evidence; the old ``sprints/`` and ``knowledge/`` file trees are
regenerated read-only views (``scripts/views.py``). ``usage.jsonl`` stays a
file: an append-only log that nothing else reads.

WRITE RULE (OL-9): every card write goes through ``txn`` -- ``mutate_card`` for
a read-modify-write of one card, ``put_card`` / ``create_card`` inside an open
``txn``. No code path may ``save_card`` a ``Card`` it loaded in a different
transaction: ``save_card`` upserts the WHOLE row, so two writers that each
load, change and save drop one another's edits. ``save_card`` / ``archive_card``
remain here only as single-statement conveniences for tests and one-off
tooling; a test greps the scripts for them.
"""
from __future__ import annotations

import json
import os
import re as _re
import sqlite3
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from scripts.models import Card, CardParseError
from scripts.store import derive_repo_root

SCHEMA_VERSION = 2
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
    labels          TEXT NOT NULL DEFAULT '[]',
    links           TEXT NOT NULL DEFAULT '[]',
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
CREATE TABLE IF NOT EXISTS label_colors (
    name      TEXT PRIMARY KEY,
    color_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orchestrators (
    card_id    TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    stamped    TEXT NOT NULL
);
"""

# Schema v2: additive tables only. Older plugin versions ignore them.
_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS sprints (
    id              TEXT PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'planned',
    budget_estimate INTEGER,
    budget_actual   INTEGER NOT NULL DEFAULT 0,
    started         TEXT NOT NULL DEFAULT '',
    body            TEXT NOT NULL DEFAULT '',
    updated         TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS facts (
    id            TEXT PRIMARY KEY,
    statement     TEXT NOT NULL,
    tags          TEXT NOT NULL DEFAULT '[]',
    source        TEXT,
    status        TEXT NOT NULL DEFAULT 'active',
    verified      TEXT NOT NULL DEFAULT '',
    created       TEXT NOT NULL DEFAULT '',
    body          TEXT NOT NULL DEFAULT '',
    retired       INTEGER NOT NULL DEFAULT 0,
    superseded_by TEXT
);
CREATE TABLE IF NOT EXISTS pending_facts (
    id        TEXT PRIMARY KEY,
    card      TEXT NOT NULL DEFAULT '',
    statement TEXT NOT NULL,
    tags      TEXT NOT NULL DEFAULT '[]',
    source    TEXT NOT NULL DEFAULT '',
    status    TEXT NOT NULL DEFAULT 'pending',
    reason    TEXT NOT NULL DEFAULT '',
    created   TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS stage_evidence (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id   TEXT NOT NULL,
    stage     TEXT NOT NULL,
    kind      TEXT NOT NULL,
    round     INTEGER,
    slot      TEXT NOT NULL DEFAULT '',
    status    TEXT NOT NULL DEFAULT '',
    critical  INTEGER,
    important INTEGER,
    minor     INTEGER,
    detail    TEXT NOT NULL DEFAULT '',
    ts        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_evidence ON stage_evidence(card_id, stage, kind, round);
"""

# Every table a v2 backup carries (orchestrators are per-session, excluded by design).
V2_TABLES = ("sprints", "facts", "pending_facts", "stage_evidence")


class MigrationError(RuntimeError):
    """The v1 -> v2 board upgrade could not be made safely; the board is
    untouched (the .bak failed to verify, or the import refused)."""


class EditAbort(Exception):
    """Raised inside a ``mutate_card`` callback to roll the edit back and
    report a user-facing reason (the verb prints it and exits 1)."""


def board_db_path(repo_root: Path) -> Path:
    override = os.environ.get(DB_ENV)
    if override:
        return Path(override)
    from scripts.config import central_root
    return central_root(repo_root) / "board.db"


def _exec_script(conn: sqlite3.Connection, script: str) -> None:
    """Run a DDL script statement by statement. ``executescript`` would COMMIT
    first, which would break the migration's single transaction."""
    for stmt in script.split(";"):
        if stmt.strip():
            conn.execute(stmt)


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def ensure_schema(
    conn: sqlite3.Connection, *, path: "Path | None" = None, state: "Path | None" = None
) -> None:
    """Create/upgrade the schema. Fast path (WF-265 OL-7): once a board has
    been through a full pass it carries ``PRAGMA user_version`` ==
    ``SCHEMA_VERSION``, and every later connect skips the DDL, the column
    probe and the meta reads.

    A board still at v1 (or v0) is upgraded to v2 here. When ``path`` names a
    real board file that already holds cards, the upgrade first takes an online
    ``.bak`` (verified) BEFORE any DDL, outside any transaction, then creates
    the v2 tables and imports the legacy sprint/fact/pending files from
    ``state`` in ONE ``BEGIN IMMEDIATE`` transaction (see ``migrate.py``). Two
    processes racing the first upgrade serialise on that lock; the loser sees
    ``user_version`` already 2 and skips.

    A plugin of an older version that opens a v2 board re-stamps
    ``user_version`` to its own number (its fast path is ``== 1``); the marker
    ``meta.state_imported_v2`` lets this code tell that apart from a real v1
    board and just restore the stamp, with no second backup or import."""
    if conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION:
        return
    from scripts import migrate  # local import: migrate imports this module

    populated = (
        _has_table(conn, "cards")
        and conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] > 0
    )
    if _has_table(conn, "meta") and get_meta(conn, "state_imported_v2") is not None:
        # Downgraded stamp from an older plugin: the v2 tables exist already.
        conn.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
        conn.commit()
        return
    if populated and path is not None:
        migrate.backup_before_v2(conn, path)  # raises MigrationError; board untouched
    conn.commit()
    # The one-time upgrade may hold the lock for a while on a big board: wait
    # for it rather than fail "database is locked", then see user_version 2.
    conn.execute("PRAGMA busy_timeout=60000")
    try:
        conn.execute("BEGIN IMMEDIATE")
    finally:
        conn.execute("PRAGMA busy_timeout=5000")
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION:
            conn.rollback()  # lost the race: another process finished the upgrade
            return
        _exec_script(conn, _SCHEMA)
        _migrate_columns(conn)
        _exec_script(conn, _SCHEMA_V2)
        set_meta(conn, "schema_version", str(SCHEMA_VERSION))
        migrate.finish_v2(conn, state, imported=populated)
        conn.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """Idempotent additive-column migration for boards created before a
    column existed. ``CREATE TABLE IF NOT EXISTS`` in ``_SCHEMA`` above is a
    no-op against an already-existing ``cards`` table, so a pre-existing
    board.db never picks up a newly added column on its own -- this runs on
    every ``ensure_schema`` call and adds any column here that's missing,
    with an ``ALTER TABLE ... ADD COLUMN`` default that matches the CREATE
    TABLE default, so existing rows backfill to the same value a brand-new
    table would have given them (no data loss, no NULLs where callers expect
    ``'[]'``). Add future additive columns to this dict rather than only to
    ``_SCHEMA``.
    """
    existing = {row[1] for row in conn.execute("PRAGMA table_info(cards)").fetchall()}
    additive_columns = {
        "labels": "TEXT NOT NULL DEFAULT '[]'",
        "links": "TEXT NOT NULL DEFAULT '[]'",
    }
    for column, ddl in additive_columns.items():
        if column not in existing:
            conn.execute(f'ALTER TABLE cards ADD COLUMN "{column}" {ddl}')


def get_meta(conn: sqlite3.Connection, key: str) -> "str | None":
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def set_label_color(conn: sqlite3.Connection, name: str, color_key: str) -> None:
    """Assign ``name`` (a label string) to ``color_key`` in the editable
    colour registry (F10, WF-067). Insert-or-replace: re-setting an
    already-registered label overwrites its previous key rather than
    erroring — the CLI/dashboard call site is the single writer of intent
    here, so "set again" always means "this is now the colour"."""
    conn.execute(
        "INSERT OR REPLACE INTO label_colors(name, color_key) VALUES (?, ?)",
        (name, color_key),
    )
    conn.commit()


def clear_label_color(conn: sqlite3.Connection, name: str) -> None:
    """Remove ``name``'s registry override. No-op (no error) if absent —
    matches the file's other clear/delete verbs (e.g. checklist deletes)."""
    conn.execute("DELETE FROM label_colors WHERE name = ?", (name,))
    conn.commit()


def load_label_colors(conn: sqlite3.Connection) -> dict[str, str]:
    """The full registry as a ``{label: color_key}`` map."""
    rows = conn.execute("SELECT name, color_key FROM label_colors").fetchall()
    # Index-based (not row["name"]) so this works whether the connection has
    # sqlite3.Row set as its row_factory (the normal db.connect() path) or
    # not (a bare sqlite3.connect() in a schema-only test).
    return {row[0]: row[1] for row in rows}


def connect(repo_root: Path, *, migrate: bool = True) -> sqlite3.Connection:
    return connect_at(board_db_path(repo_root), repo_root, migrate=migrate)


def connect_at(path: Path, repo_root: Path, *, migrate: bool = True) -> sqlite3.Connection:
    """Open the board file at an explicit ``path`` for ``repo_root`` — the
    same pragmas, schema, repo-identity stamp and migrations as ``connect``,
    which is this with the path resolved from the env/central layout. For the
    one caller that must NOT honour the ``OVERSEER_DB`` override: the board
    merge opens the folder ``find_boards`` resolved, by path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    from scripts.store import state_root
    state = state_root(repo_root)
    try:
        ensure_schema(conn, path=path, state=state)
    except BaseException:
        conn.close()
        raise
    if migrate:
        from scripts import migrate as _migrate
        _migrate.post_upgrade(conn, state)
        _migrate.stamp_gates_from(conn)
        _migrate.reimport_newer_files(conn, state)
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
        from scripts import migrate as _migrate
        if migrate_workflow_to_central(repo_root):
            # Legacy sprint/knowledge files just landed in central (with their
            # old mtimes): pull them into the v2 tables, never overwriting.
            _migrate.import_state(conn, state)
            _migrate.export_views(conn, state)
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
    parse. This is report-only — unlike ``store.load_live_cards``'s
    ``quarantined`` list (``list[Path]``, each entry physically moved to
    ``archive/corrupt/`` as it's found), a skipped path here stays exactly
    where it was on disk; the caller gets the reason string alongside it
    but nothing is moved.
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
        "labels": json.dumps(card.labels or []),
        "links": json.dumps(card.links or []),
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
        labels=_json_loads_column(row, "labels"),
        links=_json_loads_column(row, "links"),
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
    """Insert or update a card. ``archived`` follows status: 1 only for done
    and abandoned, so editing a finished card's fields keeps it archived while
    moving it back to a live stage revives it."""
    _upsert(conn, card, archived=1 if card.status in ("done", "abandoned") else 0)


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
    commit_unless_txn(conn)


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


def stamp_orchestrator(conn: sqlite3.Connection, card_id: str, session_id: str, now: str) -> None:
    """Record which Claude session orchestrates ``card_id`` (WF-113 §5.1). A
    side table rather than a ``cards`` column: the guard hook is its only
    reader, so the Card model, backups and dashboard stay untouched."""
    conn.execute(
        "INSERT INTO orchestrators(card_id, session_id, stamped) VALUES(?, ?, ?) "
        "ON CONFLICT(card_id) DO UPDATE SET session_id = excluded.session_id, "
        "stamped = excluded.stamped",
        (card_id, session_id, now),
    )
    conn.commit()


def clear_orchestrator(conn: sqlite3.Connection, card_id: str) -> str | None:
    """Forget ``card_id``'s orchestrator. Returns that session's id when it no
    longer orchestrates ANY card (so its guard marker can go), else None."""
    row = conn.execute(
        "SELECT session_id FROM orchestrators WHERE card_id = ?", (card_id,)
    ).fetchone()
    conn.execute("DELETE FROM orchestrators WHERE card_id = ?", (card_id,))
    conn.commit()
    if row is None:
        return None
    left = conn.execute(
        "SELECT 1 FROM orchestrators WHERE session_id = ? LIMIT 1", (row[0],)
    ).fetchone()
    return None if left else str(row[0])


def orchestrated_cards(conn: sqlite3.Connection, session_id: str) -> list[Card]:
    """Live cards this session orchestrates. Parked cards are shelved, so the
    guard lets go of them; blocked cards keep it (still the session's card)."""
    rows = conn.execute(
        "SELECT c.* FROM cards c JOIN orchestrators o ON o.card_id = c.id "
        "WHERE o.session_id = ? AND c.archived = 0 AND c.status != 'parked' "
        "ORDER BY c.id",
        (session_id,),
    ).fetchall()
    return [row_to_card(r) for r in rows]


_TXN_DEPTH: dict[int, int] = {}


@contextmanager
def txn(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One ``BEGIN IMMEDIATE`` write transaction: take the board's single
    writer lock up front, commit on success, roll back on ANY exception.
    Re-entrant -- a nested ``txn`` on the same connection joins the outer one
    (the outermost block commits). Reads made inside it see a stable board,
    which is what makes load -> change -> save safe against a second writer."""
    key = id(conn)
    depth = _TXN_DEPTH.get(key, 0)
    if depth:
        _TXN_DEPTH[key] = depth + 1
        try:
            yield conn
        finally:
            _TXN_DEPTH[key] -= 1
        return
    conn.commit()  # close any implicit transaction before taking the write lock
    conn.execute("BEGIN IMMEDIATE")
    _TXN_DEPTH[key] = 1
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        _TXN_DEPTH.pop(key, None)


def in_txn(conn: sqlite3.Connection) -> bool:
    """Is ``conn`` inside a ``txn`` block? (``conn.in_transaction`` is also true
    after any bare DML under the legacy isolation mode, so it cannot tell.)"""
    return bool(_TXN_DEPTH.get(id(conn)))


def commit_unless_txn(conn: sqlite3.Connection) -> None:
    """Commit a single-statement write made outside a ``txn``; inside one, the
    enclosing block commits."""
    if not in_txn(conn):
        conn.commit()


def put_card(conn: sqlite3.Connection, card: Card, *, archived: "int | None" = None) -> None:
    """Whole-row upsert of ``card`` -- ONLY inside an open ``txn`` whose
    transaction also loaded it (the write rule in the module docstring)."""
    if not in_txn(conn):
        raise RuntimeError("put_card outside db.txn: load and save must share one transaction")
    if archived is None:
        archived = 1 if card.status in ("done", "abandoned") else 0
    _upsert(conn, card, archived=archived, commit=False)


def mutate_card(
    conn: sqlite3.Connection,
    card_id: str,
    mutate: Callable[[Card], None],
    *,
    archive: "bool | None" = None,
) -> Card | None:
    """Load -> change -> save one card inside a single ``BEGIN IMMEDIATE``
    transaction (OL-9: every card write uses this). Parallel reviewers' report
    hooks, a checklist hook and a CLI verb finish together; a whole-row upsert
    after a separate load is last-write-wins and would drop verdicts.

    ``archive`` None keeps the row's archived flag, True/False sets it.
    ``mutate`` may raise ``EditAbort`` (or anything) to roll back untouched."""
    with txn(conn):
        row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            return None
        card = row_to_card(row)
        mutate(card)
        put_card(conn, card, archived=row["archived"] if archive is None else int(archive))
        return card


def record_evidence(
    conn: sqlite3.Connection, card_id: str, stage: str, kind: str, *,
    round_no: "int | None" = None, slot: str = "", status: str = "",
    critical: "int | None" = None, important: "int | None" = None,
    minor: "int | None" = None, detail: str = "", ts: str = "",
) -> None:
    """Append one ``stage_evidence`` row. Call it inside the same ``txn`` that
    changes the card so the two can never disagree."""
    conn.execute(
        "INSERT INTO stage_evidence(card_id, stage, kind, round, slot, status, "
        "critical, important, minor, detail, ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (card_id, stage, kind, round_no, slot, status, critical, important, minor, detail, ts),
    )


def evidence_for(conn: sqlite3.Connection, card_id: str) -> "list[Evidence]":
    """Every ``stage_evidence`` row of one card, oldest first (by id)."""
    from scripts.gates import Evidence

    rows = conn.execute(
        "SELECT id, stage, kind, round, slot, status, critical, important, minor, detail "
        "FROM stage_evidence WHERE card_id = ? ORDER BY id", (card_id,)).fetchall()
    return [Evidence(*tuple(r)) for r in rows]


def record_evidence_once(
    conn: sqlite3.Connection, card_id: str, stage: str, kind: str, *,
    round_no: "int | None" = None, slot: str = "", status: str = "",
    critical: "int | None" = None, important: "int | None" = None,
    minor: "int | None" = None, detail: str = "", ts: str = "",
) -> "int | None":
    """Idempotent ``record_evidence``: one row per (card, stage, kind, round,
    slot). The same row again is a no-op (a hook that fires twice); a changed
    row (a re-run slot, a second verifier) replaces the old one with a NEWER id,
    so "latest" and "dispatched after reported" stay ordered by id. Returns the
    new row id, or None when nothing was written."""
    same = conn.execute(
        "SELECT id, status, critical, important, minor, detail FROM stage_evidence "
        "WHERE card_id = ? AND stage = ? AND kind = ? AND round IS ? AND slot = ?",
        (card_id, stage, kind, round_no, slot)).fetchall()
    if (kind != "dispatch" and len(same) == 1
            and tuple(same[0])[1:] == (status, critical, important, minor, detail)):
        redispatched = conn.execute(
            "SELECT 1 FROM stage_evidence WHERE card_id = ? AND stage = ? AND kind = 'dispatch' "
            "AND slot = ? AND id > ? LIMIT 1", (card_id, stage, slot, same[0][0])).fetchone()
        if redispatched is None:
            return None  # a hook that fired twice: nothing to add
    for row in same:
        conn.execute("DELETE FROM stage_evidence WHERE id = ?", (row[0],))
    cur = conn.execute(
        "INSERT INTO stage_evidence(card_id, stage, kind, round, slot, status, "
        "critical, important, minor, detail, ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (card_id, stage, kind, round_no, slot, status, critical, important, minor, detail, ts))
    return cur.lastrowid


def delete_evidence(conn: sqlite3.Connection, row_id: int) -> None:
    conn.execute("DELETE FROM stage_evidence WHERE id = ?", (row_id,))


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
