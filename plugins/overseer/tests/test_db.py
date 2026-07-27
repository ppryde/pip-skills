from __future__ import annotations
import pytest
from scripts import db
from scripts.models import Card
from scripts.store import init_workflow, save_card as file_save_card
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

def test_archive_after_save_upserts_single_row(repo):
    conn = db.connect(repo, migrate=False)
    card = Card(id="WF-011", title="x", status="in-flight")
    db.save_card(conn, card)
    db.archive_card(conn, card)
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 1
    live, _ = db.load_live_cards(conn)
    assert live == []
    assert [c.id for c in db.load_archived_cards(conn)] == ["WF-011"]

def test_load_archived_sorted_by_updated_desc(repo):
    conn = db.connect(repo, migrate=False)
    db.archive_card(conn, Card(id="WF-020", title="older", status="done", updated="2026-07-01T09:00"))
    db.archive_card(conn, Card(id="WF-021", title="newer", status="done", updated="2026-07-05T09:00"))
    assert [c.id for c in db.load_archived_cards(conn)] == ["WF-021", "WF-020"]

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

def test_reclaim_stale_when_claimed_at_unparseable(repo):
    conn = db.connect(repo, migrate=False)
    db.save_card(conn, Card(id="WF-001", title="t", status="in-flight"))
    # Corrupt the claim timestamp directly, bypassing claim_card.
    conn.execute(
        "UPDATE cards SET claimed_by='ghost', claimed_at='not-a-date' WHERE id='WF-001'"
    )
    conn.commit()
    reclaimed = db.reclaim_stale(conn, None, ttl_minutes=30, now="2026-07-02T12:00")
    assert reclaimed == ["WF-001"]
    assert db.load_card(conn, "WF-001").claimed_by is None

def test_reclaim_empty_live_set_frees_all(repo):
    conn = db.connect(repo, migrate=False)
    _claimed(conn, "WF-001", "a", "2026-07-02T10:00")
    _claimed(conn, "WF-002", "b", "2026-07-02T10:00")
    reclaimed = db.reclaim_stale(conn, set(), ttl_minutes=30, now="2026-07-02T10:05")
    assert sorted(reclaimed) == ["WF-001", "WF-002"]

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
