"""WF-100 C5: argv hardening on `POST /api/exec`.

Sub-parsers do not abbreviate, host-path file options are refused (not
stripped), every verb that takes its root from a hook payload is denied, and
the one hook that is forwarded (`pretool-hook`) has its `cwd` pinned.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import board_service
from app.main import create_app

TOKEN = {"X-Overseer-Token": "t"}


def _exec(client: TestClient, argv: list[str], stdin: str | None = None):
    return client.post("/api/exec", json={"argv": argv, "stdin": stdin}, headers=TOKEN)


class _Spy:
    """Records (and fakes) the overseer CLI spawns only."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.real = subprocess.run

    def __call__(self, cmd, **kw):
        if isinstance(cmd, list) and str(board_service._OVERSEER_CLI) in cmd:
            self.calls.append({"cmd": cmd, **kw})
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")
        return self.real(cmd, **kw)


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> _Spy:
    s = _Spy()
    monkeypatch.setattr(board_service.subprocess, "run", s)
    return s


@pytest.fixture
def client(root: Path) -> TestClient:
    return TestClient(create_app(root, exec_token="t"))


# --- host path options are refused, not stripped -----------------------------------

@pytest.mark.parametrize("tok", [
    "--file", "--file=/etc/hosts", "--text-file", "--text-file=/etc/hosts",
    "--brief-file", "--brief-file=/etc/hosts", "--filename",
])
def test_file_flags_are_403_and_nothing_spawns(client: TestClient, spy: _Spy, tok: str) -> None:
    argv = ["set-section", "WF-1", "--section", "Plan", tok] + ([] if "=" in tok else ["/etc/hosts"])
    res = _exec(client, argv)
    assert res.status_code == 403
    assert "host path options are not permitted remotely" in res.json()["detail"]
    assert spy.calls == []


def test_file_flag_is_refused_whatever_the_verb(client: TestClient, spy: _Spy) -> None:
    assert _exec(client, ["append-body", "WF-1", "Decisions", "--text-file", "/etc/hosts"]).status_code == 403
    assert spy.calls == []


def test_text_and_stdin_still_work(client: TestClient, spy: _Spy) -> None:
    res = _exec(client, ["set-section", "WF-1", "--section", "Plan", "--text", "-"], stdin="body")
    assert res.status_code == 200
    assert spy.calls[0]["input"] == "body"
    assert spy.calls[0]["cmd"][-2:] == ["--text", "-"]


# --- hook and admin verbs that escape the pinned root --------------------------------

@pytest.mark.parametrize("verb", [
    "claude-dirs", "merge-boards", "checklist-sync-hook", "claim-stop-hook",
    "claim-prompt-hook", "report-hook", "dashboard-refresh-hook",
])
def test_root_escaping_verbs_are_denied(client: TestClient, spy: _Spy, verb: str) -> None:
    res = _exec(client, [verb], stdin=json.dumps({"cwd": "/somewhere/else"}))
    assert res.status_code == 403
    assert verb in res.json()["detail"]
    assert spy.calls == []


def test_a_verb_hidden_behind_session_id_is_still_denied(client: TestClient, spy: _Spy) -> None:
    for argv in (["--session-id", "s", "report-hook"], ["--session-id=s", "report-hook"],
                 ["--remote", "http://x", "report-hook"], ["--root", "/x", "report-hook"]):
        assert _exec(client, argv).status_code == 403, argv
    assert spy.calls == []


# --- pretool-hook: cwd is pinned ------------------------------------------------------

def _stdin_of(spy: _Spy) -> dict[str, Any]:
    return json.loads(spy.calls[-1]["input"])


def test_pretool_hook_cwd_is_overwritten_with_the_pinned_root(client: TestClient, spy: _Spy) -> None:
    payload = {"session_id": "s", "cwd": "/foreign/place", "tool_name": "Read", "tool_input": {"x": 1}}
    assert _exec(client, ["pretool-hook"], stdin=json.dumps(payload)).status_code == 200
    cmd = spy.calls[0]["cmd"]
    pinned = cmd[cmd.index("--root") + 1]
    sent = _stdin_of(spy)
    assert sent["cwd"] == pinned
    assert {k: v for k, v in sent.items() if k != "cwd"} == {k: v for k, v in payload.items() if k != "cwd"}


def test_pretool_hook_without_cwd_gets_the_pinned_one_and_same_stdin_as_a_pinned_cwd(
    client: TestClient, spy: _Spy
) -> None:
    base = {"session_id": "s", "tool_name": "Read", "tool_input": {}}
    _exec(client, ["pretool-hook"], stdin=json.dumps(base))
    cmd = spy.calls[0]["cmd"]
    pinned = cmd[cmd.index("--root") + 1]
    _exec(client, ["pretool-hook"], stdin=json.dumps({**base, "cwd": pinned}))
    _exec(client, ["pretool-hook"], stdin=json.dumps({**base, "cwd": "/foreign"}))
    inputs = [json.loads(c["input"]) for c in spy.calls]
    assert inputs[0] == inputs[1] == inputs[2]


@pytest.mark.parametrize("stdin", [None, "", "not json", "[1, 2]", '"str"', "null"])
def test_pretool_hook_needs_a_json_object_on_stdin(client: TestClient, spy: _Spy, stdin: str | None) -> None:
    assert _exec(client, ["pretool-hook"], stdin=stdin).status_code == 400
    assert spy.calls == []


# --- end to end through the real parser -------------------------------------------------

def test_abbreviated_path_option_never_reads_the_host_file(root: Path, client: TestClient, tmp_path: Path) -> None:
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text("TOP-SECRET-SENTINEL")
    out = _exec(client, ["new-card", "--title", "t"])
    assert out.status_code == 200
    card = out.json()["stdout"].split()[0] if out.json()["stdout"].strip() else "WF-001"
    for opt in ("--fi", "--fil", "--text-f", "--text-fi"):
        res = _exec(client, ["set-section", card, "--section", "Plan", opt, str(sentinel)])
        body = res.json()
        assert body["returncode"] != 0
        assert "TOP-SECRET-SENTINEL" not in body["stdout"] + body["stderr"]
        shown = _exec(client, ["show", card, "--section", "Plan"]).json()
        assert "TOP-SECRET-SENTINEL" not in shown["stdout"]


def test_denied_hook_verbs_leave_the_board_untouched(root: Path, client: TestClient, tmp_path: Path) -> None:
    before = _exec(client, ["board", "--json"]).json()["stdout"]
    for verb in ("report-hook", "claim-stop-hook", "claim-prompt-hook", "checklist-sync-hook"):
        payload = json.dumps({"cwd": str(tmp_path / "other"), "session_id": "s"})
        assert _exec(client, [verb], stdin=payload).status_code == 403
    assert _exec(client, ["board", "--json"]).json()["stdout"] == before
    assert not (tmp_path / "other").exists()


# --- WF-100 C6: verbs that run git in the repo are denied -----------------------------------

GIT_VERBS = ("bootstrap", "dispatch-prep")


@pytest.mark.parametrize("verb", GIT_VERBS)
def test_git_running_verbs_are_403_naming_the_verb_and_the_followup(
    client: TestClient, spy: _Spy, verb: str
) -> None:
    res = _exec(client, [verb, "--title", "t"])
    assert res.status_code == 403
    detail = res.json()["detail"]
    assert f"verb '{verb}' runs git in the repo" in detail
    assert board_service.GIT_FOLLOWUP_CARD == "WF-300" and "WF-300" in detail
    assert spy.calls == []


@pytest.mark.parametrize("argv", [
    ["--session-id", "s", "bootstrap", "--title", "t"],
    ["--session-id=s", "bootstrap", "--title", "t"],
    ["--remote", "http://evil", "bootstrap", "--title", "t"],
    ["--remote=http://evil", "bootstrap", "--title", "t"],
    ["--root", "/elsewhere", "bootstrap", "--title", "t"],
    ["--root=/elsewhere", "dispatch-prep", "WF-1", "--stage", "implementation", "--role", "reviewer"],
    ["--", "bootstrap", "--title", "t"],
    ["--session-id", "s", "--remote", "http://evil", "--root", "/x", "dispatch-prep", "WF-1"],
])
def test_denial_holds_however_the_verb_is_reached(client: TestClient, spy: _Spy, argv: list[str]) -> None:
    assert _exec(client, argv).status_code == 403
    assert spy.calls == []


@pytest.mark.parametrize("argv", [
    ["bootstra", "--title", "t"],            # a verb prefix is no verb
    ["BOOTSTRAP", "--title", "t"],           # nor a different case
    ["--session-i", "s", "bootstrap"],       # abbreviated global option: the child's parser refuses it
    ["--rem", "http://evil", "bootstrap"],
    ["--roo", "/x", "bootstrap"],
    ["-h", "bootstrap"],
])
def test_a_token_that_is_not_the_denied_verb_never_runs_it(root: Path, client: TestClient, argv: list[str]) -> None:
    # Through the real parser: whatever the route lets through must still not create a card
    # (bootstrap would) or a worktree, and must not succeed as bootstrap.
    before = _exec(client, ["board", "--json"]).json()["stdout"]
    res = _exec(client, argv)
    assert res.status_code in (200, 403)
    if res.status_code == 200:
        assert res.json()["returncode"] != 0 or "usage" in res.json()["stdout"]
    assert _exec(client, ["board", "--json"]).json()["stdout"] == before
    assert not list(root.glob("**/worktrees"))


def test_the_exec_child_environment_is_hardened(client: TestClient, spy: _Spy) -> None:
    _exec(client, ["board"])
    env = spy.calls[0]["env"]
    pairs = [(env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"]) for i in range(int(env["GIT_CONFIG_COUNT"]))]
    assert ("core.fsmonitor", "false") in pairs and ("core.hooksPath", "/dev/null") in pairs
    assert env["GIT_TERMINAL_PROMPT"] == "0" and env["GIT_CONFIG_NOSYSTEM"] == "1"


def test_inherited_git_config_never_reaches_the_child(
    client: TestClient, spy: _Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "http.extraheader")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "Authorization: bearer s3cret")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'core.fsmonitor'='/tmp/trap'")
    monkeypatch.setenv("GIT_DIR", "/elsewhere")
    monkeypatch.setenv("GIT_SSH_COMMAND", "evil")
    _exec(client, ["board"])
    env = spy.calls[0]["env"]
    assert env["GIT_CONFIG_COUNT"] == "2"
    assert env["GIT_CONFIG_KEY_0"] == "core.hooksPath" and env["GIT_CONFIG_KEY_1"] == "core.fsmonitor"
    assert not {"GIT_CONFIG_PARAMETERS", "GIT_DIR", "GIT_SSH_COMMAND"} & set(env)
    assert "s3cret" not in " ".join(env.values())


# --- the booby-trapped repo: nothing fires in what is still reachable -------------------------

def _plant_traps(repo: Path, tmp_path: Path) -> Path:
    fired = tmp_path / "FIRED"
    trap = tmp_path / "trap.sh"
    trap.write_text(f'#!/bin/sh\necho "$0 $*" >> "{fired}"\ncat > /dev/null 2>&1\nexit 0\n')
    trap.chmod(0o755)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for name in ("pre-commit", "post-commit", "post-checkout", "reference-transaction",
                 "post-index-change", "pre-push", "post-merge"):
        (hooks / name).write_bytes(trap.read_bytes())
        (hooks / name).chmod(0o755)
    (repo / "a.txt").write_text("x\n")
    (repo / ".gitattributes").write_text("* filter=boom\n*.txt diff=boom\n")
    for key, value in (("core.fsmonitor", str(trap)), ("core.hooksPath", str(hooks)),
                       ("filter.boom.clean", str(trap)), ("filter.boom.smudge", str(trap)),
                       ("diff.boom.textconv", str(trap))):
        subprocess.run(["git", "config", key, value], cwd=repo, check=True)
    return fired


def test_nothing_fires_when_exec_reaches_the_lookup_verbs_in_a_trapped_repo(root: Path, tmp_path: Path) -> None:
    fired = _plant_traps(root, tmp_path)
    client = TestClient(create_app(root, exec_token="t"))  # real child processes: no spy
    assert _exec(client, ["new-card", "--title", "t"]).status_code == 200
    for argv in (["resume"], ["handoff"], ["handover"], ["repos"], ["board"], ["show", "WF-001"],
                 ["set-field", "WF-001", "--branch", "main", "--worktree", "wt"], ["resume", "--json"]):
        assert _exec(client, argv).status_code == 200, argv
    assert not fired.exists(), fired.read_text()


# --- the plugin code must not live in a tree the container can write ------------------------

def test_exec_is_off_when_the_overseer_cli_lives_inside_the_pinned_repo(
    root: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from app import main as app_main

    def never(*a: Any, **kw: Any) -> None:
        raise AssertionError("the exec child must not be spawned")

    monkeypatch.setattr(app_main, "run_cli", never)

    inside = root / "plugins" / "overseer" / "scripts" / "cli.py"
    inside.parent.mkdir(parents=True)
    inside.write_text("")
    monkeypatch.setattr(app_main, "_OVERSEER_CLI", inside)
    with caplog.at_level("WARNING"):
        client = TestClient(create_app(root, exec_token="t"))
    assert "exec disabled" in caplog.text
    res = _exec(client, ["board"])
    assert res.status_code == 503
    assert "lies inside the pinned repo" in res.json()["detail"]
    assert client.get("/api/board").status_code == 200  # the dashboard still starts


def test_exec_stays_on_when_the_cli_is_outside_the_pinned_repo(client: TestClient, spy: _Spy) -> None:
    assert _exec(client, ["board"]).status_code == 200
