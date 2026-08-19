import sys

import pytest

from scripts.cli import main
from scripts import remote


def test_remote_forwards_argv_and_relays(monkeypatch, capsys):
    seen = {}

    def fake_exec(url, token, argv, stdin, **kw):
        seen.update(url=url, token=token, argv=argv, stdin=stdin)
        return remote.RemoteResult(stdout="WF-001\n", stderr="", returncode=0)

    monkeypatch.setattr(remote, "exec_remote", fake_exec)
    monkeypatch.setenv("OVERSEER_REMOTE_TOKEN", "tok")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)  # no stdin to read

    rc = main(["--remote", "http://host.docker.internal:8771", "board"])

    assert rc == 0
    assert seen["url"] == "http://host.docker.internal:8771"
    assert seen["token"] == "tok"
    assert seen["argv"] == ["board"]          # --remote stripped, verb forwarded
    assert "WF-001" in capsys.readouterr().out


def test_remote_relays_nonzero_exit(monkeypatch):
    monkeypatch.setattr(remote, "exec_remote",
                        lambda *a, **k: remote.RemoteResult(stdout="", stderr="boom\n", returncode=2))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert main(["--remote", "http://h", "show", "WF-9"]) == 2


def test_remote_does_not_touch_local_board(monkeypatch, tmp_path):
    # If dispatch went local, cmd_board would run against OVERSEER_DB. Assert the
    # remote path is taken instead (fake called), never the local func.
    called = {"remote": False}

    def fake_exec(*a, **k):
        called["remote"] = True
        return remote.RemoteResult(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(remote, "exec_remote", fake_exec)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setenv("OVERSEER_DB", str(tmp_path / "never-created.db"))

    assert main(["--remote", "http://h", "board"]) == 0
    assert called["remote"] is True
    assert not (tmp_path / "never-created.db").exists()   # local board never opened


def test_remote_transport_error_returns_1(monkeypatch, capsys):
    def boom(*a, **k):
        raise remote.RemoteError("cannot reach")

    monkeypatch.setattr(remote, "exec_remote", boom)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert main(["--remote", "http://h", "board"]) == 1
    assert "cannot reach" in capsys.readouterr().err


def test_remote_env_default(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setenv("OVERSEER_REMOTE", "http://from-env")
    seen = {}

    def fake_exec(url, *a, **k):
        seen["url"] = url
        return remote.RemoteResult("", "", 0)

    monkeypatch.setattr(remote, "exec_remote", fake_exec)
    assert main(["board"]) == 0
    assert seen["url"] == "http://from-env"
