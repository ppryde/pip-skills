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
    # ledger regenerated (now empty of live cards)
    assert (state_root(repo) / "ledger.md").exists()


def test_clear_cards_noop_uses_cards_shape(tmp_path, capsys):
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    assert main(["--root", str(tmp_path), "clear", "--scope", "cards", "--yes", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["noop"] is True
    assert payload["backup_path"] is None
    assert payload["removed"] == {"cards": 0}
