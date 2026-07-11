import json

from scripts import store as st
from scripts.resolve import normalise


def _payload(sid, cwd, **extra):
    base = {"session_id": sid, "cwd": cwd}
    base.update(extra)
    return json.dumps(base)


class TestLatestForWorktree:
    def test_returns_entry_for_matching_worktree(self, store_file):
        st.ingest(_payload("s1", "/wt/a"), now=100.0)
        result = st.latest_for_worktree("/wt/a", now=100.0)
        assert result is not None
        assert result["payload"]["session_id"] == "s1"

    def test_picks_freshest_when_several_share_worktree(self, store_file):
        st.ingest(_payload("old", "/wt/a"), now=100.0)
        st.ingest(_payload("new", "/wt/a"), now=200.0)
        result = st.latest_for_worktree("/wt/a", now=200.0)
        assert result["payload"]["session_id"] == "new"

    def test_none_when_no_match(self, store_file):
        st.ingest(_payload("s1", "/wt/a"), now=100.0)
        assert st.latest_for_worktree("/wt/other", now=100.0) is None

    def test_matches_across_trailing_slash_and_symlink_variants(self, store_file, tmp_path):
        st.ingest(_payload("s1", str(tmp_path)), now=1.0)
        assert st.latest_for_worktree(str(tmp_path) + "/", now=1.0) is not None

    def test_includes_top_level_limits(self, store_file):
        st.ingest(_payload("s1", "/wt/a", rate_limits={"five_hour": {"used_percentage": 30}}), now=1.0)
        result = st.latest_for_worktree("/wt/a", now=1.0)
        assert result["limits"]["five_hour"]["used_percentage"] == 30

    def test_fresh_entry_not_stale(self, store_file):
        st.ingest(_payload("s1", "/wt/a"), now=100.0)
        assert st.latest_for_worktree("/wt/a", now=100.0 + 10)["stale"] is False

    def test_old_entry_marked_stale(self, store_file):
        st.ingest(_payload("s1", "/wt/a"), now=100.0)
        later = 100.0 + st.STALE_HORIZON_SECONDS + 1
        assert st.latest_for_worktree("/wt/a", now=later)["stale"] is True


class TestForSession:
    def test_returns_named_session(self, store_file):
        st.ingest(_payload("s1", "/wt/a"), now=1.0)
        assert st.for_session("s1", now=1.0)["payload"]["session_id"] == "s1"

    def test_none_for_unknown_session(self, store_file):
        assert st.for_session("nope", now=1.0) is None


class TestLimitsAndReadAll:
    def test_limits_none_when_empty(self, store_file):
        assert st.limits() is None

    def test_read_all_heals_missing_store(self, store_file):
        data = st.read_all()
        assert data["sessions"] == {}
        assert data["limits"] is None

    def test_normalise_is_used_for_keys(self, store_file, tmp_path):
        st.ingest(_payload("s1", str(tmp_path)), now=1.0)
        stored = json.loads(store_file.read_text())["sessions"]["s1"]["worktree_cwd"]
        assert stored == normalise(str(tmp_path))
