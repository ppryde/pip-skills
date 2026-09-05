from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cli_client import run_overseer
from app.main import create_app


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
            "branch": "feat/night-shift",
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
    assert session["branch"] == "feat/night-shift"
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
    """Optional fields (model, pr, session_name, branch, pct) are omitted when absent."""
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
    assert "branch" not in session
    assert "pct" not in session


def test_sessions_malformed_updated_at_null(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed updated_at (null) does not raise; treated as stale."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({
        "version": 1,
        "limits": {},
        "sessions": {"s1": {
            "worktree_cwd": os.path.realpath(str(root)),
            "updated_at": None,
            "payload": {"session_name": "test"},
        }},
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))

    resp = client.get("/api/sessions")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sessions"]) == 1
    session = body["sessions"][0]
    assert session["id"] == "s1"
    assert session["updated_at"] is None
    assert session["stale"] is True


def test_sessions_malformed_updated_at_string(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed updated_at (non-numeric string) does not raise; treated as stale."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({
        "version": 1,
        "limits": {},
        "sessions": {"s1": {
            "worktree_cwd": os.path.realpath(str(root)),
            "updated_at": "bad",
            "payload": {"session_name": "test"},
        }},
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))

    resp = client.get("/api/sessions")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sessions"]) == 1
    session = body["sessions"][0]
    assert session["id"] == "s1"
    assert session["updated_at"] == "bad"
    assert session["stale"] is True


def test_sessions_malformed_updated_at_sorts_last(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed timestamps sort last (treated as 0), behind fresh entries."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    store.write_text(json.dumps({
        "version": 1,
        "limits": {},
        "sessions": {
            "fresh": {
                "worktree_cwd": os.path.realpath(str(root)),
                "updated_at": now - 10,
                "payload": {},
            },
            "malformed": {
                "worktree_cwd": os.path.realpath(str(root)),
                "updated_at": "bad",
                "payload": {},
            },
        },
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))

    resp = client.get("/api/sessions")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sessions"]) == 2
    # Fresh entry comes first
    assert body["sessions"][0]["id"] == "fresh"
    # Malformed (sorted as 0) comes last
    assert body["sessions"][1]["id"] == "malformed"


# --- /api/sessions repo scoping (+ ghost-drop) ---------------------------
#
# These tests do NOT use the shared `root`/`client` fixtures from conftest.py:
# validating a client-supplied `root` goes through `_resolve_root`, which
# checks the `repos` discovery allowlist — that needs an isolated,
# shared config-dir-style layout for TWO separate repos (mirrors
# test_repos.py's fixtures).


@pytest.fixture()
def isolated_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_dir = tmp_path / "claude-config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    monkeypatch.delenv("OVERSEER_DB", raising=False)
    monkeypatch.delenv("OVERSEER_CENTRAL", raising=False)
    return config_dir


def _make_repo(tmp_path: Path, isolated_config_dir: Path, name: str) -> Path:
    repo_root = tmp_path / name
    repo_root.mkdir()
    subprocess.run(["git", "init"], cwd=repo_root, capture_output=True, check=True)
    run_overseer(repo_root, "init")
    return repo_root.resolve()


@pytest.fixture()
def repo_a(tmp_path: Path, isolated_config_dir: Path) -> Path:
    return _make_repo(tmp_path, isolated_config_dir, "repo-a")


@pytest.fixture()
def repo_b(tmp_path: Path, isolated_config_dir: Path) -> Path:
    return _make_repo(tmp_path, isolated_config_dir, "repo-b")


def test_sessions_root_param_scopes_to_that_repo_and_drops_ghosts(
    repo_a: Path, repo_b: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`root=<repoB>` returns only sessions whose `worktree_cwd` derives to
    repo B; a session living in repo A is excluded; a session whose cwd
    doesn't resolve to any repo at all (removed worktree - a ghost) is
    dropped from the response entirely, not just filtered out of the wrong
    repo's list."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    ghost_cwd = tmp_path / "removed-worktree"  # never created -> not a git repo
    store.write_text(json.dumps({
        "version": 1,
        "limits": {},
        "sessions": {
            "in-a": {
                "worktree_cwd": str(repo_a),
                "updated_at": now,
                "payload": {"session_name": "a-session"},
            },
            "in-b": {
                "worktree_cwd": str(repo_b),
                "updated_at": now,
                "payload": {"session_name": "b-session"},
            },
            "ghost": {
                "worktree_cwd": str(ghost_cwd),
                "updated_at": now,
                "payload": {"session_name": "ghost-session"},
            },
        },
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))

    client = TestClient(create_app(repo_a))
    resp = client.get("/api/sessions", params={"root": str(repo_b)})

    assert resp.status_code == 200
    ids = {s["id"] for s in resp.json()["sessions"]}
    assert ids == {"in-b"}


def test_sessions_default_root_is_the_served_repo(
    repo_a: Path, repo_b: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Omitting `root` scopes sessions to the served (launch) repo, exactly
    as the default has always meant for /api/board and the card routes."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    store.write_text(json.dumps({
        "version": 1,
        "limits": {},
        "sessions": {
            "in-a": {
                "worktree_cwd": str(repo_a),
                "updated_at": now,
                "payload": {},
            },
            "in-b": {
                "worktree_cwd": str(repo_b),
                "updated_at": now,
                "payload": {},
            },
        },
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))

    client = TestClient(create_app(repo_a))
    resp = client.get("/api/sessions")

    assert resp.status_code == 200
    ids = {s["id"] for s in resp.json()["sessions"]}
    assert ids == {"in-a"}


def test_sessions_unknown_root_is_rejected(repo_a: Path, tmp_path: Path) -> None:
    """A `root` outside the `repos` discovery allowlist -> 400, unchanged
    from every other route's `_resolve_root` validation."""
    client = TestClient(create_app(repo_a))
    rogue = tmp_path / "not-a-discovered-repo"
    rogue.mkdir()

    resp = client.get("/api/sessions", params={"root": str(rogue)})

    assert resp.status_code == 400
    assert "unknown root" in resp.json()["detail"]


def test_sessions_idle_flag(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session still rendering (fresh updated_at) but with no activity for 10 minutes
    is idle, not stale; a session without active_at falls back to updated_at."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    cwd = os.path.realpath(str(root))
    store.write_text(json.dumps({
        "version": 1,
        "limits": {},
        "sessions": {
            "working": {"worktree_cwd": cwd, "updated_at": now - 5, "active_at": now - 5, "payload": {}},
            "dormant": {"worktree_cwd": cwd, "updated_at": now - 5, "active_at": now - 900, "payload": {}},
            "legacy": {"worktree_cwd": cwd, "updated_at": now - 5, "payload": {}},
        },
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))

    resp = client.get("/api/sessions")

    assert resp.status_code == 200
    sessions = {s["id"]: s for s in resp.json()["sessions"]}
    assert sessions["working"]["idle"] is False
    assert sessions["dormant"]["idle"] is True
    assert sessions["dormant"]["stale"] is False
    assert sessions["dormant"]["active_at"] == now - 900
    assert sessions["legacy"]["idle"] is False


def test_sessions_idle_flag_edge_cases(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A malformed active_at must not raise, and a session can be BOTH stale and
    idle — consumers check stale first, so both flags must be reported honestly."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    cwd = os.path.realpath(str(root))
    store.write_text(json.dumps({
        "version": 1,
        "limits": {},
        "sessions": {
            # Malformed active_at values fall back to updated_at rather than raising.
            "null_active": {"worktree_cwd": cwd, "updated_at": now - 5, "active_at": None, "payload": {}},
            "string_active": {"worktree_cwd": cwd, "updated_at": now - 5, "active_at": "bad", "payload": {}},
            "bool_active": {"worktree_cwd": cwd, "updated_at": now - 5, "active_at": True, "payload": {}},
            # Long dead: no render for hours, no activity for hours.
            "dead": {"worktree_cwd": cwd, "updated_at": now - 7200, "active_at": now - 7200, "payload": {}},
        },
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))

    resp = client.get("/api/sessions")

    assert resp.status_code == 200
    sessions = {s["id"]: s for s in resp.json()["sessions"]}
    for sid in ("null_active", "string_active", "bool_active"):
        assert sessions[sid]["idle"] is False, sid
        assert sessions[sid]["stale"] is False, sid
    assert sessions["dead"]["stale"] is True
    assert sessions["dead"]["idle"] is True


def test_sessions_sorted_by_activity_not_render(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dormant session rendered most recently, so an updated_at sort would
    put it first. Only the dashboard's own hook re-sorts client side; every
    other consumer of this endpoint gets the order we send."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    cwd = os.path.realpath(str(root))
    store.write_text(json.dumps({
        "version": 1,
        "limits": {},
        "sessions": {
            "dormant": {"worktree_cwd": cwd, "updated_at": now - 1, "active_at": now - 1800, "payload": {}},
            "working": {"worktree_cwd": cwd, "updated_at": now - 30, "active_at": now - 30, "payload": {}},
            "legacy": {"worktree_cwd": cwd, "updated_at": now - 120, "payload": {}},
        },
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))

    resp = client.get("/api/sessions")

    assert resp.status_code == 200
    assert [s["id"] for s in resp.json()["sessions"]] == ["working", "legacy", "dormant"]


def test_sessions_nan_active_at_does_not_500(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """json round-trips a bare NaN, and Starlette renders with allow_nan=False,
    so forwarding it raw would 500 the one census read documented as never
    doing so."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    cwd = os.path.realpath(str(root))
    store.write_text(
        '{"version": 1, "limits": {}, "sessions": {"nan": {"worktree_cwd": "'
        + cwd
        + '", "updated_at": ' + repr(now - 5) + ', "active_at": NaN, "payload": {}}}}'
    )
    monkeypatch.setenv("CENSUS_STORE", str(store))

    resp = client.get("/api/sessions")

    assert resp.status_code == 200
    session = resp.json()["sessions"][0]
    assert session["active_at"] is None
    assert session["idle"] is False  # falls back to updated_at, which is fresh


def test_sessions_numeric_string_active_at_agrees_with_census(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """census's own reader rejects a string active_at and falls back to
    updated_at. This mirror must reach the same verdict, or one entry is idle
    to one reader and working to the other."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    cwd = os.path.realpath(str(root))
    store.write_text(json.dumps({
        "version": 1,
        "limits": {},
        "sessions": {"s1": {"worktree_cwd": cwd, "updated_at": now - 5, "active_at": "700", "payload": {}}},
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))

    resp = client.get("/api/sessions")

    assert resp.status_code == 200
    assert resp.json()["sessions"][0]["idle"] is False


def test_sessions_merge_across_watched_config_dirs(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Multi-account: with a second Claude config dir listed in the primary's
    machine config, its census store's sessions join the same list, each
    tagged with the dir it came from. `CENSUS_STORE` must be unset — pinned,
    there is one store by definition."""
    monkeypatch.delenv("CENSUS_STORE", raising=False)
    primary = tmp_path / "claude"
    personal = tmp_path / "claude-personal"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(primary))
    now = time.time()
    cwd = os.path.realpath(str(root))

    def _store(config_dir: Path, sid: str, name: str) -> None:
        path = config_dir / "census" / "status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "version": 1, "limits": {},
            "sessions": {sid: {"worktree_cwd": cwd, "updated_at": now,
                                "payload": {"session_name": name}}},
        }))

    _store(primary, "s-work", "work")
    _store(personal, "s-home", "home")
    (primary / "overseer").mkdir(parents=True, exist_ok=True)
    (primary / "overseer" / "config.json").write_text(json.dumps({"claude_dirs": [str(personal)]}))

    body = client.get("/api/sessions").json()
    by_id = {s["id"]: s for s in body["sessions"]}
    assert set(by_id) == {"s-work", "s-home"}
    assert by_id["s-work"]["config_dir"] == str(primary)
    assert by_id["s-home"]["config_dir"] == str(personal)
    assert by_id["s-home"]["session_name"] == "home"
