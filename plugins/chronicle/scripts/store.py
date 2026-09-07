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
- ``file_edits`` one row per file change, with the added/removed line counts
                 taken from the diff the transcript carries (counts only —
                 never the diff content).
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
    lines_added           INTEGER NOT NULL DEFAULT 0,
    lines_removed         INTEGER NOT NULL DEFAULT 0,
    files_touched         INTEGER NOT NULL DEFAULT 0,
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
    skill                 TEXT,
    plugin                TEXT,
    agent_type            TEXT,
    mcp_server            TEXT,
    mcp_tool              TEXT,
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
    qualifier    TEXT,
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

-- One row per file change, from the unified diff Claude Code writes with
-- every Edit/Write result. Counts only: the diff CONTENT is deliberately not
-- kept, so the store stays a facts table rather than a second copy of the
-- source. Note this measures editing DONE, not lines surviving in the repo —
-- ten edits to one line are ten rows, and a later revert still counts. For
-- "what shipped", git is the truthful source.
CREATE TABLE IF NOT EXISTS file_edits (
    session_id    TEXT NOT NULL,
    tool_use_id   TEXT NOT NULL,
    agent_id      TEXT NOT NULL DEFAULT '',
    ts            REAL,
    file_path     TEXT NOT NULL,
    operation     TEXT NOT NULL DEFAULT 'edit',
    lines_added   INTEGER NOT NULL DEFAULT 0,
    lines_removed INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, tool_use_id)
);
CREATE INDEX IF NOT EXISTS file_edits_session ON file_edits(session_id);
CREATE INDEX IF NOT EXISTS file_edits_path ON file_edits(file_path);

-- One row per SUBAGENT, holding the only human-legible name it has: the task
-- its own transcript opens with. Nothing derived lives here — an agent's
-- turns, tokens, tools and churn are already keyed by `agent_id` on the fact
-- tables and stay computed from them. A row with a NULL task is still a row:
-- an agent whose opening prompt was pruned must remain listable.
CREATE TABLE IF NOT EXISTS agents (
    session_id TEXT NOT NULL,
    agent_id   TEXT NOT NULL,
    task       TEXT,
    PRIMARY KEY (session_id, agent_id)
);

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

CREATE TABLE IF NOT EXISTS accounts (
    -- Identity only, and deliberately only the parts that do not change and
    -- do not identify a person. The mutable half of an account — which plan
    -- it is on — is NOT here: a plan changes, and a row here would silently
    -- rewrite history for every session already recorded against it. That
    -- lives on `sessions` as a snapshot of what was true when it ran.
    --
    -- NOTHING personal is ever written: `.claude.json` also holds
    -- emailAddress, fullName, displayName and organizationName, and this
    -- store is read by the dashboard. The reader whitelists fields by name.
    account_uuid      TEXT PRIMARY KEY,
    organization_uuid TEXT,
    first_seen        REAL,
    last_seen         REAL
);

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
    # Identity for tools whose name alone does not say what ran: a Skill's
    # plugin-qualified name, an Agent's subagent type. Backfilled by
    # `chronicle sync --full`, which re-reads every transcript from byte 0.
    ("tool_calls", "qualifier", "TEXT"),
    # The account that owns this session's bridge, from its `bridge-session`
    # record. Sparse: only sessions bridged from claude.ai carry one, so NULL
    # is the common case and means "not stated", never "no account".
    ("sessions", "owner_account_uuid", "TEXT"),
    # The plan AS IT WAS when this session was ingested, read from the config
    # dir the transcript came from. Pinned per session rather than per account
    # on purpose: an account moves between plans, and attributing today's plan
    # to a session that ran under a previous one would be a confident lie.
    # `plan_observed_at` is what makes the snapshot legible as a snapshot.
    ("sessions", "plan_organization_type", "TEXT"),
    ("sessions", "plan_seat_tier", "TEXT"),
    ("sessions", "plan_billing_type", "TEXT"),
    ("sessions", "plan_rate_limit_tier", "TEXT"),
    ("sessions", "plan_observed_at", "REAL"),
    # The agent's own short label, from `agent-<id>.meta.json` beside its
    # transcript. Claude Code writes a purpose-built 3-5 word `description`
    # there; the `task` column holds its opening PROMPT, which runs to
    # thousands of characters and makes a poor name. Backfilled by
    # `chronicle sync --full`.
    ("agents", "description", "TEXT"),
    # Churn rollup, recomputed from `file_edits` by ingest.rollup.
    ("sessions", "lines_added", "INTEGER NOT NULL DEFAULT 0"),
    ("sessions", "lines_removed", "INTEGER NOT NULL DEFAULT 0"),
    ("sessions", "files_touched", "INTEGER NOT NULL DEFAULT 0"),
    # What was in scope for a call, as the transcript stamps it. On the TURN,
    # so these account for tokens rather than counting invocations.
    ("turns", "skill", "TEXT"),
    ("turns", "plugin", "TEXT"),
    ("turns", "agent_type", "TEXT"),
    ("turns", "mcp_server", "TEXT"),
    ("turns", "mcp_tool", "TEXT"),
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


# The ONLY fields ever read out of `.claude.json`. A whitelist, not a
# blacklist: that file also holds emailAddress, fullName, displayName,
# organizationName and more, and this store is read by the dashboard and can
# be copied around. Anything not named here never enters the database, so a
# new personal field appearing upstream cannot leak by default.
ACCOUNT_IDENTITY_FIELDS = ("accountUuid", "organizationUuid")
ACCOUNT_PLAN_FIELDS = {
    "organizationType": "plan_organization_type",
    "seatTier": "plan_seat_tier",
    "billingType": "plan_billing_type",
    "organizationRateLimitTier": "plan_rate_limit_tier",
}


def account_profile(config_dir: Path) -> dict[str, str] | None:
    """The non-personal account facts a config dir currently holds, or None.

    Source is `<config_dir>/.claude.json`'s `oauthAccount`, which describes the
    account LOGGED IN THERE NOW — it carries no history, so what it says is
    only ever true of the present. Callers stamp it onto sessions as they are
    ingested, with the time of observation, rather than treating it as a
    property of the account for all time.

    An API-key session has no `oauthAccount` at all, which is the one positive
    signal that distinguishes key auth from a subscription; that case returns
    an empty dict, distinct from None (no file / unreadable / malformed).
    """
    path = config_dir / ".claude.json"
    try:
        data = json.loads(path.read_text() or "{}")
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    oauth = data.get("oauthAccount")
    if not isinstance(oauth, dict):
        return {}
    out: dict[str, str] = {}
    for key in (*ACCOUNT_IDENTITY_FIELDS, *ACCOUNT_PLAN_FIELDS):
        value = oauth.get(key)
        if isinstance(value, str) and value:
            out[key] = value
    return out


def path_map() -> list[tuple[str, str]]:
    """Prefix rewrites from a recorded ``cwd`` to a path on THIS filesystem,
    longest prefix first.

    A session run inside a container records the cwd it saw — ``/workspaces/foo``
    — which does not exist on the host reading its transcript. Without a rewrite
    every such session resolves to no repo at all and becomes invisible to any
    repo-scoped view. Configured beside ``claude_dirs`` in the same machine
    config::

        {"path_map": {"/workspaces/foo": "/Users/me/repos/foo"}}

    Sorted longest-source-first so a more specific mapping wins over a more
    general one that shares its prefix. Malformed config yields no mappings
    rather than raising: a bad rewrite must degrade attribution, never stop
    the ingest.
    """
    machine = config_dir().joinpath(*MACHINE_CONFIG_RELPATH)
    if not machine.exists():
        return []
    try:
        data = json.loads(machine.read_text() or "{}")
    except json.JSONDecodeError:
        return []
    raw = data.get("path_map") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return []
    pairs = [
        (str(src), str(dst))
        for src, dst in raw.items()
        if isinstance(src, str) and isinstance(dst, str) and src and dst
    ]
    return sorted(pairs, key=lambda kv: len(kv[0]), reverse=True)


def projects_dir() -> Path:
    """Where the PRIMARY account's Claude Code writes session transcripts
    (``<slug>/<session>.jsonl``). ``projects_dirs`` is the full set."""
    return config_dir() / "projects"


def projects_dirs() -> list[Path]:
    """One ``projects/`` per watched config dir, primary first."""
    return [d / "projects" for d in claude_dirs()]


def db_path() -> Path:
    """The one store this machine should be writing to.

    NOT simply `<primary>/chronicle/sessions.db`. That resolves per account, so
    a second account running `sync` quietly raised a RIVAL store: this machine
    had 342 sessions in one and a stale 238-session subset in another, and
    which you saw depended on who launched the dashboard. Reading was always
    multi-account (`claude_dirs`); only writing was not, and that asymmetry is
    what split the history.

    So: among the stores that already exist across the watched dirs, take the
    FULLEST — the one with the most sessions. Every account computes the same
    answer from the same files, so they converge on one store instead of each
    preferring its own; and a second account joins the existing history rather
    than starting a rival to it. Ties go to the primary. When none exists yet,
    the primary is where a new one is created.

    `CHRONICLE_DB` still overrides everything — tests pin it, and a caller who
    means a specific file is not to be second-guessed.
    """
    override = os.environ.get(DB_ENV)
    if override:
        return Path(override)
    found = [(_session_count(d.joinpath(*DB_RELPATH)), -index, d.joinpath(*DB_RELPATH))
             for index, d in enumerate(claude_dirs())]
    # Negative index as the tiebreak, so an equal count prefers the earlier
    # dir — the primary, which `claude_dirs` lists first.
    usable = [entry for entry in found if entry[0] is not None]
    if usable:
        return max(usable)[2]
    return config_dir().joinpath(*DB_RELPATH)


def _session_count(path: Path) -> int | None:
    """Sessions in a chronicle store, or None if it is not one we can read —
    absent, locked, corrupt, or some other file entirely. None never wins the
    comparison in `db_path` and never raises out of it."""
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    except (sqlite3.Error, ValueError, OSError):
        return None
    try:
        return int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
    except sqlite3.Error:
        return None
    finally:
        conn.close()


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
