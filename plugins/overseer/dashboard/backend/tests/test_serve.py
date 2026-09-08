"""Tests for the dashboard launcher (`dashboard/serve.py`).

`serve.py` lives one directory up from this backend package (in
`dashboard/`), so it isn't reachable through the backend's own
`pythonpath=["."]` pytest config. Add `dashboard/` to `sys.path` before
importing it, mirroring what `serve.py` itself does for `backend/`.

None of these tests bind a real port or open a real browser: `serve._bind`,
`uvicorn.run`, `webbrowser.open` and `threading.Timer` are all patched.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_DASHBOARD_DIR = Path(__file__).resolve().parents[2]
if str(_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_DIR))

import serve  # must follow the sys.path setup above

FAKE_FD = 42


@pytest.fixture(autouse=True)
def _no_real_socket(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """`main()` binds the port itself before stamping. Never let a test do
    that for real: hand back a fake listening socket with a known fd."""
    fake_sock = MagicMock()
    fake_sock.fileno.return_value = FAKE_FD
    monkeypatch.setattr(serve, "_bind", MagicMock(return_value=fake_sock))
    return fake_sock


# --- argument parsing ------------------------------------------------------


def test_parse_args_defaults() -> None:
    args = serve.parse_args([])

    assert args.root == "."
    assert args.host == "127.0.0.1"
    assert args.port == serve.DEFAULT_PORT
    assert args.no_browser is False


def test_parse_args_overrides() -> None:
    args = serve.parse_args(
        ["--root", "/tmp/somewhere", "--host", "0.0.0.0", "--port", "9999", "--no-browser"]
    )

    assert args.root == "/tmp/somewhere"
    assert args.host == "0.0.0.0"
    assert args.port == 9999
    assert args.no_browser is True


def test_parse_args_help_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        serve.parse_args(["--help"])

    assert exc_info.value.code == 0
    assert "--no-browser" in capsys.readouterr().out


# --- main(): app construction + uvicorn wiring ------------------------------


def test_main_builds_app_from_resolved_root_and_runs_uvicorn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OVERSEER_DASHBOARD_TOKEN", raising=False)
    sentinel_app = MagicMock()
    fake_create_app = MagicMock(return_value=sentinel_app)
    fake_run = MagicMock()
    monkeypatch.setattr(serve, "create_app", fake_create_app)
    monkeypatch.setattr(serve.uvicorn, "run", fake_run)
    monkeypatch.setattr(serve.threading, "Timer", MagicMock())

    rc = serve.main(["--root", str(tmp_path), "--port", "9001", "--no-browser"])

    assert rc == 0
    # loopback bind, no env token → token stays None (no friction for the
    # common single-user case)
    fake_create_app.assert_called_once_with(tmp_path.resolve(), host="127.0.0.1", token=None)
    # uvicorn is handed the app wrapped in the record-removing lifespan shim
    # (not the bare app), plus the socket main() already bound.
    fake_run.assert_called_once()
    assert fake_run.call_args.kwargs == {"host": "127.0.0.1", "port": 9001, "fd": FAKE_FD}
    assert callable(fake_run.call_args.args[0]) and fake_run.call_args.args[0] is not sentinel_app
    serve._bind.assert_called_once_with("127.0.0.1", 9001)


def test_main_passes_through_custom_host(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OVERSEER_DASHBOARD_TOKEN", raising=False)
    fake_create_app = MagicMock(return_value=MagicMock())
    fake_run = MagicMock()
    monkeypatch.setattr(serve, "create_app", fake_create_app)
    monkeypatch.setattr(serve.uvicorn, "run", fake_run)
    monkeypatch.setattr(serve.threading, "Timer", MagicMock())

    serve.main(["--root", str(tmp_path), "--host", "0.0.0.0", "--port", "8080", "--no-browser"])

    # non-loopback bind, no env token → a token is auto-generated (never
    # tokenless off localhost)
    assert fake_create_app.call_count == 1
    args, kwargs = fake_create_app.call_args
    assert args == (tmp_path.resolve(),)
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["token"]
    fake_run.assert_called_once_with(fake_run.call_args.args[0], host="0.0.0.0", port=8080, fd=FAKE_FD)
    serve._bind.assert_called_once_with("0.0.0.0", 8080)


# --- WF-053: runtime record + singleton --------------------------------------


def _quiet(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    monkeypatch.delenv("OVERSEER_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setattr(serve, "create_app", MagicMock(return_value=MagicMock()))
    fake_run = MagicMock()
    monkeypatch.setattr(serve.uvicorn, "run", fake_run)
    monkeypatch.setattr(serve.threading, "Timer", MagicMock())
    return fake_run


def _live_record(monkeypatch: pytest.MonkeyPatch, *, port: int = 9003, answers: bool = True) -> None:
    """A recorded server on `port` whose pid is alive and which does (or does
    not) answer the version probe. The probe is always patched: these tests
    must never touch a real socket."""
    dr = serve.dashboard_record
    dr.write_record({"pid": 777, "host": "127.0.0.1", "port": port})
    monkeypatch.setattr(dr, "pid_alive", lambda pid: pid == 777)
    monkeypatch.setattr(
        dr, "probe_dashboard", lambda host, p, **kw: {"version": "0.21.0"} if answers else None
    )


def test_main_stamps_a_record_only_once_the_bind_succeeded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _no_real_socket: MagicMock
) -> None:
    """Ordering is the whole point: nothing on disk when `_bind` is entered,
    the record present by the time uvicorn runs, gone once it returns, and
    the socket closed behind it."""
    dr = serve.dashboard_record
    seen: dict = {}
    monkeypatch.delenv("OVERSEER_DASHBOARD_TOKEN", raising=False)
    monkeypatch.setattr(serve, "create_app", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(serve.threading, "Timer", MagicMock())

    def _bind(host, port):
        seen["at_bind"] = dr.read_record()
        return _no_real_socket

    def _run(app, **_kw):
        seen["at_run"] = dr.read_record()

    monkeypatch.setattr(serve, "_bind", _bind)
    monkeypatch.setattr(serve.uvicorn, "run", _run)

    rc = serve.main(["--root", str(tmp_path), "--host", "0.0.0.0", "--port", "9002", "--no-browser"])

    assert rc == 0
    assert seen["at_bind"] is None  # nothing claimed until the socket is ours
    rec = seen["at_run"]
    assert (rec["host"], rec["port"], rec["root"]) == ("0.0.0.0", 9002, str(tmp_path.resolve()))
    assert rec["pid"] == serve.os.getpid()
    assert rec["serve"].endswith("serve.py") and rec["python"]
    assert rec["version"] == dr.plugin_version()
    assert dr.read_record() is None  # gone once the server returns
    _no_real_socket.close.assert_called_once()


def test_the_lifespan_shim_removes_our_record_on_shutdown_and_passes_requests_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Drives a REAL lifespan: on SIGTERM uvicorn re-raises the signal
    inside `run()`, so `main()`'s `finally` never gets to remove the record.
    The `lifespan.shutdown.complete` hook has to do it on its own."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    dr = serve.dashboard_record
    inner = FastAPI()

    @inner.get("/ping")
    def _ping() -> dict:
        return {"ok": True}

    me = serve.os.getpid()
    dr.write_record({"pid": me, "host": "127.0.0.1", "port": 9005})
    with TestClient(serve._unstamp_on_shutdown(inner, me)) as client:
        assert client.get("/ping").json() == {"ok": True}
        assert dr.read_record()["pid"] == me  # still ours while serving
    assert dr.read_record() is None  # gone at lifespan shutdown, no finally involved

    # ...and never anyone else's: a replacement that stamped over ours while
    # we were shutting down keeps its record.
    dr.write_record({"pid": me + 1, "host": "127.0.0.1", "port": 9005})
    with TestClient(serve._unstamp_on_shutdown(inner, me)):
        pass
    assert dr.read_record()["pid"] == me + 1


def test_bind_returns_a_listening_socket_and_raises_when_the_port_is_taken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one test that touches a real socket, on purpose and on loopback:
    port 0 lets the OS pick a free port, and a second bind on that port must
    raise instead of silently sharing it. `_bind` is restored from the
    autouse fake for this test only."""
    import socket

    monkeypatch.undo()  # drop the autouse `_bind` fake
    real_bind = serve._bind
    sock = real_bind("127.0.0.1", 0)
    try:
        host, port = sock.getsockname()
        assert host == "127.0.0.1" and port > 0
        assert sock.fileno() > 0
        assert sock.get_inheritable()
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with pytest.raises(OSError):
                probe.bind(("127.0.0.1", port))
        finally:
            probe.close()
    finally:
        sock.close()


def test_a_failed_bind_never_claims_the_record_or_deletes_a_live_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A bind that fails with "address already in use" raises before any
    stamp is written, so the record is exactly as the launch found it and
    uvicorn is never started."""
    dr = serve.dashboard_record
    fake_run = _quiet(monkeypatch)
    monkeypatch.setattr(serve, "_bind", MagicMock(side_effect=OSError("address already in use")))
    dr.write_record({"pid": 777, "host": "127.0.0.1", "port": 9003, "version": "0.21.0"})
    monkeypatch.setattr(dr, "pid_alive", lambda pid: False)  # a stale leftover record
    monkeypatch.setattr(dr, "probe_dashboard", lambda host, p, **kw: None)

    with pytest.raises(OSError):
        serve.main(["--root", str(tmp_path), "--port", "9003", "--no-browser"])

    assert dr.read_record() is None  # the stale one was cleared, no new claim
    fake_run.assert_not_called()


def test_main_refuses_while_a_recorded_server_still_answers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dr = serve.dashboard_record
    fake_run = _quiet(monkeypatch)
    _live_record(monkeypatch)

    rc = serve.main(["--root", str(tmp_path), "--port", "9003", "--no-browser"])

    assert rc == 1
    assert "already running" in capsys.readouterr().err
    fake_run.assert_not_called()
    assert dr.read_record()["pid"] == 777  # the live server's record is untouched


def test_main_refuses_even_on_a_different_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One dashboard per config dir: a second launch elsewhere would stamp
    over the live server's record and leave it unmanaged."""
    dr = serve.dashboard_record
    fake_run = _quiet(monkeypatch)
    _live_record(monkeypatch, port=9003)

    assert serve.main(["--root", str(tmp_path), "--port", "9004", "--no-browser"]) == 1
    assert "already running" in capsys.readouterr().err
    fake_run.assert_not_called()
    assert dr.read_record()["pid"] == 777


def test_main_replace_takes_over_a_server_that_answers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dr = serve.dashboard_record
    fake_run = _quiet(monkeypatch)
    _live_record(monkeypatch)
    killed: list[int] = []
    monkeypatch.setattr(dr, "terminate_pid", lambda pid: (killed.append(pid), True)[1])

    rc = serve.main(["--root", str(tmp_path), "--port", "9003", "--no-browser", "--replace"])

    assert rc == 0
    assert killed == [777]
    fake_run.assert_called_once()


def test_replace_never_kills_a_live_pid_that_does_not_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The pid in a record that outlived a reboot can belong to anyone. With
    no answer to the probe it is not a dashboard, so it is not killed — the
    record is simply dropped and the launch goes ahead."""
    dr = serve.dashboard_record
    fake_run = _quiet(monkeypatch)
    _live_record(monkeypatch, answers=False)
    killed: list[int] = []
    monkeypatch.setattr(dr, "terminate_pid", lambda pid: (killed.append(pid), True)[1])

    assert serve.main(["--root", str(tmp_path), "--port", "9003", "--no-browser", "--replace"]) == 0
    assert killed == []
    fake_run.assert_called_once()


def test_main_ignores_a_record_whose_pid_is_dead(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    dr = serve.dashboard_record
    fake_run = _quiet(monkeypatch)
    dr.write_record({"pid": 777, "host": "127.0.0.1", "port": 9003})
    monkeypatch.setattr(dr, "pid_alive", lambda pid: False)
    probed: list[tuple] = []
    monkeypatch.setattr(dr, "probe_dashboard", lambda host, p, **kw: probed.append((host, p)))

    assert serve.main(["--root", str(tmp_path), "--port", "9003", "--no-browser"]) == 0
    assert probed == []  # a dead pid needs no probe
    fake_run.assert_called_once()


# --- browser open behaviour --------------------------------------------------


def test_main_schedules_browser_open_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(serve, "create_app", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(serve.uvicorn, "run", MagicMock())
    fake_timer_cls = MagicMock()
    monkeypatch.setattr(serve.threading, "Timer", fake_timer_cls)

    serve.main(["--root", str(tmp_path), "--port", "8770"])

    fake_timer_cls.assert_called_once()
    (_delay, function), kwargs = fake_timer_cls.call_args
    assert function is serve._open_browser
    assert kwargs["args"] == ("http://127.0.0.1:8770/",)
    fake_timer_cls.return_value.start.assert_called_once()


def test_main_no_browser_skips_scheduling(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(serve, "create_app", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(serve.uvicorn, "run", MagicMock())
    fake_timer_cls = MagicMock()
    monkeypatch.setattr(serve.threading, "Timer", fake_timer_cls)

    serve.main(["--root", str(tmp_path), "--no-browser"])

    fake_timer_cls.assert_not_called()


def test_open_browser_opens_the_given_url(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_open = MagicMock()
    monkeypatch.setattr(serve.webbrowser, "open", fake_open)

    serve._open_browser("http://127.0.0.1:8770/")

    fake_open.assert_called_once_with("http://127.0.0.1:8770/")


def test_open_browser_swallows_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_url: str) -> None:
        raise RuntimeError("no display available")

    monkeypatch.setattr(serve.webbrowser, "open", _raise)

    serve._open_browser("http://127.0.0.1:8770/")  # must not raise


# --- token resolution ---------------------------------------------------


def test_resolve_token_none_on_loopback_without_env(monkeypatch) -> None:
    monkeypatch.delenv("OVERSEER_DASHBOARD_TOKEN", raising=False)
    assert serve.resolve_token("127.0.0.1") is None


def test_resolve_token_env_wins(monkeypatch) -> None:
    monkeypatch.setenv("OVERSEER_DASHBOARD_TOKEN", "fixed-tok")
    assert serve.resolve_token("127.0.0.1") == "fixed-tok"


def test_resolve_token_autogen_on_non_loopback(monkeypatch) -> None:
    monkeypatch.delenv("OVERSEER_DASHBOARD_TOKEN", raising=False)
    tok = serve.resolve_token("0.0.0.0")
    assert tok and len(tok) >= 20


def test_main_passes_token_to_create_app(monkeypatch) -> None:
    monkeypatch.setenv("OVERSEER_DASHBOARD_TOKEN", "abc123")
    captured = {}

    def fake_create_app(root, *, host, token=None):
        captured["token"] = token
        return MagicMock()

    monkeypatch.setattr(serve, "create_app", fake_create_app)
    monkeypatch.setattr(serve.uvicorn, "run", MagicMock())
    serve.main(["--no-browser"])
    assert captured["token"] == "abc123"
