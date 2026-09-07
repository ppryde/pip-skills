"""WF-053: the dashboard runtime record and the restart-on-stale check.

No real servers, no real pids, no real HTTP: liveness, the version probe,
the detached worker spawn, the kill and the relaunch are all injected. The
config dir is the test's own (autouse fixture in conftest), so the record
lands under tmp_path."""
import json
import os
import time

import pytest
from scripts import dashboard_record as dr
from scripts.cli import main


def _answers(version="0.21.0"):
    """A probe that says a real dashboard is there, running `version`."""
    return lambda host, port: {"version": version}


#: A probe that gets no answer — nothing is listening on that host/port.
def _silent(host, port):
    return


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
        assert dr.version_tuple("0.21.3") == (0, 21, 3, 0)
        assert dr.version_tuple("1.0") < dr.version_tuple("1.0.1")
        assert dr.version_tuple("1.0") == dr.version_tuple("1.0.0")  # padded alike
        assert dr.version_tuple("v0.21.3") == dr.version_tuple("0.21.3")
        assert dr.version_tuple("") == ()
        assert dr.version_tuple("garbage") == ()
        assert dr.version_tuple("") < dr.version_tuple("0.0.1")  # unparseable is lowest

    def test_version_tuple_reads_only_the_leading_dotted_numbers(self):
        # The digits-anywhere scan this replaced turned "0.22.0-rc1" into
        # (0, 22, 1) — a version that does not exist, and one that outranked
        # the 0.22.0 release it precedes.
        assert dr.version_tuple("0.22.0-rc1")[:3] == (0, 22, 0)
        assert dr.version_tuple("0.22.0-rc1") < dr.version_tuple("0.22.0")
        assert dr.version_tuple("0.22.0-rc1") < dr.version_tuple("0.22.1")
        assert dr.version_tuple("0.21.0") < dr.version_tuple("0.22.0-rc1")
        assert dr.version_tuple("0.22.0+build.7") < dr.version_tuple("0.22.0")


    def test_pid_alive(self):
        assert dr.pid_alive(os.getpid()) is True
        assert dr.pid_alive(0) is False
        assert dr.pid_alive(2**22 + 12345) is False  # beyond any real pid on a dev box


class TestRestartIfStale:
    """The session-start decision. It never kills or launches anything
    itself — it hands both to a detached worker — so `calls["spawned"]`
    staying empty is proof that no process was signalled."""

    @pytest.fixture
    def calls(self):
        return {"spawned": [], "probed": []}

    def _run(self, calls, *, alive=True, probe=None, installed="0.22.0", now=None):
        if probe is None:
            probe = _answers()

        def _probe(host, port):
            calls["probed"].append((host, port))
            return probe(host, port)

        return dr.restart_if_stale(
            now=now,
            installed=installed,
            alive=lambda pid: alive,
            probe=_probe,
            spawn=lambda owner: (calls["spawned"].append(owner), 5151)[1],
        )

    def test_no_record_is_a_no_op(self, calls):
        assert self._run(calls) is None
        assert calls == {"spawned": [], "probed": []}

    def test_dead_pid_is_a_no_op_and_cleans_the_record(self, calls):
        _record()
        assert self._run(calls, alive=False) is None
        assert dr.read_record() is None
        assert calls["spawned"] == []
        assert calls["probed"] == []  # nothing to probe

    def test_a_live_but_silent_pid_is_never_touched(self, calls):
        """The mortal sin this guards: after a reboot the record survives and
        its pid may belong to a stranger. No answer to the probe means not
        running — drop the stamp, signal nobody, start nothing."""
        _record(version="0.20.0")
        assert self._run(calls, probe=_silent) is None
        assert calls["spawned"] == []  # no kill, no relaunch
        assert dr.read_record() is None  # the stale stamp is cleaned
        assert calls["probed"] == [("0.0.0.0", 8770)]

    @pytest.mark.parametrize("running", ["0.22.0", "0.23.0"])
    def test_equal_or_newer_running_never_restarts(self, calls, running):
        _record()
        assert self._run(calls, probe=_answers(running)) is None
        assert calls["spawned"] == []

    def test_older_running_hands_off_to_the_detached_worker(self, calls):
        _record()
        msg = self._run(calls)
        assert msg == "overseer dashboard restarting 0.21.0 → 0.22.0 (pid 4242)"
        assert len(calls["spawned"]) == 1
        # The lock stays held for the worker, stamped with the owner it was
        # handed — the worker releases it when the restart is done.
        assert dr.lock_path().read_text() == calls["spawned"][0]

    def test_the_stamp_only_fills_in_a_probe_answer_missing_a_version(self, calls):
        _record(version="0.20.0")
        assert self._run(calls, probe=lambda host, port: {}) is not None
        assert calls["spawned"]
        # ...and never overrides what the live server actually says.
        _record(version="0.20.0")
        assert self._run(calls, probe=_answers("0.99.0")) is None

    def test_unknown_installed_version_is_a_no_op(self, calls):
        _record()
        assert self._run(calls, installed="") is None
        assert calls["spawned"] == []

    def test_a_failed_spawn_releases_the_lock_and_stays_silent(self, calls):
        _record()

        def boom(owner):
            raise OSError("no fork for you")

        assert dr.restart_if_stale(
            installed="0.22.0", alive=lambda pid: True,
            probe=_answers(), spawn=boom,
        ) is None
        assert not dr.lock_path().exists()

    def test_a_fresh_lock_debounces_a_second_session(self, calls):
        _record()
        dr.lock_path().parent.mkdir(parents=True, exist_ok=True)
        dr.lock_path().write_text("other-session")
        assert self._run(calls, now=time.time()) is None
        assert calls["spawned"] == []
        # A stale lock (older than the TTL) is taken over.
        old = time.time() - dr.LOCK_TTL_SECONDS - 5
        os.utime(dr.lock_path(), (old, old))
        assert self._run(calls, now=time.time()) is not None
        assert len(calls["spawned"]) == 1

    def test_record_missing_relaunch_details_is_a_no_op(self, calls):
        _record(serve="")
        assert self._run(calls) is None
        assert calls["spawned"] == []


class TestLock:
    def test_release_only_removes_our_own_lock(self):
        assert dr._take_lock(time.time(), "mine") is True
        dr._release_lock("someone-else")
        assert dr.lock_path().exists()  # not ours to delete
        dr._release_lock("mine")
        assert not dr.lock_path().exists()

    def test_stale_takeover_leaves_no_temp_file_and_records_the_new_owner(self):
        assert dr._take_lock(time.time(), "first") is True
        old = time.time() - dr.LOCK_TTL_SECONDS - 5
        os.utime(dr.lock_path(), (old, old))
        assert dr._take_lock(time.time(), "second") is True
        assert dr.lock_path().read_text() == "second"
        assert not list(dr.lock_path().parent.glob("*.tmp"))
        # The loser of the takeover must not be able to unlink the winner's.
        dr._release_lock("first")
        assert dr.lock_path().exists()


class TestRestartWorker:
    """The detached half — the only place that signals or spawns."""

    def _calls(self):
        return {"terminated": [], "launched": []}

    def test_kills_the_recorded_server_and_relaunches_it_as_recorded(self):
        rec = _record()
        calls = self._calls()
        dr._take_lock(time.time(), "owner")
        rc = dr.run_restart_worker(
            "owner",
            terminate=lambda pid: (calls["terminated"].append(pid), True)[1],
            relaunch=lambda r: (calls["launched"].append(r), 5151)[1],
        )
        assert rc == 0
        assert calls["terminated"] == [4242]
        assert calls["launched"] == [rec]  # same host/port/root/python/serve
        assert not dr.lock_path().exists()  # lock released
        assert dr.take_failure_note() is None

    def test_a_kill_that_fails_means_no_relaunch(self):
        _record()
        calls = self._calls()
        assert dr.run_restart_worker(
            "owner",
            terminate=lambda pid: False,
            relaunch=lambda r: calls["launched"].append(r),
        ) == 1
        assert calls["launched"] == []

    def test_a_relaunch_that_raises_leaves_a_note_for_the_next_session(self):
        _record()

        def boom(record):
            raise RuntimeError("port taken")

        dr._take_lock(time.time(), "owner")
        assert dr.run_restart_worker("owner", terminate=lambda pid: True, relaunch=boom) == 1
        assert not dr.lock_path().exists()
        note = dr.take_failure_note()
        assert note and "FAILED" in note and "port taken" in note
        assert dr.take_failure_note() is None  # read once, then cleared

    def test_no_record_is_a_no_op(self):
        calls = self._calls()
        assert dr.run_restart_worker(
            "owner",
            terminate=lambda pid: calls["terminated"].append(pid),
            relaunch=lambda r: calls["launched"].append(r),
        ) == 0
        assert calls == {"terminated": [], "launched": []}

    def test_worker_main_reads_the_lock_owner_from_argv(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(dr, "run_restart_worker", lambda owner: seen.setdefault("owner", owner))
        dr._worker_main(["--restart-worker", "--lock-owner", "tok123"])
        assert seen["owner"] == "tok123"


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

    def test_reports_a_failed_restart_left_by_an_earlier_session(self, capsys, tmp_path):
        """The worker stopped the old server and could not start the new one:
        the dashboard is DOWN, and saying nothing would hide that."""
        dr._write_failure("overseer dashboard restart FAILED — port taken")
        assert main(["--root", str(tmp_path), "dashboard-refresh-hook"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["systemMessage"] == "overseer dashboard restart FAILED — port taken"
        # Reported once, then cleared.
        assert main(["--root", str(tmp_path), "dashboard-refresh-hook"]) == 0
        assert capsys.readouterr().out == ""

    def test_a_note_still_reaches_the_session_when_the_check_itself_blows_up(
        self, monkeypatch, capsys, tmp_path
    ):
        def boom(**kw):
            raise RuntimeError("no")
        monkeypatch.setattr(dr, "restart_if_stale", boom)
        dr._write_failure("overseer dashboard restart FAILED — port taken")
        assert main(["--root", str(tmp_path), "dashboard-refresh-hook"]) == 0
        assert "FAILED" in json.loads(capsys.readouterr().out)["systemMessage"]
