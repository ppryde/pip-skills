"""WF-280: the ``next`` verb and ``dispatch-prep --panel``."""
import re
import subprocess

import pytest
from factories import git_init

from scripts import db
from scripts.cli import main
from scripts.store import state_root


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    git_init(root)
    (root / "a.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    assert main(["--root", str(root), "init"]) == 0
    return root


def run(repo, *argv):
    return main(["--root", str(repo), *argv])


def card_at(repo, stage, complexity="M", plan="1. do it"):
    run(repo, "new-card", "--title", "T", "--complexity", complexity)
    run(repo, "set-section", "WF-001", "--section", "Plan", "--text", plan)
    run(repo, "set-stage", "WF-001", stage)


class TestNextVerb:
    def test_prints_exactly_one_line(self, repo, capsys):
        card_at(repo, "plan-review")
        capsys.readouterr()
        assert run(repo, "next", "WF-001") == 0
        text = capsys.readouterr().out
        assert text.count("\n") == 1
        assert text.startswith("WF-001 plan-review: no reviewers dispatched (cap 3) · next: ")
        assert "--role reviewer --panel --round 1" in text

    def test_reads_the_recorded_verdicts(self, repo, capsys):
        card_at(repo, "plan-review")
        run(repo, "dispatch-prep", "WF-001", "--stage", "plan-review", "--role", "reviewer",
            "--panel", "--round", "1")
        conn = db.connect(repo, migrate=False)
        with db.txn(conn):
            db.record_evidence_once(conn, "WF-001", "plan-review", "review", round_no=1, slot="A",
                                    status="approved", critical=0, important=0, minor=0, ts="t")
            db.record_evidence_once(conn, "WF-001", "plan-review", "review", round_no=1, slot="B",
                                    status="found wanting", critical=0, important=2, minor=0, ts="t")
        conn.close()
        capsys.readouterr()
        run(repo, "next", "WF-001")
        text = capsys.readouterr().out
        assert "plan-review r1: A approved, B found wanting 0C/2I (cap 3)" in text
        assert "--role fixer --round 1 → overseer:overseer-fixer sonnet" in text

    def test_unknown_card(self, repo, capsys):
        assert run(repo, "next", "WF-404") == 1
        assert "WF-404" in capsys.readouterr().err

    def test_it_writes_nothing(self, repo, capsys):
        card_at(repo, "planning")
        before = db.connect(repo, migrate=False).execute("SELECT updated FROM cards").fetchall()
        run(repo, "next", "WF-001")
        assert db.connect(repo, migrate=False).execute("SELECT updated FROM cards").fetchall() == before

    def test_help_lists_it(self, repo, capsys):
        run(repo, "help", "next")
        assert capsys.readouterr().out.strip() == "next <card-id>"


class TestPanel:
    def test_m_panel_writes_two_bundles_and_prints_agent_model_path(self, repo, capsys):
        card_at(repo, "plan-review")
        capsys.readouterr()
        assert run(repo, "dispatch-prep", "WF-001", "--stage", "plan-review", "--role", "reviewer",
                   "--panel", "--round", "1") == 0
        lines = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 2
        paths = []
        for line, slot in zip(lines, "AB"):
            agent, model, path = line.split(" ", 2)
            assert (agent, model) == ("overseer:overseer-reviewer", "sonnet")
            assert path.endswith(f"bundle-reviewer-{slot}-r1.md")
            text = open(path).read()
            assert f"{slot}" in text
            paths.append(path)
        assert "correctness" in open(paths[0]).read() and "spec-compliance" in open(paths[1]).read()

    def test_every_slot_gets_a_dispatch_row_so_a_crashed_one_blocks_the_gate(self, repo):
        card_at(repo, "plan-review")
        run(repo, "dispatch-prep", "WF-001", "--stage", "plan-review", "--role", "reviewer",
            "--panel", "--round", "1")
        rows = db.evidence_for(db.connect(repo, migrate=False), "WF-001")
        assert sorted(e.slot for e in rows if e.kind == "dispatch") == ["A", "B"]

    def test_an_s_card_gets_a_panel_of_one(self, repo, capsys):
        card_at(repo, "plan-review", complexity="S")
        capsys.readouterr()
        run(repo, "dispatch-prep", "WF-001", "--stage", "plan-review", "--role", "reviewer",
            "--panel", "--round", "1")
        assert len(capsys.readouterr().out.strip().splitlines()) == 1

    def test_an_l_card_round_one_has_a_strong_slot_a(self, repo, capsys):
        card_at(repo, "plan-review", complexity="L")
        capsys.readouterr()
        run(repo, "dispatch-prep", "WF-001", "--stage", "plan-review", "--role", "reviewer",
            "--panel", "--round", "1")
        models = [ln.split(" ")[1] for ln in capsys.readouterr().out.strip().splitlines()]
        assert models == ["opus", "sonnet", "sonnet"]

    def test_advance_moves_the_stage_first(self, repo, capsys):
        card_at(repo, "planning")
        capsys.readouterr()
        assert run(repo, "dispatch-prep", "WF-001", "--stage", "plan-review", "--role", "reviewer",
                   "--panel", "--round", "1", "--advance") == 0
        assert db.load_card(db.connect(repo, migrate=False), "WF-001").stage == "plan-review"

    def test_without_panel_the_output_is_still_only_the_path(self, repo, capsys):
        card_at(repo, "plan-review")
        capsys.readouterr()
        run(repo, "dispatch-prep", "WF-001", "--stage", "plan-review", "--role", "reviewer",
            "--slot", "A", "--round", "1")
        out = capsys.readouterr().out.strip()
        assert re.fullmatch(r"/\S+bundle-reviewer-A-r1\.md", out)

    @pytest.mark.parametrize("extra,msg", [
        (["--role", "fixer"], "reviewer"),
        (["--role", "reviewer", "--slot", "A"], "--slot"),
        (["--role", "reviewer", "--lens", "x"], "--lens"),
    ])
    def test_misuse_is_refused_before_anything_is_written(self, repo, capsys, extra, msg):
        card_at(repo, "plan-review")
        capsys.readouterr()
        assert run(repo, "dispatch-prep", "WF-001", "--stage", "plan-review", "--panel", *extra) == 1
        assert msg in capsys.readouterr().err
        assert not db.evidence_for(db.connect(repo, migrate=False), "WF-001")

    def test_panel_outside_a_review_stage_is_refused(self, repo, capsys):
        card_at(repo, "planning")
        capsys.readouterr()
        assert run(repo, "dispatch-prep", "WF-001", "--stage", "implementation", "--role",
                   "reviewer", "--panel") == 1
        assert "review stage" in capsys.readouterr().err

    def test_the_round_cap_gate_still_applies(self, repo, monkeypatch, capsys):
        monkeypatch.setenv("OVERSEER_GATES", "hard")
        card_at(repo, "plan-review", complexity="S")
        capsys.readouterr()
        rc = run(repo, "dispatch-prep", "WF-001", "--stage", "plan-review", "--role", "reviewer",
                 "--panel", "--round", "3")
        assert rc == 3 and "GATE" in capsys.readouterr().err
