"""Store must be rooted at CLAUDE_CONFIG_DIR so multiple accounts never commingle."""
import json

from scripts import store as st


class TestStorePath:
    def test_censusstore_json_value_names_its_parent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "x" / "status.json"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        assert st.census_dir() == tmp_path / "x"
        assert st.store_path() == tmp_path / "x" / "status.json"

    def test_censusstore_dir_value_is_the_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "c"))
        assert st.census_dir() == tmp_path / "c"
        assert st.sessions_dir() == tmp_path / "c" / "sessions"
        assert st.limits_path() == tmp_path / "c" / "limits.json"

    def test_rooted_at_config_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CENSUS_STORE", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude-personal"))
        assert st.census_dir() == tmp_path / ".claude-personal" / "census"

    def test_falls_back_to_home_claude(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CENSUS_STORE", raising=False)
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        monkeypatch.setattr(st.Path, "home", classmethod(lambda cls: tmp_path))
        assert st.census_dir() == tmp_path / ".claude" / "census"


class TestSafeSessionId:
    def test_uuid_is_safe(self):
        sid = "0c843531-0068-439d-bb54-2a3b48806e82"
        assert st.safe_session_id(sid) == sid

    def test_rejects_unsafe(self):
        for bad in ["", "../x", "a/b", ".hidden", "x" * 129, None, 7, "a b"]:
            assert st.safe_session_id(bad) is None, bad

    def test_session_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "c"))
        assert st.session_path("s1") == tmp_path / "c" / "sessions" / "s1.json"


class TestAccountIsolation:
    def test_two_accounts_write_separate_stores(self, tmp_path, monkeypatch):
        personal = tmp_path / ".claude-personal"
        work = tmp_path / ".claude"
        monkeypatch.delenv("CENSUS_STORE", raising=False)

        # personal (Max) session — carries live rate_limits (future resets_at)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(personal))
        st.ingest(json.dumps({
            "session_id": "p1", "cwd": "/proj/personal",
            "rate_limits": {"five_hour": {"used_percentage": 55, "resets_at": 1000}},
        }), now=1.0)

        # work (API) session — no rate_limits
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(work))
        st.ingest(json.dumps({"session_id": "w1", "cwd": "/proj/work"}), now=2.0)

        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(personal))
        p_store = st.read_all()
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(work))
        w_store = st.read_all()

        # sessions do not leak across accounts
        assert set(p_store["sessions"]) == {"p1"}
        assert set(w_store["sessions"]) == {"w1"}
        # the personal Max limits never appear in the work store
        assert p_store["limits"]["five_hour"]["used_percentage"] == 55
        assert w_store["limits"] is None
