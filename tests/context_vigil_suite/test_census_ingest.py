import json

import pytest
from context_vigil import census as st

from .conftest import census_payload as _payload
from .conftest import read_store as _read


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

    @pytest.mark.parametrize("env_value", [
        pytest.param(None, id="env_absent"),
        pytest.param("", id="blank_env_var_treated_as_absent"),
    ])
    def test_omits_tmux_pane_key_when_env_absent_or_blank(self, store_file, monkeypatch,
                                                          env_value):
        if env_value is None:
            monkeypatch.delenv("TMUX_PANE", raising=False)
        else:
            monkeypatch.setenv("TMUX_PANE", env_value)
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


_CACHE = {
    "warm": True,
    "ttl": "1h",
    "expires_at": 1788515961,
    "requests": 29,
    "misses": 0,
    "hit_ratio": 0.973,
}


class TestPromptCachePassthrough:
    """``prompt_cache`` needs no special handling: the payload is stored verbatim.

    The one thing worth pinning is the interaction with the post-/compact
    context guard — that guard carries forward ONLY ``context_window``. A stale
    cache reading is worse than none, so ``prompt_cache`` must never be
    resurrected from a prior entry.
    """

    def test_prompt_cache_stored_verbatim(self, store_file):
        st.ingest(_payload(sid="s1", prompt_cache=_CACHE), now=1.0)
        assert _read(store_file)["sessions"]["s1"]["payload"]["prompt_cache"] == _CACHE

    def test_blank_context_carries_window_but_not_prior_cache(self, store_file):
        good = {
            "context_window": {"used_percentage": 42, "current_usage": {"input_tokens": 9}},
            "prompt_cache": _CACHE,
        }
        st.ingest(_payload(sid="s1", **good), now=1.0)
        blank = {"context_window": {"used_percentage": None, "current_usage": None}}
        st.ingest(_payload(sid="s1", **blank), now=2.0)  # post-/compact, no prompt_cache
        payload = _read(store_file)["sessions"]["s1"]["payload"]
        assert payload["context_window"]["used_percentage"] == 42
        assert "prompt_cache" not in payload

    def test_fresh_cache_replaces_prior_wholesale(self, store_file):
        st.ingest(_payload(sid="s1", prompt_cache=_CACHE), now=1.0)
        cold = {"warm": False, "requests": 30, "misses": 1, "hit_ratio": 0.9}
        st.ingest(_payload(sid="s1", prompt_cache=cold), now=2.0)
        assert _read(store_file)["sessions"]["s1"]["payload"]["prompt_cache"] == cold


def _busy(**counters):
    """A payload slice whose counters only move on real API activity."""
    base = {
        "prompt_id": "p1",
        "cost": {"total_cost_usd": 1.0, "total_api_duration_ms": 100},
        "context_window": {
            "total_input_tokens": 10, "total_output_tokens": 5, "used_percentage": 3,
        },
        "prompt_cache": {"requests": 4},
    }
    for key, value in counters.items():
        section, _, field = key.partition("__")
        if field:
            base[section][field] = value
        else:
            base[section] = value
    return base


def _seed_prior_entry(store_file, **entry):
    """A store already holding session ``s1`` (``entry`` adds keys such as ``active_at``)."""
    store_file.parent.mkdir(parents=True, exist_ok=True)
    store_file.write_text(json.dumps({
        "version": 1,
        "limits": None,
        "sessions": {"s1": {"worktree_cwd": "/wt/a", "updated_at": 5.0,
                            "payload": _busy(), **entry}},
    }))


class TestActivityTracking:
    """``active_at`` moves only when the session did work; ``updated_at`` moves on every render."""

    def test_first_sight_stamps_active_at_now(self, store_file):
        st.ingest(_payload(sid="s1", **_busy()), now=10.0)
        entry = _read(store_file)["sessions"]["s1"]
        assert entry["active_at"] == 10.0
        assert entry["updated_at"] == 10.0

    def test_timer_rerun_with_identical_counters_keeps_active_at(self, store_file):
        st.ingest(_payload(sid="s1", **_busy()), now=10.0)
        st.ingest(_payload(sid="s1", **_busy()), now=70.0)  # refreshInterval tick, nothing happened
        entry = _read(store_file)["sessions"]["s1"]
        assert entry["updated_at"] == 70.0
        assert entry["active_at"] == 10.0

    @pytest.mark.parametrize("change", [
        pytest.param({"cost__total_cost_usd": 1.5}, id="cost_change"),
        pytest.param({"prompt_id": "p2"}, id="new_prompt"),
        pytest.param({"prompt_cache__requests": 5}, id="cache_requests_change"),
        # `context_window.total_input_tokens` / `total_output_tokens` are real payload
        # fields (they appear in captured status-line payloads); a turn that only
        # moves them is still real activity.
        pytest.param({"context_window__total_input_tokens": 99}, id="token_totals_moving"),
        pytest.param({"context_window__total_output_tokens": 77}, id="output_tokens_moving"),
        pytest.param({"cost__total_api_duration_ms": 250}, id="api_duration_moving"),
    ])
    def test_counter_change_advances_active_at(self, store_file, change):
        st.ingest(_payload(sid="s1", **_busy()), now=10.0)
        st.ingest(_payload(sid="s1", **_busy(**change)), now=70.0)
        assert _read(store_file)["sessions"]["s1"]["active_at"] == 70.0

    def test_cosmetic_change_does_not_advance_active_at(self, store_file):
        st.ingest(_payload(sid="s1", **_busy()), now=10.0)
        st.ingest(_payload(sid="s1", session_name="renamed", **_busy()), now=70.0)
        assert _read(store_file)["sessions"]["s1"]["active_at"] == 10.0

    def test_pre_upgrade_entry_without_active_at_starts_clock_now(self, store_file):
        _seed_prior_entry(store_file)
        st.ingest(_payload(sid="s1", **_busy()), now=70.0)
        assert _read(store_file)["sessions"]["s1"]["active_at"] == 70.0

    @pytest.mark.parametrize("bad", [
        pytest.param(True, id="bool"),
        pytest.param(float("nan"), id="nan"),
        pytest.param("700", id="numeric_string"),
        pytest.param(None, id="none"),
    ])
    def test_malformed_prior_active_at_restarts_the_clock(self, store_file, bad):
        """A bool, a NaN or a numeric STRING is not a usable timestamp. NaN is
        the dangerous one: json round-trips it and every comparison is false."""
        _seed_prior_entry(store_file, active_at=bad)
        st.ingest(_payload(sid="s1", **_busy()), now=70.0)
        assert _read(store_file)["sessions"]["s1"]["active_at"] == 70.0, bad

    def test_future_prior_active_at_restarts_the_clock(self, store_file):
        """A clock step must not leave a session reporting non-idle for hours."""
        _seed_prior_entry(store_file, active_at=70.0 + 7200)
        st.ingest(_payload(sid="s1", **_busy()), now=70.0)
        assert _read(store_file)["sessions"]["s1"]["active_at"] == 70.0

    def test_rate_limits_change_alone_does_not_advance_active_at(self, store_file):
        """`rate_limits` is deliberately NOT in the fingerprint: it can change
        for account-wide reasons while this session does nothing."""
        rate = {"five_hour": {"used_percentage": 10, "resets_at": 10_000.0}}
        st.ingest(_payload(sid="s1", rate_limits=rate, **_busy()), now=10.0)
        moved = {"five_hour": {"used_percentage": 40, "resets_at": 10_000.0}}
        st.ingest(_payload(sid="s1", rate_limits=moved, **_busy()), now=70.0)
        assert _read(store_file)["sessions"]["s1"]["active_at"] == 10.0

    def test_a_session_that_never_prompts_keeps_its_first_activity_stamp(self, store_file):
        """A TUI opened and never prompted carries none of the fingerprint
        fields. Treating "no evidence" as activity on every tick would pin it
        as the most active session of its worktree forever."""
        later = 10.0 + 10 * 60 + 60
        st.ingest(_payload(sid="s1"), now=10.0)
        st.ingest(_payload(sid="s1"), now=later)
        assert _read(store_file)["sessions"]["s1"]["active_at"] == 10.0

    def test_evidence_appearing_counts_as_activity(self, store_file):
        """Its first real turn must wake it, not be read as another blank tick."""
        later = 10.0 + 10 * 60 + 60
        st.ingest(_payload(sid="s1"), now=10.0)
        st.ingest(_payload(sid="s1", **_busy()), now=later)
        assert _read(store_file)["sessions"]["s1"]["active_at"] == later

    def test_evidence_vanishing_counts_as_activity(self, store_file):
        """An unrecognised payload shape must not be read as dormancy."""
        later = 10.0 + 10 * 60 + 60
        st.ingest(_payload(sid="s1", **_busy()), now=10.0)
        st.ingest(_payload(sid="s1"), now=later)
        assert _read(store_file)["sessions"]["s1"]["active_at"] == later

    def test_identical_repeat_ingest_at_the_same_instant_keeps_active_at(self, store_file):
        """`active == prior` — the boundary case, pinned explicitly."""
        st.ingest(_payload(sid="s1", **_busy()), now=10.0)
        st.ingest(_payload(sid="s1", **_busy()), now=10.0)
        assert _read(store_file)["sessions"]["s1"]["active_at"] == 10.0

    def test_active_at_survives_post_compact_blank_context(self, store_file):
        st.ingest(_payload(sid="s1", **_busy()), now=10.0)
        blank = _busy(context_window={"used_percentage": None, "current_usage": None})
        st.ingest(_payload(sid="s1", **blank), now=70.0)
        entry = _read(store_file)["sessions"]["s1"]
        assert entry["payload"]["context_window"]["used_percentage"] == 3
        assert isinstance(entry["active_at"], float)
