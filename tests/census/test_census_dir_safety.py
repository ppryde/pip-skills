"""SS-2: a CENSUS_STORE that resolves to the Claude config dir must not let census sweep or purge Claude Code's own
`sessions/` (its pid registry). Ingest refuses, `where` warns, install and purge refuse, and even where a sweep or purge
does run it only touches census-shaped records."""
import json
import time

import pytest

from scripts import cli
from scripts import install as ins
from scripts import store as st
from scripts import where as wh


@pytest.fixture
def aimed(tmp_path, monkeypatch):
    """CENSUS_STORE=<config dir>/x.json: the legacy spelling that maps to the config dir itself."""
    cfg = tmp_path / "cfg"
    (cfg / "sessions").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("CENSUS_STORE", str(cfg / "status.json"))
    registry = cfg / "sessions" / "4242.json"
    registry.write_text(json.dumps({"pid": 4242, "sessionId": "abc", "procStart": "Mon Oct  5 10:00:00 2026"}))
    return cfg, registry


def test_the_census_dir_is_the_config_dir_here(aimed):
    cfg, _ = aimed
    assert st.census_dir_is_config() is True
    assert st.census_dir() == cfg


def test_the_default_layout_is_not_flagged(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.delenv("CENSUS_STORE", raising=False)
    assert st.census_dir_is_config() is False


def test_ingest_refuses_and_writes_nothing(aimed):
    cfg, registry = aimed
    before = sorted(p.name for p in (cfg / "sessions").iterdir())
    st.ingest(json.dumps({"session_id": "s1", "cwd": "/wt"}), now=time.time())
    assert sorted(p.name for p in (cfg / "sessions").iterdir()) == before
    assert registry.exists() and not (cfg / ".sweep").exists()


def test_a_sweep_leaves_a_file_that_is_not_a_census_record(tmp_path, monkeypatch):
    monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "census"))
    foreign = st.sessions_dir() / "4242.json"
    foreign.parent.mkdir(parents=True)
    foreign.write_text(json.dumps({"pid": 4242, "sessionId": "abc"}))
    st.ingest(json.dumps({"session_id": "s1", "cwd": "/wt"}), now=time.time())
    assert foreign.exists()


def test_where_warns(aimed):
    notes = wh.report()["notes"]
    assert any("census dir is the Claude config dir" in n for n in notes)


def test_install_refuses(aimed, tmp_path, capsys):
    cfg, _ = aimed
    (cfg / "settings.json").write_text("{}")
    code = cli.main(["install", "--statusline", "--shim", str(tmp_path / "bin" / "census"), "--yes"])
    assert code == 1
    assert "census dir is the Claude config dir" in capsys.readouterr().out
    assert json.loads((cfg / "settings.json").read_text()) == {}


def test_purge_refuses_and_keeps_the_registry(aimed, tmp_path, capsys):
    cfg, registry = aimed
    code = cli.main(["uninstall", "--purge", "--yes", "--shim", str(tmp_path / "bin" / "census"),
                     "--script", str(cfg / "none.sh")])
    assert code == 1
    assert registry.exists()
    assert "census dir is the Claude config dir" in capsys.readouterr().out


def test_a_purge_removes_only_census_shaped_files(tmp_path, monkeypatch):
    monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "census"))
    census = st.census_dir()
    (census / "sessions").mkdir(parents=True)
    mine = census / "sessions" / "s1.json"
    mine.write_text(json.dumps({"version": 2, "updated_at": 1.0, "payload": {"session_id": "s1"}}))
    foreign = census / "sessions" / "4242.json"
    foreign.write_text(json.dumps({"pid": 4242, "sessionId": "abc"}))
    lines = ins._purge(census, apply=True)
    assert not mine.exists() and foreign.exists()
    assert any("kept" in line for line in lines)
