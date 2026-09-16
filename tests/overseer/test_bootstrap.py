import json
import subprocess

import pytest
from factories import git_init

from scripts import db
from scripts.cli import main, worktree_path


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
    local_path = root / ".overseer" / "config.local.json"
    local_config = json.loads(local_path.read_text() or "{}")
    local_config["worktree_dir"] = str(tmp_path / "wt")
    local_path.write_text(json.dumps(local_config))
    return root


def test_worktree_path_default_and_config(tmp_path):
    assert worktree_path(tmp_path / "proj", "WF-12", {}) == tmp_path / "proj-wf-12"
    assert worktree_path(tmp_path / "proj", "WF-12", {"worktree_dir": "/w"}).as_posix() == "/w/proj-wf-12"


def test_new_card_bootstrap(repo, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-1")
    capsys.readouterr()
    assert main(["--root", str(repo), "bootstrap", "--title", "Add the Thing!",
                 "--complexity", "S"]) == 0
    path = tmp_path / "wt" / "proj-wf-001"
    assert capsys.readouterr().out.strip() == (
        f"WF-001 planning · feat/WF-001-add-the-thing · {path} (base main)")
    conn = db.connect(repo, migrate=False)
    card = db.load_card(conn, "WF-001")
    assert (card.stage, card.status, card.branch, card.worktree, card.complexity) == (
        "planning", "in-flight", "feat/WF-001-add-the-thing", str(path), "S")
    head = subprocess.run(["git", "branch", "--show-current"], cwd=path,
                          capture_output=True, text=True, check=False).stdout.strip()
    assert head == "feat/WF-001-add-the-thing"
    assert [c.id for c in db.orchestrated_cards(conn, "sess-1")] == ["WF-001"]


def test_existing_card_and_custom_type_slug(repo, tmp_path, capsys):
    main(["--root", str(repo), "new-card", "--title", "T"])
    assert main(["--root", str(repo), "bootstrap", "--card", "WF-001",
                 "--type", "fix", "--slug", "short"]) == 0
    assert db.load_card(db.connect(repo, migrate=False), "WF-001").branch == "fix/WF-001-short"


def test_worktree_failure_leaves_card_at_bootstrap(repo, capsys):
    subprocess.run(["git", "branch", "feat/WF-001-t"], cwd=repo, check=True)
    capsys.readouterr()
    assert main(["--root", str(repo), "bootstrap", "--title", "T"]) == 1
    assert "error:" in capsys.readouterr().err
    card = db.load_card(db.connect(repo, migrate=False), "WF-001")
    assert (card.stage, card.branch) == ("bootstrap", None)


def test_title_or_card_required(repo):
    assert main(["--root", str(repo), "bootstrap"]) == 1
