"""SS-3: the status-line hot path. The sweep parses every session file, so it runs at most once per interval (a marker's
mtime says when it last ran) and migration is checked once per process, not on every ingest and every read."""
import json
import os
import time

import pytest

from scripts import store as st


@pytest.fixture
def sweeping(monkeypatch):
    """The real interval (conftest zeroes it so older tests sweep on every ingest)."""
    monkeypatch.setattr(st, "SWEEP_INTERVAL_SECONDS", 300)


def _ingest(sid, now):
    st.ingest(json.dumps({"session_id": sid, "cwd": "/wt/a"}), now=now)


def _old_session(sid="old", updated_at=1.0):
    path = st.session_path(sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 2, "updated_at": updated_at, "payload": {}}))
    return path


def test_the_first_ingest_sweeps_and_leaves_a_marker(store_file, sweeping):
    old = _old_session()
    _ingest("live", time.time())
    assert not old.exists()
    assert (st.census_dir() / ".sweep").is_file()


def test_a_second_ingest_inside_the_interval_does_not_sweep_again(store_file, sweeping):
    _ingest("live", time.time())
    old = _old_session()
    _ingest("live", time.time())
    assert old.exists()  # the sweep would have removed it


def test_an_ingest_after_the_interval_sweeps_again(store_file, sweeping):
    _ingest("live", time.time())
    marker = st.census_dir() / ".sweep"
    stale = time.time() - 301
    os.utime(marker, (stale, stale))
    old = _old_session()
    _ingest("live", time.time())
    assert not old.exists()


def test_a_marker_from_the_future_does_not_stop_the_sweep_forever(store_file, sweeping):
    _ingest("live", time.time())
    marker = st.census_dir() / ".sweep"
    future = time.time() + 86400
    os.utime(marker, (future, future))
    old = _old_session()
    _ingest("live", time.time())
    assert not old.exists()


def test_migration_is_checked_once_per_process(store_file, monkeypatch):
    calls = []
    real = st._migrate_limits_json
    monkeypatch.setattr(st, "_migrate_limits_json", lambda now: (calls.append(now), real(now))[1])
    _ingest("a", 10.0)
    _ingest("b", 11.0)
    st.limits(now=12.0)
    st.read_all()
    assert len(calls) == 1


def test_a_legacy_store_is_still_migrated_on_the_first_look(store_file):
    store_file.parent.mkdir(parents=True, exist_ok=True)
    store_file.write_text(json.dumps({"sessions": {"v1": {"updated_at": time.time(), "payload": {"session_id": "v1"}}}}))
    assert "v1" in st.read_all()["sessions"]
