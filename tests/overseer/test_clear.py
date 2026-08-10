import json

import pytest

from scripts import config, db
from scripts.cli import main
from scripts.store import state_root


def run(repo, *argv: str) -> int:
    return main(["--root", str(repo), *argv])


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    return tmp_path


def test_clear_cards_deletes_all_cards_and_keeps_identity_meta(repo, capsys):
    run(repo, "new-card", "--title", "A")
    run(repo, "new-card", "--title", "B")
    conn = db.connect(repo, migrate=False)
    schema_before = db.get_meta(conn, "schema_version")
    repo_root_before = db.get_meta(conn, "repo_root")
    capsys.readouterr()  # discard new-card stdout so the clear JSON is isolated

    assert run(repo, "clear", "--scope", "cards", "--yes", "--json") == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "cards"
    assert payload["removed"]["cards"] == 2
    assert payload["backup_path"]  # a snapshot was taken

    conn = db.connect(repo, migrate=False)
    live, _ = db.load_live_cards(conn)
    assert live == []
    assert db.load_archived_cards(conn) == []
    # identity meta preserved
    assert db.get_meta(conn, "schema_version") == schema_before
    assert db.get_meta(conn, "repo_root") == repo_root_before
    # ledger.md is retired (WF-072) -- board.db (asserted above via
    # load_live_cards) is the source of truth, no generated file to check.
    assert not (state_root(repo) / "ledger.md").exists()


def test_clear_cards_noop_uses_cards_shape(tmp_path, capsys):
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    assert main(["--root", str(tmp_path), "clear", "--scope", "cards", "--yes", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["noop"] is True
    assert payload["backup_path"] is None
    assert payload["removed"] == {"cards": 0}


def test_clear_repo_removes_central_folder_after_backup(repo, capsys):
    run(repo, "new-card", "--title", "A")
    folder = config.central_root(repo)
    assert folder.exists()
    capsys.readouterr()  # discard new-card stdout so the clear JSON is isolated

    assert run(repo, "clear", "--scope", "repo", "--yes", "--json") == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "repo"
    assert payload["removed"]["existed"] is True
    assert payload["removed"]["folder"] == str(folder)
    assert payload["backup_path"]
    assert not folder.exists()


def test_clear_no_backup_skips_snapshot(repo, capsys):
    run(repo, "new-card", "--title", "A")
    capsys.readouterr()  # discard new-card stdout so the clear JSON is isolated
    assert run(repo, "clear", "--scope", "cards", "--yes", "--no-backup", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["backup_path"] is None


def test_clear_is_noop_when_no_board(tmp_path, capsys):
    # A repo root with NO overseer init -> no board.db.
    from factories import git_init
    git_init(tmp_path)
    assert main(["--root", str(tmp_path), "clear", "--scope", "repo", "--yes", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["noop"] is True
    assert payload["backup_path"] is None


def test_clear_aborts_wipe_when_backup_fails(repo, capsys, monkeypatch):
    run(repo, "new-card", "--title", "A")
    folder = config.central_root(repo)

    from scripts import backup
    def boom(*a, **k):
        raise OSError("read-only filesystem")
    monkeypatch.setattr(backup, "backup_board", boom)

    # main() maps OSError-family/ValueError to exit 1 with "error:" on stderr.
    capsys.readouterr()  # discard new-card stdout
    assert main(["--root", str(repo), "clear", "--scope", "repo", "--yes"]) == 1
    assert "error:" in capsys.readouterr().err
    assert folder.exists()  # wipe never happened
