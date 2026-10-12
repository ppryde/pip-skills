"""The sprint / knowledge file trees are regenerated read-only views (OL-10)."""
from __future__ import annotations

import json
import os

import pytest
from factories import git_init

from scripts import db, views
from scripts.cli import main
from scripts.knowledge import Fact, save_fact
from scripts.pending import add_pending
from scripts.sprints import Sprint, save_sprint
from scripts.store import state_root


@pytest.fixture
def repo(tmp_path):
    git_init(tmp_path)
    assert main(["--root", str(tmp_path), "init"]) == 0
    return tmp_path


def run(repo, *argv):
    return main(["--root", str(repo), *argv])


def test_export_writes_every_tree(repo):
    conn = db.connect(repo, migrate=False)
    save_sprint(conn, Sprint(id="S1", body="## Goal\nx"))
    save_fact(conn, Fact(id="KB-001", statement="Alpha truth", created="2026-09-01",
                         verified="2026-09-01"))
    save_fact(conn, Fact(id="KB-002", statement="Old news", status="retired",
                         superseded_by="KB-001"))
    add_pending(conn, "WF-001", "maybe", ["t"], "/d")
    assert views.export(conn, state_root(repo))
    state = state_root(repo)
    assert Sprint.from_text((state / "sprints" / "S1.md").read_text()).id == "S1"
    assert (state / "knowledge" / "facts" / "KB-001-alpha-truth.md").is_file()
    assert (state / "knowledge" / "retired" / "KB-002-old-news.md").is_file()
    assert "Alpha truth" in (state / "knowledge" / "knowledge.md").read_text()
    assert "Old news" not in (state / "knowledge" / "knowledge.md").read_text()
    [row] = [json.loads(x) for x in (state / "knowledge" / "pending.jsonl").read_text().splitlines()]
    # the exact shape an older plugin's PendingFact(**row) accepts
    assert set(row) == {"id", "card", "statement", "tags", "source", "status", "reason"}


def test_retiring_a_fact_removes_its_live_view_file(repo):
    assert run(repo, "add-fact", "--statement", "Gone soon", "--source", "WF-1") == 0
    state = state_root(repo)
    assert list((state / "knowledge" / "facts").glob("KB-001-*"))
    assert run(repo, "retire-fact", "KB-001") == 0
    assert not list((state / "knowledge" / "facts").glob("KB-001-*"))
    assert list((state / "knowledge" / "retired").glob("KB-001-*"))


def test_unchanged_files_are_not_rewritten(repo):
    conn = db.connect(repo, migrate=False)
    save_sprint(conn, Sprint(id="S1"))
    views.export(conn, state_root(repo))
    f = state_root(repo) / "sprints" / "S1.md"
    os.utime(f, (1_000_000, 1_000_000))
    views.export(conn, state_root(repo))
    assert f.stat().st_mtime == 1_000_000


def test_a_failed_export_warns_and_never_raises(repo, capsys, monkeypatch):
    conn = db.connect(repo, migrate=False)
    save_sprint(conn, Sprint(id="S1"))
    monkeypatch.setattr(views, "_write_if_changed",
                        lambda *a: (_ for _ in ()).throw(OSError("read-only filesystem")))
    assert views.export(conn, state_root(repo)) is False
    assert "could not refresh" in capsys.readouterr().err


def test_a_verb_still_succeeds_when_the_views_cannot_be_written(repo, monkeypatch, capsys):
    monkeypatch.setattr(views, "_write_if_changed",
                        lambda *a: (_ for _ in ()).throw(OSError("read-only filesystem")))
    assert run(repo, "new-sprint", "S9", "--goal", "g") == 0
    assert db.connect(repo, migrate=False).execute("SELECT id FROM sprints").fetchone()[0] == "S9"


def test_hand_edits_to_a_view_file_are_overwritten_by_the_next_write(repo):
    assert run(repo, "new-sprint", "S1", "--goal", "real") == 0
    f = state_root(repo) / "sprints" / "S1.md"
    original = f.read_text()
    # an edit at the SAME mtime as the export is a hand edit to a generated file
    st = f.stat()
    f.write_text(original.replace("real", "hand-edited"))
    os.utime(f, (st.st_atime, st.st_mtime))
    conn = db.connect(repo, migrate=False)
    assert run(repo, "rollup-sprint", "S1") == 0
    assert "hand-edited" not in f.read_text()
    assert "hand-edited" not in conn.execute("SELECT body FROM sprints").fetchone()[0]


def test_reads_never_move_or_delete_anything(repo):
    state = state_root(repo)
    bad = state / "sprints" / "bad.md"
    bad.write_text("garbage")
    badfact = state / "knowledge" / "facts" / "KB-9-bad.md"
    badfact.parent.mkdir(parents=True, exist_ok=True)
    badfact.write_text("garbage")
    for verb in (["facts"], ["facts", "--stale"], ["facts", "--pending"], ["resume"]):
        assert run(repo, *verb) == 0
    assert bad.read_text() == "garbage" and badfact.read_text() == "garbage"
    assert not (state / "knowledge" / "corrupt").exists() or not list(
        (state / "knowledge" / "corrupt").iterdir())
