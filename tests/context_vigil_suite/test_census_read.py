import json
from pathlib import Path

from context_vigil import census as st
from context_vigil.census import normalise


def _payload(sid, cwd, pct=None, **extra):
    base = {"session_id": sid, "cwd": cwd}
    if pct is not None:
        base["context_window"] = {"used_percentage": pct}
    base.update(extra)
    return json.dumps(base)


class TestWorktreeRead:
    def test_reads_the_entry_for_the_matching_worktree(self, store_file):
        st.ingest(_payload("s1", "/wt/a", 40), now=100.0)
        assert st.context_percent(Path("/wt/a"), now=100.0) == 40
        assert st.context_percent(Path("/wt/other"), now=100.0) is None

    def test_matches_across_trailing_slash_and_symlink_variants(self, store_file, tmp_path):
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        link.symlink_to(real)
        st.ingest(_payload("s1", str(real), 40), now=1.0)
        assert st.context_percent(Path(str(real) + "/"), now=1.0) == 40
        assert st.context_percent(link, now=1.0) == 40

    def test_an_entry_beyond_the_staleness_horizon_is_ignored(self, store_file):
        st.ingest(_payload("s1", "/wt/a", 40), now=100.0)
        assert st.context_percent(Path("/wt/a"), now=100.0 + 10) == 40
        assert st.context_percent(Path("/wt/a"), now=100.0 + st.STALE_HORIZON_SECONDS + 1) is None


class TestForSession:
    def test_returns_named_session(self, store_file):
        st.ingest(_payload("s1", "/wt/a"), now=1.0)
        assert st.for_session("s1")["payload"]["session_id"] == "s1"

    def test_none_for_unknown_session(self, store_file):
        assert st.for_session("nope") is None

    def test_includes_tmux_pane(self, store_file, monkeypatch):
        monkeypatch.setenv("TMUX_PANE", "%7")
        st.ingest(_payload("s1", "/wt/a"), now=1.0)
        assert st.for_session("s1")["tmux_pane"] == "%7"

    def test_absent_pane_not_present(self, store_file, monkeypatch):
        monkeypatch.delenv("TMUX_PANE", raising=False)
        st.ingest(_payload("s1", "/wt/a"), now=1.0)
        assert "tmux_pane" not in st.for_session("s1")

    def test_normalise_is_used_for_keys(self, store_file, tmp_path):
        st.ingest(_payload("s1", str(tmp_path)), now=1.0)
        stored = json.loads(store_file.read_text())["sessions"]["s1"]["worktree_cwd"]
        assert stored == normalise(str(tmp_path))


class TestWorktreeSelectionRanksByActivity:
    def _store(self, store_file, sessions):
        store_file.parent.mkdir(parents=True, exist_ok=True)
        store_file.write_text(json.dumps({"version": 1, "sessions": sessions}))

    @staticmethod
    def _entry(sid, pct, **times):
        return {"worktree_cwd": "/wt/a", **times,
                "payload": {"session_id": sid, "context_window": {"used_percentage": pct}}}

    def test_picks_the_working_session_over_the_dormant_one(self, store_file):
        """The dormant TUI rendered most recently, so ranking on updated_at would
        hand the worktree's answer to the session that is NOT working."""
        self._store(store_file, {
            "dormant": self._entry("dormant", 10, updated_at=1000.0, active_at=100.0),
            "working": self._entry("working", 70, updated_at=970.0, active_at=970.0),
        })
        assert st.context_percent(Path("/wt/a"), now=1001.0) == 70

    def test_entries_predating_active_at_fall_back_to_updated_at(self, store_file):
        self._store(store_file, {
            "older": self._entry("older", 10, updated_at=860.0),
            "newer": self._entry("newer", 70, updated_at=900.0),
        })
        assert st.context_percent(Path("/wt/a"), now=901.0) == 70

    def test_a_corrupt_timestamp_does_not_raise(self, store_file):
        """`ingest` and every reader are documented as never raising. A raw
        float() on a hand-edited value would break the status line for every
        session, and the crash would be inside the pruner that should remove it."""
        self._store(store_file, {
            "bad": self._entry("bad", 10, updated_at="bad"),
            "good": self._entry("good", 70, updated_at=900.0),
        })
        assert st.context_percent(Path("/wt/a"), now=901.0) == 70
        st.ingest(json.dumps({"session_id": "new", "cwd": "/wt/a"}), now=902.0)  # must not raise
