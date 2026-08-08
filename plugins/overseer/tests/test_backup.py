import json, os, shutil, subprocess, tempfile
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


def _make_staged(tmp_path, marker):
    staged = Path(tempfile.mkdtemp(dir=tmp_path))
    (staged / "manifest.json").write_text(json.dumps({"marker": marker}))
    return staged


def test_atomic_replace_dir_recovers_from_crash_mid_swap(tmp_path):
    """Fix round 2, recovery-on-entry: on-disk state {dest absent,
    dest.old present} is what a PRIOR run leaves behind if it was hard-
    killed right after `os.replace(dest, old)` but before
    `os.replace(staged, dest)` — `old` is the recovery snapshot, not stale
    garbage. A fresh call must recover cleanly: swap the new staged
    content into `dest` and leave no `.old` lingering."""
    dest = tmp_path / "backups"
    old = dest.with_name(dest.name + ".old")
    old.mkdir()
    (old / "manifest.json").write_text(json.dumps({"marker": "recovery-snapshot"}))
    assert not dest.exists()

    staged = _make_staged(tmp_path, "new-snapshot")
    backup._atomic_replace_dir(staged, dest)

    assert dest.exists()
    assert json.loads((dest / "manifest.json").read_text())["marker"] == "new-snapshot"
    assert not old.exists()


def test_atomic_replace_dir_survives_crash_during_retry_swap(tmp_path, monkeypatch):
    """Fix round 2, crash-during-retry — the exact scenario the reviewer
    reproduced: recovery state {dest absent, old present with the last
    good snapshot}, and the retry's own staged->dest swap ALSO fails (disk
    full, lock, etc). The old (round-1) implementation unconditionally
    rmtree'd `old` on entry whenever it existed, so by the time the swap
    failed there was nothing left to roll back to -> total loss. The fix
    only treats `old` as disposable once `dest` exists again (i.e. a swap
    has actually completed), so a failed retry must still leave a complete
    snapshot in place (restored from `old`) rather than losing everything."""
    dest = tmp_path / "backups"
    old = dest.with_name(dest.name + ".old")
    old.mkdir()
    (old / "manifest.json").write_text(json.dumps({"marker": "recovery-snapshot"}))
    assert not dest.exists()

    staged = _make_staged(tmp_path, "new-snapshot")

    real_replace = os.replace

    def flaky_replace(src, dst):
        if Path(src) == staged:
            raise OSError("simulated disk full")
        return real_replace(src, dst)

    monkeypatch.setattr(backup.os, "replace", flaky_replace)

    with pytest.raises(OSError):
        backup._atomic_replace_dir(staged, dest)

    # Not total loss: a complete snapshot must exist after the failed retry.
    assert dest.exists()
    assert json.loads((dest / "manifest.json").read_text())["marker"] == "recovery-snapshot"


def test_restore_roundtrip_and_lmw(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    central = _seed(repo, monkeypatch)
    backup.backup_board(repo)
    # mutate live: bump WF-001 to older-in-backup vs newer-in-db scenarios
    conn = db.connect(repo)
    from scripts.models import Card
    # a newer local edit than the backup -> restore must NOT clobber it
    db.save_card(conn, Card(id="WF-001", title="Edited later", status="in-flight",
                            updated="2026-09-01T00:00:00"))
    res = backup.restore_board(repo)
    conn = db.connect(repo)
    card = db.load_card(conn, "WF-001")
    assert card.title == "Edited later"          # local newer kept
    assert res["skipped_older"] == 1


def test_restore_inserts_missing_and_fills_files(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    central = _seed(repo, monkeypatch)
    backup.backup_board(repo)
    # wipe central entirely (simulate fresh clone / lost board)
    shutil.rmtree(central)
    res = backup.restore_board(repo)
    conn = db.connect(repo)
    assert db.load_card(conn, "WF-001") is not None
    assert (config.central_root(repo) / "sprints" / "sprint-1.md").exists()
    assert res["inserted"] == 1


def test_restore_refuses_schema_mismatch(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    _seed(repo, monkeypatch); backup.backup_board(repo)
    man = config.backup_dir(repo) / "manifest.json"
    m = json.loads(man.read_text()); m["schema_version"] = 999
    man.write_text(json.dumps(m))
    with pytest.raises(ValueError, match="schema"):
        backup.restore_board(repo)


def test_restore_corrupt_cards_is_loud(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    _seed(repo, monkeypatch); backup.backup_board(repo)
    (config.backup_dir(repo) / "cards.json").write_text("{ not json")
    with pytest.raises(ValueError, match="cards.json"):
        backup.restore_board(repo)
