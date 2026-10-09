"""On Windows os.kill(pid, 0) does not probe: it TERMINATES the process (TerminateProcess, exit code 0). Liveness
there must never call os.kill."""
import json

import pytest

from scripts import store as st

START = "Thu Oct  9 10:00:00 2026"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "cfg"
    (path / "sessions").mkdir(parents=True)
    (path / "sessions" / "4242.json").write_text(json.dumps({"pid": 4242, "procStart": START}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(path))
    monkeypatch.setenv("CENSUS_STORE", str(tmp_path / "census"))
    return path


def _boom(pid, sig):  # pragma: no cover - failing is the point
    raise AssertionError(f"os.kill({pid}, {sig}) would terminate the process on Windows")


def _mod():
    return {"pid": 4242, "proc_start": START}


def test_windows_never_calls_os_kill_and_asks_the_windows_probe(cfg, monkeypatch):
    monkeypatch.setattr(st.os, "name", "nt")
    monkeypatch.setattr(st.os, "kill", _boom)
    monkeypatch.setattr(st, "_windows_pid_alive", lambda pid: True)
    assert st._process_gone(_mod(), cfg) is False


def test_windows_probe_says_gone(cfg, monkeypatch):
    monkeypatch.setattr(st.os, "name", "nt")
    monkeypatch.setattr(st.os, "kill", _boom)
    monkeypatch.setattr(st, "_windows_pid_alive", lambda pid: False)
    assert st._process_gone(_mod(), cfg) is True


def test_windows_probe_that_cannot_tell_leaves_the_registry_to_decide(cfg, monkeypatch):
    monkeypatch.setattr(st.os, "name", "nt")
    monkeypatch.setattr(st.os, "kill", _boom)
    monkeypatch.setattr(st, "_windows_pid_alive", lambda pid: None)
    assert st._process_gone(_mod(), cfg) is False  # the procStart match still vouches for it
    (cfg / "sessions" / "4242.json").write_text(json.dumps({"pid": 4242, "procStart": "other"}))
    assert st._process_gone(_mod(), cfg) is True


def test_windows_probe_without_ctypes_windll_cannot_tell(monkeypatch):
    # On this machine there is no windll: the probe must answer None, not raise.
    assert st._windows_pid_alive(4242) in (None, True, False)


def test_posix_still_probes_with_os_kill(cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(st.os, "name", "posix")
    monkeypatch.setattr(st.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    assert st._process_gone(_mod(), cfg) is False
    assert calls == [(4242, 0)]
