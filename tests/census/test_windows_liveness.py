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
    import ctypes

    monkeypatch.delattr(ctypes, "windll", raising=False)   # whatever this machine has: pretend it is not Windows
    assert st._windows_pid_alive(4242) is None


class _Fn:
    """A stand-in Win32 function: records its calls, and accepts the argtypes/restype ctypes would set."""

    def __init__(self, result, on_call=None):
        self.result, self.on_call, self.calls, self.argtypes, self.restype = result, on_call, [], None, None

    def __call__(self, *args):
        self.calls.append(args)
        if self.on_call:
            self.on_call(*args)
        return self.result


def _fake_windll(monkeypatch, handle, code=259):
    import ctypes
    from types import SimpleNamespace

    kernel32 = SimpleNamespace(
        OpenProcess=_Fn(handle),
        GetExitCodeProcess=_Fn(1, on_call=lambda h, ref: setattr(ref._obj, "value", code)),
        CloseHandle=_Fn(1),
        GetLastError=lambda: 0,
    )
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=kernel32), raising=False)
    return kernel32


def test_the_win32_calls_declare_pointer_sized_handles(monkeypatch):
    import ctypes

    k = _fake_windll(monkeypatch, handle=0x1_2345_6789)
    assert st._windows_pid_alive(4242) is True
    assert k.OpenProcess.restype is ctypes.c_void_p
    assert k.GetExitCodeProcess.argtypes[0] is ctypes.c_void_p
    assert k.CloseHandle.argtypes == [ctypes.c_void_p]
    assert k.OpenProcess.argtypes is not None and len(k.OpenProcess.argtypes) == 3


def test_a_handle_wider_than_32_bits_reaches_the_later_calls_whole(monkeypatch):
    k = _fake_windll(monkeypatch, handle=0x1_2345_6789)
    st._windows_pid_alive(4242)
    assert k.GetExitCodeProcess.calls[0][0] == 0x1_2345_6789
    assert k.CloseHandle.calls == [(0x1_2345_6789,)]


def test_an_exited_process_is_not_alive(monkeypatch):
    _fake_windll(monkeypatch, handle=0x1_0000_0001, code=0)
    assert st._windows_pid_alive(4242) is False


def test_posix_still_probes_with_os_kill(cfg, monkeypatch):
    calls = []
    monkeypatch.setattr(st.os, "name", "posix")
    monkeypatch.setattr(st.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    assert st._process_gone(_mod(), cfg) is False
    assert calls == [(4242, 0)]
