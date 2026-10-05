from __future__ import annotations

import json

from scripts import liveness


def test_live_session_ids_returns_none_without_census(tmp_path, monkeypatch):
    monkeypatch.delenv("CENSUS_STORE", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "nope"))
    assert liveness.live_session_ids() is None


def test_live_session_ids_reads_census_store(tmp_path, monkeypatch):
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True)
    now = 1_000_000.0
    store.write_text(json.dumps({
        "version": 1,
        "limits": None,
        "sessions": {
            "sess-live": {"worktree_cwd": "/tmp/x", "updated_at": now},
            "sess-old": {"worktree_cwd": "/tmp/x", "updated_at": now - 999},
        },
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))
    monkeypatch.setattr(liveness, "_now_epoch", lambda: now)
    assert liveness.live_session_ids() == {"sess-live"}


def test_live_session_ids_exactly_at_horizon_is_live(tmp_path, monkeypatch):
    store = tmp_path / "status.json"
    now = 1_000_000.0
    store.write_text(json.dumps({
        "sessions": {"sess-edge": {"updated_at": now - liveness.STALE_HORIZON_SECONDS}},
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))
    monkeypatch.setattr(liveness, "_now_epoch", lambda: now)
    assert liveness.live_session_ids() == {"sess-edge"}


def test_live_session_ids_none_on_malformed_json(tmp_path, monkeypatch):
    store = tmp_path / "status.json"
    store.write_text("not json at all")
    monkeypatch.setenv("CENSUS_STORE", str(store))
    assert liveness.live_session_ids() is None


def test_live_session_ids_none_when_sessions_key_missing(tmp_path, monkeypatch):
    store = tmp_path / "status.json"
    store.write_text(json.dumps({"version": 1}))
    monkeypatch.setenv("CENSUS_STORE", str(store))
    assert liveness.live_session_ids() is None


def test_live_session_ids_skips_malformed_entries(tmp_path, monkeypatch):
    store = tmp_path / "status.json"
    now = 1_000_000.0
    store.write_text(json.dumps({
        "sessions": {
            "sess-good": {"updated_at": now},
            "sess-bad-shape": "not a dict",
            "sess-bad-ts": {"updated_at": "not-a-number"},
        },
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))
    monkeypatch.setattr(liveness, "_now_epoch", lambda: now)
    assert liveness.live_session_ids() == {"sess-good"}


def test_live_session_ids_honours_config_dir_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("CENSUS_STORE", raising=False)
    config = tmp_path / "cfg"
    store = config / "census" / "status.json"
    store.parent.mkdir(parents=True)
    now = 1_000_000.0
    store.write_text(json.dumps({"sessions": {"sess-live": {"updated_at": now}}}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    monkeypatch.setattr(liveness, "_now_epoch", lambda: now)
    assert liveness.live_session_ids() == {"sess-live"}


def test_empty_sessions_is_unknown_not_none_live(tmp_path, monkeypatch):
    monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "census"))
    (tmp_path / "census" / "sessions").mkdir(parents=True)
    assert liveness.live_session_ids() is None


def test_cli_failure_is_unknown(tmp_path, monkeypatch):
    fake = tmp_path / "fake-census"
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(0o755)
    monkeypatch.setenv("CENSUS_CLI", str(fake))
    assert liveness.live_session_ids() is None


def test_junk_output_is_unknown(tmp_path, monkeypatch):
    fake = tmp_path / "fake-census"
    fake.write_text("#!/bin/sh\necho '[1,2]'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("CENSUS_CLI", str(fake))
    assert liveness.live_session_ids() is None


def test_cli_timeout_is_unknown(tmp_path, monkeypatch):
    fake = tmp_path / "fake-census"
    fake.write_text("#!/bin/sh\nexec sleep 5\n")
    fake.chmod(0o755)
    monkeypatch.setenv("CENSUS_CLI", str(fake))
    monkeypatch.setattr(liveness, "_TIMEOUT_SECONDS", 0.2)
    assert liveness.live_session_ids() is None


def test_fake_cli_view_yields_only_fresh_sessions(tmp_path, monkeypatch):
    now = 1_000_000.0
    view = {
        "version": 1,
        "limits": None,
        "sessions": {
            "fresh": {"updated_at": now},
            "stale": {"updated_at": now - 999},
        },
    }
    fake = tmp_path / "fake-census"
    fake.write_text(f"#!/bin/sh\ncat <<'EOF_VIEW'\n{json.dumps(view)}\nEOF_VIEW\n")
    fake.chmod(0o755)
    monkeypatch.setenv("CENSUS_CLI", str(fake))
    monkeypatch.setattr(liveness, "_now_epoch", lambda: now)
    assert liveness.live_session_ids() == {"fresh"}


def test_reads_v2_session_files(tmp_path, monkeypatch):
    sessions = tmp_path / "census" / "sessions"
    sessions.mkdir(parents=True)
    now = 1_000_000.0
    (sessions / "live.json").write_text(json.dumps({"version": 2, "updated_at": now}))
    (sessions / "old.json").write_text(json.dumps({"version": 2, "updated_at": now - 999}))
    monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "census"))
    monkeypatch.setattr(liveness, "_now_epoch", lambda: now)
    assert liveness.live_session_ids() == {"live"}


def _cache(tmp_path, versions, orphaned=()):
    base = tmp_path / "cache" / "mkt"
    for ver in versions:
        cli = base / "census" / ver / "scripts" / "cli.py"
        cli.parent.mkdir(parents=True)
        cli.write_text("")
    for ver in orphaned:
        (base / "census" / ver / ".orphaned_at").write_text("1")
    here = base / "overseer" / "0.2.2" / "scripts" / "liveness.py"
    here.parent.mkdir(parents=True)
    here.write_text("")
    return base, here


class TestFindCensusInCache:
    def test_finds_cached_census_not_a_sibling(self, tmp_path):
        base, here = _cache(tmp_path, ["0.3.0"])
        assert liveness.find_census(_from=here) == base / "census" / "0.3.0" / "scripts" / "cli.py"

    def test_prefers_highest_version_numerically(self, tmp_path):
        base, here = _cache(tmp_path, ["0.9.0", "0.10.0"])
        assert liveness.find_census(_from=here).parents[1].name == "0.10.0"

    def test_skips_orphaned(self, tmp_path):
        base, here = _cache(tmp_path, ["0.9.0", "0.10.0"], orphaned=["0.10.0"])
        assert liveness.find_census(_from=here).parents[1].name == "0.9.0"

    def test_repo_layout_and_absent(self, tmp_path):
        direct = tmp_path / "plugins" / "census" / "scripts" / "cli.py"
        direct.parent.mkdir(parents=True)
        direct.write_text("")
        here = tmp_path / "plugins" / "overseer" / "scripts" / "liveness.py"
        here.parent.mkdir(parents=True)
        here.write_text("")
        assert liveness.find_census(_from=here) == direct
        assert liveness.find_census(_from=tmp_path / "nowhere" / "x.py") is None
