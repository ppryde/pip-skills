import json, subprocess
from pathlib import Path
import pytest
from scripts import backup, db, config


def _init_git(root): subprocess.run(["git","init","-q"], cwd=root, check=True)


def _seed(repo, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(repo.parent / "cfg"))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    monkeypatch.delenv("OVERSEER_DB", raising=False)
    central = config.central_root(repo)
    central.mkdir(parents=True, exist_ok=True)
    conn = db.connect(repo)
    from scripts.models import Card
    conn_card = Card(id="WF-001", title="First", status="planned",
                     touches=["a.py", "b.py"], updated="2026-08-01T00:00:00")
    db.create_card(conn, conn_card)
    (central / "sprints").mkdir(exist_ok=True)
    (central / "sprints" / "sprint-1.md").write_text("---\nid: sprint-1\nstatus: active\n---\n")
    (central / "usage.jsonl").write_text('{"card":"WF-001","tokens":5}\n')
    return central


def test_backup_writes_json_and_copies_state(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    _seed(repo, monkeypatch)
    summary = backup.backup_board(repo)
    dest = config.backup_dir(repo)
    cards = json.loads((dest / "cards.json").read_text())
    assert [c["id"] for c in cards] == ["WF-001"]
    # lossless JSON column: touches copied verbatim as its stored TEXT
    assert json.loads(cards[0]["touches"]) == ["a.py", "b.py"]
    assert (dest / "sprints" / "sprint-1.md").exists()
    assert (dest / "usage.jsonl").exists()
    manifest = json.loads((dest / "manifest.json").read_text())
    assert manifest["schema_version"] == db.SCHEMA_VERSION
    assert summary["cards"] == 1


def test_backup_excludes_identity_meta(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    _seed(repo, monkeypatch)
    backup.backup_board(repo)
    meta = json.loads((config.backup_dir(repo) / "meta.json").read_text())
    keys = {m["key"] for m in meta}
    assert not (keys & backup.IDENTITY_META_KEYS)
