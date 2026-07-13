import json

from scripts import store as st


def _payload(sid="s1", cwd="/wt/a", **extra):
    base = {"session_id": sid, "cwd": cwd}
    base.update(extra)
    return json.dumps(base)


def _read(store_file):
    return json.loads(store_file.read_text())


class TestBasicIngest:
    def test_records_session_keyed_by_id(self, store_file):
        st.ingest(_payload(sid="abc", cwd="/wt/a"), now=100.0)
        data = _read(store_file)
        assert "abc" in data["sessions"]
        entry = data["sessions"]["abc"]
        assert entry["worktree_cwd"].endswith("/wt/a")
        assert entry["updated_at"] == 100.0
        assert entry["payload"]["session_id"] == "abc"

    def test_stores_full_payload_verbatim(self, store_file):
        st.ingest(_payload(sid="abc", model={"id": "claude-opus-4-8"}, pr={"number": 7}), now=1.0)
        payload = _read(store_file)["sessions"]["abc"]["payload"]
        assert payload["model"] == {"id": "claude-opus-4-8"}
        assert payload["pr"] == {"number": 7}

    def test_missing_session_id_writes_nothing(self, store_file):
        st.ingest(json.dumps({"cwd": "/wt/a"}), now=1.0)
        assert not store_file.exists()

    def test_invalid_json_writes_nothing(self, store_file):
        st.ingest("{not json", now=1.0)
        assert not store_file.exists()

    def test_upsert_overwrites_same_session(self, store_file):
        st.ingest(_payload(sid="abc", cwd="/wt/a"), now=1.0)
        st.ingest(_payload(sid="abc", cwd="/wt/b"), now=2.0)
        sessions = _read(store_file)["sessions"]
        assert len(sessions) == 1
        assert sessions["abc"]["worktree_cwd"].endswith("/wt/b")
        assert sessions["abc"]["updated_at"] == 2.0


class TestLimitsHoist:
    RATE = {"five_hour": {"used_percentage": 20, "resets_at": 111}}

    def test_hoists_rate_limits_to_top_level(self, store_file):
        st.ingest(_payload(rate_limits=self.RATE), now=5.0)
        limits = _read(store_file)["limits"]
        assert limits["five_hour"] == {"used_percentage": 20, "resets_at": 111}
        assert limits["updated_at"] == 5.0

    def test_absent_rate_limits_leaves_existing_untouched(self, store_file):
        st.ingest(_payload(sid="s1", rate_limits=self.RATE), now=5.0)
        st.ingest(_payload(sid="s2"), now=6.0)  # no rate_limits
        assert _read(store_file)["limits"]["five_hour"]["used_percentage"] == 20


class TestContextPreservationGuard:
    def test_blank_context_keeps_prior_reading(self, store_file):
        good = {"context_window": {"used_percentage": 42, "current_usage": {"input_tokens": 9}}}
        st.ingest(_payload(sid="s1", **good), now=1.0)
        # post-/compact: both null
        blank = {"context_window": {"used_percentage": None, "current_usage": None}}
        st.ingest(_payload(sid="s1", **blank), now=2.0)
        window = _read(store_file)["sessions"]["s1"]["payload"]["context_window"]
        assert window["used_percentage"] == 42

    def test_missing_context_window_keeps_prior_reading(self, store_file):
        good = {"context_window": {"used_percentage": 42, "current_usage": {"input_tokens": 9}}}
        st.ingest(_payload(sid="s1", **good), now=1.0)
        st.ingest(_payload(sid="s1"), now=2.0)  # no context_window at all
        window = _read(store_file)["sessions"]["s1"]["payload"]["context_window"]
        assert window["used_percentage"] == 42

    def test_no_prior_reading_stores_as_is(self, store_file):
        st.ingest(_payload(sid="s1", context_window={"used_percentage": None}), now=1.0)
        window = _read(store_file)["sessions"]["s1"]["payload"]["context_window"]
        assert window == {"used_percentage": None}


class TestTmuxPane:
    def test_records_tmux_pane_when_env_present(self, store_file, monkeypatch):
        monkeypatch.setenv("TMUX_PANE", "%42")
        st.ingest(_payload(sid="abc"), now=1.0)
        entry = _read(store_file)["sessions"]["abc"]
        assert entry["tmux_pane"] == "%42"

    def test_omits_tmux_pane_key_when_env_absent(self, store_file, monkeypatch):
        monkeypatch.delenv("TMUX_PANE", raising=False)
        st.ingest(_payload(sid="abc"), now=1.0)
        entry = _read(store_file)["sessions"]["abc"]
        assert "tmux_pane" not in entry

    def test_blank_env_var_treated_as_absent(self, store_file, monkeypatch):
        monkeypatch.setenv("TMUX_PANE", "")
        st.ingest(_payload(sid="abc"), now=1.0)
        entry = _read(store_file)["sessions"]["abc"]
        assert "tmux_pane" not in entry

    def test_reingest_without_env_drops_previously_recorded_pane(self, store_file, monkeypatch):
        # Sibling fields (worktree_cwd, payload) are replaced wholesale on
        # every ingest, not merged with the previous entry — tmux_pane follows
        # the same rule, so a session that has moved out of tmux stops
        # reporting a now-stale pane.
        monkeypatch.setenv("TMUX_PANE", "%42")
        st.ingest(_payload(sid="abc"), now=1.0)
        monkeypatch.delenv("TMUX_PANE", raising=False)
        st.ingest(_payload(sid="abc"), now=2.0)
        entry = _read(store_file)["sessions"]["abc"]
        assert "tmux_pane" not in entry


class TestPrune:
    def test_stale_sessions_pruned_on_write(self, store_file):
        st.ingest(_payload(sid="old", cwd="/wt/a"), now=0.0)
        # a later write far beyond the TTL evicts the old entry
        st.ingest(_payload(sid="new", cwd="/wt/b"), now=st.SESSION_TTL_SECONDS + 10)
        sessions = _read(store_file)["sessions"]
        assert "old" not in sessions
        assert "new" in sessions
