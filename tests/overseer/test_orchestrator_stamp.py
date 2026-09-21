import pytest

from scripts import db
from scripts.cli import main


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    assert main(["--root", str(tmp_path), "new-card", "--title", "T"]) == 0
    return tmp_path


def run(repo, *argv):
    return main(["--root", str(repo), *argv])


def _orchestrated(repo, session="sess-1"):
    return [c.id for c in db.orchestrated_cards(db.connect(repo, migrate=False), session)]


@pytest.mark.parametrize("argv", [
    ("set-stage", "WF-001", "planning"),
    ("log-progress", "WF-001", "--note", "n", "--tokens", "1k"),
    ("log-review", "WF-001", "--stage", "plan-review", "--reviewers", "1", "--verdict", "ok"),
])
def test_work_verbs_stamp_calling_session(repo, monkeypatch, argv):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-1")
    assert run(repo, *argv) == 0
    assert _orchestrated(repo) == ["WF-001"]


def test_no_session_env_is_a_noop(repo):
    assert run(repo, "set-stage", "WF-001", "planning") == 0
    conn = db.connect(repo, migrate=False)
    assert conn.execute("SELECT COUNT(*) FROM orchestrators").fetchone()[0] == 0


@pytest.mark.parametrize("argv", [
    ("park", "WF-001"), ("unclaim", "WF-001"), ("release", "WF-001"),
    ("done", "WF-001"), ("abandon", "WF-001"),
])
def test_closing_verbs_clear_the_stamp(repo, monkeypatch, argv):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "sess-1")
    run(repo, "set-stage", "WF-001", "planning")
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID")
    assert run(repo, *argv) == 0
    conn = db.connect(repo, migrate=False)
    assert conn.execute("SELECT COUNT(*) FROM orchestrators").fetchone()[0] == 0


def test_release_unknown_card_fails(repo):
    assert run(repo, "release", "WF-404") == 1
