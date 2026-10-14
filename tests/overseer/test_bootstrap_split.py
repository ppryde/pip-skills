"""WF-300 C1: `bootstrap` split into git-free `bootstrap-begin` / `bootstrap-finish`.

A `--remote` client runs the git half itself (`remote_git`), so the host needs the
board halves as verbs of their own. begin + finish + a local worktree == `bootstrap`.
"""
import json
import subprocess

import pytest
from factories import git_init

from scripts import db
from scripts.cli import main


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    git_init(root)
    (root / "a.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=root, check=True)
    assert main(["--root", str(root), "init"]) == 0
    return root


def _card(repo, card_id="WF-001"):
    return db.load_card(db.connect(repo, migrate=False), card_id)


def _begin(repo, capsys, *extra):
    capsys.readouterr()
    rc = main(["--root", str(repo), "bootstrap-begin", *extra])
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_begin_creates_card_at_bootstrap_and_prints_json(repo, capsys):
    rc, out, _ = _begin(repo, capsys, "--title", "Add the Thing!", "--complexity", "S")
    assert rc == 0
    assert json.loads(out) == {"v": 1, "id": "WF-001", "branch": "feat/WF-001-add-the-thing"}
    card = _card(repo)
    assert (card.stage, card.branch, card.worktree) == ("bootstrap", None, None)


def test_begin_is_idempotent_on_a_card_at_bootstrap(repo, capsys):
    main(["--root", str(repo), "new-card", "--title", "T"])
    first = _begin(repo, capsys, "--card", "WF-001", "--type", "fix", "--slug", "s")
    second = _begin(repo, capsys, "--card", "WF-001", "--type", "fix", "--slug", "s")
    assert first[:2] == second[:2] == (0, '{"v": 1, "id": "WF-001", "branch": "fix/WF-001-s"}\n')
    assert _card(repo).stage == "bootstrap"


def test_begin_duplicate_jira_id_is_refused(repo, capsys):
    assert _begin(repo, capsys, "--title", "T", "--jira", "ABC-1")[0] == 0
    rc, _, err = _begin(repo, capsys, "--title", "T", "--jira", "ABC-1")
    assert rc == 1 and "card already exists" in err


def test_begin_needs_title_or_card(repo, capsys):
    rc, _, err = _begin(repo, capsys)
    assert rc == 1 and "needs --title" in err


def test_begin_has_no_file_option(repo, capsys):
    rc, _, _ = _begin(repo, capsys, "--title", "T", "--brief-file", "x")
    assert rc == 1  # argparse refuses the unknown option
    assert db.load_card(db.connect(repo, migrate=False), "WF-001") is None


def test_begin_brief_gate_refusal_creates_nothing(repo, capsys, monkeypatch):
    monkeypatch.setenv("OVERSEER_GATES", "hard")
    rc, _, err = _begin(repo, capsys, "--title", "T", "--complexity", "M", "--brief", "plan")
    assert rc == 3 and "GATE" in err
    assert db.load_card(db.connect(repo, migrate=False), "WF-001") is None


def test_begin_reads_brief_dash_from_stdin(repo, capsys, monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("the plan\n"))
    rc, _, _ = _begin(repo, capsys, "--title", "T", "--complexity", "S", "--brief", "-")
    assert rc == 0


def _finish(repo, capsys, *extra):
    capsys.readouterr()
    rc = main(["--root", str(repo), "bootstrap-finish", "WF-001", *extra])
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_finish_records_state_and_lands_at_planning(repo, capsys):
    _begin(repo, capsys, "--title", "T")
    rc, out, _ = _finish(repo, capsys, "--branch", "feat/WF-001-t", "--worktree", "/c/wt", "--base", "main")
    assert rc == 0
    assert out.strip() == "WF-001 planning · feat/WF-001-t · /c/wt (base main)"
    card = _card(repo)
    assert (card.stage, card.branch, card.worktree) == ("planning", "feat/WF-001-t", "/c/wt")


def test_finish_with_brief_lands_at_implementation(repo, capsys, monkeypatch):
    import io
    _begin(repo, capsys, "--title", "T", "--complexity", "S")
    monkeypatch.setattr("sys.stdin", io.StringIO("Fix it.\n"))
    rc, out, _ = _finish(repo, capsys, "--branch", "b", "--worktree", "/w", "--brief", "-")
    assert rc == 0 and "implementation" in out
    card = _card(repo)
    assert card.stage == "implementation" and card.sections["## Plan"] == "Fix it."


@pytest.mark.parametrize("stage", ["planning", "implementation"])
def test_finish_refused_when_card_is_past_bootstrap(repo, capsys, stage):
    _begin(repo, capsys, "--title", "T")
    main(["--root", str(repo), "set-stage", "WF-001", stage, "--force-gate", "user: test"])
    before = _card(repo)
    rc, _, err = _finish(repo, capsys, "--branch", "b", "--worktree", "/w")
    assert rc == 1 and f"is at {stage}" in err
    after = _card(repo)
    assert (after.stage, after.branch, after.worktree, after.sections) == (
        before.stage, before.branch, before.worktree, before.sections)


def test_finish_refused_with_different_branch_or_worktree_and_equal_rerun_ok(repo, capsys):
    _begin(repo, capsys, "--title", "T")
    # branch/worktree recorded while still at bootstrap (e.g. an interrupted earlier finish)
    main(["--root", str(repo), "set-field", "WF-001", "--branch", "b", "--worktree", "/w"])
    rc, _, err = _finish(repo, capsys, "--branch", "other", "--worktree", "/w")
    assert rc == 1 and "already set to b / /w" in err
    assert _card(repo).stage == "bootstrap"
    assert _finish(repo, capsys, "--branch", "b", "--worktree", "/w")[0] == 0
    assert _card(repo).stage == "planning"


def test_begin_then_finish_equals_local_bootstrap_state(repo, tmp_path, capsys):
    local = tmp_path / "wt"
    cfg = repo / ".overseer" / "config.local.json"
    cfg.write_text(json.dumps({"worktree_dir": str(local)}))
    assert main(["--root", str(repo), "bootstrap", "--title", "Same"]) == 0
    whole = _card(repo)
    _begin(repo, capsys, "--title", "Same")
    rc, _, _ = _finish_for(repo, capsys, "WF-002", "--branch", "feat/WF-002-same",
                           "--worktree", str(local / "proj-wf-002"))
    split = _card(repo, "WF-002")
    assert rc == 0
    assert (split.stage, split.status, split.branch.replace("002", "001"),
            split.worktree.replace("002", "001")) == (
        whole.stage, whole.status, whole.branch, whole.worktree)


def _finish_for(repo, capsys, card_id, *extra):
    capsys.readouterr()
    rc = main(["--root", str(repo), "bootstrap-finish", card_id, *extra])
    out = capsys.readouterr()
    return rc, out.out, out.err
