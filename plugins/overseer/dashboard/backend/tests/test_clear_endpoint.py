from pathlib import Path

from fastapi.testclient import TestClient

from app.cli_client import run_overseer
from app.main import create_app


def _new_card(root: Path, title: str = "A") -> None:
    run_overseer(root, "new-card", "--title", title)


def test_clear_cards_endpoint_returns_backup_path(client: TestClient, root: Path) -> None:
    _new_card(root)
    resp = client.post("/api/repo/clear", json={"scope": "cards"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "cards"
    assert body["removed"]["cards"] == 1
    assert body["backup_path"]


def test_clear_unknown_scope_is_400(client: TestClient, root: Path) -> None:
    resp = client.post("/api/repo/clear", json={"scope": "everything"})
    assert resp.status_code == 400


def test_clear_is_403_on_non_loopback_without_optin(root: Path) -> None:
    remote = TestClient(create_app(root, host="0.0.0.0"))
    resp = remote.post("/api/repo/clear", json={"scope": "cards"})
    assert resp.status_code == 403


def test_clear_is_403_on_empty_host_without_optin(root: Path) -> None:
    remote = TestClient(create_app(root, host=""))
    resp = remote.post("/api/repo/clear", json={"scope": "cards"})
    assert resp.status_code == 403


def test_clear_allowed_on_non_loopback_with_optin(root: Path, monkeypatch) -> None:
    monkeypatch.setenv("OVERSEER_DASHBOARD_ALLOW_REMOTE_DESTRUCTIVE", "1")
    remote = TestClient(create_app(root, host="0.0.0.0"))
    resp = remote.post("/api/repo/clear", json={"scope": "cards"})
    assert resp.status_code == 200
