from __future__ import annotations
import pytest
from scripts import db
from scripts.models import Card
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
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"cards", "meta"} <= tables
    assert db.get_meta(conn, "schema_version") == str(db.SCHEMA_VERSION)

def test_connect_is_idempotent(repo):
    db.connect(repo, migrate=False).close()
    conn = db.connect(repo, migrate=False)  # must not raise on existing schema
    assert db.get_meta(conn, "schema_version") == str(db.SCHEMA_VERSION)

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
        complexity="M", jira="OPS-1", linear="LIN-1", branch="wf-007",
        worktree="/tmp/wt", pr="42", blocked_on="WF-003",
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
