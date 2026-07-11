from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_board_shape(client: TestClient) -> None:
    resp = client.get("/api/board")

    assert resp.status_code == 200
    body = resp.json()

    assert "board" in body
    assert "cards" in body["board"]
    assert "sprints" in body["board"]

    assert "context" in body
    assert isinstance(body["context"]["threshold"], int)
    # No transcript and no census entry in a tmp root -> vigil reports no live pct.
    assert body["context"]["pct"] is None
    # census absent for this worktree -> no rich extras, no limits.
    assert body["limits"] is None


def test_board_surfaces_census(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When census has a live entry for this worktree, the board carries its
    pct (via vigil), model / pr / session_name (extras), and the 5h/7d limits."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({
        "version": 1,
        "limits": {
            "five_hour": {"used_percentage": 20, "resets_at": 1},
            "seven_day": {"used_percentage": 40, "resets_at": 2},
        },
        "sessions": {"s1": {
            "worktree_cwd": os.path.realpath(str(root)),
            "updated_at": time.time(),
            "payload": {
                "model": {"display_name": "Opus"},
                "session_name": "night-shift",
                "pr": {"number": 22, "url": "http://pr/22", "review_state": "pending"},
                "context_window": {"used_percentage": 44},
            },
        }},
    }))
    # subprocesses (vigil + census) inherit this env
    monkeypatch.setenv("CENSUS_STORE", str(store))

    body = client.get("/api/board").json()
    ctx = body["context"]
    assert ctx["pct"] == 44                       # vigil read census, worktree-correct
    assert ctx["model"] == "Opus"
    assert ctx["session_name"] == "night-shift"
    assert ctx["pr"]["number"] == 22
    assert ctx["pr"]["review_state"] == "pending"
    assert ctx["stale"] is False
    assert body["limits"]["five_hour"]["used_percentage"] == 20
    assert body["limits"]["seven_day"]["used_percentage"] == 40
