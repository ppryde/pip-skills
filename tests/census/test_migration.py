import json
import os
import time

from scripts import store as st

V1 = {
    "version": 1,
    "limits": {"five_hour": {"used_percentage": 55, "resets_at": 9_000}, "updated_at": 100},
    "sessions": {
        "s1": {"worktree_cwd": "/wt/a", "updated_at": 100.0, "active_at": 90.0,
               "branch": "main", "payload": {"session_id": "s1"}},
        "../evil": {"worktree_cwd": "/x", "updated_at": 100.0, "payload": {}},
    },
}


def _write_v1(store_file, data=V1):
    store_file.parent.mkdir(parents=True, exist_ok=True)
    store_file.write_text(json.dumps(data))
    (store_file.parent / "status.json.lock").write_text("")
    (store_file.parent / ".status.abc.tmp").write_text("")


class TestMigrate:
    def test_splits_v1_and_retires_it(self, store_file):
        _write_v1(store_file)
        assert st.migrate(now=200.0) is True
        assert not store_file.exists()
        assert (store_file.parent / "status.json.v1-migrated").exists()
        assert not (store_file.parent / "status.json.lock").exists()
        assert not (store_file.parent / ".status.abc.tmp").exists()
        view = st.read_all()
        assert set(view["sessions"]) == {"s1"}          # unsafe id dropped
        assert view["sessions"]["s1"]["branch"] == "main"
        assert view["limits"]["five_hour"]["used_percentage"] == 55

    def test_second_run_is_a_noop(self, store_file):
        _write_v1(store_file)
        assert st.migrate(now=200.0) is True
        assert st.migrate(now=201.0) is False

    def test_newer_v2_file_is_not_overwritten(self, store_file):
        st.ingest(json.dumps({"session_id": "s1", "cwd": "/wt/new"}), now=500.0)
        _write_v1(store_file)                           # an old census still writing
        st.migrate(now=600.0)
        assert st.read_all()["sessions"]["s1"]["worktree_cwd"] == "/wt/new"

    def test_held_lock_skips_migration_but_ingest_still_writes(self, store_file):
        _write_v1(store_file)
        (store_file.parent / ".migrate.lock").write_text("")
        st.ingest(json.dumps({"session_id": "s2", "cwd": "/wt/b"}), now=200.0)
        assert store_file.exists()                       # not migrated this run
        assert st.session_path("s2").exists()            # but s2 recorded

    def test_stale_lock_is_broken(self, store_file):
        _write_v1(store_file)
        lock = store_file.parent / ".migrate.lock"
        lock.write_text("")
        old = time.time() - 120
        os.utime(lock, (old, old))
        assert st.migrate(now=200.0) is True

    def test_two_accounts_migrate_independently(self, tmp_path, monkeypatch):
        for account in ("a", "b"):
            path = tmp_path / account / "census" / "status.json"
            _write_v1(path)
        for account in ("a", "b"):
            monkeypatch.setenv("CENSUS_STORE", str(tmp_path / account / "census"))
            (tmp_path / account / "census" / ".migrate.lock").write_text("") if account == "a" else None
            st.migrate(now=200.0)
        assert (tmp_path / "a" / "census" / "status.json").exists()      # a was locked
        assert not (tmp_path / "b" / "census" / "status.json").exists()  # b migrated

    def test_corrupt_v1_is_still_retired(self, store_file):
        store_file.parent.mkdir(parents=True, exist_ok=True)
        store_file.write_text("{broken")
        assert st.migrate(now=200.0) is True
        assert st.read_all()["sessions"] == {}

    def test_expired_v1_limits_kept_verbatim_when_no_limits_file(self, store_file):
        data = dict(V1, limits={"five_hour": {"used_percentage": 10, "resets_at": 1}})
        _write_v1(store_file, data)
        st.migrate(now=200.0)
        assert st.read_all()["limits"]["five_hour"]["resets_at"] == 1

    def test_reads_migrate_transparently(self, store_file):
        _write_v1(store_file)
        assert st.for_session("s1") is not None
        assert not store_file.exists()

    def test_migrated_copy_deleted_after_seven_days(self, store_file):
        _write_v1(store_file)
        st.migrate(now=200.0)
        retired = store_file.parent / "status.json.v1-migrated"
        old = time.time() - st.MIGRATED_KEEP_SECONDS - 60
        os.utime(retired, (old, old))
        st.ingest(json.dumps({"session_id": "s9", "cwd": "/wt"}), now=time.time())
        assert not retired.exists()
