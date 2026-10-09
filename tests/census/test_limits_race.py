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
        for p, text in procs:   # every child is fed before any is waited on, so they really overlap
            p.stdin.write(text)
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
        monkeypatch.setattr(st, "_acquire_limits_lock", lambda _p: False)
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
        monkeypatch.setattr(st, "_acquire_limits_lock", lambda _p: False)
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
        monkeypatch.setattr(st, "_acquire_limits_lock", lambda _p: False)
        st.ingest(payload("b", 60), now=NOW)   # must return, not spin
        assert 1 < writes["n"] <= st._MERGE_ATTEMPTS

    def test_the_lock_is_taken_and_released(self, tmp_path):
        lock = tmp_path / "x.json.lock"
        assert st._acquire_limits_lock(lock) is True
        assert lock.exists()
        st._release_limits_lock(lock)
        assert not lock.exists()

    def test_a_held_lock_is_waited_for_then_given_up_not_blocked_on(self, tmp_path, monkeypatch):
        lock = tmp_path / "x.json.lock"
        lock.write_text("")
        monkeypatch.setattr(st, "_LOCK_WAIT_SECONDS", 0.05)
        started = time.monotonic()
        assert st._acquire_limits_lock(lock) is False
        assert time.monotonic() - started < 1
        assert lock.exists()   # not ours: left alone

    def test_a_stale_lock_from_a_crashed_writer_is_taken_over(self, tmp_path):
        lock = tmp_path / "x.json.lock"
        lock.write_text("")
        os.utime(lock, (1, 1))
        assert st._acquire_limits_lock(lock) is True

    def test_an_unwritable_folder_means_go_without_the_lock(self, tmp_path):
        (tmp_path / "file").write_text("x")   # a folder cannot be made inside a file
        assert st._acquire_limits_lock(tmp_path / "file" / "x.lock") is False

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
