"""WF-100 C3: `POST /api/exec` lives on `create_app` (one server), behind its own
fail-closed token, running the CLI against a board pinned at app start."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from scripts import config

from app import board_service
from app.main import create_app

TOKEN = {"X-Overseer-Token": "t"}


def _exec(client: TestClient, argv: list[str], stdin: str | None = None, **kw: Any):
    return client.post("/api/exec", json={"argv": argv, "stdin": stdin}, headers=kw.pop("headers", TOKEN))


class _Spy:
    """Replaces subprocess.run; records (and fakes) the overseer CLI spawns only.
    Everything else (the app's own git lookups) runs for real."""

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


# --- spec §8 tests 1, 2, 3, 5 --------------------------------------------------

def test_exec_without_a_configured_token_is_503_never_200(root: Path) -> None:
    client = TestClient(create_app(root, token=None))
    assert _exec(client, ["board"], headers={}).status_code == 503
    assert _exec(client, ["board"]).status_code == 503  # even with a header


def test_loopback_bind_gets_no_exec_exemption(root: Path) -> None:
    client = TestClient(create_app(root, host="127.0.0.1", exec_token="t"))
    assert _exec(client, ["board"], headers={}).status_code == 401


def test_dashboard_stays_open_while_exec_is_gated(root: Path) -> None:
    client = TestClient(create_app(root, token=None, exec_token="t"))
    assert client.get("/api/board").status_code == 200
    assert client.post("/api/card", json={"title": "ui card"}).status_code == 200


def test_dashboard_token_does_not_open_exec_and_exec_token_does_not_open_mutations(root: Path) -> None:
    client = TestClient(create_app(root, token="dash", exec_token="exec"))
    assert _exec(client, ["board"], headers={"X-Overseer-Token": "dash"}).status_code == 401
    assert client.post(
        "/api/card", json={"title": "x"}, headers={"X-Overseer-Token": "exec"}
    ).status_code == 401


def test_denied_verbs_and_root_stripping_survive_the_merged_route(root: Path, spy: _Spy) -> None:
    client = TestClient(create_app(root, exec_token="t"))
    for argv in (["clear", "--yes"], ["init"], ["backup", "--dir", "/x"], ["restore", "--dir", "/x"]):
        assert _exec(client, argv).status_code == 403, argv
    assert spy.calls == []
    assert _exec(client, ["--root", "/elsewhere", "board"]).status_code == 200
    assert "/elsewhere" not in spy.calls[0]["cmd"]


def test_route_table_exec_has_its_own_gate_and_everything_else_the_dashboard_gate(root: Path) -> None:
    app = create_app(root, token="s", exec_token="t")
    seen = {}
    for route in app.routes:
        if isinstance(route, APIRoute) and "POST" in route.methods and route.path.startswith("/api"):
            seen[route.path] = {getattr(d.call, "__name__", None) for d in route.dependant.dependencies}
    assert "require_exec_token" in seen["/api/exec"] and "require_token" not in seen["/api/exec"]
    for path, deps in seen.items():
        if path not in ("/api/exec", "/api/chronicle/sync"):
            assert "require_token" in deps and "require_exec_token" not in deps, path


# --- child environment ---------------------------------------------------------

def test_child_env_drops_remote_and_dashboard_tokens_and_pins_central(
    root: Path, spy: _Spy, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OVERSEER_REMOTE", "http://h")
    monkeypatch.setenv("OVERSEER_REMOTE_TOKEN", "r")
    monkeypatch.setenv("OVERSEER_DASHBOARD_TOKEN", "d")
    client = TestClient(create_app(root, exec_token="t"))
    _exec(client, ["board"])
    env = spy.calls[0]["env"]
    for gone in ("OVERSEER_REMOTE", "OVERSEER_REMOTE_TOKEN", "OVERSEER_DASHBOARD_TOKEN"):
        assert gone not in env
    assert env["OVERSEER_CENTRAL"] == str(tmp_path / "state")  # the pin (env value here)


def test_child_env_strips_secret_shaped_names_and_keeps_what_the_cli_needs(
    root: Path, spy: _Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("ANTHROPIC_API_KEY", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "gh_enterprise_x",
                 "DB_PASSWORD", "my_secret"):
        monkeypatch.setenv(name, "x")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent")
    monkeypatch.setenv("CHRONICLE_DB", "/tmp/c.db")
    monkeypatch.setenv("CENSUS_KEY_X", "kept: CENSUS_ prefix is exempt")
    client = TestClient(create_app(root, exec_token="t"))
    _exec(client, ["board"])
    env = spy.calls[0]["env"]
    assert not {"ANTHROPIC_API_KEY", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "gh_enterprise_x",
                "DB_PASSWORD", "my_secret"} & set(env)
    for kept in ("PATH", "HOME", "SSH_AUTH_SOCK", "CENSUS_CLI", "CHRONICLE_DB", "CENSUS_KEY_X"):
        assert kept in env, kept


# --- limits ----------------------------------------------------------------------

def test_oversized_body_is_413(root: Path, spy: _Spy) -> None:
    client = TestClient(create_app(root, exec_token="t"))
    big = "x" * (1024 * 1024 + 1)
    assert _exec(client, ["set-section", "WF-1"], stdin=big).status_code == 413
    assert _exec(client, ["new-card", "--title", big]).status_code == 413
    assert spy.calls == []
    assert _exec(client, ["board"], stdin="x" * 1000).status_code == 200


def test_busy_server_is_503_and_releases_the_slot(root: Path, spy: _Spy) -> None:
    client = TestClient(create_app(root, exec_token="t"))
    taken = [board_service._EXEC_SLOTS.acquire(blocking=False) for _ in range(4)]
    try:
        assert all(taken)
        assert _exec(client, ["board"]).status_code == 503
        assert spy.calls == []
    finally:
        for _ in taken:
            board_service._EXEC_SLOTS.release()
    assert _exec(client, ["board"]).status_code == 200


def test_slot_is_released_when_the_cli_times_out(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(board_service.subprocess, "run", boom)
    client = TestClient(create_app(root, exec_token="t"))
    for _ in range(6):  # more than the 4 slots
        assert _exec(client, ["board"]).status_code == 504


# --- the pin ---------------------------------------------------------------------

def test_board_is_pinned_at_start_a_later_central_dir_edit_does_not_move_it(
    root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OVERSEER_CENTRAL")
    monkeypatch.delenv("OVERSEER_DB")
    pinned = config.central_root(root)
    client = TestClient(create_app(root, exec_token="t"))
    sentinel = tmp_path / "sentinel-board"
    (root / ".overseer").mkdir(exist_ok=True)
    (root / ".overseer" / "config.json").write_text(json.dumps({"central_dir": str(sentinel)}))

    resp = _exec(client, ["new-card", "--title", "pinned"])

    assert resp.status_code == 200 and resp.json()["returncode"] == 0, resp.text
    assert (pinned / "board.db").is_file()
    assert not sentinel.exists()


def test_busy_and_size_limits_are_checked_after_auth(root: Path, spy: _Spy) -> None:
    client = TestClient(create_app(root, exec_token="t"))
    big = "x" * (1024 * 1024 + 1)
    assert _exec(client, ["board"], stdin=big, headers={}).status_code == 401
