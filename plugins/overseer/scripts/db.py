"""SQLite persistence for overseer cards. One board.db per repo, shared by all
its worktrees. Owns schema, card CRUD, atomic claiming, and the one-time
.workflow/ import. Sprints/usage/knowledge remain file-based this phase."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from scripts.models import Card, format_tokens, parse_tokens
from scripts.store import derive_repo_label, slugify

SCHEMA_VERSION = 1
DB_ENV = "OVERSEER_DB"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"

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


def _config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    return Path(override) if override else Path.home() / ".claude"


def board_db_path(repo_root: Path) -> Path:
    override = os.environ.get(DB_ENV)
    if override:
        return Path(override)
    label = derive_repo_label(repo_root) or slugify(repo_root.resolve().name) or "repo"
    return _config_dir() / "overseer" / label / "board.db"


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
    if migrate:
        _maybe_import(conn, repo_root)  # defined in Task 6; no-op stub until then
    return conn


def _maybe_import(conn: sqlite3.Connection, repo_root: Path) -> None:
    """Filled in by Task 6. Stub keeps connect() working until then."""
    return None
