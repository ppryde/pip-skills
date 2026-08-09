import json, os, shutil, subprocess, tempfile
from datetime import datetime
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
    # CLEAN display label, NOT the (hash-disambiguated) central folder name.
    from scripts.store import derive_repo_label
    assert manifest["repo_label"] == derive_repo_label(repo)
    plugin_json = Path(backup.__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json"
    assert manifest["overseer_version"] == json.loads(plugin_json.read_text())["version"]
    assert manifest["created"]
    datetime.strptime(manifest["created"], "%Y-%m-%dT%H:%M")  # raises if unparseable


def test_backup_manifest_repo_label_is_clean_when_folder_is_hashed(tmp_path, monkeypatch):
    """I2: even when the central folder is `<label>-<hash>`, the manifest's
    repo_label must be the CLEAN label, never the hashed folder name."""
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    central = _seed(repo, monkeypatch)
    # precondition: default resolution produced the hash-disambiguated folder
    assert "-" in central.name and central.name != "r"
    backup.backup_board(repo)
    manifest = json.loads((config.backup_dir(repo) / "manifest.json").read_text())
    assert manifest["repo_label"] == "r"
    assert manifest["repo_label"] != central.name


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


def test_restore_stamps_real_ledger_timestamp(tmp_path, monkeypatch):
    """Regression: rebuild_index used to be called with manifest.get("created", "")
    — a key backup_board never writes — leaving ledger.md's `Updated:` line
    blank after every restore. restore_board must stamp a real current
    timestamp in cli._now()'s "%Y-%m-%dT%H:%M" format instead."""
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    central = _seed(repo, monkeypatch)
    backup.backup_board(repo)
    shutil.rmtree(central)
    backup.restore_board(repo)
    from scripts.store import state_root
    ledger = (state_root(repo) / "ledger.md").read_text()
    first_line = ledger.splitlines()[1]
    assert first_line.startswith("Updated: ")
    stamp = first_line.removeprefix("Updated: ")
    assert stamp != ""
    # must parse as a real "%Y-%m-%dT%H:%M" timestamp, not a blank/garbage string
    from datetime import datetime
    datetime.strptime(stamp, "%Y-%m-%dT%H:%M")


def test_restore_replaces_when_backup_is_newer(tmp_path, monkeypatch):
    """Inverse of the LMW roundtrip test: when the LIVE card is older than
    the backup's copy, restore must replace it with the backup version and
    count it under "updated"."""
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    central = _seed(repo, monkeypatch)
    backup.backup_board(repo)  # captures WF-001 updated="2026-08-01T00:00:00"
    conn = db.connect(repo)
    from scripts.models import Card
    db.save_card(conn, Card(id="WF-001", title="Stale local edit", status="in-flight",
                             updated="2026-07-01T00:00:00"))  # older than the backup
    res = backup.restore_board(repo)
    conn = db.connect(repo)
    card = db.load_card(conn, "WF-001")
    assert card.title == "First"  # backup's newer copy wins
    assert card.updated == "2026-08-01T00:00:00"
    assert res["updated"] == 1


def test_backup_restore_round_trips_quarantined_corrupt_files(tmp_path, monkeypatch):
    """`archive/corrupt/` holds quarantined files that are unrecoverable
    elsewhere (migrate_workflow_to_central deliberately preserves them on
    disk for the same reason) — excluding them from backup/restore would
    make that guarantee inconsistent. A corrupt-quarantine file must
    round-trip: survive a backup, and be restored if the central folder is
    lost."""
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    central = _seed(repo, monkeypatch)
    (central / "archive" / "corrupt").mkdir(parents=True, exist_ok=True)
    (central / "archive" / "corrupt" / "WF-666-bad.md").write_text("not a valid card\n")

    backup.backup_board(repo)
    dest = config.backup_dir(repo)
    assert (dest / "archive" / "corrupt" / "WF-666-bad.md").read_text() == "not a valid card\n"

    shutil.rmtree(central)
    backup.restore_board(repo)
    assert (central / "archive" / "corrupt" / "WF-666-bad.md").read_text() == "not a valid card\n"


def test_restore_fill_gaps_leaves_existing_files_untouched(tmp_path, monkeypatch):
    """Partial loss: sprints/ survives locally (with local edits since the
    backup), usage.jsonl and knowledge/ are gone. Restore must leave the
    surviving file byte-for-byte untouched (files_skipped) and only fill in
    what's actually missing (files_restored)."""
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    central = _seed(repo, monkeypatch, with_knowledge=True)
    backup.backup_board(repo)

    local_content = "---\nid: sprint-1\nstatus: LOCAL-EDIT\n---\n"
    (central / "sprints" / "sprint-1.md").write_text(local_content)
    (central / "usage.jsonl").unlink()
    shutil.rmtree(central / "knowledge")

    res = backup.restore_board(repo)

    assert (central / "sprints" / "sprint-1.md").read_text() == local_content
    assert (central / "usage.jsonl").exists()
    assert (central / "knowledge" / "KB-001-x.md").exists()
    assert res["files_skipped"] == 1
    assert res["files_restored"] == 2


def test_restore_merges_meta_excluding_identity_keys(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    central = _seed(repo, monkeypatch)
    conn = db.connect(repo)
    db.set_meta(conn, "some_key", "v")
    conn.commit()
    backup.backup_board(repo)

    # tamper: inject an identity key into the backup's meta.json to prove
    # restore refuses to apply it even when present in the snapshot
    meta_path = config.backup_dir(repo) / "meta.json"
    meta = json.loads(meta_path.read_text())
    meta.append({"key": "repo_root", "value": "/tainted/from/backup"})
    meta_path.write_text(json.dumps(meta))

    shutil.rmtree(central)
    backup.restore_board(repo)
    conn = db.connect(repo)
    assert db.get_meta(conn, "some_key") == "v"          # non-identity key restored
    assert db.get_meta(conn, "repo_root") != "/tainted/from/backup"  # identity key not taken from backup


def test_restore_preserves_archived_flag(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    central = _seed(repo, monkeypatch)
    conn = db.connect(repo)
    from scripts.models import Card
    db.archive_card(conn, Card(id="WF-002", title="Done card", status="done",
                                updated="2026-08-02T00:00:00"))
    backup.backup_board(repo)
    shutil.rmtree(central)
    backup.restore_board(repo)
    conn = db.connect(repo)
    archived = db.load_archived_cards(conn)
    assert any(c.id == "WF-002" for c in archived)


def test_restore_refuses_corrupt_manifest(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    _seed(repo, monkeypatch); backup.backup_board(repo)
    (config.backup_dir(repo) / "manifest.json").write_text("{ not json")
    with pytest.raises(ValueError, match="manifest.json"):
        backup.restore_board(repo)


def test_restore_refuses_corrupt_meta(tmp_path, monkeypatch):
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    _seed(repo, monkeypatch); backup.backup_board(repo)
    (config.backup_dir(repo) / "meta.json").write_text("{ not json")
    with pytest.raises(ValueError, match="meta.json"):
        backup.restore_board(repo)


def test_restore_refuses_card_row_missing_id_with_clear_error(tmp_path, monkeypatch):
    """A cards.json row with no `id` key (hand-edited backup, truncated
    export) must raise a clear ValueError naming cards.json — not let a
    bare KeyError escape from `row["id"]`, matching the unknown-column
    guard's shape."""
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    _seed(repo, monkeypatch); backup.backup_board(repo)
    dest = config.backup_dir(repo)
    cards = json.loads((dest / "cards.json").read_text())
    del cards[0]["id"]
    (dest / "cards.json").write_text(json.dumps(cards))
    with pytest.raises(ValueError, match="cards.json"):
        backup.restore_board(repo)


def test_restore_refuses_unknown_card_column_with_clear_error(tmp_path, monkeypatch):
    """A cards.json row with a key that isn't a real `cards` table column
    (hand-edited backup, future/foreign schema, typo) must raise a clear
    ValueError naming cards.json — not let a raw sqlite OperationalError
    escape from the INSERT."""
    repo = tmp_path / "r"; repo.mkdir(); _init_git(repo)
    _seed(repo, monkeypatch); backup.backup_board(repo)
    dest = config.backup_dir(repo)
    cards = json.loads((dest / "cards.json").read_text())
    cards[0]["totally_not_a_real_column"] = "surprise"
    (dest / "cards.json").write_text(json.dumps(cards))
    with pytest.raises(ValueError, match="cards.json"):
        backup.restore_board(repo)
