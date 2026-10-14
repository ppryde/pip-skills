"""WF-101 W3: the container side of root-selecting exec.

`OVERSEER_REMOTE_REPO=<label>` rides in the request body as `repo`. Unset sends
nothing; a malformed value is a hard error before any request.
"""
from __future__ import annotations

import io
import json
import sys

import httpx
import pytest
from scripts import remote
from scripts.cli import main


@pytest.fixture(autouse=True)
def _no_tty_stdin(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.delenv("OVERSEER_REMOTE_REPO", raising=False)
    monkeypatch.setenv("OVERSEER_REMOTE_TOKEN", "tok")


def _capture(monkeypatch):
    seen: dict = {"calls": 0}

    def fake_exec(url, token, argv, stdin, **kw):
        seen.update(url=url, argv=argv, stdin=stdin, kw=kw)
        seen["calls"] += 1
        return remote.RemoteResult(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(remote, "exec_remote", fake_exec)
    return seen


# --- exec_remote: the payload ---------------------------------------------------------

def _post(repo, **kw):
    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"stdout": "", "stderr": "", "returncode": 0})

    remote.exec_remote("http://svc", "t", ["board"], None, repo=repo,
                       transport=httpx.MockTransport(handler), **kw)
    return sent


def test_payload_has_no_repo_key_unless_one_is_set():
    assert _post(None) == {"argv": ["board"], "stdin": None}
    assert _post("pip-skills") == {"argv": ["board"], "stdin": None, "repo": "pip-skills"}


def test_exec_remote_default_sends_no_repo():
    sent: dict = {}

    def handler(request):
        sent.update(json.loads(request.content))
        return httpx.Response(200, json={"stdout": "", "stderr": "", "returncode": 0})

    remote.exec_remote("http://svc", None, ["board"], None, transport=httpx.MockTransport(handler))
    assert "repo" not in sent


@pytest.mark.parametrize("status,detail,extra", [
    (400, "repo must be a label like 'pip-skills'", "400"),
    (404, "unknown repo 'x'; valid: a, b, c", "OVERSEER_REMOTE_REPO"),
    (409, "ambiguous repo 'twin': twin (/r/1), twin (/r/2); add an alias", "alias"),
])
def test_repo_errors_show_the_servers_message_in_full(status, detail, extra):
    long_detail = detail + (" " + "pad" * 200 if status == 404 else "")
    transport = httpx.MockTransport(lambda r: httpx.Response(status, json={"detail": long_detail}))
    with pytest.raises(remote.RemoteError) as err:
        remote.exec_remote("http://svc", "t", ["board"], None, repo="x", transport=transport)
    text = str(err.value)
    assert long_detail in text and str(status) in text and extra in text


def test_a_404_without_a_json_detail_is_still_readable():
    transport = httpx.MockTransport(lambda r: httpx.Response(404, text="nope"))
    with pytest.raises(remote.RemoteError) as err:
        remote.exec_remote("http://svc", "t", ["board"], None, transport=transport)
    assert "404" in str(err.value)


# --- the CLI: env handling --------------------------------------------------------------

def test_unset_env_forwards_no_repo(monkeypatch):
    seen = _capture(monkeypatch)
    assert main(["--remote", "http://h", "board"]) == 0
    assert seen["kw"].get("repo") is None


def test_set_env_forwards_the_label(monkeypatch):
    seen = _capture(monkeypatch)
    monkeypatch.setenv("OVERSEER_REMOTE_REPO", "pip-skills")
    assert main(["--remote", "http://h", "board"]) == 0
    assert seen["kw"]["repo"] == "pip-skills"


@pytest.mark.parametrize("bad", ["", " ", "a/b", "..", ".", "/etc", "a b", "é", "x" * 101, "a\nb"])
def test_a_malformed_label_is_a_hard_error_before_any_request(monkeypatch, capsys, bad):
    seen = _capture(monkeypatch)
    monkeypatch.setenv("OVERSEER_REMOTE_REPO", bad)
    assert main(["--remote", "http://h", "board"]) == 1
    assert seen["calls"] == 0
    assert "OVERSEER_REMOTE_REPO must be a repo label like 'pip-skills'" in capsys.readouterr().err


def test_the_forwarded_pretool_hook_carries_the_label(monkeypatch):
    seen = _capture(monkeypatch)
    monkeypatch.setenv("OVERSEER_REMOTE_REPO", "alpha")
    payload = json.dumps({"session_id": "s", "cwd": "/container/ws", "tool_name": "Bash",
                          "tool_input": {"command": "ls"}})
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    assert main(["--remote", "http://h", "pretool-hook"]) == 0
    assert seen["argv"] == ["pretool-hook"] and seen["stdin"] == payload
    assert seen["kw"]["repo"] == "alpha"


def test_the_label_is_not_added_to_the_argv(monkeypatch):
    seen = _capture(monkeypatch)
    monkeypatch.setenv("OVERSEER_REMOTE_REPO", "alpha")
    main(["--remote", "http://h", "show", "WF-1"])
    assert seen["argv"] == ["show", "WF-1"]
