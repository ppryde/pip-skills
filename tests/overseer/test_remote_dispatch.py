import sys

from scripts import remote
from scripts.cli import main


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


def test_abbreviated_global_flag_is_rejected(monkeypatch):
    # allow_abbrev=False: `--roo` must NOT resolve to `--root`. argparse errors
    # (exit 2), which main() relays as a non-zero return — it never dispatches
    # a verb against a bogus root. Guards the /api/exec root-escape bypass.
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    called = {"remote": False}
    monkeypatch.setattr(remote, "exec_remote",
                        lambda *a, **k: called.__setitem__("remote", True))
    # `--rem` must not resolve to `--remote` either (outbound re-forward / SSRF).
    assert main(["--roo", "/x", "board"]) != 0
    assert main(["--rem", "http://evil", "board"]) != 0
    assert called["remote"] is False   # abbreviation never triggered a remote dispatch


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


def test_remote_reads_token_from_file_when_env_unset(monkeypatch, tmp_path, capsys):
    from scripts.remote_token import write_remote_token
    from scripts import remote
    write_remote_token(tmp_path, "file-tok")
    monkeypatch.delenv("OVERSEER_REMOTE_TOKEN", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    seen = {}
    monkeypatch.setattr(remote, "exec_remote",
                        lambda url, token, argv, stdin, **k: seen.update(token=token)
                        or remote.RemoteResult("", "", 0))
    assert main(["--root", str(tmp_path), "--remote", "http://h", "board"]) == 0
    assert seen["token"] == "file-tok"


def test_remote_env_token_wins_over_file(monkeypatch, tmp_path):
    from scripts.remote_token import write_remote_token
    from scripts import remote
    write_remote_token(tmp_path, "file-tok")
    monkeypatch.setenv("OVERSEER_REMOTE_TOKEN", "env-tok")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    seen = {}
    monkeypatch.setattr(remote, "exec_remote",
                        lambda url, token, argv, stdin, **k: seen.update(token=token)
                        or remote.RemoteResult("", "", 0))
    assert main(["--root", str(tmp_path), "--remote", "http://h", "board"]) == 0
    assert seen["token"] == "env-tok"
