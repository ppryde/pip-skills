"""Liveness by process: an entry carrying census_mod.pid is stale when its process
is gone, not when updated_at is old. Entries without census_mod keep the 90 s rule."""
import errno
import json
import os

import pytest

from scripts import store as st

NOW = 10_000.0
START = "Thu Oct  9 10:00:00 2026"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "cfg"
    (path / "sessions").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(path))
    monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "census"))
    return path


@pytest.fixture
def alive(monkeypatch):
    """Fake os.kill: pids in `dead` raise ESRCH, `denied` raise EPERM, the rest succeed."""
    state = {"dead": set(), "denied": set(), "calls": []}

    def fake(pid, sig):
        state["calls"].append((pid, sig))
        if pid in state["dead"]:
            raise ProcessLookupError(errno.ESRCH, "no such process")
        if pid in state["denied"]:
            raise PermissionError(errno.EPERM, "not permitted")

    monkeypatch.setattr(st.os, "kill", fake)
    return state


def registry(cfg, pid, proc_start=START):
    (cfg / "sessions" / f"{pid}.json").write_text(json.dumps({"pid": pid, "procStart": proc_start}))


def entry(updated_at=NOW - 3600, mod=None):
    payload = {"session_id": "s1"}
    if mod is not None:
        payload["census_mod"] = mod
    return {"updated_at": updated_at, "payload": payload}


def mod(pid=4242, proc_start=START, **extra):
    return {"pid": pid, "proc_start": proc_start, **extra}


def stale(e, config=None):
    return st.is_stale(e, NOW, config)


class TestWithoutCensusMod:
    def test_fresh_is_live(self, cfg):
        assert stale(entry(NOW - 10)) is False

    def test_old_is_stale(self, cfg):
        assert stale(entry(NOW - 91)) is True

    def test_ninety_seconds_exactly_is_live(self, cfg):
        assert stale(entry(NOW - 90)) is False

    def test_a_census_mod_without_a_pid_keeps_the_rule(self, cfg):
        assert stale(entry(NOW - 3600, {"ended": None})) is True


class TestWithCensusMod:
    def test_live_process_is_live_however_old(self, cfg, alive):
        registry(cfg, 4242)
        assert stale(entry(NOW - 86_400, mod())) is False

    def test_ended_is_stale_even_if_the_process_lives(self, cfg, alive):
        registry(cfg, 4242)
        assert stale(entry(NOW, mod(ended=NOW - 5))) is True

    def test_gone_process_is_stale_even_if_fresh(self, cfg, alive):
        registry(cfg, 4242)
        alive["dead"].add(4242)
        assert stale(entry(NOW, mod())) is True

    def test_eperm_means_alive(self, cfg, alive):
        registry(cfg, 4242)
        alive["denied"].add(4242)
        assert stale(entry(NOW - 3600, mod())) is False

    def test_missing_registry_file_means_gone(self, cfg, alive):
        assert stale(entry(NOW, mod())) is True

    def test_reused_pid_has_a_different_proc_start(self, cfg, alive):
        registry(cfg, 4242, "Fri Oct 10 09:00:00 2026")
        assert stale(entry(NOW, mod())) is True

    def test_proc_start_is_compared_as_text_only(self, cfg, alive):
        registry(cfg, 4242, START + " ")  # not the same string, so not the same process
        assert stale(entry(NOW, mod())) is True

    @pytest.mark.parametrize("pid", [0, 1, -5])
    def test_pid_one_and_below_are_refused_without_a_kill(self, cfg, alive, pid):
        registry(cfg, pid)
        assert stale(entry(NOW, mod(pid=pid))) is True
        assert alive["calls"] == []

    @pytest.mark.parametrize("pid", ["4242", 4242.0, True, [4242]])
    def test_a_pid_that_is_not_an_int_is_unusable(self, cfg, alive, pid):
        registry(cfg, 4242)
        assert stale(entry(NOW, mod(pid=pid))) is True

    def test_missing_recorded_proc_start_cannot_match(self, cfg, alive):
        registry(cfg, 4242)
        assert stale(entry(NOW, {"pid": 4242})) is True

    def test_kill_is_signal_zero(self, cfg, alive):
        registry(cfg, 4242)
        stale(entry(NOW, mod()))
        assert alive["calls"] == [(4242, 0)]

    def test_unexpected_oserror_is_gone_not_a_crash(self, cfg, monkeypatch):
        registry(cfg, 4242)
        monkeypatch.setattr(st.os, "kill", lambda pid, sig: (_ for _ in ()).throw(OSError(errno.EINVAL, "x")))
        assert stale(entry(NOW, mod())) is True

    def test_corrupt_registry_file_means_gone(self, cfg, alive):
        (cfg / "sessions" / "4242.json").write_text("{nope")
        assert stale(entry(NOW, mod())) is True

    def test_registry_that_is_not_an_object_means_gone(self, cfg, alive):
        (cfg / "sessions" / "4242.json").write_text("[1]")
        assert stale(entry(NOW, mod())) is True

    def test_census_mod_that_is_not_an_object_keeps_the_rule(self, cfg):
        assert stale(entry(NOW - 3600, "x")) is True
        assert stale(entry(NOW - 3, "x")) is False

    def test_payload_that_is_not_an_object_keeps_the_rule(self, cfg):
        assert stale({"updated_at": NOW - 3600, "payload": "x"}) is True


class TestConfigDir:
    def test_injected_dir_wins_over_the_environment(self, cfg, alive, tmp_path):
        other = tmp_path / "other"
        (other / "sessions").mkdir(parents=True)
        registry(cfg, 4242)  # present only in the environment's dir
        assert stale(entry(NOW, mod()), config=other) is True
        assert stale(entry(NOW, mod()), config=cfg) is False

    def test_defaults_to_the_accounts_config_dir(self, cfg, alive):
        registry(cfg, 4242)
        assert stale(entry(NOW, mod())) is False


class TestReaders:
    def seed(self, cfg, alive, **kw):
        st.ingest(json.dumps({"session_id": "s1", "cwd": "/wt/a", "census_mod": mod(**kw)}), now=1.0)

    def test_for_session_uses_the_process_not_the_clock(self, cfg, alive):
        registry(cfg, 4242)
        self.seed(cfg, alive)
        assert st.for_session("s1", now=1.0 + 3600)["stale"] is False

    def test_for_session_flags_a_dead_process(self, cfg, alive):
        registry(cfg, 4242)
        self.seed(cfg, alive)
        alive["dead"].add(4242)
        assert st.for_session("s1", now=2.0)["stale"] is True

    def test_latest_for_worktree_uses_it_too(self, cfg, alive):
        registry(cfg, 4242)
        self.seed(cfg, alive)
        assert st.latest_for_worktree("/wt/a", now=1.0 + 3600)["stale"] is False

    def test_idle_is_unchanged(self, cfg, alive):
        registry(cfg, 4242)
        self.seed(cfg, alive)
        got = st.for_session("s1", now=1.0 + st.IDLE_HORIZON_SECONDS + 5)
        assert got["stale"] is False and got["idle"] is True

    def test_a_reader_never_raises_on_a_hostile_entry(self, cfg, alive, monkeypatch):
        registry(cfg, 4242)
        self.seed(cfg, alive)
        monkeypatch.setattr(st, "_registry_proc_start", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
        assert st.for_session("s1", now=2.0)["stale"] is True

    def test_the_view_keeps_the_payload_and_adds_stale(self, cfg, alive):
        registry(cfg, 4242)
        self.seed(cfg, alive)
        assert "census_mod" in st.read_all()["sessions"]["s1"]["payload"]
        assert st.read_all()["sessions"]["s1"]["stale"] is False


class TestReadViewCarriesStale:
    """`census read` adds an additive per-session `stale` boolean, from is_stale."""

    def _cli(self, capsys, *argv):
        from scripts import cli

        cli.main(["read", *argv])
        return json.loads(capsys.readouterr().out)

    def seed(self, cfg, alive, sid="s1", cwd="/wt/a", **kw):
        st.ingest(json.dumps({"session_id": sid, "cwd": cwd, "census_mod": mod(**kw)}), now=1.0)

    def test_full_view_entries_carry_stale(self, cfg, alive, capsys):
        registry(cfg, 4242)
        self.seed(cfg, alive)
        st.ingest(json.dumps({"session_id": "plain", "cwd": "/wt/b"}), now=1.0)  # no census_mod, ancient
        view = self._cli(capsys)
        assert view["sessions"]["s1"]["stale"] is False  # live process, however old
        assert view["sessions"]["plain"]["stale"] is True  # 90 s rule

    def test_full_view_marks_a_dead_process(self, cfg, alive, capsys):
        registry(cfg, 4242)
        self.seed(cfg, alive)
        alive["dead"].add(4242)
        assert self._cli(capsys)["sessions"]["s1"]["stale"] is True

    def test_single_entry_forms_agree(self, cfg, alive, capsys):
        registry(cfg, 4242)
        self.seed(cfg, alive)
        assert self._cli(capsys, "--session", "s1")["stale"] is False
        assert self._cli(capsys, "--worktree", "/wt/a")["stale"] is False

    def test_only_stale_is_added(self, cfg, alive, capsys):
        registry(cfg, 4242)
        self.seed(cfg, alive)
        stored = json.loads(st.session_path("s1").read_text())
        stored.pop("version")
        shown = self._cli(capsys)["sessions"]["s1"]
        assert {k: v for k, v in shown.items() if k != "stale"} == stored

    def test_stale_is_not_written_to_the_store(self, cfg, alive, capsys):
        registry(cfg, 4242)
        self.seed(cfg, alive)
        self._cli(capsys)
        assert "stale" not in json.loads(st.session_path("s1").read_text())
