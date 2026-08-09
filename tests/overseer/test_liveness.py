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
