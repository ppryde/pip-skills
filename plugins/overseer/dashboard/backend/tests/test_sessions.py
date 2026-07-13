from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_sessions_empty_store(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing/empty census store yields {"sessions": []} with a 200."""
    store = tmp_path / "census" / "status.json"
    monkeypatch.setenv("CENSUS_STORE", str(store))

    resp = client.get("/api/sessions")

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"sessions": []}


def test_sessions_single_session(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A single session appears with all its fields."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    store.write_text(json.dumps({
        "version": 1,
        "limits": {},
        "sessions": {"s1": {
            "worktree_cwd": os.path.realpath(str(root)),
            "updated_at": now,
            "payload": {
                "model": {"display_name": "Opus"},
                "session_name": "night-shift",
                "pr": {"number": 22, "url": "http://pr/22", "review_state": "pending"},
                "context_window": {"used_percentage": 44},
            },
        }},
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))

    resp = client.get("/api/sessions")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sessions"]) == 1
    session = body["sessions"][0]
    assert session["id"] == "s1"
    assert session["session_name"] == "night-shift"
    assert session["model"] == "Opus"
    assert session["worktree_cwd"] == os.path.realpath(str(root))
    assert session["pct"] == 44
    assert session["pr"]["number"] == 22
    assert session["pr"]["review_state"] == "pending"
    assert session["updated_at"] == now
    assert session["stale"] is False


def test_sessions_sort_order(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sessions are sorted by updated_at descending (freshest first)."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    store.write_text(json.dumps({
        "version": 1,
        "limits": {},
        "sessions": {
            "s1": {
                "worktree_cwd": os.path.realpath(str(root)),
                "updated_at": now - 100,
                "payload": {"session_name": "oldest"},
            },
            "s2": {
                "worktree_cwd": os.path.realpath(str(root)),
                "updated_at": now,
                "payload": {"session_name": "newest"},
            },
            "s3": {
                "worktree_cwd": os.path.realpath(str(root)),
                "updated_at": now - 50,
                "payload": {"session_name": "middle"},
            },
        },
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))

    resp = client.get("/api/sessions")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sessions"]) == 3
    assert body["sessions"][0]["id"] == "s2"
    assert body["sessions"][1]["id"] == "s3"
    assert body["sessions"][2]["id"] == "s1"


def test_sessions_stale_flag(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session older than 90 seconds is flagged as stale."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    store.write_text(json.dumps({
        "version": 1,
        "limits": {},
        "sessions": {
            "fresh": {
                "worktree_cwd": os.path.realpath(str(root)),
                "updated_at": now - 30,
                "payload": {},
            },
            "stale": {
                "worktree_cwd": os.path.realpath(str(root)),
                "updated_at": now - 120,
                "payload": {},
            },
        },
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))

    resp = client.get("/api/sessions")

    assert resp.status_code == 200
    body = resp.json()
    sessions = {s["id"]: s for s in body["sessions"]}
    assert sessions["fresh"]["stale"] is False
    assert sessions["stale"]["stale"] is True


def test_sessions_optional_fields(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Optional fields (model, pr, session_name, pct) are omitted when absent."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    store.write_text(json.dumps({
        "version": 1,
        "limits": {},
        "sessions": {"s1": {
            "worktree_cwd": os.path.realpath(str(root)),
            "updated_at": now,
            "payload": {},
        }},
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))

    resp = client.get("/api/sessions")

    assert resp.status_code == 200
    body = resp.json()
    session = body["sessions"][0]
    assert session["id"] == "s1"
    assert session["updated_at"] == now
    assert session["stale"] is False
    # Optional fields should not appear
    assert "model" not in session
    assert "session_name" not in session
    assert "pr" not in session
    assert "pct" not in session
