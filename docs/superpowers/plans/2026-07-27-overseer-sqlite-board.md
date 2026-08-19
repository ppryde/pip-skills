# Overseer SQLite Board — Core Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move overseer's *card* store from per-worktree `.workflow/cards/` files to a single per-repo SQLite `board.db` in the config dir, so every worktree of a repo shares one board and card-claiming is atomic across worktrees.

**Architecture:** A new `scripts/db.py` owns the SQLite connection (WAL, `busy_timeout`), the schema, per-repo rooting (`$CLAUDE_CONFIG_DIR/overseer/<repo-label>/board.db` via existing `derive_repo_label`), card CRUD, atomic claim, stale-claim reclaim, and a one-time `.workflow/` → DB importer. The `Card` dataclass and all derived-view logic (`relations`, `index`, `board`, `resume`) are unchanged; only the *card* read/write seam moves from files to `db.py`. Sprints, usage, and knowledge stay as files this phase (non-regressing) and move in follow-on plans.

**Tech Stack:** Python 3.9+ stdlib `sqlite3`, `json` for list/dict columns, existing `pyyaml` (card text round-trip only where migrating). No new dependencies.

## Global Constraints

- **No new runtime dependencies.** Stdlib `sqlite3` only.
- **Python 3.9 floor** — no `match`, no `X | Y` runtime unions in isinstance, `from __future__ import annotations` at top of every module (matches existing files).
- **The `Card` dataclass in `models.py` is the canonical in-memory shape and does not change.** `db.py` serialises to/from it losslessly.
- **CLI verb contracts are frozen** — every verb in the inventory keeps its name, flags, JSON output shape, and exit codes (0 ok, 1 parse/not-found, 2 tripwire). The dashboard shells these; breaking them breaks the dashboard.
- **DB location override for tests:** `board_db_path` honours env `OVERSEER_DB` (explicit file path) before `CLAUDE_CONFIG_DIR`. Tests set `OVERSEER_DB` to a `tmp_path` file. (`conftest.py` already strips `CLAUDE_CONFIG_DIR`.)
- **Timestamps** are ISO minute strings `YYYY-MM-DDTHH:MM` as produced by cli's existing `_now()`. `db.py` must not invent its own format; callers pass `now: str`.
- **Card ids** are `WF-NNN` (zero-padded to 3), minted as `max(existing)+1` across live **and** archived cards.
- Run tests with the worktree venv per project convention: `/Users/philip.pryde/repos/pip-skills/.claude/worktrees/overseer-orchestration/.venv/bin/python -m pytest` (fallback: `python -m pytest`). Commands below say `pytest` for brevity — use the venv python.

---

## File Structure

- **Create `plugins/overseer/scripts/db.py`** — the entire SQLite persistence layer for cards: path resolution, connection/pragmas, schema + versioning, card row↔dataclass serialisation, card CRUD, atomic claim, stale reclaim, and the `.workflow/` importer. One responsibility: *card persistence in SQLite*.
- **Create `plugins/overseer/scripts/liveness.py`** — a thin, optional adapter that reads the census store for the set of live session ids (soft dependency, data-contract only, quarantine-safe, returns `None` on any failure). Mirrors `plugins/vigil/scripts/census.py`. One responsibility: *answer "which sessions are live?" or None*.
- **Modify `plugins/overseer/scripts/store.py`** — keep all file functions (still used by sprints/knowledge and `init_workflow`). The card functions (`mint_id`, `save_card`, `load_card`, `find_card_path`, `load_live_cards`, `archive_card`, `load_archived_cards`, `quarantine`) become *thin shims that delegate to `db.py`* OR are removed and callers import `db` directly (this plan removes them and repoints callers — see Task 7). `state_root`, `init_workflow`, `derive_repo_label`, `slugify`, `_uniquify` stay.
- **Modify `plugins/overseer/scripts/cli.py`** — repoint every card read/write call site from `store.*(state_root(...))` to `db.*(conn)`; add reclaim-on-claim; keep sprint/usage/knowledge/index call sites unchanged.
- **Modify `plugins/overseer/scripts/board.py`, `index.py`, `resume.py`** — their card reads (`load_live_cards`/`load_archived_cards`) switch from a file `state_root` to a `db.connect(repo_root)` connection. Derived logic untouched.
- **Modify tests** — `tests/test_db.py` (new), and card-assertion updates in `tests/test_store.py`, `tests/test_cli.py`, `tests/test_board.py`, `tests/test_resume.py`, `tests/test_composition.py`. Sprint/usage/knowledge tests untouched.
- **Add `tests/factories.py` helper** — `db_repo(tmp_path)` that git-inits, sets `OVERSEER_DB`, and returns `(repo_root, conn)`.

### `db.py` public interface (the contract every later task depends on)

```python
# scripts/db.py
SCHEMA_VERSION = 1
DB_ENV = "OVERSEER_DB"
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"

def board_db_path(repo_root: Path) -> Path
def connect(repo_root: Path, *, migrate: bool = True) -> sqlite3.Connection   # WAL, busy_timeout, schema ensured, one-time import if applicable
def ensure_schema(conn: sqlite3.Connection) -> None
def get_meta(conn, key: str) -> str | None
def set_meta(conn, key: str, value: str) -> None

def row_to_card(row: sqlite3.Row) -> Card
def card_to_params(card: Card) -> dict          # column-name -> value, for upsert

def mint_id(conn) -> str                         # 'WF-NNN'
def save_card(conn, card: Card) -> None          # upsert by id (archived=0)
def load_card(conn, card_id: str) -> Card | None # live OR archived
def load_live_cards(conn) -> tuple[list[Card], list[Path]]   # ([], []) shape preserved; quarantined always []
def load_archived_cards(conn) -> list[Card]
def archive_card(conn, card: Card) -> None       # upsert with archived=1

def claim_card(conn, card_id: str, session_id: str, now: str, *, force: bool = False) -> bool   # True iff this call won the claim
def reclaim_stale(conn, live_session_ids: "set[str] | None", ttl_minutes: int, now: str) -> list[str]  # returns reclaimed ids
```

`liveness.py` interface:

```python
# scripts/liveness.py
def live_session_ids() -> "set[str] | None"   # None if census absent/unreadable; never raises
```

---

## Task 1: `db.py` foundation — path, connect, schema, meta

**Files:**
- Create: `plugins/overseer/scripts/db.py`
- Test: `plugins/overseer/tests/test_db.py`

**Interfaces:**
- Consumes: `store.derive_repo_label`, `store.slugify`.
- Produces: `board_db_path`, `connect`, `ensure_schema`, `get_meta`, `set_meta`, `SCHEMA_VERSION`, `DB_ENV`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_db.py
from __future__ import annotations
import sqlite3
from pathlib import Path
import pytest
from scripts import db
from tests.factories import git_init

@pytest.fixture
def repo(tmp_path, monkeypatch):
    git_init(tmp_path)
    monkeypatch.setenv(db.DB_ENV, str(tmp_path / "board.db"))
    return tmp_path

def test_board_db_path_honours_env(repo, monkeypatch):
    assert db.board_db_path(repo) == repo / "board.db"

def test_board_db_path_falls_back_to_config_dir(tmp_path, monkeypatch):
    git_init(tmp_path)
    monkeypatch.delenv(db.DB_ENV, raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    p = db.board_db_path(tmp_path)
    # rooted under <config>/overseer/<repo-label>/board.db
    assert p.parent.parent == tmp_path / "cfg" / "overseer"
    assert p.name == "board.db"

def test_connect_sets_wal_and_schema(repo):
    conn = db.connect(repo, migrate=False)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"cards", "meta"} <= tables
    assert db.get_meta(conn, "schema_version") == str(db.SCHEMA_VERSION)

def test_connect_is_idempotent(repo):
    db.connect(repo, migrate=False).close()
    conn = db.connect(repo, migrate=False)  # must not raise on existing schema
    assert db.get_meta(conn, "schema_version") == str(db.SCHEMA_VERSION)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest plugins/overseer/tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: scripts.db` / attributes missing.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/db.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest plugins/overseer/tests/test_db.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/db.py plugins/overseer/tests/test_db.py
git commit -m "feat(overseer): db.py foundation — sqlite board path, connect, schema, meta"
```

---

## Task 2: Card row ↔ dataclass serialisation

**Files:**
- Modify: `plugins/overseer/scripts/db.py`
- Test: `plugins/overseer/tests/test_db.py`

**Interfaces:**
- Consumes: `Card` (models.py), `SCHEMA_VERSION`.
- Produces: `row_to_card(row) -> Card`, `card_to_params(card) -> dict`. `card_to_params` returns a dict keyed by exact column names (list/dict fields JSON-encoded, bools as 0/1, `archived` NOT included — callers set it).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_db.py
from scripts.models import Card

def _sample_card():
    return Card(
        id="WF-007", title="thing", status="in-flight", stage="implementation",
        order=3, priority="P1", sprint="2026-07-S3", parent="WF-001",
        touches=["a.py", "b.py"], depends_on=["WF-002"],
        budget_estimate=400_000, budget_actual=120_000,
        created="2026-07-01T09:00", updated="2026-07-02T10:00",
        checklist=[{"task": "t1", "subject": "s", "status": "done"}],
        repo="pip-skills", claimed_by="sess-1", claimed_at="2026-07-02T10:00",
        claim_acked=True, claim_nudged=False, body="## Progress log\n\n- did x",
    )

def test_card_roundtrips_through_row(repo):
    conn = db.connect(repo, migrate=False)
    card = _sample_card()
    params = db.card_to_params(card)
    cols = ", ".join(f'"{k}"' for k in params)
    ph = ", ".join(f":{k}" for k in params)
    conn.execute(f"INSERT INTO cards ({cols}) VALUES ({ph})", params)
    row = conn.execute("SELECT * FROM cards WHERE id='WF-007'").fetchone()
    restored = db.row_to_card(row)
    assert restored == card
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest plugins/overseer/tests/test_db.py::test_card_roundtrips_through_row -v`
Expected: FAIL — `card_to_params` missing.

- [ ] **Step 3: Write minimal implementation**

```python
# add to scripts/db.py
_CARD_COLUMNS = (
    "id", "title", "status", "stage", "order", "complexity", "priority",
    "jira", "linear", "sprint", "parent", "branch", "worktree", "pr",
    "touches", "depends_on", "budget_estimate", "budget_actual",
    "created", "updated", "blocked_on", "checklist", "repo",
    "claimed_by", "claimed_at", "claim_acked", "claim_nudged", "body",
)


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
        touches=json.loads(row["touches"] or "[]"),
        depends_on=json.loads(row["depends_on"] or "[]"),
        budget_estimate=row["budget_estimate"],
        budget_actual=row["budget_actual"] or 0,
        created=row["created"] or "",
        updated=row["updated"] or "",
        blocked_on=row["blocked_on"],
        checklist=json.loads(row["checklist"] or "[]"),
        repo=row["repo"],
        claimed_by=row["claimed_by"],
        claimed_at=row["claimed_at"],
        claim_acked=bool(row["claim_acked"]),
        claim_nudged=bool(row["claim_nudged"]),
        body=row["body"] or "",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest plugins/overseer/tests/test_db.py::test_card_roundtrips_through_row -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/db.py plugins/overseer/tests/test_db.py
git commit -m "feat(overseer): lossless card row<->dataclass serialisation"
```

---

## Task 3: Card CRUD on SQLite

**Files:**
- Modify: `plugins/overseer/scripts/db.py`
- Modify: `plugins/overseer/tests/factories.py` (add `db_repo`)
- Test: `plugins/overseer/tests/test_db.py`

**Interfaces:**
- Consumes: `card_to_params`, `row_to_card`, `_CARD_COLUMNS`.
- Produces: `mint_id(conn)`, `save_card(conn, card)`, `load_card(conn, id)`, `load_live_cards(conn)`, `archive_card(conn, card)`, `load_archived_cards(conn)`. `save_card` upserts with `archived=0`; `archive_card` upserts with `archived=1`; `load_live_cards` returns `(cards_sorted_by_id, [])`; `load_archived_cards` sorts by `updated` desc.

- [ ] **Step 1: Write the failing test** (and factory helper)

```python
# add to tests/factories.py
import sqlite3
from scripts import db

def db_repo(tmp_path, monkeypatch):
    git_init(tmp_path)
    monkeypatch.setenv(db.DB_ENV, str(tmp_path / "board.db"))
    return tmp_path, db.connect(tmp_path, migrate=False)
```

```python
# add to tests/test_db.py
def test_save_and_load_card(repo):
    conn = db.connect(repo, migrate=False)
    card = _sample_card()
    db.save_card(conn, card)
    assert db.load_card(conn, "WF-007") == card

def test_save_card_upserts(repo):
    conn = db.connect(repo, migrate=False)
    card = _sample_card()
    db.save_card(conn, card)
    card.status = "blocked"
    db.save_card(conn, card)
    assert db.load_card(conn, "WF-007").status == "blocked"
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 1

def test_load_live_excludes_archived(repo):
    conn = db.connect(repo, migrate=False)
    live = Card(id="WF-001", title="live", status="in-flight")
    done = Card(id="WF-002", title="done", status="done")
    db.save_card(conn, live)
    db.archive_card(conn, done)
    cards, quarantined = db.load_live_cards(conn)
    assert [c.id for c in cards] == ["WF-001"]
    assert quarantined == []
    assert [c.id for c in db.load_archived_cards(conn)] == ["WF-002"]

def test_mint_id_spans_live_and_archived(repo):
    conn = db.connect(repo, migrate=False)
    db.save_card(conn, Card(id="WF-003", title="a", status="planned"))
    db.archive_card(conn, Card(id="WF-009", title="b", status="done"))
    assert db.mint_id(conn) == "WF-010"

def test_load_card_finds_archived(repo):
    conn = db.connect(repo, migrate=False)
    db.archive_card(conn, Card(id="WF-005", title="gone", status="done"))
    assert db.load_card(conn, "WF-005").status == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest plugins/overseer/tests/test_db.py -v -k "save or load or mint"`
Expected: FAIL — CRUD functions missing.

- [ ] **Step 3: Write minimal implementation**

```python
# add to scripts/db.py
import re as _re
_ID_RE = _re.compile(r"\AWF-(\d+)\Z")


def _upsert(conn: sqlite3.Connection, card: Card, archived: int) -> None:
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
    conn.commit()


def save_card(conn: sqlite3.Connection, card: Card) -> None:
    _upsert(conn, card, archived=0)


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
```

*Note:* existing card ids in the repo use the `WF-NNN-slug` filename but the frontmatter `id` is `WF-NNN` (see `models.py` — `id` is stored bare). `_ID_RE` matches the bare id. Confirm against a migrated card in Task 6.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest plugins/overseer/tests/test_db.py -v`
Expected: PASS (all db tests so far).

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/db.py plugins/overseer/tests/test_db.py plugins/overseer/tests/factories.py
git commit -m "feat(overseer): card CRUD on sqlite (save/load/archive/mint)"
```

---

## Task 4: Atomic claim

**Files:**
- Modify: `plugins/overseer/scripts/db.py`
- Test: `plugins/overseer/tests/test_db.py`

**Interfaces:**
- Consumes: card table.
- Produces: `claim_card(conn, card_id, session_id, now, *, force=False) -> bool`. Returns `True` iff this call transitioned the claim. Unforced: only claims when `claimed_by IS NULL`. Forced: always claims (displacement). On a win, resets `claim_acked`/`claim_nudged` to 0 and stamps `updated=now` (mirrors `Card.claim`).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_db.py
def test_claim_unclaimed_wins(repo):
    conn = db.connect(repo, migrate=False)
    db.save_card(conn, Card(id="WF-001", title="t", status="planned"))
    assert db.claim_card(conn, "WF-001", "sess-A", "2026-07-02T10:00") is True
    got = db.load_card(conn, "WF-001")
    assert got.claimed_by == "sess-A" and got.claimed_at == "2026-07-02T10:00"
    assert got.claim_acked is False and got.claim_nudged is False

def test_second_claimer_loses(repo):
    conn = db.connect(repo, migrate=False)
    db.save_card(conn, Card(id="WF-001", title="t", status="planned"))
    assert db.claim_card(conn, "WF-001", "sess-A", "2026-07-02T10:00") is True
    assert db.claim_card(conn, "WF-001", "sess-B", "2026-07-02T10:01") is False
    assert db.load_card(conn, "WF-001").claimed_by == "sess-A"

def test_force_displaces(repo):
    conn = db.connect(repo, migrate=False)
    db.save_card(conn, Card(id="WF-001", title="t", status="planned"))
    db.claim_card(conn, "WF-001", "sess-A", "2026-07-02T10:00")
    assert db.claim_card(conn, "WF-001", "sess-B", "2026-07-02T10:02", force=True) is True
    assert db.load_card(conn, "WF-001").claimed_by == "sess-B"

def test_claim_missing_card_returns_false(repo):
    conn = db.connect(repo, migrate=False)
    assert db.claim_card(conn, "WF-404", "sess-A", "2026-07-02T10:00") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest plugins/overseer/tests/test_db.py -v -k claim`
Expected: FAIL — `claim_card` missing.

- [ ] **Step 3: Write minimal implementation**

```python
# add to scripts/db.py
def claim_card(conn, card_id, session_id, now, *, force: bool = False) -> bool:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest plugins/overseer/tests/test_db.py -v -k claim`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/db.py plugins/overseer/tests/test_db.py
git commit -m "feat(overseer): atomic card claim via conditional UPDATE"
```

---

## Task 5: Stale-claim reclaim (census-liveness + TTL)

**Files:**
- Modify: `plugins/overseer/scripts/db.py`
- Test: `plugins/overseer/tests/test_db.py`

**Interfaces:**
- Consumes: card table, `claimed_at` ISO strings.
- Produces: `reclaim_stale(conn, live_session_ids, ttl_minutes, now) -> list[str]`. Semantics:
  - If `live_session_ids` is a set: any claimed card whose `claimed_by` is **not in** the set is reclaimed (its claim fields cleared) — census is authoritative on liveness.
  - If `live_session_ids is None` (census absent): fall back to TTL — reclaim any claim whose `claimed_at` is older than `ttl_minutes` before `now`. Unparseable `claimed_at` → treated as stale.
  - Clearing a claim sets `claimed_by=NULL, claimed_at=NULL, claim_acked=0, claim_nudged=0` and stamps `updated=now`.
  - Returns the list of reclaimed card ids.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_db.py
def _claimed(conn, cid, sess, at):
    db.save_card(conn, Card(id=cid, title="t", status="in-flight"))
    db.claim_card(conn, cid, sess, at)

def test_reclaim_frees_dead_sessions(repo):
    conn = db.connect(repo, migrate=False)
    _claimed(conn, "WF-001", "dead", "2026-07-02T10:00")
    _claimed(conn, "WF-002", "alive", "2026-07-02T10:00")
    reclaimed = db.reclaim_stale(conn, {"alive"}, ttl_minutes=30, now="2026-07-02T10:05")
    assert reclaimed == ["WF-001"]
    assert db.load_card(conn, "WF-001").claimed_by is None
    assert db.load_card(conn, "WF-002").claimed_by == "alive"

def test_reclaim_ttl_fallback_when_census_absent(repo):
    conn = db.connect(repo, migrate=False)
    _claimed(conn, "WF-001", "old", "2026-07-02T10:00")
    _claimed(conn, "WF-002", "fresh", "2026-07-02T11:50")
    reclaimed = db.reclaim_stale(conn, None, ttl_minutes=30, now="2026-07-02T12:00")
    assert reclaimed == ["WF-001"]
    assert db.load_card(conn, "WF-002").claimed_by == "fresh"

def test_reclaim_none_when_all_live(repo):
    conn = db.connect(repo, migrate=False)
    _claimed(conn, "WF-001", "a", "2026-07-02T10:00")
    assert db.reclaim_stale(conn, {"a"}, ttl_minutes=30, now="2026-07-02T10:05") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest plugins/overseer/tests/test_db.py -v -k reclaim`
Expected: FAIL — `reclaim_stale` missing.

- [ ] **Step 3: Write minimal implementation**

```python
# add to scripts/db.py
from datetime import datetime, timedelta


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest plugins/overseer/tests/test_db.py -v -k reclaim`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/db.py plugins/overseer/tests/test_db.py
git commit -m "feat(overseer): stale-claim reclaim — census-liveness with TTL fallback"
```

---

## Task 6: One-time `.workflow/` importer

**Files:**
- Modify: `plugins/overseer/scripts/db.py` (replace the `_maybe_import` stub; add `migrate_from_workflow`)
- Test: `plugins/overseer/tests/test_db.py`

**Interfaces:**
- Consumes: `store.state_root`, `store.load_live_cards` (the FILE version — import it under an alias before Task 7 removes it; if Task 7 already ran, read files directly here), `Card.from_text`.
- Produces: `migrate_from_workflow(conn, repo_root) -> int` (count imported). Idempotent via `meta` key `migrated_from_workflow`. Imports live cards (`archived=0`) from `.workflow/cards/*.md` and archived cards (`archived=1`) from `.workflow/archive/cards/*.md`. `connect(..., migrate=True)` calls it once.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_db.py
from scripts.store import init_workflow, save_card as file_save_card, state_root

def test_migrate_imports_live_and_archived(tmp_path, monkeypatch):
    git_init(tmp_path)
    monkeypatch.setenv(db.DB_ENV, str(tmp_path / "board.db"))
    root = init_workflow(tmp_path)
    file_save_card(root, Card(id="WF-001", title="live one", status="in-flight"))
    # archived card written straight into archive/cards
    (root / "archive" / "cards" / "WF-002-done.md").write_text(
        Card(id="WF-002", title="done one", status="done").to_text()
    )
    conn = db.connect(tmp_path, migrate=True)
    assert db.load_card(conn, "WF-001").title == "live one"
    assert [c.id for c in db.load_archived_cards(conn)] == ["WF-002"]
    assert db.get_meta(conn, "migrated_from_workflow") == "1"

def test_migrate_is_idempotent(tmp_path, monkeypatch):
    git_init(tmp_path)
    monkeypatch.setenv(db.DB_ENV, str(tmp_path / "board.db"))
    root = init_workflow(tmp_path)
    file_save_card(root, Card(id="WF-001", title="one", status="planned"))
    db.connect(tmp_path, migrate=True).close()
    conn = db.connect(tmp_path, migrate=True)  # second connect re-imports?
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest plugins/overseer/tests/test_db.py -v -k migrate`
Expected: FAIL — importer is a stub.

- [ ] **Step 3: Write minimal implementation**

```python
# in scripts/db.py — replace _maybe_import stub and add migrate_from_workflow
from scripts.models import CardParseError


def migrate_from_workflow(conn: sqlite3.Connection, repo_root: Path) -> int:
    from scripts.store import state_root  # local import: avoid cycle
    root = state_root(repo_root)
    imported = 0
    live_dir = root / "cards"
    arch_dir = root / "archive" / "cards"
    if live_dir.is_dir():
        for path in sorted(live_dir.glob("*.md")):
            try:
                save_card(conn, Card.from_text(path.read_text()))
                imported += 1
            except CardParseError:
                continue
    if arch_dir.is_dir():
        for path in sorted(arch_dir.glob("*.md")):
            try:
                archive_card(conn, Card.from_text(path.read_text()))
                imported += 1
            except CardParseError:
                continue
    set_meta(conn, "migrated_from_workflow", "1")
    conn.commit()
    return imported


def _maybe_import(conn: sqlite3.Connection, repo_root: Path) -> None:
    if get_meta(conn, "migrated_from_workflow") == "1":
        return
    already = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    if already:
        set_meta(conn, "migrated_from_workflow", "1")  # DB pre-seeded; don't double-import
        conn.commit()
        return
    migrate_from_workflow(conn, repo_root)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest plugins/overseer/tests/test_db.py -v -k migrate`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/db.py plugins/overseer/tests/test_db.py
git commit -m "feat(overseer): one-time idempotent .workflow/ -> board.db import"
```

---

## Task 7: `liveness.py` census adapter + wire cli.py card verbs to `db`

**Files:**
- Create: `plugins/overseer/scripts/liveness.py`
- Modify: `plugins/overseer/scripts/store.py` (remove card functions `mint_id`, `save_card`, `load_card`, `find_card_path`, `load_live_cards`, `archive_card`, `load_archived_cards`, `quarantine`, `card_path`; keep file/state functions)
- Modify: `plugins/overseer/scripts/cli.py` (repoint all card call sites; add reclaim-on-claim)
- Test: `plugins/overseer/tests/test_liveness.py` (new), `plugins/overseer/tests/test_cli.py` (update card assertions)

**Interfaces:**
- Consumes: `db.connect`, `db.claim_card`, `db.reclaim_stale`, `db.load_live_cards`, `db.load_card`, `db.save_card`, `db.archive_card`, `db.mint_id`; `liveness.live_session_ids`.
- Produces: cli behaviour unchanged from the user's perspective; card state now in `board.db`.

**Repoint map (from the inventory — exact call sites in `cli.py`):**
- `_sync(repo_root, card)` `:174` — was `save_card(state_root(r), card); index.rebuild_index(...)`. Now: `conn = db.connect(r); db.save_card(conn, card); index.rebuild_index(r, project, now)` (index reads cards via db too — Task 8). Keep a module-level per-invocation connection helper `_conn(repo_root)`.
- `_load(repo_root, card_id)` `:188` — was `load_card(find_card_path(state_root(r), id))`. Now: `card = db.load_card(_conn(r), card_id); if card is None: raise FileNotFoundError(f"no card with id {card_id}")` (preserve the stderr string the dashboard greps — see Global Constraints).
- `cmd_new_card` `:199` — `mint_id(state_root)` → `db.mint_id(_conn(r))`; `find_card_path` existence check → `db.load_card` is-None check; final `save_card` via `_sync`.
- `_close` (done/abandon) `:258` — `archive_card(state_root, card)` → `db.archive_card(_conn(r), card)` (and remove the now-archived live row: archive upsert flips `archived=1` on the same id, so no separate delete needed — verify the row isn't duplicated).
- `cmd_claim` `:615` — before claiming, `reclaim = db.reclaim_stale(conn, liveness.live_session_ids(), ttl_minutes=DEFAULT_TTL, now=_now())`; then `won = db.claim_card(conn, card_id, session, _now(), force=args.force)`; preserve existing output/exit semantics (already-claimed → the current message/return).
- `cmd_unclaim` `:647`, `cmd_claim_nudged` `:676`, `_mark_claim_nudged` `:657`, `_unacked_claims` `:693` — operate on cards loaded/saved via db (`_load`/`_sync`).
- `cmd_set_field/cmd_depends/cmd_rollup_sprint/cmd_set_sprint_status/cmd_resume/cmd_conflicts` — replace `load_live_cards(state_root(r))` with `db.load_live_cards(_conn(r))`.
- `cmd_calibration` `:993`, `cmd_set_sprint_status` `:843` — `load_archived_cards(state_root(r))` → `db.load_archived_cards(_conn(r))`.
- `cmd_show` `:908` — live: `db.load_card`; archived fallback (was direct glob of `archive/cards`) → `db.load_card` already spans archived, so drop the glob.
- `cmd_init` `:192` — keep `init_workflow(r)` (file dirs for sprints/usage/knowledge) AND add `db.connect(r, migrate=True)` to create+seed the board, then `index.rebuild_index`.
- Add `DEFAULT_TTL = 30` (minutes) constant near the top of cli.py.
- Add `_conn(repo_root)` caching a single connection per `main()` call (store on a module global or thread it through; simplest: a small `functools.lru_cache`-free dict keyed by resolved path, closed in `main`'s finally).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_liveness.py
from __future__ import annotations
from scripts import liveness

def test_live_session_ids_returns_none_without_census(tmp_path, monkeypatch):
    monkeypatch.delenv("CENSUS_STORE", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "nope"))
    assert liveness.live_session_ids() is None

def test_live_session_ids_reads_census_store(tmp_path, monkeypatch):
    import json, time
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True)
    now = 1_000_000.0
    store.write_text(json.dumps({
        "sessions": {
            "sess-live": {"updated_epoch": now},
            "sess-old":  {"updated_epoch": now - 999},
        }
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))
    # liveness uses its own clock injection point _now_epoch() -> patchable
    monkeypatch.setattr(liveness, "_now_epoch", lambda: now)
    assert liveness.live_session_ids() == {"sess-live"}
```

*Adapt the census JSON shape to census's actual `status.json` structure — read `plugins/census/scripts/store.py` for the real keys before writing the parser; the test above is illustrative and MUST be updated to the real schema.*

```python
# tests/test_cli.py — update the existing card-file assertions
# Replace every `find_card_path(state_root(repo), "WF-001").read_text()` /
# `(state_root(repo)/"cards"/...).exists()` assertion with a db read:
from scripts import db
def _card(repo, cid):
    return db.load_card(db.connect(repo, migrate=False), cid)
# e.g. assert _card(repo, "WF-001").status == "in-flight"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest plugins/overseer/tests/test_liveness.py plugins/overseer/tests/test_cli.py -v`
Expected: FAIL — `liveness` missing; cli still writes files.

- [ ] **Step 3: Write the implementation**

Write `scripts/liveness.py` modelled on `plugins/vigil/scripts/census.py` (read that file first): resolve the census store via `CENSUS_STORE` then `CLAUDE_CONFIG_DIR/census/status.json`; parse it; return the set of session ids whose last-write is within census's stale horizon (~90s) of `_now_epoch()`; return `None` on any missing-file/parse error. Provide `_now_epoch()` wrapping `time.time()` for test injection. Never raise.

Then repoint `cli.py` per the Repoint map above. Add `_conn`, `DEFAULT_TTL`, reclaim-on-claim. Remove the dead card functions from `store.py`.

*(Full cli.py code not reproduced here — the subagent reads the actual function bodies and applies the exact repoint at each cited line. Every change is a mechanical substitution of a file-store call for the `db` equivalent with the same return type: `load_live_cards` returns `(list[Card], list[Path])` in both; `load_card` returns `Card` (raise FileNotFoundError with the preserved string on None); `save_card`/`archive_card`/`mint_id` map 1:1.)*

- [ ] **Step 4: Run the full overseer suite**

Run: `pytest plugins/overseer/tests/ -v`
Expected: card/cli/liveness tests PASS. Sprint/usage/knowledge tests unaffected. `test_board.py`/`test_resume.py`/`test_composition.py` may still fail — fixed in Task 8.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/liveness.py plugins/overseer/scripts/cli.py plugins/overseer/scripts/store.py plugins/overseer/tests/test_liveness.py plugins/overseer/tests/test_cli.py
git commit -m "feat(overseer): cli card verbs on board.db; census-liveness reclaim on claim"
```

---

## Task 8: Repoint derived-view modules (`board`, `index`, `resume`) + green the remaining suites

**Files:**
- Modify: `plugins/overseer/scripts/board.py`, `scripts/index.py`, `scripts/resume.py`
- Modify: `plugins/overseer/tests/test_board.py`, `tests/test_resume.py`, `tests/test_composition.py`

**Interfaces:**
- Consumes: `db.connect`, `db.load_live_cards`, `db.load_archived_cards`.
- Produces: `board_data`, `rebuild_index`, `resume_entries`, `handoff_data`, `handoff_report` — same signatures and outputs as today; card reads now via db. `board_data`/`index` keep reading sprints via files (`sprints.load_sprints(state_root(...))`), unchanged.

**Repoint map:**
- `board.py:53-55` — `root = state_root(r); load_live_cards(root); load_archived_cards(root)` → `conn = db.connect(r); db.load_live_cards(conn); db.load_archived_cards(conn)`. Keep `sprints.load_sprints(state_root(r))` for sprints (still files).
- `index.py:126-128` — same card-read swap; keep writing `ledger.md` to `state_root(r)`.
- `resume.py:64-65, 109-110` — same card-read swap. `resume_entries(repo_root, session_id)` still receives `repo_root`; open a db connection inside.

- [ ] **Step 1: Update the tests first**

In `test_board.py`, `test_resume.py`, `test_composition.py`: any test that seeds cards by writing files (`file_save_card(state_root(repo), ...)`) must seed via `db.save_card(db.connect(repo), ...)` OR via the CLI (`main(["--root", repo, "new-card", ...])`). Keep sprint seeding as files. The composition test already exercises `handoff_report(tmp_path, ...)` → assert unchanged (rollup content identical), only the seeding path changes.

- [ ] **Step 2: Run to verify they fail**

Run: `pytest plugins/overseer/tests/test_board.py plugins/overseer/tests/test_resume.py plugins/overseer/tests/test_composition.py -v`
Expected: FAIL — modules still read file `state_root` for cards.

- [ ] **Step 3: Apply the repoint** to `board.py`, `index.py`, `resume.py` per the map.

- [ ] **Step 4: Run the FULL overseer suite**

Run: `pytest plugins/overseer/tests/ -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/board.py plugins/overseer/scripts/index.py plugins/overseer/scripts/resume.py plugins/overseer/tests/test_board.py plugins/overseer/tests/test_resume.py plugins/overseer/tests/test_composition.py
git commit -m "feat(overseer): board/index/resume read cards from board.db"
```

---

## Task 9: End-to-end verification + version bump + dashboard smoke

**Files:**
- Modify: `plugins/overseer/.claude-plugin/plugin.json` (version bump)
- Modify: `plugins/overseer/README.md` (note the board.db store location + that sprints/usage/knowledge remain file-based this phase)

- [ ] **Step 1: Full suite + lint/type**

Run: `pytest plugins/overseer/tests/ -q` — expect all green.
Run (if configured): `ruff check plugins/overseer/scripts` and `mypy plugins/overseer/scripts` — no new errors.

- [ ] **Step 2: Manual cross-worktree claim smoke (real board.db, temp config dir)**

```bash
export CLAUDE_CONFIG_DIR=$(mktemp -d)
python plugins/overseer/scripts/cli.py --root . init
python plugins/overseer/scripts/cli.py --root . new-card --title "smoke card"
python plugins/overseer/scripts/cli.py --root . claim WF-XXX --session sess-1   # wins
python plugins/overseer/scripts/cli.py --root . claim WF-XXX --session sess-2   # loses (already claimed)
python plugins/overseer/scripts/cli.py --root . board --json | python -m json.tool | head
ls "$CLAUDE_CONFIG_DIR/overseer/pip-skills/board.db"   # confirm location
```
Expected: second claim reports already-claimed; board.db at the config-dir path.

- [ ] **Step 3: Dashboard smoke (subprocess contract intact)**

Confirm `python plugins/overseer/scripts/cli.py --root . board --json` and `show WF-XXX --json` produce the same JSON shape the backend expects (`dashboard/backend/app/main.py` `_board_response`). No backend code changes; this is a contract check only.

- [ ] **Step 4: Bump version + document**

Edit `plugin.json` version (e.g. `0.7.0` → `0.8.0`). Add a README line: board cards now persist in `$CLAUDE_CONFIG_DIR/overseer/<repo>/board.db` (shared across worktrees); sprints/usage/knowledge remain under `.workflow/` pending follow-on migration.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/.claude-plugin/plugin.json plugins/overseer/README.md
git commit -m "chore(overseer): bump version; document sqlite board store"
```

---

## Deferred to follow-on plans (same branch/PR if desired)
- Sprints → `board.db` (`sprints` table), repoint `sprints.py` + `test_sprints.py`.
- Usage → `board.db` (`usage` table), repoint `usage.py`; migrate `usage.jsonl` history in the importer.
- Knowledge → `board.db` (`knowledge` table), repoint `knowledge.py` + `test_knowledge.py`.
- `.workflow/` teardown + `ledger.md` provenance once nothing reads files.

## Self-Review notes
- **Spec coverage:** shared per-repo board ✓ (Task 1 rooting), atomic claim ✓ (Task 4), census-liveness+TTL reclaim ✓ (Task 5), migrate main's `.workflow/` ✓ (Task 6), preserve model behaviour ✓ (Task 2 round-trip), dashboard untouched ✓ (Task 9 contract check). Usage-history preservation is DEFERRED (usage stays file-based this phase) — flagged, not dropped.
- **Type consistency:** `load_live_cards` returns `(list[Card], list[Path])` in both file and db forms; `load_card` returns `Card | None` in db but callers via `_load` raise `FileNotFoundError` to preserve cli behaviour; `claim_card`/`reclaim_stale` signatures fixed in their tasks and consumed unchanged in Task 7.
- **Open confirmations for the implementer:** (a) census `status.json` real schema — read `plugins/census/scripts/store.py` before writing `liveness.py`/its test; (b) card `id` is the bare `WF-NNN` in frontmatter — confirm on a migrated card; (c) cli's `_now()` format — reuse it verbatim, don't reinvent.
