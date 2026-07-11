import json
import time

from scripts import census


def _store(store_file, root, pct, *, updated=None, sid="s1"):
    import os
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
    def test_censusstore_env_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "x.json"))
        assert census.store_path() == tmp_path / "x.json"

    def test_rooted_at_config_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CENSUS_STORE", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        assert census.store_path() == tmp_path / "cfg" / "census" / "status.json"


class TestContextPercent:
    def test_reads_pct_for_worktree(self, tmp_path, monkeypatch):
        store = tmp_path / "census" / "status.json"
        monkeypatch.setenv("CENSUS_STORE", str(store))
        _store(store, tmp_path, 37)
        assert census.context_percent(tmp_path) == 37

    def test_none_when_store_absent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "nope.json"))
        assert census.context_percent(tmp_path) is None

    def test_none_when_no_matching_worktree(self, tmp_path, monkeypatch):
        store = tmp_path / "census" / "status.json"
        monkeypatch.setenv("CENSUS_STORE", str(store))
        _store(store, tmp_path / "other", 50)
        assert census.context_percent(tmp_path) is None

    def test_none_when_stale(self, tmp_path, monkeypatch):
        store = tmp_path / "census" / "status.json"
        monkeypatch.setenv("CENSUS_STORE", str(store))
        _store(store, tmp_path, 37, updated=1000.0)
        assert census.context_percent(tmp_path, now=1000.0 + census.STALE_HORIZON_SECONDS + 1) is None

    def test_fresh_entry_returned(self, tmp_path, monkeypatch):
        store = tmp_path / "census" / "status.json"
        monkeypatch.setenv("CENSUS_STORE", str(store))
        _store(store, tmp_path, 37, updated=1000.0)
        assert census.context_percent(tmp_path, now=1000.0 + 10) == 37

    def test_rounds_float_percentage(self, tmp_path, monkeypatch):
        store = tmp_path / "census" / "status.json"
        monkeypatch.setenv("CENSUS_STORE", str(store))
        _store(store, tmp_path, 41.6)
        assert census.context_percent(tmp_path) == 42

    def test_none_when_used_percentage_missing(self, tmp_path, monkeypatch):
        store = tmp_path / "census" / "status.json"
        monkeypatch.setenv("CENSUS_STORE", str(store))
        store.parent.mkdir(parents=True, exist_ok=True)
        import os
        store.write_text(json.dumps({"sessions": {"s1": {
            "worktree_cwd": os.path.realpath(str(tmp_path)),
            "updated_at": time.time(),
            "payload": {"context_window": {"used_percentage": None}},
        }}}))
        assert census.context_percent(tmp_path) is None

    def test_corrupt_store_is_none(self, tmp_path, monkeypatch):
        store = tmp_path / "census" / "status.json"
        monkeypatch.setenv("CENSUS_STORE", str(store))
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text("{not json")
        assert census.context_percent(tmp_path) is None


class TestCmdContextIntegration:
    def test_uses_census_when_present(self, repo, monkeypatch, capsys):
        from scripts.cli import main
        store = repo / "census" / "status.json"
        monkeypatch.setenv("CENSUS_STORE", str(store))
        _store(store, repo, 37)
        assert main(["--root", str(repo), "context"]) == 0
        assert "ctx 37%" in capsys.readouterr().out

    def test_falls_back_to_unknown_when_census_absent(self, repo, monkeypatch, capsys):
        from scripts.cli import main
        monkeypatch.setenv("CENSUS_STORE", str(repo / "absent.json"))
        # no census entry and no transcript in a tmp root -> unknown, not a crash
        assert main(["--root", str(repo), "context"]) == 0
        assert "ctx unknown" in capsys.readouterr().out
