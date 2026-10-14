"""WF-101 W2: `POST /api/exec` with a `repo` label reaches any watched LIVE board.

The host resolves the label in-process against `boards.discover()` (live entries
only), then runs the CLI child with `--root <root>` and `OVERSEER_CENTRAL`
pinned to the discovered board. Every hardening from WF-100 must hold for a
labelled call exactly as for the pinned one.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from scripts import boards, config

from app import board_service
from app import main as main_mod
from app.main import create_app

TOKEN = {"X-Overseer-Token": "t"}
_CLI = Path(__file__).resolve().parents[3] / "scripts" / "cli.py"
_REAL_RUN = subprocess.run  # seeding must not go through the spy


def _exec(client: TestClient, argv: list[str], stdin: str | None = None, **body: Any):
    headers = body.pop("headers", TOKEN)
    return client.post("/api/exec", json={"argv": argv, "stdin": stdin, **body}, headers=headers)


class _Spy:
    """Replaces subprocess.run for the overseer CLI spawn only."""

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


def _tree_hash(folder: Path) -> dict[str, str]:
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*")) if p.is_file()
    }


class Machine:
    """Two live config dirs (primary, live2), one archive dir, and the repos."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp = tmp_path
        self.primary = tmp_path / "cfg-primary"
        self.live2 = tmp_path / "cfg-live2"
        self.archive = tmp_path / "cfg" / "backups" / "old"
        for d in (self.primary, self.live2, self.archive):
            d.mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(self.primary))
        monkeypatch.delenv("OVERSEER_DB", raising=False)
        monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
        self.save_config()
        self.board_dirs: dict[str, Path] = {}

    def save_config(self, **extra: Any) -> None:
        config.save_machine_config({"claude_dirs": [str(self.live2), str(self.archive)], **extra})
        boards._discover_cache_clear()

    def seed(self, name: str, cfg: Path, parent: str = "repos") -> Path:
        """A git repo `<tmp>/<parent>/<name>` with a board in `<cfg>/overseer/`."""
        repo = self.tmp / parent / name
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        folder = cfg / "overseer" / f"{name}-{parent}"
        env = {k: v for k, v in os.environ.items() if k != "OVERSEER_DB"}
        env["OVERSEER_CENTRAL"] = str(folder)
        _REAL_RUN([sys.executable, str(_CLI), "--root", str(repo), "init"],
                  env=env, capture_output=True, check=True)
        self.board_dirs[f"{parent}/{name}"] = folder
        boards._discover_cache_clear()
        return repo.resolve()

    def launch(self) -> Path:
        launch = self.tmp / "launch"
        launch.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=launch, check=True)
        return launch

    def client(self, **kw: Any) -> TestClient:
        return TestClient(create_app(self.launch_root, exec_token="t", **kw))

    launch_root: Path


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Machine:
    m = Machine(tmp_path, monkeypatch)
    m.alpha = m.seed("alpha", m.primary)  # type: ignore[attr-defined]
    m.beta = m.seed("beta", m.live2)  # type: ignore[attr-defined]
    m.old = m.seed("old", m.archive)  # type: ignore[attr-defined]
    m.launch_root = m.launch()
    return m


# --- guard order: a rejected caller never reaches discovery --------------------------

@pytest.fixture
def discovery_calls(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    real = boards.discover

    def counting(*a: Any, **k: Any):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(boards, "discover", counting)
    return calls


def test_rejected_callers_never_reach_discovery(
    machine: Machine, spy: _Spy, discovery_calls: list[int]
) -> None:
    ok = machine.client()
    assert _exec(ok, ["board"], repo="alpha", headers={}).status_code == 401
    assert _exec(ok, ["board"], repo="alpha", headers={"X-Overseer-Token": "wrong"}).status_code == 401
    unconfigured = TestClient(create_app(machine.launch_root, exec_token=None))
    assert _exec(unconfigured, ["board"], repo="alpha").status_code == 503
    public = TestClient(create_app(machine.launch_root, exec_token="t"), client=("8.8.8.8", 4000))
    assert _exec(public, ["board"], repo="alpha").status_code == 403
    big = "x" * (1024 * 1024 + 1)
    assert _exec(ok, ["board"], stdin=big, repo="alpha").status_code == 413
    assert _exec(ok, ["board", "\0"], repo="alpha").status_code == 400
    assert discovery_calls == [] and spy.calls == []


def test_an_unlabelled_call_never_runs_discovery(machine: Machine, spy: _Spy, discovery_calls: list[int]) -> None:
    assert _exec(machine.client(), ["board"]).status_code == 200
    assert discovery_calls == []


# --- the child: argv and env ----------------------------------------------------------

def test_a_labelled_call_runs_the_child_on_the_discovered_root_and_board(machine: Machine, spy: _Spy) -> None:
    resp = _exec(machine.client(), ["board"], repo="beta")
    assert resp.status_code == 200, resp.text
    cmd = spy.calls[0]["cmd"]
    assert cmd[:4] == [sys.executable, str(board_service._OVERSEER_CLI), "--root", str(machine.beta)]
    assert cmd.count("--root") == 1
    assert spy.calls[0]["env"]["OVERSEER_CENTRAL"] == str(machine.board_dirs["repos/beta"])


def test_root_flags_smuggled_in_argv_leave_exactly_one_discovered_root(machine: Machine, spy: _Spy) -> None:
    resp = _exec(machine.client(), ["--root", "/etc", "--root=/var", "board"], repo="alpha")
    assert resp.status_code == 200
    cmd = spy.calls[0]["cmd"]
    assert cmd.count("--root") == 1 and cmd[cmd.index("--root") + 1] == str(machine.alpha)
    assert "/etc" not in cmd and "--root=/var" not in cmd


@pytest.mark.parametrize("body", [{}, {"repo": None}])
def test_absent_or_null_repo_is_exactly_the_pinned_behaviour(
    machine: Machine, spy: _Spy, discovery_calls: list[int], body: dict
) -> None:
    client = machine.client()
    pinned = config.central_root(machine.launch_root)
    assert _exec(client, ["board"], **body).status_code == 200
    call = spy.calls[0]
    assert call["cmd"][2:4] == ["--root", str(machine.launch_root.resolve())]
    assert call["env"]["OVERSEER_CENTRAL"] == str(pinned)
    assert discovery_calls == []


@pytest.mark.parametrize("repo,code", [
    ("", 400), ("..", 400), ("a/b", 400), ("../alpha", 400), ("%2e%2e", 400), ("a\nb", 400),
    ("é", 400), ("a" * 101, 400), ("unknown", 404), ("ALPHA", 404), ("alpha ", 400),
    ("old", 404),  # the archive-only repo
    (None, 200),
])
def test_present_but_bad_repo_never_reaches_the_pinned_board_or_the_child(
    machine: Machine, spy: _Spy, repo: str | None, code: int
) -> None:
    resp = _exec(machine.client(), ["board"], repo=repo)
    assert resp.status_code == code, resp.text
    if code != 200:
        assert spy.calls == []


def test_a_real_discovered_root_string_as_a_label_is_400(machine: Machine, spy: _Spy) -> None:
    assert _exec(machine.client(), ["board"], repo=str(machine.alpha)).status_code == 400
    assert spy.calls == []


def test_404_lists_only_live_labels(machine: Machine, spy: _Spy) -> None:
    detail = _exec(machine.client(), ["board"], repo="nope").json()["detail"]
    assert "valid: alpha, beta" in detail and "old" not in detail


def test_child_env_for_a_labelled_call_is_the_hardened_secret_free_one(
    machine: Machine, spy: _Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("OVERSEER_REMOTE", "OVERSEER_REMOTE_TOKEN", "OVERSEER_DASHBOARD_TOKEN",
                 "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "GIT_SSH_COMMAND", "GIT_DIR"):
        monkeypatch.setenv(name, "x")
    _exec(machine.client(), ["board"], repo="alpha")
    env = spy.calls[0]["env"]
    for gone in ("OVERSEER_REMOTE", "OVERSEER_REMOTE_TOKEN", "OVERSEER_DASHBOARD_TOKEN",
                 "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "GIT_SSH_COMMAND", "GIT_DIR"):
        assert gone not in env, gone
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_COUNT"] != "0"


# --- hardening holds for labelled calls ------------------------------------------------

@pytest.mark.parametrize("argv", [
    ["clear", "--yes"], ["init"], ["backup", "--dir", "/x"], ["restore", "--dir", "/x"],
    ["claude-dirs"], ["merge-boards"], ["report-hook"], ["claim-stop-hook"],
    ["checklist-sync-hook"], ["dashboard-refresh-hook"],
    ["bootstrap"], ["dispatch-prep"],
])
def test_denied_verbs_stay_denied_whatever_the_label(machine: Machine, spy: _Spy, argv: list[str]) -> None:
    assert _exec(machine.client(), argv, repo="alpha").status_code == 403
    assert spy.calls == []


def test_git_verbs_name_the_followup_card_for_a_labelled_call(machine: Machine, spy: _Spy) -> None:
    detail = _exec(machine.client(), ["bootstrap"], repo="alpha").json()["detail"]
    assert "bootstrap" in detail and board_service.GIT_FOLLOWUP_CARD in detail


@pytest.mark.parametrize("argv", [
    ["set-section", "WF-1", "--file", "/etc/passwd"],
    ["set-section", "WF-1", "--file=/etc/passwd"],
    ["append-body", "WF-1", "--text-file", "/x"],
    ["set-section", "WF-1", "--filename", "/x"],
])
def test_host_file_options_stay_refused_for_a_labelled_call(machine: Machine, spy: _Spy, argv: list[str]) -> None:
    assert _exec(machine.client(), argv, repo="alpha").status_code == 403
    assert spy.calls == []


def test_pretool_hook_cwd_is_overwritten_with_the_resolved_root(machine: Machine, spy: _Spy) -> None:
    payload = {"session_id": "s", "cwd": "/foreign", "tool_name": "Bash", "tool_input": {"command": "ls"}}
    assert _exec(machine.client(), ["pretool-hook"], stdin=json.dumps(payload), repo="beta").status_code == 200
    assert json.loads(spy.calls[0]["input"])["cwd"] == str(machine.beta)
    assert spy.calls[0]["cmd"][2:4] == ["--root", str(machine.beta)]


def test_labelled_calls_respect_the_busy_limit(machine: Machine, spy: _Spy) -> None:
    taken = [board_service._EXEC_SLOTS.acquire(blocking=False) for _ in range(4)]
    try:
        assert _exec(machine.client(), ["board"], repo="alpha").status_code == 503
    finally:
        for _ in taken:
            board_service._EXEC_SLOTS.release()
    assert spy.calls == []


def test_exec_is_off_when_the_cli_lies_inside_the_resolved_target(
    machine: Machine, spy: _Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check runs against the RESOLVED root, not only the pinned one."""
    inside = machine.alpha / "plugins" / "overseer" / "scripts" / "cli.py"
    inside.parent.mkdir(parents=True)
    inside.write_text("")
    monkeypatch.setattr(board_service, "_OVERSEER_CLI", inside)
    monkeypatch.setattr(main_mod, "_OVERSEER_CLI", inside)
    client = machine.client()  # the pinned launch repo is NOT the one holding the CLI

    resp = _exec(client, ["board"], repo="alpha")

    assert resp.status_code == 503 and "inside" in resp.json()["detail"]
    assert spy.calls == []
    assert _exec(client, ["board"], repo="beta").status_code == 200  # another repo is fine
    assert _exec(client, ["board"]).status_code == 200  # and so is the pinned one


# --- the table rows from the spec --------------------------------------------------------

def test_a_planted_central_dir_does_not_redirect_a_labelled_call(machine: Machine) -> None:
    sentinel = machine.tmp / "sentinel-board"
    (machine.alpha / ".overseer").mkdir(exist_ok=True)
    (machine.alpha / ".overseer" / "config.json").write_text(json.dumps({"central_dir": str(sentinel)}))
    client = machine.client()

    resp = _exec(client, ["new-card", "--title", "planted"], repo="alpha")

    assert resp.status_code == 200 and resp.json()["returncode"] == 0, resp.text
    assert not sentinel.exists()
    assert _exec(client, ["board"], repo="alpha").json()["stdout"].startswith("1 cards")


@pytest.mark.parametrize("var", ["OVERSEER_CENTRAL", "OVERSEER_DB"])
def test_labelled_selection_fails_closed_while_the_server_is_pinned_by_env(
    machine: Machine, spy: _Spy, monkeypatch: pytest.MonkeyPatch, var: str
) -> None:
    pinned = machine.tmp / "env-pinned"
    pinned.mkdir()
    monkeypatch.setenv(var, str(pinned) if var == "OVERSEER_CENTRAL" else str(pinned / "board.db"))
    client = machine.client()
    before = _tree_hash(pinned)

    resp = _exec(client, ["new-card", "--title", "x"], repo="alpha")

    assert resp.status_code == 409 and "pinned by" in resp.json()["detail"] and var in resp.json()["detail"]
    assert spy.calls == [] and _tree_hash(pinned) == before
    assert _exec(client, ["board"]).status_code == 200  # unlabelled calls still use the pin


def test_duplicate_labels_are_409_naming_both_and_an_alias_picks_one(machine: Machine, spy: _Spy) -> None:
    one = machine.seed("twin", machine.primary, parent="one")
    two = machine.seed("twin", machine.live2, parent="two")
    resp = _exec(machine.client(), ["board"], repo="twin")
    assert resp.status_code == 409
    assert str(one) in resp.json()["detail"] and str(two) in resp.json()["detail"]
    assert "aliases" in resp.json()["detail"] and spy.calls == []

    machine.save_config(aliases={"twin-two": str(two)})
    assert _exec(machine.client(), ["board"], repo="twin-two").status_code == 200
    assert spy.calls[0]["cmd"][3] == str(two)
    assert spy.calls[0]["env"]["OVERSEER_CENTRAL"] == str(machine.board_dirs["two/twin"])


def test_an_archive_only_repo_is_404_and_its_board_is_untouched(machine: Machine) -> None:
    folder = machine.board_dirs["repos/old"]
    before = _tree_hash(folder)
    client = machine.client()

    resp = _exec(client, ["new-card", "--title", "x"], repo="old")

    assert resp.status_code == 404
    assert _tree_hash(folder) == before
    repos = client.get("/api/repos").json()["repos"]  # the dashboard still lists the archive
    assert next(r for r in repos if r.get("archived"))["label"] == "old [archived]"


def test_pinned_board_in_an_archive_blocks_only_unlabelled_exec(machine: Machine, spy: _Spy) -> None:
    launch = machine.launch_root
    (launch / ".overseer").mkdir()
    (launch / ".overseer" / "config.json").write_text(
        json.dumps({"central_dir": str(machine.board_dirs["repos/old"])}))
    client = machine.client()

    assert _exec(client, ["board"]).status_code == 503
    assert spy.calls == []
    assert _exec(client, ["board"], repo="alpha").status_code == 200
    assert spy.calls[0]["env"]["OVERSEER_CENTRAL"] == str(machine.board_dirs["repos/alpha"])


# --- one real-discovery run, no spy --------------------------------------------------------

def test_real_discovery_across_accounts_and_an_archive(machine: Machine) -> None:
    one = machine.seed("twin", machine.primary, parent="one")
    two = machine.seed("twin", machine.live2, parent="two")
    del one, two
    client = machine.client()
    archive_before = _tree_hash(machine.board_dirs["repos/old"])
    alpha_before = _tree_hash(machine.board_dirs["repos/alpha"])

    # the cross-account live repo: the card lands in live2's board and nowhere else
    resp = _exec(client, ["new-card", "--title", "from-container"], repo="beta")
    assert resp.status_code == 200 and resp.json()["returncode"] == 0, resp.text
    assert _exec(client, ["board"], repo="beta").json()["stdout"].startswith("1 cards")
    assert _exec(client, ["board"], repo="alpha").json()["stdout"].startswith("0 cards")
    assert _tree_hash(machine.board_dirs["repos/alpha"]) == alpha_before

    # the archive-only repo and the ambiguous twin never run anything
    assert _exec(client, ["new-card", "--title", "x"], repo="old").status_code == 404
    assert _exec(client, ["board"], repo="twin").status_code == 409
    assert _tree_hash(machine.board_dirs["repos/old"]) == archive_before

    # nothing outside tmp_path was written: every board.db lives where it was seeded
    found = {str(p.parent) for p in machine.tmp.rglob("board.db")}
    assert found <= {str(d) for d in machine.board_dirs.values()}
    assert not (machine.tmp / "no-ambient-config" / "overseer").exists()
