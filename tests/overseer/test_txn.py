"""OL-9: every card write goes through one BEGIN IMMEDIATE transaction."""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest
from factories import git_init, make_card

from scripts import db
from scripts.cli import main

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "overseer"
SCRIPTS = PLUGIN / "scripts"


@pytest.fixture
def repo(tmp_path):
    git_init(tmp_path)
    assert main(["--root", str(tmp_path), "init"]) == 0
    assert main(["--root", str(tmp_path), "new-card", "--title", "T"]) == 0
    return tmp_path


def run(repo, *argv):
    return main(["--root", str(repo), *argv])


class TestTxn:
    def test_commits_on_success_and_rolls_back_on_error(self, board_conn):
        with db.txn(board_conn):
            board_conn.execute("INSERT INTO meta(key, value) VALUES('k', 'v')")
        assert db.get_meta(board_conn, "k") == "v"
        with pytest.raises(RuntimeError):
            with db.txn(board_conn):
                board_conn.execute("INSERT INTO meta(key, value) VALUES('k2', 'v')")
                raise RuntimeError("boom")
        assert db.get_meta(board_conn, "k2") is None

    def test_is_reentrant_and_only_the_outermost_commits(self, board_conn, tmp_path):
        other = db.connect(tmp_path, migrate=False)
        with db.txn(board_conn):
            with db.txn(board_conn):
                board_conn.execute("INSERT INTO meta(key, value) VALUES('inner', '1')")
            assert db.get_meta(other, "inner") is None  # inner exit did not commit
        assert db.get_meta(other, "inner") == "1"

    def test_a_second_writer_waits_for_the_first(self, board_conn, tmp_path):
        other = db.connect(tmp_path, migrate=False)
        other.execute("PRAGMA busy_timeout=100")
        with db.txn(board_conn):
            with pytest.raises(Exception, match="locked"):
                with db.txn(other):
                    pass  # pragma: no cover

    def test_put_card_refuses_to_run_outside_a_transaction(self, board_conn):
        with pytest.raises(RuntimeError, match="outside db.txn"):
            db.put_card(board_conn, make_card("WF-001"))

    def test_mutate_card_edit_abort_rolls_back_and_reraises(self, board_conn):
        db.create_card(board_conn, make_card("WF-001", title="before"))

        def change(card):
            card.title = "after"
            raise db.EditAbort("nope")

        with pytest.raises(db.EditAbort):
            db.mutate_card(board_conn, "WF-001", change)
        assert db.load_card(board_conn, "WF-001").title == "before"

    def test_mutate_card_keeps_or_sets_the_archived_flag(self, board_conn):
        db.create_card(board_conn, make_card("WF-001"))
        db.mutate_card(board_conn, "WF-001", lambda c: c.complete("t"), archive=True)
        assert board_conn.execute("SELECT archived FROM cards").fetchone()[0] == 1
        db.mutate_card(board_conn, "WF-001", lambda c: setattr(c, "pr", "x"))
        assert board_conn.execute("SELECT archived FROM cards").fetchone()[0] == 1

    def test_unknown_card_returns_none(self, board_conn):
        assert db.mutate_card(board_conn, "WF-404", lambda c: None) is None


def test_no_script_saves_a_card_it_loaded_in_another_transaction():
    """The write rule is mechanical: `save_card`/`archive_card` (whole-row upserts
    that commit on their own) are never called outside db.py; `put_card` is."""
    offenders = []
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.name == "db.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name in {"save_card", "archive_card", "_sync"}:
                    offenders.append(f"{path.name}:{node.lineno} {name}")
    assert offenders == []


_WORKER = """
import sys
sys.path.insert(0, {plugin!r})
from scripts.cli import main
kind, n, root = sys.argv[1], int(sys.argv[2]), sys.argv[3]
fail = 0
for i in range(n):
    if kind == "checklist":
        argv = ["checklist", "WF-001", "--task", f"t{{i}}", "--subject", "s", "--status", "pending"]
    elif kind == "progress":
        argv = ["log-progress", "WF-001", "--note", f"n{{i}}", "--tokens", "1"]
    else:
        argv = ["append-body", "WF-001", "Decisions", "--text", f"d{{i}}"]
    fail += main(["--root", root, *argv]) != 0
sys.exit(fail)
"""


def test_interleaved_edits_from_three_processes_all_survive(repo, tmp_path):
    """Before: every verb was load -> mutate -> whole-row save, so the later
    writer dropped the others' checklist/progress/decision edits."""
    script = tmp_path / "worker.py"
    script.write_text(_WORKER.format(plugin=str(PLUGIN)))
    env = dict(os.environ)  # the autouse fixture already pinned OVERSEER_*/CLAUDE_CONFIG_DIR
    n = 15
    procs = [
        subprocess.Popen([sys.executable, str(script), kind, str(n), str(repo)], env=env)
        for kind in ("checklist", "progress", "decisions")
    ]
    assert [p.wait(timeout=300) for p in procs] == [0, 0, 0]
    card = db.load_card(db.connect(repo, migrate=False), "WF-001")
    assert {e["task"] for e in card.checklist} == {f"t{i}" for i in range(n)}
    progress = card.sections["## Progress log"]
    assert all(f"n{i}" in progress for i in range(n))
    decisions = card.sections["## Decisions"]
    assert all(f"d{i}" in decisions for i in range(n))
    assert card.budget_actual == n


def test_the_hooks_use_the_same_path(repo):
    conn = db.connect(repo, migrate=False)
    from scripts.cli import _apply_checklist
    assert _apply_checklist(repo, "WF-001", "t1", "first", "pending") == 0
    assert _apply_checklist(repo, "WF-001", "t1", None, "completed") == 0
    assert _apply_checklist(repo, "WF-001", "t2", None, "pending") == 1   # new entry needs a subject
    assert db.load_card(conn, "WF-001").checklist == [
        {"task": "t1", "subject": "first", "status": "completed"}]


@pytest.mark.parametrize("argv,needle", [
    (["depends", "WF-001", "--on", "WF-001"], "cannot depend on itself"),
    (["set-field", "WF-001", "--priority", "bogus"], "unknown priority"),
    (["set-field", "WF-001", "--title", " "], "title cannot be empty"),
])
def test_a_refused_edit_changes_nothing(repo, capsys, argv, needle):
    conn = db.connect(repo, migrate=False)
    before = db.load_card(conn, "WF-001")
    capsys.readouterr()
    assert run(repo, *argv) == 1
    assert needle in capsys.readouterr().err
    assert db.load_card(conn, "WF-001") == before


def test_reorder_touches_only_the_order_column(repo):
    assert run(repo, "new-card", "--title", "U") == 0
    assert run(repo, "set-field", "WF-001", "--title", "renamed") == 0
    assert run(repo, "reorder", "--ids", "WF-002,WF-001") == 0
    conn = db.connect(repo, migrate=False)
    assert db.load_card(conn, "WF-002").order == 10
    assert db.load_card(conn, "WF-001").order == 20
    assert db.load_card(conn, "WF-001").title == "renamed"
    assert run(repo, "reorder", "--ids", "WF-001,WF-999") == 1


def test_pull_children_moves_every_child_in_one_transaction(repo):
    assert run(repo, "new-card", "--title", "kid") == 0
    assert run(repo, "set-field", "WF-002", "--parent", "WF-001") == 0
    assert run(repo, "set-stage", "WF-001", "planning") == 0
    assert run(repo, "pull-children", "WF-001") == 0
    conn = db.connect(repo, migrate=False)
    assert db.load_card(conn, "WF-002").stage == "planning"
