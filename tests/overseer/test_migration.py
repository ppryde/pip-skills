"""Schema v1 -> v2 upgrade (WF-265 PR D1): backup, import, evidence, mixed versions."""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import pytest
from factories import git_init, make_card

from scripts import backup, db, migrate, views
from scripts.knowledge import Fact
from scripts.sprints import Sprint

SPRINT = Sprint(id="2026-07-S1", status="active", budget_estimate=1000, started="2026-07-01",
                body="## Goal\nShip.")
REVIEWED = """## Plan
do it

## Review log
### impl-review — round 1
- A: approved 0C 0I 1M → /d/r1-A.md
- B: found wanting 1C 2I 0M → /d/r1-B.md
### plan-review — round 1 (2 reviewers)
Verdict: approved

## Verification
pytest: 12 passed, PASS
"""


def make_v1_board(path: Path, state: Path, *, n_cards: int = 260) -> None:
    """A board exactly as 0.26 leaves it: v1 tables only, user_version 1, sprint /
    knowledge / pending state as FILES (one corrupt of each kind)."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    db._exec_script(conn, db._SCHEMA)
    db.set_meta(conn, "schema_version", "1")
    db.set_meta(conn, "repo_root", "/some/repo")
    db.set_meta(conn, "migrated_from_workflow", "1")
    db.set_meta(conn, "workflow_fs_imported", "1")
    for i in range(1, n_cards + 1):
        body = REVIEWED if i == 7 else "## Review log\n\n## Verification\n"
        card = make_card(f"WF-{i:03d}", body=body, labels=["x"], budget_actual=i)
        db._upsert(conn, card, archived=1 if i % 3 == 0 else 0, commit=False)
    conn.commit()
    conn.execute("PRAGMA user_version = 1")
    conn.close()

    (state / "sprints").mkdir(parents=True)
    (state / "sprints" / "2026-07-S1.md").write_text(SPRINT.to_text())
    (state / "sprints" / "2026-07-S2.md").write_text(
        Sprint(id="2026-07-S2", budget_actual=5).to_text())
    (state / "sprints" / "broken.md").write_text("garbage, no frontmatter")
    for sub in ("facts", "retired", "corrupt"):
        (state / "knowledge" / sub).mkdir(parents=True)
    for n in (1, 2, 3):
        fact = Fact(id=f"KB-00{n}", statement=f"fact {n}", tags=["x"], source="WF-1",
                    created="2026-07-01", verified="2026-07-01")
        (state / "knowledge" / "facts" / f"KB-00{n}-fact-{n}.md").write_text(fact.to_text())
    (state / "knowledge" / "retired" / "KB-009-old.md").write_text(
        Fact(id="KB-009", statement="old", status="retired", superseded_by="KB-001").to_text())
    (state / "knowledge" / "facts" / "KB-777-bad.md").write_text("no frontmatter")
    (state / "knowledge" / "pending.jsonl").write_text(
        json.dumps({"id": "P-aaaaaa", "card": "WF-001", "statement": "p1", "tags": ["t"],
                    "source": "/d", "status": "pending", "reason": ""}) + "\n"
        + json.dumps({"id": "P-bbbbbb", "card": "WF-002", "statement": "p2", "tags": [],
                      "source": "", "status": "rejected", "reason": "noise"}) + "\n"
        + "{broken\n")


@pytest.fixture
def board(tmp_path):
    git_init(tmp_path)
    path = tmp_path / "board.db"           # OVERSEER_DB, pinned by the autouse fixture
    state = tmp_path / "state"             # OVERSEER_CENTRAL
    make_v1_board(path, state)
    return tmp_path, path, state


def card_rows(path: Path) -> list[tuple]:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT * FROM cards ORDER BY id").fetchall()
    finally:
        conn.close()


def baks(path: Path) -> list[Path]:
    return sorted(path.parent.glob("board.db.pre-v2.*.bak"))


def test_upgrade_keeps_every_card_row_and_stamps_v2(board, capsys):
    repo, path, state = board
    before = card_rows(path)
    conn = db.connect(repo)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION == 2
    assert db.get_meta(conn, "schema_version") == "2"
    assert card_rows(path) == before
    assert conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == 260
    err = capsys.readouterr().err
    assert "upgraded to schema v2" in err and "2 sprints" in err
    assert "Upgrade every Claude account" in err


def test_a_verified_bak_is_taken_before_any_ddl_and_restores_the_exact_board(board):
    repo, path, state = board
    before = card_rows(path)
    db.connect(repo).close()
    [bak] = baks(path)
    chk = sqlite3.connect(str(bak))
    assert chk.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    tables = {r[0] for r in chk.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "sprints" not in tables                    # taken BEFORE the DDL
    assert chk.execute("PRAGMA user_version").fetchone()[0] == 1
    chk.close()

    result = backup.restore_from_bak(repo, bak)
    assert result["cards"] == 260 and result["previous_board_saved_as"]
    assert card_rows(path) == before
    raw = sqlite3.connect(str(path))
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 1
    assert "sprints" not in {r[0] for r in raw.execute("SELECT name FROM sqlite_master")}
    raw.close()
    assert Path(result["previous_board_saved_as"]).exists()


def test_the_import_counts_and_unparsed_files_are_reported_and_left_alone(board, capsys):
    repo, path, state = board
    conn = db.connect(repo)
    assert [s[0] for s in conn.execute("SELECT id FROM sprints ORDER BY id")] == [
        "2026-07-S1", "2026-07-S2"]
    assert [r[0] for r in conn.execute("SELECT id FROM facts WHERE retired=0 ORDER BY id")] == [
        "KB-001", "KB-002", "KB-003"]
    assert [r[0] for r in conn.execute("SELECT id FROM facts WHERE retired=1")] == ["KB-009"]
    assert conn.execute("SELECT status, reason FROM pending_facts WHERE id='P-bbbbbb'"
                        ).fetchone()[:] == ("rejected", "noise")
    assert conn.execute("SELECT COUNT(*) FROM pending_facts").fetchone()[0] == 2
    err = capsys.readouterr().err
    assert "3 unparsed" in err
    for name in ("broken.md", "KB-777-bad.md", "pending.jsonl:3"):
        assert name in err
    # never moved, renamed or rewritten
    assert (state / "sprints" / "broken.md").read_text() == "garbage, no frontmatter"
    assert (state / "knowledge" / "facts" / "KB-777-bad.md").read_text() == "no frontmatter"
    assert not any((state / "knowledge" / "corrupt").iterdir())
    assert not (state / "archive").exists()


def test_the_import_is_idempotent(board):
    repo, path, state = board
    conn = db.connect(repo)
    snapshot = {t: conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()
                for t in ("sprints", "facts", "pending_facts", "stage_evidence")}
    with db.txn(conn):
        again = migrate.import_state(conn, state)
    assert (again.sprints, again.facts, again.retired, again.pending) == (0, 0, 0, 0)
    conn.close()
    conn = db.connect(repo)                      # a second process connecting
    assert len(baks(path)) == 1                  # no second backup
    for t, rows in snapshot.items():
        assert conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall() == rows


def test_evidence_is_backfilled_from_a_well_formed_review_log(board):
    repo, path, state = board
    conn = db.connect(repo)
    rows = conn.execute(
        "SELECT stage, kind, round, slot, status, critical, important, minor FROM stage_evidence "
        "WHERE card_id='WF-007' ORDER BY id").fetchall()
    assert [tuple(r) for r in rows] == [
        ("impl-review", "review", 1, "A", "approved", 0, 0, 1),
        ("impl-review", "review", 1, "B", "found wanting", 1, 2, 0),
        ("plan-review", "review", 1, "", "approved", None, None, None),
        ("verification", "verify", None, "", "PASS", None, None, None),
    ]
    # an archived card (WF-003) and cards with empty logs get nothing
    assert conn.execute("SELECT COUNT(*) FROM stage_evidence WHERE card_id != 'WF-007'"
                        ).fetchone()[0] == 0


def test_gates_since_marks_the_moment_of_the_upgrade(board):
    repo, path, state = board
    conn = db.connect(repo)
    assert db.get_meta(conn, "gates_since")
    assert db.get_meta(conn, "state_imported_v2")


def test_a_fresh_board_is_born_v2_with_no_backup(tmp_path):
    git_init(tmp_path)
    conn = db.connect(tmp_path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert baks(tmp_path / "board.db") == []
    assert db.get_meta(conn, "gates_since")


def test_a_failed_backup_aborts_with_the_board_untouched(board, monkeypatch):
    repo, path, state = board
    before = card_rows(path)

    def broken(conn, p):
        raise db.MigrationError("disk full; board left untouched")

    monkeypatch.setattr(migrate, "backup_before_v2", broken)
    with pytest.raises(db.MigrationError, match="untouched"):
        db.connect(repo)
    raw = sqlite3.connect(str(path))
    assert raw.execute("PRAGMA user_version").fetchone()[0] == 1
    assert "sprints" not in {r[0] for r in raw.execute("SELECT name FROM sqlite_master")}
    raw.close()
    assert card_rows(path) == before
    assert baks(path) == []


def test_an_unwritable_backup_destination_is_a_migration_error(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "board.db"))
    db._exec_script(conn, db._SCHEMA)
    with pytest.raises(db.MigrationError, match="left untouched"):
        migrate.backup_before_v2(conn, tmp_path / "no-such-dir" / "board.db")


def test_only_the_three_newest_baks_are_kept_and_the_new_one_always_survives(tmp_path):
    path = tmp_path / "board.db"
    conn = sqlite3.connect(str(path))
    db._exec_script(conn, db._SCHEMA)
    for stamp in ("20200101T000000Z", "20210101T000000Z", "20220101T000000Z", "20230101T000000Z"):
        (tmp_path / f"board.db.pre-v2.{stamp}.bak").write_bytes(b"x")
    new = migrate.backup_before_v2(conn, path)
    names = [p.name for p in baks(path)]
    assert new.name in names and len(names) == 3
    assert "board.db.pre-v2.20200101T000000Z.bak" not in names
    # a new stamp that sorts OLDEST still survives
    (tmp_path / "board.db.pre-v2.29990101T000000Z.bak").write_bytes(b"x")
    (tmp_path / "board.db.pre-v2.29990102T000000Z.bak").write_bytes(b"x")
    (tmp_path / "board.db.pre-v2.29990103T000000Z.bak").write_bytes(b"x")
    newest = migrate.backup_before_v2(conn, path)
    assert newest.exists()


def test_a_process_that_loses_the_first_upgrade_race_skips_it(board, monkeypatch):
    repo, path, state = board
    loser = sqlite3.connect(str(path))
    loser.row_factory = sqlite3.Row
    winner = sqlite3.connect(str(path))
    winner.row_factory = sqlite3.Row
    real_backup = migrate.backup_before_v2
    calls = []
    real_finish = migrate.finish_v2
    monkeypatch.setattr(migrate, "finish_v2",
                        lambda *a, **k: (calls.append(1), real_finish(*a, **k))[1])

    def backup_then_other_process_finishes(conn, p):
        monkeypatch.setattr(migrate, "backup_before_v2", real_backup)  # the winner's own call
        out = real_backup(conn, p)
        db.ensure_schema(winner, path=path, state=state)   # the other process wins now
        return out

    monkeypatch.setattr(migrate, "backup_before_v2", backup_then_other_process_finishes)
    db.ensure_schema(loser, path=path, state=state)
    assert calls == [1]                                    # imported exactly once
    assert loser.execute("PRAGMA user_version").fetchone()[0] == 2


def test_an_older_plugin_restamping_user_version_does_not_trigger_a_second_upgrade(board):
    repo, path, state = board
    db.connect(repo).close()
    raw = sqlite3.connect(str(path))               # what 0.26's ensure_schema does on open
    raw.execute("PRAGMA user_version = 1")
    raw.commit()
    raw.close()
    conn = db.connect(repo)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    assert len(baks(path)) == 1


# ---- mixed versions: a v1 plugin keeps writing the legacy files ----------------

def _touch_later(path: Path) -> None:
    future = time.time() + 5
    os.utime(path, (future, future))


def test_a_sprint_file_written_by_an_older_plugin_is_imported_not_overwritten(board):
    repo, path, state = board
    db.connect(repo).close()
    old = Sprint(id="2026-07-S3", status="planned", body="## Goal\nfrom the other account")
    f = state / "sprints" / "2026-07-S3.md"
    f.write_text(old.to_text())
    _touch_later(f)
    conn = db.connect(repo)                          # next v2 command
    assert conn.execute("SELECT body FROM sprints WHERE id='2026-07-S3'").fetchone()[0].endswith(
        "from the other account")
    assert f.read_text() == old.to_text()            # the view kept it


def test_an_edited_fact_and_a_retirement_by_an_older_plugin_win_when_newer(board):
    repo, path, state = board
    db.connect(repo).close()
    kb = state / "knowledge"
    edited = kb / "facts" / "KB-001-fact-1.md"
    edited.write_text(Fact(id="KB-001", statement="fact 1", tags=["x"], created="2026-07-01",
                           verified="2026-10-01").to_text())
    _touch_later(edited)
    # older-plugin retire-fact: file moved from facts/ to retired/
    moved = kb / "retired" / "KB-002-fact-2.md"
    moved.write_text(Fact(id="KB-002", statement="fact 2", status="retired").to_text())
    (kb / "facts" / "KB-002-fact-2.md").unlink()
    _touch_later(moved)
    conn = db.connect(repo)
    assert conn.execute("SELECT verified FROM facts WHERE id='KB-001'").fetchone()[0] == "2026-10-01"
    assert conn.execute("SELECT retired FROM facts WHERE id='KB-002'").fetchone()[0] == 1
    assert not list((kb / "facts").glob("KB-002-*"))


def test_a_pending_decision_by_an_older_plugin_is_imported(board):
    repo, path, state = board
    db.connect(repo).close()
    pf = state / "knowledge" / "pending.jsonl"
    lines = [json.loads(x) for x in pf.read_text().splitlines() if x.startswith("{\"")]
    lines[0]["status"] = "accepted"
    lines.append({"id": "P-cccccc", "card": "WF-003", "statement": "p3", "tags": [], "source": "",
                  "status": "pending", "reason": ""})
    pf.write_text("".join(json.dumps(x) + "\n" for x in lines))
    _touch_later(pf)
    conn = db.connect(repo)
    assert dict(conn.execute("SELECT id, status FROM pending_facts").fetchall()) == {
        "P-aaaaaa": "accepted", "P-bbbbbb": "rejected", "P-cccccc": "pending"}


def test_a_v2_write_after_the_older_plugins_write_does_not_lose_it(board):
    """The bug this guards: v1 writes a file; v2's next write exports the views and
    the file's content is gone. connect() re-imports first, so the export keeps it."""
    from scripts.cli import main
    repo, path, state = board
    db.connect(repo).close()
    f = state / "sprints" / "2026-07-S3.md"
    f.write_text(Sprint(id="2026-07-S3", body="## Goal\nlegacy write").to_text())
    _touch_later(f)
    assert main(["--root", str(repo), "new-sprint", "2026-07-S4", "--goal", "mine"]) == 0
    assert "legacy write" in f.read_text()
    conn = db.connect(repo)
    assert {r[0] for r in conn.execute("SELECT id FROM sprints")} >= {"2026-07-S3", "2026-07-S4"}


def test_nothing_is_reimported_when_no_file_changed(board, monkeypatch):
    repo, path, state = board
    db.connect(repo).close()
    called = []
    monkeypatch.setattr(migrate, "import_state", lambda *a, **k: called.append(1))
    db.connect(repo).close()
    assert called == []


def test_files_the_views_wrote_are_not_mistaken_for_older_plugin_writes(board):
    repo, path, state = board
    conn = db.connect(repo)
    exported = float(db.get_meta(conn, "views_exported_at"))
    newest = max(p.stat().st_mtime for p in migrate._view_files(state) if p.exists())
    assert newest <= exported


def test_legacy_workflow_state_copied_in_on_a_fresh_board_is_imported(tmp_path):
    git_init(tmp_path)
    (tmp_path / ".workflow" / "sprints").mkdir(parents=True)
    (tmp_path / ".workflow" / "sprints" / "S1.md").write_text(Sprint(id="S1").to_text())
    conn = db.connect(tmp_path)
    assert [r[0] for r in conn.execute("SELECT id FROM sprints")] == ["S1"]


def test_the_views_can_always_rebuild_what_the_tables_hold(board):
    repo, path, state = board
    conn = db.connect(repo)
    for f in list((state / "sprints").glob("2026*.md")):
        f.unlink()
    assert views.export(conn, state)
    assert (state / "sprints" / "2026-07-S1.md").read_text() == SPRINT.to_text()


# --- round 1 review fixes -------------------------------------------------


def test_a_loser_that_backs_up_after_the_winner_finished_leaves_no_backup_of_a_v2_board(board, monkeypatch):
    repo, path, state = board
    loser = sqlite3.connect(str(path))
    loser.row_factory = sqlite3.Row
    winner = sqlite3.connect(str(path))
    winner.row_factory = sqlite3.Row
    real_backup = migrate.backup_before_v2

    def winner_first(conn, p):
        monkeypatch.setattr(migrate, "backup_before_v2", real_backup)
        db.ensure_schema(winner, path=path, state=state)       # winner takes the true .bak
        return real_backup(conn, p)                             # loser copies a v2 board

    monkeypatch.setattr(migrate, "backup_before_v2", winner_first)
    db.ensure_schema(loser, path=path, state=state)
    [only] = baks(path)
    check = sqlite3.connect(str(only))
    assert check.execute("PRAGMA user_version").fetchone()[0] == 1   # the pre-upgrade copy
    check.close()


def test_a_failed_export_does_not_let_old_files_revert_later_v2_writes(board, monkeypatch):
    from scripts.knowledge import Fact, save_fact

    repo, path, state = board
    conn = db.connect(repo)
    save_fact(conn, Fact(id="KB-900", statement="old", created="2026-09-01", verified="2026-09-01"))
    views.export(conn, state)
    conn.close()
    monkeypatch.setattr(views, "_export", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    conn = db.connect(repo)
    db.set_meta(conn, "views_exported_at", "0")                   # as after a failed export
    conn.commit()
    conn.close()
    db.connect(repo).close()                                      # first connect re-imports once
    conn = db.connect(repo)
    conn.execute("UPDATE facts SET statement='NEWEST' WHERE id='KB-900'")
    conn.commit()
    conn.close()
    conn = db.connect(repo)
    assert conn.execute("SELECT statement FROM facts WHERE id='KB-900'").fetchone()[0] == "NEWEST"


def test_a_legacy_write_between_connect_and_export_is_imported_not_overwritten(board):
    repo, path, state = board
    conn = db.connect(repo)
    f = state / "sprints" / "2026-07-S3.md"
    f.write_text(Sprint(id="2026-07-S3", body="## Goal\nlate legacy write").to_text())
    _touch_later(f)
    assert views.export(conn, state)
    assert "late legacy write" in conn.execute(
        "SELECT body FROM sprints WHERE id='2026-07-S3'").fetchone()[0]


@pytest.mark.parametrize("text,expected", [
    ("pytest: 12 passed\nPASS", "PASS"),
    ("FAIL first run\nfixed it\nPASS", "UNKNOWN"),
    ("FAIL: 2 failed", "FAIL"),
])
def test_verification_backfill_reads_a_verdict_only_when_unambiguous(text, expected):
    from scripts.models import Card
    card = make_card("WF-1", body=f"## Verification\n{text}\n")
    [row] = [r for r in migrate._evidence_rows(card) if r["kind"] == "verify"]
    assert row["status"] == expected
