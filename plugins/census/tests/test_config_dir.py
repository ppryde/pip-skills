"""Store must be rooted at CLAUDE_CONFIG_DIR so multiple accounts never commingle."""
import json

from scripts import store as st


class TestStorePath:
    def test_censusstore_override_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "x.json"))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        assert st.store_path() == tmp_path / "x.json"

    def test_rooted_at_config_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CENSUS_STORE", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / ".claude-personal"))
        assert st.store_path() == tmp_path / ".claude-personal" / "census" / "status.json"

    def test_falls_back_to_home_claude(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CENSUS_STORE", raising=False)
        monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
        monkeypatch.setattr(st.Path, "home", classmethod(lambda cls: tmp_path))
        assert st.store_path() == tmp_path / ".claude" / "census" / "status.json"


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

        p_store = json.loads((personal / "census" / "status.json").read_text())
        w_store = json.loads((work / "census" / "status.json").read_text())

        # sessions do not leak across accounts
        assert set(p_store["sessions"]) == {"p1"}
        assert set(w_store["sessions"]) == {"w1"}
        # the personal Max limits never appear in the work store
        assert p_store["limits"]["five_hour"]["used_percentage"] == 55
        assert w_store["limits"] is None
