from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cli_client import run_overseer


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
            # resets_at must be in the future: census drops expired windows (22f0aa9)
            "five_hour": {"used_percentage": 20, "resets_at": time.time() + 3600},
            "seven_day": {"used_percentage": 40, "resets_at": time.time() + 86400},
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


def test_board_carries_checklist_passthrough(client: TestClient, root: Path) -> None:
    """`board_data` (overseer core) gained a `checklist` field on cards. The
    dashboard backend shells `overseer board --json` and does no transform on
    card dicts, so this must pass through verbatim with no backend code change."""
    card_id = run_overseer(root, "new-card", "--title", "Checklist card").strip()

    card_path = next((root / ".workflow" / "cards").glob(f"{card_id}-*.md"))
    text = card_path.read_text().replace(
        "status: planned\n",
        "status: planned\n"
        "checklist:\n"
        "  - {task: '1', subject: write tests, status: in_progress}\n"
        "  - {task: '2', subject: implement, status: pending}\n",
        1,
    )
    card_path.write_text(text)

    resp = client.get("/api/board")

    assert resp.status_code == 200
    cards = {c["id"]: c for c in resp.json()["board"]["cards"]}
    assert cards[card_id]["checklist"] == [
        {"task": "1", "subject": "write tests", "status": "in_progress"},
        {"task": "2", "subject": "implement", "status": "pending"},
    ]


def test_board_carries_repo_passthrough(client: TestClient, root: Path) -> None:
    """`board_data` (overseer core) gained a `repo` field on cards. The
    dashboard backend shells `overseer board --json` and does no transform on
    card dicts, so this must pass through verbatim with no backend code change."""
    card_id = run_overseer(
        root, "new-card", "--title", "Repo card", "--repo", "pip-skills"
    ).strip()

    resp = client.get("/api/board")

    assert resp.status_code == 200
    cards = {c["id"]: c for c in resp.json()["board"]["cards"]}
    assert cards[card_id]["repo"] == "pip-skills"
