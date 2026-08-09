from __future__ import annotations
import pytest
from scripts import db
from scripts.models import Card
from scripts.store import save_card as file_save_card, workflow_root
from factories import git_init


def _seed_legacy_workflow(repo_root):
    """Create the legacy on-disk ``.workflow/cards`` and
    ``.workflow/archive/cards`` directories directly (NOT via
    ``init_workflow``, which resolves through ``state_root`` — the CENTRAL
    folder under this suite's autouse env pinning, not ``.workflow/``).
    ``migrate_from_workflow`` sources legacy card markdown from
    ``.workflow/`` on disk, so tests exercising that import must seed cards
    there, not in the central folder."""
    root = workflow_root(repo_root)
    (root / "cards").mkdir(parents=True, exist_ok=True)
    (root / "archive" / "cards").mkdir(parents=True, exist_ok=True)
    return root

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
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
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
    root = _seed_legacy_workflow(tmp_path)
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
    root = _seed_legacy_workflow(tmp_path)
    file_save_card(root, Card(id="WF-001", title="one", status="planned"))
    db.connect(tmp_path, migrate=True).close()
    conn = db.connect(tmp_path, migrate=True)  # second connect re-imports?
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 1

def test_two_connections_one_winner(repo):
    # Two independent connections to the SAME board.db (repo fixture pins
    # OVERSEER_DB to one file). Proves the atomic-claim guard holds across
    # connections, not just within a single one.
    conn_a = db.connect(repo, migrate=False)
    conn_b = db.connect(repo, migrate=False)
    db.save_card(conn_a, Card(id="WF-001", title="t", status="planned"))

    won_a = db.claim_card(conn_a, "WF-001", "A", "2026-07-02T10:00")
    won_b = db.claim_card(conn_b, "WF-001", "B", "2026-07-02T10:01")

    assert {won_a, won_b} == {True, False}
    winner = "A" if won_a else "B"
    assert db.load_card(conn_a, "WF-001").claimed_by == winner

def test_claim_visible_across_connections(repo):
    conn_a = db.connect(repo, migrate=False)
    conn_b = db.connect(repo, migrate=False)
    db.save_card(conn_a, Card(id="WF-001", title="t", status="planned"))

    assert db.claim_card(conn_a, "WF-001", "A", "2026-07-02T10:00") is True
    # claim_card commits internally; connection B, reading afterward, must
    # see the claim (WAL cross-connection visibility).
    seen = db.load_card(conn_b, "WF-001")
    assert seen.claimed_by == "A"
    assert seen.claimed_at == "2026-07-02T10:00"

class TestRepoRootMeta:
    def test_connect_sets_repo_root_when_derivable(self, tmp_path, monkeypatch):
        git_init(tmp_path)
        monkeypatch.setenv(db.DB_ENV, str(tmp_path / "board.db"))
        conn = db.connect(tmp_path, migrate=False)
        assert db.get_meta(conn, "repo_root") == str(tmp_path.resolve())

    def test_connect_leaves_repo_root_unset_without_git(self, tmp_path, monkeypatch):
        monkeypatch.setenv(db.DB_ENV, str(tmp_path / "board.db"))
        conn = db.connect(tmp_path, migrate=False)
        assert db.get_meta(conn, "repo_root") is None

    def test_connect_does_not_overwrite_existing_repo_root(self, tmp_path, monkeypatch):
        git_init(tmp_path)
        monkeypatch.setenv(db.DB_ENV, str(tmp_path / "board.db"))
        conn = db.connect(tmp_path, migrate=False)
        db.set_meta(conn, "repo_root", "/some/other/recorded/path")
        conn.commit()
        conn.close()

        conn2 = db.connect(tmp_path, migrate=False)
        assert db.get_meta(conn2, "repo_root") == "/some/other/recorded/path"


def test_migrate_is_atomic_on_failure(tmp_path, monkeypatch):
    git_init(tmp_path)
    monkeypatch.setenv(db.DB_ENV, str(tmp_path / "board.db"))
    root = _seed_legacy_workflow(tmp_path)
    file_save_card(root, Card(id="WF-001", title="one", status="planned"))
    file_save_card(root, Card(id="WF-002", title="two", status="planned"))
    conn = db.connect(tmp_path, migrate=False)  # no import yet
    # Force a failure partway through the import.
    calls = {"n": 0}
    real_upsert = db._upsert
    def boom(c, card, archived, commit=True):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("simulated crash mid-import")
        return real_upsert(c, card, archived, commit=commit)
    monkeypatch.setattr(db, "_upsert", boom)
    with pytest.raises(RuntimeError):
        db.migrate_from_workflow(conn, tmp_path)
    # Rolled back: no cards, no marker.
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 0
    assert db.get_meta(conn, "migrated_from_workflow") is None


def test_import_reads_from_derived_main_root_not_connecting_root(tmp_path, monkeypatch):
    """Guards against permanent card loss (Fix 1): `board_db_path` keys one
    shared board.db per MAIN repo, but the one-time import used to read
    straight from `state_root(repo_root)` (and even after resolving to the
    main root, from the CENTRAL folder rather than `.workflow/` on disk) —
    not the raw connecting root, and not the wrong on-disk tree. If a
    worktree (with no `.workflow/` of its own) happened to be the FIRST
    caller to connect, the import would read the worktree's empty tree,
    import 0 cards, and permanently stamp migrated_from_workflow=1 —
    stranding the main repo's cards forever, since the import never retries.

    `derive_repo_root` is stubbed here (rather than using a real `git
    worktree`) to isolate the exact behaviour under test: the import must
    resolve its source from the DB's OWN repo identity
    (`derive_repo_root(repo_root)`) and from `.workflow/` on disk (via
    `workflow_root`), not from whichever root happens to make the first
    connection, and not from the central folder.
    """
    main_root = tmp_path / "main"
    connecting_root = tmp_path / "not-the-main-root"
    main_root.mkdir()
    connecting_root.mkdir()
    git_init(main_root)

    wf_root = _seed_legacy_workflow(main_root)
    file_save_card(wf_root, Card(id="WF-001", title="one", status="planned"))

    monkeypatch.setenv(db.DB_ENV, str(tmp_path / "shared-board.db"))
    monkeypatch.setattr(db, "derive_repo_root", lambda p: main_root)

    conn = db.connect(connecting_root)  # migrate=True (default) — first connect
    cards, _ = db.load_live_cards(conn)

    assert [c.id for c in cards] == ["WF-001"]
    assert db.get_meta(conn, "migrated_from_workflow") == "1"


def test_connect_imports_cards_and_migrates_workflow_files_together(tmp_path, monkeypatch):
    """`connect()` runs BOTH one-time migrations behind their own meta guards:
    `_maybe_import` (cards -> DB, guarded by `migrated_from_workflow`) and
    `migrate_workflow_to_central` (remaining .workflow/ files -> central,
    guarded by `workflow_fs_imported`). Seeds a live card, an archived card,
    and a non-card file (sprints/) in the legacy `.workflow/` tree, then
    asserts a single `connect()` call lands the cards in the DB (live +
    archived) AND copies the sprint file to the central folder. A second
    `connect()` must be a no-op for both: no double import, no re-copy, both
    guards stay set at "1"."""
    git_init(tmp_path)
    monkeypatch.setenv(db.DB_ENV, str(tmp_path / "board.db"))
    root = _seed_legacy_workflow(tmp_path)
    file_save_card(root, Card(id="WF-001", title="live one", status="in-flight"))
    (root / "archive" / "cards" / "WF-002-done.md").write_text(
        Card(id="WF-002", title="done one", status="done").to_text()
    )
    (root / "sprints").mkdir(parents=True)
    (root / "sprints" / "sprint-1.md").write_text("---\nid: sprint-1\n---\n")

    conn = db.connect(tmp_path)  # migrate=True (default) — first connect
    assert db.load_card(conn, "WF-001").title == "live one"
    assert [c.id for c in db.load_archived_cards(conn)] == ["WF-002"]
    assert db.get_meta(conn, "migrated_from_workflow") == "1"
    assert db.get_meta(conn, "workflow_fs_imported") == "1"

    from scripts.config import central_root
    central = central_root(tmp_path)
    assert (central / "sprints" / "sprint-1.md").exists()

    # Second connect: no-op for both migrations — no double import, guards stay set.
    (central / "sprints" / "sprint-1.md").write_text("LOCAL EDIT\n")
    conn2 = db.connect(tmp_path)
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 2
    assert db.get_meta(conn2, "migrated_from_workflow") == "1"
    assert db.get_meta(conn2, "workflow_fs_imported") == "1"
    assert (central / "sprints" / "sprint-1.md").read_text() == "LOCAL EDIT\n"


def test_connect_warns_on_repo_root_meta_mismatch(tmp_path, monkeypatch, capsys):
    """I2 identity guard: a board.db that already records a DIFFERENT canonical
    root than the one connecting now (a residual basename collision) prints a
    loud one-line warning to stderr. Behaviour is otherwise unchanged — the
    stamped repo_root is NOT overwritten (set-if-absent)."""
    dir_a = tmp_path / "a"; dir_a.mkdir(); git_init(dir_a)
    dir_b = tmp_path / "b"; dir_b.mkdir(); git_init(dir_b)
    shared_db = tmp_path / "shared.db"
    monkeypatch.setenv(db.DB_ENV, str(shared_db))

    conn_a = db.connect(dir_a, migrate=False)  # stamps repo_root = dir_a
    from scripts.store import derive_repo_root
    assert db.get_meta(conn_a, "repo_root") == str(derive_repo_root(dir_a))
    capsys.readouterr()  # drain

    conn_b = db.connect(dir_b, migrate=False)  # different root → warn
    err = capsys.readouterr().err
    assert "warning:" in err
    assert str(derive_repo_root(dir_a)) in err  # created-for root
    assert str(derive_repo_root(dir_b)) in err  # now-connected-from root
    # set-if-absent preserved: original owner NOT overwritten
    assert db.get_meta(conn_b, "repo_root") == str(derive_repo_root(dir_a))
