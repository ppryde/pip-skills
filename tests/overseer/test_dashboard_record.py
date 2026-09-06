"""WF-053: the dashboard runtime record and the restart-on-stale check.

No real servers, no real pids: liveness, the version probe, the kill and
the relaunch are all injected. The config dir is the test's own (autouse
fixture in conftest), so the record lands under tmp_path."""
import json
import os
import time

import pytest
from scripts import dashboard_record as dr
from scripts.cli import main


def _record(**over):
    base = {
        "pid": 4242, "host": "0.0.0.0", "port": 8770, "root": "/repo",
        "version": "0.21.0", "started_at": "2026-09-06T10:00:00",
        "python": "/venv/bin/python", "serve": "/plugins/overseer/dashboard/serve.py",
    }
    base.update(over)
    dr.write_record(base)
    return base


class TestRecord:
    def test_write_read_remove_round_trip(self):
        assert dr.read_record() is None
        rec = _record()
        assert dr.read_record() == rec
        assert dr.record_path().name == ".dashboard.json"
        assert not list(dr.record_path().parent.glob("*.tmp"))  # atomic: no temp left
        # Only the owner's pid removes it.
        assert dr.remove_record(999) is False
        assert dr.read_record() is not None
        assert dr.remove_record(4242) is True
        assert dr.read_record() is None

    def test_malformed_record_reads_as_none(self):
        dr.record_path().parent.mkdir(parents=True, exist_ok=True)
        dr.record_path().write_text("{not json")
        assert dr.read_record() is None

    def test_stamp_carries_how_to_relaunch(self, tmp_path):
        rec = dr.stamp(host="127.0.0.1", port=9001, root=tmp_path, serve=tmp_path / "serve.py")
        assert rec["pid"] == os.getpid()
        assert rec["python"] and rec["serve"].endswith("serve.py")
        assert rec["version"] == dr.plugin_version() != ""

    def test_version_tuple(self):
        assert dr.version_tuple("0.21.3") == (0, 21, 3)
        assert dr.version_tuple("1.0") < dr.version_tuple("1.0.1")
        assert dr.version_tuple("") == ()
        assert dr.version_tuple("garbage") == ()

    def test_pid_alive(self):
        assert dr.pid_alive(os.getpid()) is True
        assert dr.pid_alive(0) is False
        assert dr.pid_alive(2**22 + 12345) is False  # beyond any real pid on a dev box


class TestRestartIfStale:
    @pytest.fixture
    def calls(self):
        return {"terminated": [], "launched": []}

    def _run(self, calls, *, alive=True, running="0.21.0", installed="0.22.0", now=None,
             terminate_ok=True):
        return dr.restart_if_stale(
            now=now,
            installed=installed,
            alive=lambda pid: alive,
            ask_version=lambda host, port: running,
            terminate=lambda pid: (calls["terminated"].append(pid), terminate_ok)[1],
            relaunch=lambda rec: (calls["launched"].append(rec), 5151)[1],
        )

    def test_no_record_is_a_no_op(self, calls):
        assert self._run(calls) is None
        assert calls == {"terminated": [], "launched": []}

    def test_dead_pid_is_a_no_op_and_cleans_the_record(self, calls):
        _record()
        assert self._run(calls, alive=False) is None
        assert dr.read_record() is None
        assert calls["launched"] == []

    @pytest.mark.parametrize("running", ["0.22.0", "0.23.0"])
    def test_equal_or_newer_running_never_restarts(self, calls, running):
        _record()
        assert self._run(calls, running=running) is None
        assert calls["launched"] == []

    def test_older_running_is_killed_and_relaunched_as_recorded(self, calls):
        rec = _record()
        msg = self._run(calls)
        assert msg == "overseer dashboard restarted 0.21.0 → 0.22.0 (pid 4242 → 5151)"
        assert calls["terminated"] == [4242]
        assert calls["launched"] == [rec]  # same host/port/root/python/serve
        assert not dr.lock_path().exists()  # lock released

    def test_falls_back_to_the_stamped_version_when_the_server_does_not_answer(self, calls):
        _record(version="0.20.0")
        assert self._run(calls, running=None) is not None
        assert calls["launched"]

    def test_unknown_installed_version_is_a_no_op(self, calls):
        _record()
        assert self._run(calls, installed="") is None
        assert calls["launched"] == []

    def test_kill_failure_means_no_relaunch(self, calls):
        _record()
        assert self._run(calls, terminate_ok=False) is None
        assert calls["launched"] == []
        assert not dr.lock_path().exists()

    def test_a_fresh_lock_debounces_a_second_session(self, calls):
        _record()
        dr.lock_path().parent.mkdir(parents=True, exist_ok=True)
        dr.lock_path().write_text("other")
        assert self._run(calls, now=time.time()) is None
        assert calls["launched"] == []
        # A stale lock (older than the TTL) is taken over.
        old = time.time() - dr.LOCK_TTL_SECONDS - 5
        os.utime(dr.lock_path(), (old, old))
        assert self._run(calls, now=time.time()) is not None
        assert len(calls["launched"]) == 1

    def test_record_missing_relaunch_details_is_a_no_op(self, calls):
        _record(serve="")
        assert self._run(calls) is None
        assert calls["launched"] == []


class TestHookVerb:
    def test_prints_a_system_message_only_when_it_restarted(self, monkeypatch, capsys, tmp_path):
        assert main(["--root", str(tmp_path), "dashboard-refresh-hook"]) == 0
        assert capsys.readouterr().out == ""
        monkeypatch.setattr(dr, "restart_if_stale", lambda **kw: "overseer dashboard restarted 1 → 2")
        assert main(["--root", str(tmp_path), "dashboard-refresh-hook"]) == 0
        assert json.loads(capsys.readouterr().out) == {"systemMessage": "overseer dashboard restarted 1 → 2"}

    def test_fails_open(self, monkeypatch, capsys, tmp_path):
        def boom(**kw):
            raise RuntimeError("no")
        monkeypatch.setattr(dr, "restart_if_stale", boom)
        assert main(["--root", str(tmp_path), "dashboard-refresh-hook"]) == 0
        assert capsys.readouterr().out == ""
