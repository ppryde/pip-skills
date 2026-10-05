"""census v2 on disk: one file per session, a forward-merged limits file, no lock."""
import json
import os
from pathlib import Path

from scripts import store as st

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "census"


def _payload(sid, **extra):
    return json.dumps({"session_id": sid, "cwd": f"/wt/{sid}", **extra})


class TestSessionFiles:
    def test_ingest_writes_one_file_per_session(self, store_file):
        st.ingest(_payload("s1"), now=100.0)
        st.ingest(_payload("s2"), now=101.0)
        files = sorted(p.name for p in st.sessions_dir().iterdir())
        assert files == ["s1.json", "s2.json"]
        body = json.loads(st.session_path("s1").read_text())
        assert body["version"] == 2
        assert body["worktree_cwd"] == "/wt/s1"
        assert body["updated_at"] == 100.0
        assert not st.store_path().exists()

    def test_view_has_v1_shape(self, store_file):
        st.ingest(_payload("s1"), now=100.0)
        view = st.read_all()
        assert view["version"] == 1
        assert set(view) == {"version", "limits", "sessions"}
        assert "version" not in view["sessions"]["s1"]

    def test_unsafe_session_id_writes_nothing(self, store_file, tmp_path):
        for bad in ["../escape", ".hidden", "a/b", "x" * 200]:
            st.ingest(json.dumps({"session_id": bad, "cwd": "/wt"}), now=1.0)
        assert not st.sessions_dir().exists() or list(st.sessions_dir().iterdir()) == []
        assert not (tmp_path / "escape.json").exists()
        assert st.for_session("../escape") is None

    def test_corrupt_session_file_is_skipped_then_healed(self, store_file):
        st.sessions_dir().mkdir(parents=True)
        st.session_path("s1").write_text("{not json")
        assert st.read_all()["sessions"] == {}
        assert st.for_session("s1") is None
        st.ingest(_payload("s1"), now=5.0)
        assert st.read_all()["sessions"]["s1"]["updated_at"] == 5.0

    def test_dotfiles_and_non_json_are_ignored(self, store_file):
        st.ingest(_payload("s1"), now=5.0)
        (st.sessions_dir() / ".s9.json.abc.tmp").write_text("{}")
        (st.sessions_dir() / "notes.txt").write_text("x")
        assert set(st.read_all()["sessions"]) == {"s1"}

    def test_ingest_prunes_sessions_older_than_ttl(self, store_file):
        st.ingest(_payload("old"), now=0.0)
        st.ingest(_payload("new"), now=st.SESSION_TTL_SECONDS + 10.0)
        assert set(st.read_all()["sessions"]) == {"new"}
        assert not st.session_path("old").exists()

    def test_unparseable_file_older_than_ttl_is_swept(self, store_file):
        import time

        st.sessions_dir().mkdir(parents=True)
        bad = st.session_path("bad")
        bad.write_text("{not json")
        old = time.time() - st.SESSION_TTL_SECONDS - 100
        os.utime(bad, (old, old))
        st.ingest(_payload("s1"), now=time.time())
        assert not bad.exists()

    def test_reads_never_prune(self, store_file):
        st.ingest(_payload("s1"), now=0.0)
        st.read_all(now=10 * st.SESSION_TTL_SECONDS)
        assert st.session_path("s1").exists()


class TestLimitsFile:
    def _rl(self, pct, resets):
        return {"five_hour": {"used_percentage": pct, "resets_at": resets}}

    def test_limits_written_to_their_own_file(self, store_file):
        st.ingest(_payload("s1", rate_limits=self._rl(40, 5000)), now=100.0)
        body = json.loads(st.limits_path().read_text())
        assert body["version"] == 2
        assert body["five_hour"]["used_percentage"] == 40

    def test_lower_reading_in_same_window_never_wins(self, store_file):
        st.ingest(_payload("busy", rate_limits=self._rl(60, 5000)), now=100.0)
        st.ingest(_payload("dormant", rate_limits=self._rl(20, 5000)), now=101.0)
        assert st.limits(now=102.0)["five_hour"]["used_percentage"] == 60

    def test_unchanged_limits_are_not_rewritten(self, store_file):
        st.ingest(_payload("s1", rate_limits=self._rl(60, 5000)), now=100.0)
        before = st.limits_path().stat().st_mtime_ns
        st.ingest(_payload("s2", rate_limits=self._rl(20, 5000)), now=101.0)
        assert st.limits_path().stat().st_mtime_ns == before


class TestPortable:
    def test_no_census_module_imports_fcntl(self):
        for path in (PLUGIN / "scripts").glob("*.py"):
            text = path.read_text()
            assert "import fcntl" not in text, path.name


class TestIngestNeverRaises:
    def test_deeply_nested_payload(self, store_file):
        raw = "[" * 100_000 + "]" * 100_000
        assert st.ingest(raw, now=1.0) is None

    def test_odd_cwd_and_workspace_types(self, store_file):
        for extra in ({"cwd": 7}, {"workspace": "x"}, {"cwd": 7, "workspace": "x"}):
            raw = json.dumps({"session_id": "s1", **extra})
            assert st.ingest(raw, now=1.0) is None
