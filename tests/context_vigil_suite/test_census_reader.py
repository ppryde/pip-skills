import json
import os
import time

import pytest
from context_vigil import census, paths


@pytest.fixture
def store_file(iso):
    return paths.census_path()


def _store(store_file, root, pct, *, updated=None, sid="s1"):
    store_file.parent.mkdir(parents=True, exist_ok=True)
    store_file.write_text(json.dumps({
        "version": 1,
        "limits": None,
        "sessions": {
            sid: {
                "worktree_cwd": os.path.realpath(str(root)),
                "updated_at": updated if updated is not None else time.time(),
                "payload": {"context_window": {"used_percentage": pct}},
            }
        },
    }))


class TestStorePath:
    def test_rooted_at_the_data_root(self, tmp_path):
        assert census.store_path() == tmp_path / "data" / "census.json"


class TestContextPercent:
    def test_reads_pct_for_worktree(self, tmp_path, store_file):
        _store(store_file, tmp_path, 37)
        assert census.context_percent(tmp_path) == 37

    def test_none_when_store_absent(self, tmp_path, store_file):
        assert census.context_percent(tmp_path) is None

    def test_none_when_no_matching_worktree(self, tmp_path, store_file):
        _store(store_file, tmp_path / "other", 50)
        assert census.context_percent(tmp_path) is None

    def test_none_when_stale(self, tmp_path, store_file):
        _store(store_file, tmp_path, 37, updated=1000.0)
        now = 1000.0 + census.STALE_HORIZON_SECONDS + 1
        assert census.context_percent(tmp_path, now=now) is None

    def test_fresh_entry_returned(self, tmp_path, store_file):
        _store(store_file, tmp_path, 37, updated=1000.0)
        assert census.context_percent(tmp_path, now=1000.0 + 10) == 37

    def test_rounds_float_percentage(self, tmp_path, store_file):
        _store(store_file, tmp_path, 41.6)
        assert census.context_percent(tmp_path) == 42

    def test_none_when_used_percentage_missing(self, tmp_path, store_file):
        store_file.parent.mkdir(parents=True, exist_ok=True)
        store_file.write_text(json.dumps({"sessions": {"s1": {
            "worktree_cwd": os.path.realpath(str(tmp_path)),
            "updated_at": time.time(),
            "payload": {"context_window": {"used_percentage": None}},
        }}}))
        assert census.context_percent(tmp_path) is None

    def test_corrupt_store_is_none(self, tmp_path, store_file):
        store_file.parent.mkdir(parents=True, exist_ok=True)
        store_file.write_text("{not json")
        assert census.context_percent(tmp_path) is None


def _two_sessions_same_worktree(store_file, root, *, mine_pct, sibling_pct, now,
                                 mine_updated=None, sibling_updated=None,
                                 mine_id="s-mine", sibling_id="s-sibling"):
    """Two sessions sharing a worktree — the regression fixture for the bug:
    without session-id keying, the newest write wins regardless of whose
    session it belongs to."""
    store_file.parent.mkdir(parents=True, exist_ok=True)
    key = os.path.realpath(str(root))
    store_file.write_text(json.dumps({
        "version": 1,
        "limits": None,
        "sessions": {
            mine_id: {
                "worktree_cwd": key,
                "updated_at": mine_updated if mine_updated is not None else now - 5,
                "payload": {"context_window": {"used_percentage": mine_pct}},
            },
            sibling_id: {
                "worktree_cwd": key,
                # sibling is the newer write — this is what used to win pre-fix
                "updated_at": sibling_updated if sibling_updated is not None else now,
                "payload": {"context_window": {"used_percentage": sibling_pct}},
            },
        },
    }))


class TestContextPercentBySessionId:
    def test_session_id_wins_over_newest_write_same_worktree(self, tmp_path, store_file):
        # Regression test: two live sessions in the same worktree, sibling's
        # write is newer and has a much higher pct. Passing our session_id
        # must return OUR pct, not the sibling's, even though it lost the
        # newest-write race.
        now = 1000.0
        _two_sessions_same_worktree(store_file, tmp_path, mine_pct=9, sibling_pct=49, now=now)
        assert census.context_percent(tmp_path, now=now, session_id="s-mine") == 9

    def test_stale_own_entry_does_not_fall_back_to_sibling(self, tmp_path, store_file):
        # Our own entry is stale (beyond the horizon). This must read as
        # "unavailable" (None) so the caller falls back to transcript
        # measurement — NOT silently resurrect the bug by falling back to a
        # different, fresher session's entry.
        now = 1000.0
        _two_sessions_same_worktree(
            store_file, tmp_path, mine_pct=9, sibling_pct=49, now=now,
            mine_updated=now - census.STALE_HORIZON_SECONDS - 1,
            sibling_updated=now,
        )
        assert census.context_percent(tmp_path, now=now, session_id="s-mine") is None

    def test_session_id_absent_from_store_falls_back_to_worktree_scan(self, tmp_path, store_file):
        _store(store_file, tmp_path, 37)  # keyed "s1" by the _store helper
        assert census.context_percent(tmp_path, session_id="no-such-session") == 37

    def test_no_session_id_keeps_existing_worktree_scan_behaviour(self, tmp_path, store_file):
        _store(store_file, tmp_path, 37)
        assert census.context_percent(tmp_path) == 37

    def test_malformed_updated_at_on_own_entry_is_none_not_raise(self, tmp_path, store_file):
        # Quarantine contract: a non-numeric updated_at must never raise.
        # Malformed timestamp -> treated as 0 -> stale -> None (session-id branch).
        _store(store_file, tmp_path, 37, updated="bad", sid="s-mine")
        assert census.context_percent(tmp_path, session_id="s-mine") is None

    def test_malformed_updated_at_in_worktree_scan_is_none_not_raise(self, tmp_path, store_file):
        # Same contract on the no-session-id worktree-scan branch.
        _store(store_file, tmp_path, 37, updated="bad")
        assert census.context_percent(tmp_path) is None
