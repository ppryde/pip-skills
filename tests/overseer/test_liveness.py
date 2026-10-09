from __future__ import annotations

import json
import os
import sys
import time

from scripts import liveness


def test_live_session_ids_returns_none_without_census(tmp_path, monkeypatch):
    monkeypatch.delenv("CENSUS_STORE", raising=False)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "nope"))
    assert liveness.live_session_ids() is None


def test_live_session_ids_reads_census_store(tmp_path, monkeypatch):
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True)
    now = time.time()  # census (the real CLI) judges against the real clock
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


def test_live_session_ids_just_inside_the_horizon_is_live(tmp_path, monkeypatch):
    store = tmp_path / "status.json"
    now = time.time()  # census (the real CLI) judges against the real clock
    store.write_text(json.dumps({
        "sessions": {"sess-edge": {"updated_at": now - liveness.STALE_HORIZON_SECONDS + 10}},
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
    now = time.time()  # census (the real CLI) judges against the real clock
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
    now = time.time()  # census (the real CLI) judges against the real clock
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
    now = time.time()  # census (the real CLI) judges against the real clock
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
    now = time.time()  # census (the real CLI) judges against the real clock
    (sessions / "live.json").write_text(json.dumps({"version": 2, "updated_at": now}))
    (sessions / "old.json").write_text(json.dumps({"version": 2, "updated_at": now - 999}))
    monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "census"))
    monkeypatch.setattr(liveness, "_now_epoch", lambda: now)
    assert liveness.live_session_ids() == {"live"}


class TestCensusCliDiscovery:
    @staticmethod
    def _pointer(tmp_path, monkeypatch, target):
        monkeypatch.delenv("CENSUS_CLI", raising=False)
        monkeypatch.delenv("CENSUS_STORE", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        monkeypatch.setenv("PATH", str(tmp_path / "emptybin"))
        pointer = tmp_path / "cfg" / "census" / "cli.path"
        pointer.parent.mkdir(parents=True)
        pointer.write_text(str(target))
        return pointer

    def test_pointer_to_existing_cli_is_used(self, tmp_path, monkeypatch):
        fake = tmp_path / "cli.py"
        fake.write_text("")
        self._pointer(tmp_path, monkeypatch, fake)
        assert liveness.census_cli() == [sys.executable, str(fake)]

    def test_pointer_to_missing_file_falls_through_to_none(self, tmp_path, monkeypatch):
        self._pointer(tmp_path, monkeypatch, tmp_path / "gone.py")
        assert liveness.census_cli() is None

    def test_missing_pointer_falls_through_to_path(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CENSUS_CLI", raising=False)
        monkeypatch.delenv("CENSUS_STORE", raising=False)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
        binary = tmp_path / "bin" / "census"
        binary.parent.mkdir()
        binary.write_text("#!/bin/sh\n")
        binary.chmod(0o755)
        monkeypatch.setenv("PATH", str(binary.parent))
        assert liveness.census_cli() == [str(binary)]

    def test_census_cli_env_beats_pointer(self, tmp_path, monkeypatch):
        fake = tmp_path / "cli.py"
        fake.write_text("")
        self._pointer(tmp_path, monkeypatch, fake)
        monkeypatch.setenv("CENSUS_CLI", "/somewhere/census")
        assert liveness.census_cli() == ["/somewhere/census"]

    def test_census_store_json_resolves_pointer_in_parent(self, tmp_path, monkeypatch):
        fake = tmp_path / "cli.py"
        fake.write_text("")
        self._pointer(tmp_path, monkeypatch, tmp_path / "unused.py")
        store = tmp_path / "elsewhere" / "status.json"
        store.parent.mkdir()
        (store.parent / "cli.path").write_text(str(fake))
        monkeypatch.setenv("CENSUS_STORE", str(store))
        assert liveness.census_cli() == [sys.executable, str(fake)]


def _view(monkeypatch, sessions):
    monkeypatch.setattr(liveness, "_census_view", lambda: {"version": 1, "sessions": sessions})
    monkeypatch.setattr(liveness, "_now_epoch", lambda: 1_000_000.0)


def test_census_stale_false_keeps_an_old_entry_live(monkeypatch):
    """A census-mod session has no heartbeat: ancient updated_at, process alive."""
    _view(monkeypatch, {"mod": {"updated_at": 1.0, "stale": False}})
    assert liveness.live_session_ids() == {"mod"}


def test_census_stale_true_beats_a_fresh_updated_at(monkeypatch):
    _view(monkeypatch, {"gone": {"updated_at": 1_000_000.0, "stale": True}, "ok": {"updated_at": 1_000_000.0}})
    assert liveness.live_session_ids() == {"ok"}


def test_a_non_bool_stale_falls_back_to_the_age_rule(monkeypatch):
    _view(monkeypatch, {"a": {"updated_at": 1_000_000.0, "stale": "no"}, "b": {"updated_at": 1.0, "stale": None}})
    assert liveness.live_session_ids() == {"a"}


def test_end_to_end_a_census_mod_session_is_judged_by_its_process(tmp_path, monkeypatch):
    """Through the real census CLI: updated_at is ancient, the process (this one) is alive."""
    config = tmp_path / "cfg"
    (config / "sessions").mkdir(parents=True)
    start = "Thu Oct  9 10:00:00 2026"
    (config / "sessions" / f"{os.getpid()}.json").write_text(json.dumps({"procStart": start}))
    census = tmp_path / "census" / "sessions"
    census.mkdir(parents=True)
    live = {"version": 2, "updated_at": 1.0, "payload": {"census_mod": {"pid": os.getpid(), "proc_start": start}}}
    ended = {"version": 2, "updated_at": time.time(),
             "payload": {"census_mod": {"pid": os.getpid(), "proc_start": start, "ended": 5}}}
    (census / "live.json").write_text(json.dumps(live))
    (census / "ended.json").write_text(json.dumps(ended))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "census"))
    assert liveness.live_session_ids() == {"live"}
