import pytest

from scripts import db
from scripts.cli import main
from scripts.knowledge import load_facts
from scripts.pending import add_pending, load_pending, set_status


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    return tmp_path


def run(repo, *argv):
    return main(["--root", str(repo), *argv])


@pytest.fixture
def conn(repo):
    c = db.connect(repo, migrate=False)
    yield c
    c.close()


class TestQueue:
    def test_add_load_and_status(self, conn):
        f = add_pending(conn, "WF-001", "a fact", ["x"], "/d/r1-A.md")
        assert f.id.startswith("P-") and f.status == "pending"
        assert [p.statement for p in load_pending(conn)] == ["a fact"]
        set_status(conn, f.id, "rejected", "not durable")
        assert load_pending(conn)[0].reason == "not durable"
        with pytest.raises(ValueError, match="already rejected"):
            set_status(conn, f.id, "accepted")
        with pytest.raises(FileNotFoundError):
            set_status(conn, "P-nope", "accepted")

    def test_adjudication_is_conditional_so_a_race_has_one_winner(self, repo):
        a = db.connect(repo, migrate=False)
        b = db.connect(repo, migrate=False)
        f = add_pending(a, "WF-001", "x", [], "")
        set_status(a, f.id, "accepted")
        with pytest.raises(ValueError, match="already accepted"):
            set_status(b, f.id, "rejected", "late")
        assert load_pending(b)[0].status == "accepted"

    def test_an_add_during_another_connections_adjudication_is_not_lost(self, repo):
        a = db.connect(repo, migrate=False)
        b = db.connect(repo, migrate=False)
        first = add_pending(a, "WF-001", "one", [], "")
        with db.txn(a):
            set_status(a, first.id, "rejected", "r")
        add_pending(b, "WF-002", "two", [], "")
        assert [p.statement for p in load_pending(a)] == ["one", "two"]


class TestCli:
    def test_facts_pending_accept_reject(self, repo, conn, capsys):
        a = add_pending(conn, "WF-001", "keep me", ["t"], "/d/r1-A.md")
        b = add_pending(conn, "WF-002", "drop me", [], "/d/r1-B.md")
        capsys.readouterr()
        assert run(repo, "facts", "--pending", "--card", "WF-001") == 0
        assert capsys.readouterr().out.strip() == f"{a.id} WF-001 (t): keep me"
        assert run(repo, "accept-fact", a.id) == 0
        kb_id = capsys.readouterr().out.strip()
        facts, _ = load_facts(conn)
        assert [(x.id, x.statement, x.source) for x in facts] == [
            (kb_id, "keep me", "WF-001 /d/r1-A.md")]
        assert run(repo, "reject-fact", b.id, "--reason", "noise") == 0
        assert run(repo, "facts", "--pending", "--json") == 0
        capsys.readouterr()
        assert run(repo, "facts", "--pending") == 0
        assert capsys.readouterr().out.strip() == "No pending facts."

    def test_accept_fact_does_not_duplicate_on_reaccept_or_reject(self, repo, conn, capsys):
        a = add_pending(conn, "WF-001", "keep me", ["t"], "/d/r1-A.md")
        b = add_pending(conn, "WF-002", "drop me", [], "/d/r1-B.md")
        assert run(repo, "accept-fact", a.id) == 0
        capsys.readouterr()
        assert run(repo, "accept-fact", a.id) == 1
        facts, _ = load_facts(conn)
        assert len(facts) == 1

        assert run(repo, "reject-fact", b.id, "--reason", "noise") == 0
        assert run(repo, "accept-fact", b.id) == 1
        facts, _ = load_facts(conn)
        assert len(facts) == 1

    def test_set_section(self, repo, tmp_path):
        run(repo, "new-card", "--title", "T")
        plan = tmp_path / "plan.md"
        plan.write_text("## Chunks\n1. x")
        assert run(repo, "set-section", "WF-001", "--section", "Plan", "--file", str(plan)) == 0
        card = db.load_card(db.connect(repo, migrate=False), "WF-001")
        assert card.sections["## Plan"] == "### Chunks\n1. x"

    def test_set_section_text_needs_no_temp_file(self, repo):
        # Round 2 of WF-113: the orchestrator's one-call S-card brief no
        # longer has to shell out to a scratch file just to set ## Plan.
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-section", "WF-001", "--section", "Plan", "--text", "Just do X.") == 0
        card = db.load_card(db.connect(repo, migrate=False), "WF-001")
        assert card.sections["## Plan"] == "Just do X."

    def test_set_section_rejects_unknown_section(self, repo, tmp_path):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-section", "WF-001", "--section", "Goal", "--file", "x") == 1

    def test_set_section_requires_exactly_one_of_file_or_text(self, repo, capsys):
        run(repo, "new-card", "--title", "T")
        capsys.readouterr()
        assert run(repo, "set-section", "WF-001", "--section", "Plan") == 1
        assert "one of the arguments --file/--text-file --text is required" in capsys.readouterr().err
        capsys.readouterr()
        assert run(repo, "set-section", "WF-001", "--section", "Plan",
                   "--file", "x", "--text", "y") == 1
        assert "not allowed with argument" in capsys.readouterr().err
