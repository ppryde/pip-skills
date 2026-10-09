"""Concurrent ingests must not regress an account's limit window: a stale read may not win the replace."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts import store as st

CLI = Path(__file__).resolve().parents[2] / "plugins" / "census" / "scripts" / "cli.py"
NOW = 1_800_000_000.0


def payload(sid, pct, resets=NOW + 3 * 3600):
    return json.dumps({"session_id": sid, "cwd": f"/wt/{sid}", "rate_limits": {"five_hour": {"used_percentage": pct, "resets_at": resets}}})


def five_hour():
    return (st.limits(now=NOW) or {}).get("five_hour", {}).get("used_percentage")


class TestRealConcurrentProcesses:
    @pytest.mark.parametrize("round_", range(3))
    def test_the_highest_reading_survives_a_pile_up_of_writers(self, tmp_path, round_):
        store = tmp_path / "census"
        env = {**os.environ, "CENSUS_STORE": str(store), "HOME": str(tmp_path), "CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")}
        future = time.time() + 3 * 3600
        readings = list(range(1, 25))
        procs = []
        for pct in readings:
            p = subprocess.Popen([sys.executable, str(CLI), "ingest"], stdin=subprocess.PIPE, env=env, text=True)
            procs.append((p, payload(f"s{pct}", pct, future)))
        for p, text in procs:   # phase 1: every child is up and holds its whole payload, none has finished reading
            p.stdin.write(text)
            p.stdin.flush()
        for p, _ in procs:      # phase 2 (the barrier): the closes land back to back, so the ingests overlap
            p.stdin.close()
        for p, _ in procs:
            assert p.wait(timeout=60) == 0
        limits = json.loads(next((store / "limits").glob("*.json")).read_text())
        assert limits["five_hour"]["used_percentage"] == max(readings)


class TestTheMergeItself:
    @pytest.fixture(autouse=True)
    def _store(self, store_file):
        return store_file

    def test_a_snapshot_that_went_stale_before_the_write_is_merged_again(self, monkeypatch):
        """Two writers both read 40; the 60 lands first. The 45 writer's second look sees the file changed and
        merges onto the 60 instead of replacing it."""
        st.ingest(payload("a", 40), now=NOW)
        path = st.limits_path()
        snapshot = json.loads(path.read_text())
        st._atomic_write(path, {**snapshot, "five_hour": {**snapshot["five_hour"], "used_percentage": 60}})   # the 60 landed
        real = st._read_json
        served = {"n": 0}

        def read(p):
            if Path(p) == path and served["n"] == 0:
                served["n"] += 1
                return snapshot   # the 45 writer's early, now stale, read
            return real(p)

        monkeypatch.setattr(st, "_read_json", read)
        monkeypatch.setattr(st, "_acquire_limits_lock", lambda _p: st.LOCK_UNAVAILABLE)
        st.ingest(payload("b", 45), now=NOW)
        monkeypatch.setattr(st, "_read_json", real)
        assert five_hour() == 60

    def test_a_write_that_a_stale_one_clobbers_afterwards_is_put_back(self, monkeypatch):
        st.ingest(payload("a", 40), now=NOW)
        path = st.limits_path()
        stale = json.loads(path.read_text())
        real = st._atomic_write
        done = {"n": 0}

        def write(p, data):
            real(p, data)
            if Path(p) == path and done["n"] == 0:
                done["n"] += 1
                real(p, stale)   # a slower writer's replace of an older snapshot lands right after ours

        monkeypatch.setattr(st, "_atomic_write", write)
        monkeypatch.setattr(st, "_acquire_limits_lock", lambda _p: st.LOCK_UNAVAILABLE)
        st.ingest(payload("b", 60), now=NOW)
        monkeypatch.setattr(st, "_atomic_write", real)
        assert five_hour() == 60

    def test_the_retries_are_bounded(self, monkeypatch):
        st.ingest(payload("a", 40), now=NOW)
        path = st.limits_path()
        stale = json.loads(path.read_text())
        real = st._atomic_write
        writes = {"n": 0}

        def always_clobbered(p, data):
            real(p, data)
            if Path(p) == path:
                writes["n"] += 1
                real(p, stale)

        monkeypatch.setattr(st, "_atomic_write", always_clobbered)
        monkeypatch.setattr(st, "_acquire_limits_lock", lambda _p: st.LOCK_UNAVAILABLE)
        st.ingest(payload("b", 60), now=NOW)   # must return, not spin
        assert 1 < writes["n"] <= st._MERGE_ATTEMPTS

    def test_the_lock_is_taken_and_released(self, tmp_path):
        lock = tmp_path / "x.json.lock"
        assert st._acquire_limits_lock(lock) == st.LOCK_HELD
        assert lock.exists()
        st._release_limits_lock(lock)
        assert not lock.exists()

    def test_a_held_lock_is_waited_for_then_given_up_not_blocked_on(self, tmp_path, monkeypatch):
        lock = tmp_path / "x.json.lock"
        lock.write_text("")
        monkeypatch.setattr(st, "_LOCK_WAIT_SECONDS", 0.05)
        started = time.monotonic()
        assert st._acquire_limits_lock(lock) == st.LOCK_BUSY
        assert time.monotonic() - started < 1
        assert lock.exists()   # not ours: left alone

    def test_a_stale_lock_from_a_crashed_writer_is_taken_over(self, tmp_path):
        lock = tmp_path / "x.json.lock"
        lock.write_text("")
        os.utime(lock, (1, 1))
        assert st._acquire_limits_lock(lock) == st.LOCK_HELD
        assert list(tmp_path.glob("*.stale.*")) == []   # the aside copy is cleaned up

    def test_an_unwritable_folder_means_go_without_the_lock(self, tmp_path):
        (tmp_path / "file").write_text("x")   # a folder cannot be made inside a file
        assert st._acquire_limits_lock(tmp_path / "file" / "x.lock") == st.LOCK_UNAVAILABLE

    def test_the_lock_never_outlives_an_ingest(self, store_file):
        st.ingest(payload("a", 40), now=NOW)
        assert list(st.limits_dir().glob("*.lock")) == []

    def test_the_figure_still_moves_forward_and_never_back(self):
        st.ingest(payload("a", 40), now=NOW)
        st.ingest(payload("b", 60), now=NOW)
        st.ingest(payload("c", 45), now=NOW)
        assert five_hour() == 60

    def test_a_new_window_replaces_a_higher_old_one(self):
        st.ingest(payload("a", 90, NOW + 600), now=NOW)
        st.ingest(payload("b", 5, NOW + 6 * 3600), now=NOW)
        assert five_hour() == 5


class TestWaitingOutAHolder:
    @pytest.fixture(autouse=True)
    def _store(self, store_file):
        return store_file

    def test_a_writer_that_waited_out_a_live_holder_writes_nothing(self, monkeypatch):
        """It must not write from a snapshot taken around the wait: the holder's fresher window would be lost."""
        st.ingest(payload("a", 60), now=NOW)
        lock = st.limits_path().with_name(st.limits_path().name + ".lock")
        lock.write_text("")   # a live holder (fresh mtime)
        monkeypatch.setattr(st, "_LOCK_WAIT_SECONDS", 0.05)
        writes = []
        real = st._atomic_write
        monkeypatch.setattr(st, "_atomic_write", lambda p, d: (writes.append(p), real(p, d))[1])
        st._merge_limits_file({"five_hour": {"used_percentage": 99, "resets_at": NOW + 3600}}, NOW)

        assert all(".pending." in str(p) for p in writes)   # the limits file itself is never touched
        assert five_hour() == 60
        assert lock.exists()   # not ours: left alone

    def test_the_next_ingest_carries_the_skipped_reading(self, monkeypatch):
        st.ingest(payload("a", 40), now=NOW)
        lock = st.limits_path().with_name(st.limits_path().name + ".lock")
        lock.write_text("")
        monkeypatch.setattr(st, "_LOCK_WAIT_SECONDS", 0.05)
        st.ingest(payload("b", 70), now=NOW)
        assert five_hour() == 40
        lock.unlink()
        st.ingest(payload("b", 70), now=NOW)
        assert five_hour() == 70


class TestAtomicTakeover:
    def test_a_live_lock_grabbed_by_a_stale_looker_is_given_back(self, tmp_path):
        lock = tmp_path / "x.json.lock"
        lock.write_text("")   # fresh: a live owner's
        st._take_over_stale_lock(lock)
        assert lock.exists() and list(tmp_path.glob("*.stale.*")) == []

    def test_a_stale_lock_is_removed_once(self, tmp_path):
        lock = tmp_path / "x.json.lock"
        lock.write_text("")
        os.utime(lock, (1, 1))
        st._take_over_stale_lock(lock)
        assert not lock.exists() and list(tmp_path.glob("*.stale.*")) == []
        st._take_over_stale_lock(lock)   # a second waiter finds nothing to take: no error

    def test_a_fresh_lock_created_after_a_waiters_look_survives_its_takeover(self, tmp_path, monkeypatch):
        lock = tmp_path / "x.json.lock"
        lock.write_text("")
        os.utime(lock, (1, 1))
        st._take_over_stale_lock(lock)       # waiter A takes the stale lock...
        lock.write_text("")                  # ...and creates its own
        st._take_over_stale_lock(lock)       # waiter B acts on its earlier look
        assert lock.exists()


class TestNeverSpins:
    def test_a_stale_lock_whose_rename_always_fails_still_ends_at_the_deadline(self, tmp_path, monkeypatch):
        lock = tmp_path / "x.json.lock"
        lock.write_text("")
        os.utime(lock, (1, 1))   # stale
        monkeypatch.setattr(st.os, "rename", lambda *a, **k: (_ for _ in ()).throw(PermissionError("denied")))
        monkeypatch.setattr(st, "_LOCK_WAIT_SECONDS", 0.1)
        started = time.monotonic()
        assert st._acquire_limits_lock(lock) == st.LOCK_BUSY
        assert time.monotonic() - started < 2

    def test_a_lock_that_cannot_be_statted_still_ends_at_the_deadline(self, tmp_path, monkeypatch):
        lock = tmp_path / "x.json.lock"
        lock.write_text("")
        real_stat = Path.stat

        def stat(self, *a, **k):
            if self == lock:
                raise PermissionError("denied")
            return real_stat(self, *a, **k)

        monkeypatch.setattr(Path, "stat", stat)
        monkeypatch.setattr(st, "_LOCK_WAIT_SECONDS", 0.1)
        started = time.monotonic()
        assert st._acquire_limits_lock(lock) == st.LOCK_BUSY
        assert time.monotonic() - started < 2


class TestASkippedReadingIsNotLost:
    """A merge that waited out a live holder queues its windows in its own pending file; the next successful
    merge folds them in (forward-only), even when that next ingest carries no rate_limits at all."""

    @pytest.fixture(autouse=True)
    def _store(self, store_file, monkeypatch):
        monkeypatch.setattr(st, "_LOCK_WAIT_SECONDS", 0.02)
        return store_file

    def _hold(self):
        lock = st.limits_path().with_name(st.limits_path().name + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("")
        return lock

    def _pending(self):
        return sorted(st.limits_dir().glob("*.pending.*"))

    def test_a_skipped_reading_is_queued_not_dropped(self):
        st.ingest(payload("a", 40), now=NOW)
        lock = self._hold()
        st.ingest(payload("b", 70), now=NOW)
        assert five_hour() == 40 and len(self._pending()) == 1
        lock.unlink()

    def test_a_later_ingest_with_no_rate_limits_drains_the_queue(self):
        st.ingest(payload("a", 40), now=NOW)
        lock = self._hold()
        st.ingest(payload("b", 70), now=NOW)
        lock.unlink()
        st.ingest(json.dumps({"session_id": "b", "cwd": "/wt/b"}), now=NOW)   # no rate_limits field at all
        assert five_hour() == 70 and self._pending() == []

    def test_queued_readings_merge_forward_only(self):
        st.ingest(payload("a", 80), now=NOW)
        lock = self._hold()
        st.ingest(payload("b", 30), now=NOW)   # lower than what is stored
        st.ingest(payload("c", 90), now=NOW)
        lock.unlink()
        st.ingest(json.dumps({"session_id": "d", "cwd": "/wt/d"}), now=NOW)
        assert five_hour() == 90 and self._pending() == []

    def test_a_queued_old_window_does_not_beat_a_newer_one(self):
        st.ingest(payload("a", 10, NOW + 7 * 3600), now=NOW)   # a newer window is stored
        lock = self._hold()
        st.ingest(payload("b", 95, NOW + 3600), now=NOW)       # an older window, queued
        lock.unlink()
        st.ingest(json.dumps({"session_id": "d", "cwd": "/wt/d"}), now=NOW)
        assert five_hour() == 10

    def test_a_failed_write_keeps_the_queue_for_next_time(self, monkeypatch):
        st.ingest(payload("a", 40), now=NOW)
        lock = self._hold()
        st.ingest(payload("b", 70), now=NOW)
        lock.unlink()
        real = st._atomic_write
        monkeypatch.setattr(st, "_atomic_write", lambda p, d: (_ for _ in ()).throw(OSError("disk full")))
        st.ingest(json.dumps({"session_id": "d", "cwd": "/wt/d"}), now=NOW)
        assert len(self._pending()) == 1
        monkeypatch.setattr(st, "_atomic_write", real)
        st.ingest(json.dumps({"session_id": "d", "cwd": "/wt/d"}), now=NOW)
        assert five_hour() == 70 and self._pending() == []

    def test_pending_files_are_not_accounts_in_the_all_accounts_listing(self):
        st.ingest(payload("a", 40), now=NOW)
        lock = self._hold()
        st.ingest(payload("b", 70), now=NOW)
        assert set(st.all_limits(now=NOW)) == {st.limits_path().stem}
        lock.unlink()
