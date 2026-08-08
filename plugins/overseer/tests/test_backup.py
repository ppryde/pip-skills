import json, subprocess
from pathlib import Path
import pytest
from scripts import backup, db, config


def _init_git(root): subprocess.run(["git","init","-q"], cwd=root, check=True)


def _seed(repo, monkeypatch, *, with_knowledge=False):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(repo.parent / "cfg"))
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    monkeypatch.delenv("OVERSEER_DB", raising=False)
    central = config.central_root(repo)
    central.mkdir(parents=True, exist_ok=True)
    conn = db.connect(repo)
    from scripts.models import Card
    conn_card = Card(id="WF-001", title="First", status="planned",
                     touches=["a.py", "b.py"], depends_on=["WF-000"],
                     checklist=[{"task": "review", "subject": "impl", "status": "pending"}],
                     updated="2026-08-01T00:00:00")
    db.create_card(conn, conn_card)
    (central / "sprints").mkdir(exist_ok=True)
    (central / "sprints" / "sprint-1.md").write_text("---\nid: sprint-1\nstatus: active\n---\n")
    (central / "usage.jsonl").write_text('{"card":"WF-001","tokens":5}\n')
    if with_knowledge:
        (central / "knowledge").mkdir(exist_ok=True)
        (central / "knowledge" / "KB-001-x.md").write_text("# fact\n")
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


def test_backup_overwrite_reflects_current_state_and_leaves_no_old_dir(tmp_path, monkeypatch):
    """Regression test for the crash-unsafe rmtree-then-move implementation:
    backup_dir is a repeatedly-refreshed committed path, so running
    backup_board twice against the same dest (the overwrite path) is the
    PRIMARY case, not an edge case. The second run must succeed and its
    output must reflect the current DB/central state, and no `.old`
    staging leftover should linger once the run completes cleanly."""
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    central = _seed(repo, monkeypatch)
    backup.backup_board(repo)

    conn = db.connect(repo)
    from scripts.models import Card
    db.create_card(conn, Card(id="WF-002", title="Second", status="planned",
                               updated="2026-08-02T00:00:00"))

    summary = backup.backup_board(repo)
    dest = config.backup_dir(repo)
    cards = json.loads((dest / "cards.json").read_text())
    assert sorted(c["id"] for c in cards) == ["WF-001", "WF-002"]
    manifest = json.loads((dest / "manifest.json").read_text())
    assert manifest["cards"] == 2
    assert summary["cards"] == 2
    assert not dest.with_name(dest.name + ".old").exists()


def test_backup_manifest_fields(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    central = _seed(repo, monkeypatch)
    backup.backup_board(repo)
    manifest = json.loads((config.backup_dir(repo) / "manifest.json").read_text())
    assert manifest["sprint_files"] == 1
    assert manifest["usage_lines"] == 1
    assert manifest["repo_label"] == central.name


def test_backup_depends_on_and_checklist_round_trip_verbatim(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    _seed(repo, monkeypatch)
    backup.backup_board(repo)
    cards = json.loads((config.backup_dir(repo) / "cards.json").read_text())
    assert json.loads(cards[0]["depends_on"]) == ["WF-000"]
    assert json.loads(cards[0]["checklist"]) == [
        {"task": "review", "subject": "impl", "status": "pending"}
    ]


def test_backup_copies_knowledge_dir_and_counts_fact_files(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    _seed(repo, monkeypatch, with_knowledge=True)
    summary = backup.backup_board(repo)
    dest = config.backup_dir(repo)
    assert (dest / "knowledge" / "KB-001-x.md").exists()
    manifest = json.loads((dest / "manifest.json").read_text())
    assert manifest["fact_files"] == 1
    assert summary["fact_files"] == 1
