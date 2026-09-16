import pytest

from scripts import db
from scripts.cli import main
from scripts.knowledge import knowledge_root, load_facts
from scripts.pending import add_pending, load_pending, parse_learned, set_status


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    return tmp_path


def run(repo, *argv):
    return main(["--root", str(repo), *argv])


class TestParseLearned:
    def test_forms(self):
        text = (
            "findings...\n"
            "Learned: dbt builds need --target ci [tags: dbt, ci]\n"
            "- Learned: the ledger CLI is single-writer\n"
            "Learned: none\n"
            "Learned:   \n"
            "not Learned: inline mention\n"
        )
        assert parse_learned(text) == [
            ("dbt builds need --target ci", ["dbt", "ci"]),
            ("the ledger CLI is single-writer", []),
        ]


class TestQueue:
    def test_add_load_and_status(self, repo):
        f = add_pending(repo, "WF-001", "a fact", ["x"], "/d/r1-A.md")
        assert f.id.startswith("P-") and f.status == "pending"
        assert [p.statement for p in load_pending(repo)] == ["a fact"]
        set_status(repo, f.id, "rejected", "not durable")
        assert load_pending(repo)[0].reason == "not durable"
        with pytest.raises(ValueError, match="already rejected"):
            set_status(repo, f.id, "accepted")
        with pytest.raises(FileNotFoundError):
            set_status(repo, "P-nope", "accepted")

    def test_corrupt_line_is_skipped(self, repo):
        add_pending(repo, "WF-001", "ok", [], "")
        path = knowledge_root(repo) / "pending.jsonl"
        path.write_text(path.read_text() + "{broken\n")
        assert len(load_pending(repo)) == 1


class TestCli:
    def test_facts_pending_accept_reject(self, repo, capsys):
        a = add_pending(repo, "WF-001", "keep me", ["t"], "/d/r1-A.md")
        b = add_pending(repo, "WF-002", "drop me", [], "/d/r1-B.md")
        capsys.readouterr()
        assert run(repo, "facts", "--pending", "--card", "WF-001") == 0
        assert capsys.readouterr().out.strip() == f"{a.id} WF-001 (t): keep me"
        assert run(repo, "accept-fact", a.id) == 0
        kb_id = capsys.readouterr().out.strip()
        facts, _ = load_facts(knowledge_root(repo))
        assert [(x.id, x.statement, x.source) for x in facts] == [
            (kb_id, "keep me", "WF-001 /d/r1-A.md")]
        assert run(repo, "reject-fact", b.id, "--reason", "noise") == 0
        assert run(repo, "facts", "--pending", "--json") == 0
        capsys.readouterr()
        assert run(repo, "facts", "--pending") == 0
        assert capsys.readouterr().out.strip() == "No pending facts."

    def test_accept_fact_does_not_duplicate_on_reaccept_or_reject(self, repo, capsys):
        a = add_pending(repo, "WF-001", "keep me", ["t"], "/d/r1-A.md")
        b = add_pending(repo, "WF-002", "drop me", [], "/d/r1-B.md")
        assert run(repo, "accept-fact", a.id) == 0
        capsys.readouterr()
        assert run(repo, "accept-fact", a.id) == 1
        facts, _ = load_facts(knowledge_root(repo))
        assert len(facts) == 1

        assert run(repo, "reject-fact", b.id, "--reason", "noise") == 0
        assert run(repo, "accept-fact", b.id) == 1
        facts, _ = load_facts(knowledge_root(repo))
        assert len(facts) == 1

    def test_set_section(self, repo, tmp_path):
        run(repo, "new-card", "--title", "T")
        plan = tmp_path / "plan.md"
        plan.write_text("## Chunks\n1. x")
        assert run(repo, "set-section", "WF-001", "--section", "Plan", "--file", str(plan)) == 0
        card = db.load_card(db.connect(repo, migrate=False), "WF-001")
        assert card.sections["## Plan"] == "### Chunks\n1. x"

    def test_set_section_rejects_unknown_section(self, repo, tmp_path):
        run(repo, "new-card", "--title", "T")
        assert run(repo, "set-section", "WF-001", "--section", "Goal", "--file", "x") == 1
