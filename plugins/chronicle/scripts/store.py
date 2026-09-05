"""Chronicle store: one account-scoped SQLite file of session telemetry.

Layout of ``$CLAUDE_CONFIG_DIR/chronicle/sessions.db`` (override the file with
``CHRONICLE_DB``). Rooted under the Claude config dir for the same reason census
is: ``CLAUDE_CONFIG_DIR`` is the account isolation boundary, so two accounts on
one machine never commingle their session history.

Tables (see ``_SCHEMA``):

- ``sessions``   one row per Claude Code session, with a denormalised rollup
                 (token totals, turn/prompt/tool counts, peak context, ...)
                 recomputed from the fact tables after every ingest.
- ``turns``      one row per assistant API call (deduped by ``message_id`` —
                 the transcript writes one JSONL line per content block, all
                 sharing the same message id and usage). Cache columns: a
                 turn's prompt is served as ``input`` (uncached), ``cache_read``
                 (warm hit) or ``cache_creation`` (cold — the prefix was
                 written), the last split by TTL into ``cache_5m``/``cache_1h``.
- ``tool_calls`` one row per ``tool_use`` block, with the size and time of its
                 ``tool_result`` once that lands (the result is what grows the
                 next turn's context — see ``report.biggest_turns``).
- ``artifacts``  one row per Artifact publish (title, description, favicon,
                 published URL parsed from the tool result).
- ``events``     prompts, compactions and turn durations, keyed by record uuid
                 (scoped by session: ids are globally unique in practice, but
                 nothing here depends on it).
- ``cursors``    per-transcript-file byte offset + the file's mtime/size as
                 last seen, so ``sync`` can skip files that have not moved.
- ``meta``       schema version, last sync time.

Why SQLite: the writers are many short-lived hook processes (one per session,
per Stop), the readers are the CLI and the dashboard, and the data is tabular
and time-series shaped. WAL mode + a busy timeout handles the concurrent
writers; it is stdlib-only (no install step for a hook), and the overseer
dashboard already speaks SQLite. The volume (thousands of turns per account)
is far below anything that would justify a columnar or graph engine.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

DB_ENV = "CHRONICLE_DB"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
CLAUDE_DIRS_ENV = "CLAUDE_CONFIG_DIRS"
# The machine-level config shared with the overseer plugin (see claude_dirs).
MACHINE_CONFIG_RELPATH = ("overseer", "config.json")
DB_RELPATH = ("chronicle", "sessions.db")
SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id            TEXT PRIMARY KEY,
    project_slug          TEXT,
    cwd                   TEXT,
    repo_root             TEXT,
    git_branch            TEXT,
    entrypoint            TEXT,
    version               TEXT,
    title                 TEXT,
    transcript_path       TEXT,
    transcript_bytes      INTEGER NOT NULL DEFAULT 0,
    transcript_mtime      REAL,
    started_at            REAL,
    ended_at              REAL,
    end_reason            TEXT,
    last_activity_at      REAL,
    updated_at            REAL NOT NULL DEFAULT 0,
    -- rollup (recomputed from the fact tables by ingest.rollup)
    turns                 INTEGER NOT NULL DEFAULT 0,
    prompts               INTEGER NOT NULL DEFAULT 0,
    tool_calls            INTEGER NOT NULL DEFAULT 0,
    input_tokens          INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens     INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens         INTEGER NOT NULL DEFAULT 0,
    thinking_tokens       INTEGER NOT NULL DEFAULT 0,
    peak_context_tokens   INTEGER NOT NULL DEFAULT 0,
    compactions           INTEGER NOT NULL DEFAULT 0,
    cold_turns            INTEGER NOT NULL DEFAULT 0,
    artifacts             INTEGER NOT NULL DEFAULT 0,
    subagents             INTEGER NOT NULL DEFAULT 0,
    active_ms             INTEGER NOT NULL DEFAULT 0,
    models                TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS sessions_repo_root ON sessions(repo_root);
CREATE INDEX IF NOT EXISTS sessions_started_at ON sessions(started_at);

CREATE TABLE IF NOT EXISTS turns (
    session_id            TEXT NOT NULL,
    agent_id              TEXT NOT NULL DEFAULT '',
    message_id            TEXT NOT NULL,
    request_id            TEXT,
    ts                    REAL,
    model                 TEXT,
    input_tokens          INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens     INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens         INTEGER NOT NULL DEFAULT 0,
    thinking_tokens       INTEGER NOT NULL DEFAULT 0,
    cache_5m_tokens       INTEGER NOT NULL DEFAULT 0,
    cache_1h_tokens       INTEGER NOT NULL DEFAULT 0,
    tool_calls            INTEGER NOT NULL DEFAULT 0,
    stop_reason           TEXT,
    effort                TEXT,
    PRIMARY KEY (session_id, agent_id, message_id)
);
CREATE INDEX IF NOT EXISTS turns_session_ts ON turns(session_id, ts);
CREATE INDEX IF NOT EXISTS turns_ts ON turns(ts);

CREATE TABLE IF NOT EXISTS tool_calls (
    session_id   TEXT NOT NULL,
    tool_use_id  TEXT NOT NULL,
    agent_id     TEXT NOT NULL DEFAULT '',
    message_id   TEXT NOT NULL,
    tool_name    TEXT NOT NULL,
    ts           REAL,
    result_chars INTEGER,
    result_ts    REAL,
    PRIMARY KEY (session_id, tool_use_id)
);

CREATE TABLE IF NOT EXISTS artifacts (
    session_id  TEXT NOT NULL,
    tool_use_id TEXT NOT NULL,
    agent_id    TEXT NOT NULL DEFAULT '',
    ts          REAL,
    url         TEXT,
    title       TEXT,
    description TEXT,
    favicon     TEXT,
    redeploy    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, tool_use_id)
);
CREATE INDEX IF NOT EXISTS artifacts_session ON artifacts(session_id);
CREATE INDEX IF NOT EXISTS tool_calls_session ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS tool_calls_name ON tool_calls(tool_name);

CREATE TABLE IF NOT EXISTS events (
    session_id TEXT NOT NULL,
    uuid       TEXT NOT NULL,
    agent_id   TEXT NOT NULL DEFAULT '',
    kind       TEXT NOT NULL,
    ts         REAL,
    value      INTEGER,
    PRIMARY KEY (session_id, uuid)
);
CREATE INDEX IF NOT EXISTS events_session_kind ON events(session_id, kind);

CREATE TABLE IF NOT EXISTS cursors (
    path        TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    agent_id    TEXT NOT NULL DEFAULT '',
    byte_offset INTEGER NOT NULL DEFAULT 0,
    mtime       REAL NOT NULL DEFAULT 0,
    size        INTEGER NOT NULL DEFAULT 0,
    updated_at  REAL NOT NULL DEFAULT 0
);
"""

# Columns added after a table first shipped: (table, column, DDL type+default).
# ``CREATE TABLE IF NOT EXISTS`` never alters an existing table, so each is
# added here when missing — cheap, idempotent, and keeps an older store usable.
_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    ("cursors", "mtime", "REAL NOT NULL DEFAULT 0"),
    ("cursors", "size", "INTEGER NOT NULL DEFAULT 0"),
    ("sessions", "transcript_mtime", "REAL"),
    ("turns", "cache_5m_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("turns", "cache_1h_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("sessions", "cold_turns", "INTEGER NOT NULL DEFAULT 0"),
    ("tool_calls", "result_chars", "INTEGER"),
    ("tool_calls", "result_ts", "REAL"),
    ("sessions", "artifacts", "INTEGER NOT NULL DEFAULT 0"),
    # Which Claude config dir the transcript was read from (multi-account).
    ("sessions", "config_dir", "TEXT"),
)


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, ddl in _MIGRATIONS:
        present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in present:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def config_dir() -> Path:
    """The active Claude config dir — the account isolation boundary. The
    store lives here; ``claude_dirs`` is where transcripts are read from."""
    override = os.environ.get(CONFIG_DIR_ENV)
    return Path(override) if override else Path.home() / ".claude"


def claude_dirs() -> list[Path]:
    """Every Claude config dir whose transcripts this chronicle records: the
    primary first, then ``CLAUDE_CONFIG_DIRS`` (os.pathsep list), then the
    ``claude_dirs`` list in the machine config the overseer plugin also
    reads (``<primary>/overseer/config.json``) — deduplicated, order kept,
    missing dirs dropped. A second account (``~/.claude-personal``) keeps
    its own ``projects/``; listing it here folds its sessions into the one
    store, each row remembering which dir it came from (``config_dir``).

    Deliberately a small copy of overseer's loader rather than an import:
    chronicle stands alone."""
    primary = config_dir()
    candidates: list[Path] = [primary]
    env = os.environ.get(CLAUDE_DIRS_ENV, "")
    candidates.extend(Path(p).expanduser() for p in env.split(os.pathsep) if p.strip())
    machine = primary.joinpath(*MACHINE_CONFIG_RELPATH)
    if machine.exists():
        try:
            data = json.loads(machine.read_text() or "{}")
        except json.JSONDecodeError:
            data = {}
        listed = data.get("claude_dirs") if isinstance(data, dict) else None
        if isinstance(listed, list):
            candidates.extend(Path(str(p)).expanduser() for p in listed if p)
    out: list[Path] = []
    seen: set[Path] = set()
    for c in candidates:
        try:
            key = c.resolve()
        except OSError:
            continue
        if key in seen or not key.is_dir():
            continue
        seen.add(key)
        out.append(c)
    return out


def projects_dir() -> Path:
    """Where the PRIMARY account's Claude Code writes session transcripts
    (``<slug>/<session>.jsonl``). ``projects_dirs`` is the full set."""
    return config_dir() / "projects"


def projects_dirs() -> list[Path]:
    """One ``projects/`` per watched config dir, primary first."""
    return [d / "projects" for d in claude_dirs()]


def db_path() -> Path:
    override = os.environ.get(DB_ENV)
    if override:
        return Path(override)
    return config_dir().joinpath(*DB_RELPATH)


def connect(path: Path | None = None, *, readonly: bool = False) -> sqlite3.Connection:
    """Open (and, unless readonly, create/migrate) the chronicle database.

    WAL journal + busy timeout: hooks from every live session write here
    concurrently; WAL lets readers (the dashboard) proceed during a write and
    the timeout turns a brief lock into a short wait rather than an error.
    """
    target = path if path is not None else db_path()
    if readonly:
        if not target.exists():
            raise FileNotFoundError(str(target))
        uri = f"{target.resolve().as_uri()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        return conn
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.executescript(_SCHEMA)
    _migrate(conn)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn
