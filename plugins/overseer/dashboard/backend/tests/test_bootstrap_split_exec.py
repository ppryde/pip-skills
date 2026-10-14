"""WF-300 C1: the bootstrap halves over `/api/exec`, against a real CLI child."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import board_service
from app.main import create_app

TOKEN = {"X-Overseer-Token": "t"}


def _exec(client: TestClient, argv: list[str], stdin: str | None = None):
    return client.post("/api/exec", json={"argv": argv, "stdin": stdin}, headers=TOKEN)


@pytest.fixture
def client(root: Path) -> TestClient:
    return TestClient(create_app(root, exec_token="t"))


def test_begin_and_finish_work_over_exec_and_bootstrap_stays_denied(client: TestClient) -> None:
    assert _exec(client, ["bootstrap", "--title", "T"]).status_code == 403
    res = _exec(client, ["bootstrap-begin", "--title", "T"]).json()
    assert res["returncode"] == 0 and json.loads(res["stdout"])["id"] == "WF-001"
    res = _exec(client, ["bootstrap-finish", "WF-001", "--branch", "feat/WF-001-t",
                         "--worktree", "/container/wt"]).json()
    assert res["returncode"] == 0 and "WF-001 planning" in res["stdout"]


def test_finish_on_a_card_past_bootstrap_is_refused_over_exec(client: TestClient) -> None:
    _exec(client, ["bootstrap-begin", "--title", "T"])
    _exec(client, ["bootstrap-finish", "WF-001", "--branch", "b", "--worktree", "/w"])
    res = _exec(client, ["bootstrap-finish", "WF-001", "--branch", "evil", "--worktree", "/x",
                         "--brief", "-"], stdin="rewritten plan").json()
    assert res["returncode"] == 1 and "is at planning" in res["stderr"]
    shown = json.loads(_exec(client, ["show", "WF-001", "--json"]).json()["stdout"])
    assert shown["branch"] == "b" and "rewritten" not in json.dumps(shown)


def test_session_id_never_reaches_the_exec_child(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "host-session")
    assert "CLAUDE_CODE_SESSION_ID" not in board_service._child_env(tmp_path)


def test_dispatch_record_is_allowed_and_dispatch_prep_stays_denied(client: TestClient) -> None:
    _exec(client, ["bootstrap-begin", "--title", "T"])
    _exec(client, ["bootstrap-finish", "WF-001", "--branch", "b", "--worktree", "/c/wt"])
    denied = _exec(client, ["dispatch-prep", "WF-001", "--stage", "planning", "--role", "planner"])
    assert denied.status_code == 403
    res = _exec(client, ["dispatch-record", "WF-001", "--stage", "planning", "--role", "planner"]).json()
    assert res["returncode"] == 0 and json.loads(res["stdout"])["card"]["worktree"] == "/c/wt"
