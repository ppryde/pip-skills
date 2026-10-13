"""WF-100 C2b: the dashboard shows archived boards, truly read-only.

An archived board (a backup of an old account's overseer folder) is listed
marked ``[archived]`` and readable, but nothing may write it: not a POST, not
the sqlite WAL/shm/migration side effects of a plain read.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from scripts import boards, config

from app import main as main_mod
from app.main import create_app

# A valid body per mutating POST route (path template -> json), so the walk can
# actually reach each handler. A new POST route fails the walk until listed.
BODIES: dict[str, dict[str, Any]] = {
    "/api/card": {"title": "x"},
    "/api/card/{card_id}": {"title": "x"},
    "/api/card/{card_id}/order": {"order": 1},
    "/api/lane/order": {"ids": ["WF-1"]},
    "/api/card/{card_id}/priority": {"priority": "high"},
    "/api/card/{card_id}/attributes": {"estimate": 3},
    "/api/card/{card_id}/labels": {"labels": ["a"]},
    "/api/card/{card_id}/parent": {"parent": None},
    "/api/card/{card_id}/depends": {"on": "WF-2"},
    "/api/card/{card_id}/park": {},
    "/api/card/{card_id}/pull-children": {},
    "/api/card/{card_id}/unpark": {},
    "/api/card/{card_id}/claim": {"session_id": "s"},
    "/api/card/{card_id}/unclaim": {},
    "/api/card/{card_id}/move": {"stage": "build"},
    "/api/config/threshold": {"value": 50},
    "/api/labels/colors": {"name": "a", "color": "sky"},
    "/api/repo/clear": {"scope": "cards"},
}
_CLI = Path(__file__).resolve().parents[3] / "scripts" / "cli.py"
EXEMPT = {"/api/chronicle/sync", "/api/exec"}


def _tree_hash(folder: Path) -> dict[str, str]:
    """sha256 of EVERY file under the folder, plus the listing itself."""
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*")) if p.is_file()
    }


@pytest.fixture
def archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A repo whose ONLY board lives in an archived claude dir, with one card;
    the ambient central/db overrides are gone so discovery is by layout."""
    primary = tmp_path / "primary-cfg"
    arch_cfg = tmp_path / "cfg" / "backups" / "old"
    primary.mkdir()
    arch_cfg.mkdir(parents=True)
    repo = tmp_path / "archived-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(primary))
    config.save_machine_config({"claude_dirs": [str(arch_cfg)]})
    folder = arch_cfg / "overseer" / "archived-repo-aaaaaaaa"
    monkeypatch.setenv("OVERSEER_CENTRAL", str(folder))
    monkeypatch.delenv("OVERSEER_DB", raising=False)
    # Seed through the CLI directly: `run_overseer` would (rightly) open an
    # archived central read-only.
    def cli(*args: str) -> str:
        return subprocess.run(
            [sys.executable, str(_CLI), "--root", str(repo), *args],
            capture_output=True, text=True, check=True,
        ).stdout

    cli("init")
    card_id = cli("new-card", "--title", "old", "--complexity", "S").strip()
    monkeypatch.delenv("OVERSEER_CENTRAL")
    boards._discover_cache_clear()
    return {"repo": repo, "folder": folder, "card": card_id, "arch_cfg": arch_cfg, "primary": primary}


def _client(root: Path) -> TestClient:
    return TestClient(create_app(root))


def test_repos_lists_the_archive_marked_and_flagged(archive: dict[str, Any]) -> None:
    resp = _client(archive["primary"]).get("/api/repos")
    entries = [r for r in resp.json()["repos"] if r.get("archived")]
    assert [e["label"] for e in entries] == ["archived-repo [archived]"]
    assert Path(entries[0]["root"]).resolve() == archive["repo"].resolve()


def test_reads_leave_the_whole_archive_folder_untouched(archive: dict[str, Any]) -> None:
    client = _client(archive["primary"])
    root = str(archive["repo"])
    client.get("/api/repos")  # fills the archived map, as the UI does first
    before = _tree_hash(archive["folder"])
    assert before, "seed produced no files"

    board = client.get("/api/board", params={"root": root})
    assert board.status_code == 200, board.text
    assert [c["id"] for c in board.json()["board"]["cards"]] == [archive["card"]]
    card = client.get(f"/api/card/{archive['card']}", params={"root": root})
    assert card.status_code == 200, card.text

    assert _tree_hash(archive["folder"]) == before  # content AND listing (no -wal/-shm)


def test_every_post_route_refuses_an_archived_root(archive: dict[str, Any]) -> None:
    app = create_app(archive["primary"])
    client = TestClient(app)
    root = str(archive["repo"])
    client.get("/api/repos")
    before = _tree_hash(archive["folder"])
    seen = set()
    for route in app.routes:
        if not isinstance(route, APIRoute) or "POST" not in route.methods:
            continue
        if not route.path.startswith("/api") or route.path in EXEMPT:
            continue
        seen.add(route.path)
        assert route.path in BODIES, f"add a valid body for new POST route {route.path}"
        assert "mutating=True" in inspect.getsource(route.endpoint), route.path
        url = route.path.replace("{card_id}", archive["card"])
        body = dict(BODIES[route.path])
        params: dict[str, str] = {"root": root}
        if route.path == "/api/repo/clear":
            body["root"] = root
            params = {}
        resp = client.post(url, params=params, json=body)
        assert resp.status_code == 403, (route.path, resp.status_code, resp.text)
        assert "archived" in resp.json()["detail"]
    assert seen == set(BODIES)
    assert _tree_hash(archive["folder"]) == before


def test_default_root_whose_central_dir_points_into_an_archive_is_read_only(
    archive: dict[str, Any], tmp_path: Path
) -> None:
    launch = tmp_path / "launch"
    launch.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=launch, check=True)
    (launch / ".overseer").mkdir()
    (launch / ".overseer" / "config.json").write_text(json.dumps({"central_dir": str(archive["folder"])}))
    client = _client(launch)
    before = _tree_hash(archive["folder"])

    resp = client.post("/api/card", json={"title": "sneaky"})  # no root: the launch default

    assert resp.status_code == 403
    assert _tree_hash(archive["folder"]) == before


def test_launch_root_pinned_into_an_archive_reads_read_only(
    archive: dict[str, Any], tmp_path: Path
) -> None:
    """R7-3: the switch keys on the EFFECTIVE central, not only discovered roots."""
    launch = tmp_path / "launch"
    launch.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=launch, check=True)
    (launch / ".overseer").mkdir()
    (launch / ".overseer" / "config.json").write_text(json.dumps({"central_dir": str(archive["folder"])}))
    before = _tree_hash(archive["folder"])

    resp = _client(launch).get("/api/board")

    assert resp.status_code == 200, resp.text
    assert _tree_hash(archive["folder"]) == before


def test_resolve_root_signature_has_the_mutating_switch() -> None:
    assert "mutating" in inspect.signature(main_mod._resolve_root).parameters
    with pytest.raises(HTTPException):
        main_mod._resolve_root(Path("/x"), Path("/x"), "/not-a-known-root", mutating=True)


def test_readonly_env_keys_on_the_effective_central(archive: dict[str, Any], tmp_path: Path) -> None:
    from app import cli_client

    launch = tmp_path / "launch"
    launch.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=launch, check=True)
    (launch / ".overseer").mkdir()
    (launch / ".overseer" / "config.json").write_text(json.dumps({"central_dir": str(archive["folder"])}))

    env = cli_client._readonly_env(launch)
    assert env is not None
    assert env["OVERSEER_READONLY"] == "1" and env["OVERSEER_CENTRAL"] == str(archive["folder"])

    live = tmp_path / "live"
    live.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=live, check=True)
    assert cli_client._readonly_env(live) is None  # an ordinary live board is untouched


def test_pinned_board_in_an_archive_disables_unlabelled_exec_only(
    archive: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R4-4: the server still starts (one process, the dashboard must live);
    only exec without a repo label answers 503, and the child is never spawned."""
    from app import board_service

    launch = tmp_path / "launch"
    launch.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=launch, check=True)
    (launch / ".overseer").mkdir()
    (launch / ".overseer" / "config.json").write_text(json.dumps({"central_dir": str(archive["folder"])}))
    app = create_app(launch, exec_token="t")
    spawned: list[Any] = []
    real_run = board_service.subprocess.run
    monkeypatch.setattr(board_service.subprocess, "run", lambda *a, **k: spawned.append(a))
    client = TestClient(app)
    before = _tree_hash(archive["folder"])

    resp = client.post("/api/exec", json={"argv": ["board"]}, headers={"X-Overseer-Token": "t"})

    assert resp.status_code == 503
    assert "archive" in resp.json()["detail"] and "disabled" in resp.json()["detail"]
    assert spawned == []
    monkeypatch.setattr(board_service.subprocess, "run", real_run)
    assert client.get("/api/board").status_code == 200  # the dashboard is up and read-only
    assert _tree_hash(archive["folder"]) == before
