import re
import subprocess
from pathlib import Path

import pytest
from factories import git_init

from scripts import bundle, db
from scripts.cli import main
from scripts.dispatch import dispatch_dir
from scripts.knowledge import Fact, ensure_kb, knowledge_root, save_fact

TEMPLATES = bundle.TEMPLATES_DIR


def _git(path, *argv):
    subprocess.run(["git", *argv], cwd=path, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git_init(tmp_path)
    (tmp_path / "a.txt").write_text("one\n")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "feat/x")
    (tmp_path / "a.txt").write_text("one\ntwo\n")
    _git(tmp_path, "commit", "-qam", "change")
    assert main(["--root", str(tmp_path), "init"]) == 0
    assert main(["--root", str(tmp_path), "new-card", "--title", "T", "--goal", "Ship it",
                 "--labels", "dbt"]) == 0
    conn = db.connect(tmp_path, migrate=False)
    card = db.load_card(conn, "WF-001")
    card.worktree = str(tmp_path)
    card.set_section("## Plan", "1. chunk one", "t")
    db.save_card(conn, card)
    kb = knowledge_root(tmp_path)
    ensure_kb(kb)
    save_fact(kb, Fact(id="KB-001", statement="dbt needs --target ci", tags=["dbt"],
                       created="2026-09-01", verified="2026-09-01"))
    save_fact(kb, Fact(id="KB-002", statement="unrelated", tags=["web"],
                       created="2026-09-01", verified="2026-09-01"))
    return tmp_path


def _prep(repo, capsys, *argv):
    capsys.readouterr()
    code = main(["--root", str(repo), "dispatch-prep", "WF-001", *argv])
    out = capsys.readouterr()
    return code, out.out.strip(), out.err


def test_every_template_placeholder_is_supplied():
    known = set(bundle.KNOWN_PLACEHOLDERS)
    for role in ("planner", "implementer", "reviewer", "fixer", "verifier"):
        found = set(re.findall(r"\{\{(\w+)\}\}", (TEMPLATES / f"{role}.md").read_text()))
        assert found <= known, (role, found - known)


def test_reviewer_impl_review_bundle(repo, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-1")
    code, out, _ = _prep(repo, capsys, "--stage", "impl-review", "--role", "reviewer",
                         "--slot", "A", "--lens", "correctness")
    assert code == 0
    d = dispatch_dir(repo, "WF-001", "impl-review")
    assert out == str(d / "bundle-reviewer-A-r1.md")
    text = (d / "bundle-reviewer-A-r1.md").read_text()
    assert str(d / "r1-A.md") in text and str(d / "diff.patch") in text
    assert "correctness" in text and "Ship it" in text and bundle.TERSE_CHARTER in text
    assert "dbt needs --target ci" in text and "unrelated" not in text
    assert "+two" in (d / "diff.patch").read_text()
    assert "{{" not in text
    assert [c.id for c in db.orchestrated_cards(db.connect(repo, migrate=False), "sess-1")] == ["WF-001"]


def test_round_two_lists_prior_verdicts_and_fix_reports(repo, capsys):
    d = dispatch_dir(repo, "WF-001", "impl-review")
    d.mkdir(parents=True)
    for name in ("r1-A.md", "r1-B.md", "r1-fix.md"):
        (d / name).write_text("x")
    _, _out, _ = _prep(repo, capsys, "--stage", "impl-review", "--role", "reviewer",
                       "--slot", "A", "--round", "2")
    text = (d / "bundle-reviewer-A-r2.md").read_text()
    assert all(str(d / n) in text for n in ("r1-A.md", "r1-B.md", "r1-fix.md"))


def test_fixer_gets_this_rounds_verdicts_only(repo, capsys):
    d = dispatch_dir(repo, "WF-001", "impl-review")
    d.mkdir(parents=True)
    for name in ("r1-A.md", "r2-A.md", "r2-B.md"):
        (d / name).write_text("x")
    _prep(repo, capsys, "--stage", "impl-review", "--role", "fixer", "--round", "2",
          "--var", "gate_commands=pytest -q")
    text = (d / "bundle-fixer-r2.md").read_text()
    assert str(d / "r2-A.md") in text and str(d / "r2-B.md") in text
    assert str(d / "r1-A.md") not in text and "pytest -q" in text
    assert str(d / "r2-fix.md") in text


def test_plan_review_snapshots_the_plan(repo, capsys):
    _prep(repo, capsys, "--stage", "plan-review", "--role", "reviewer", "--slot", "A")
    d = dispatch_dir(repo, "WF-001", "plan-review")
    assert (d / "plan.snapshot.md").read_text() == "1. chunk one"


def test_verbosity_normal_drops_charter(repo, capsys):
    (repo / ".overseer").mkdir(exist_ok=True)
    (repo / ".overseer" / "config.local.json").write_text('{"verbosity": "normal"}')
    _, out, _ = _prep(repo, capsys, "--stage", "implementation", "--role", "implementer",
                      "--chunk", "1")
    assert bundle.TERSE_CHARTER not in Path(out).read_text()


@pytest.mark.parametrize("argv, message", [
    (("--stage", "impl-review", "--role", "reviewer"), "--slot is required"),
    (("--stage", "impl-review", "--role", "reviewer", "--slot", "fix"), "reserved"),
    (("--stage", "implementation", "--role", "implementer"), "--chunk is required"),
    (("--stage", "implementation", "--role", "implementer", "--chunk", "1",
      "--var", "constraints=" + "x" * 301), "cap 300"),
    (("--stage", "implementation", "--role", "implementer", "--chunk", "1",
      "--var", "novalue"), "key=value"),
])
def test_errors(repo, capsys, argv, message):
    code, _, err = _prep(repo, capsys, *argv)
    assert code == 1 and message in err


def test_reply_names():
    assert bundle.reply_name("planner", round_no=1, slot=None, chunk=None) == "plan.md"
    assert bundle.reply_name("verifier", round_no=1, slot=None, chunk=None) == "verification.md"
    assert bundle.reply_name("implementer", round_no=1, slot=None, chunk=3) == "c3.md"
    assert bundle.reply_name("fixer", round_no=2, slot=None, chunk=None) == "r2-fix.md"
