from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cli_client import run_overseer


def _new_card(root: Path, title: str = "T") -> str:
    out: str = run_overseer(root, "new-card", "--title", title, "--complexity", "S")
    return out.strip()


def _show(root: Path, card_id: str) -> dict:
    return run_overseer(root, "show", card_id, "--json", json_out=True)  # type: ignore[no-any-return]


def _seed_census(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sid: str, stale: bool) -> None:
    """Seed a CENSUS_STORE entry for `sid`, live or stale — mirrors
    test_sessions.py's env-var seeding, so overseer's `claim` verb (shelled
    from the endpoint, which shells census in turn) sees it through the same
    subprocess-env-inheritance chain."""
    store = tmp_path / "census" / "status.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    now = time.time()
    updated_at = now - 120 if stale else now
    store.write_text(json.dumps({
        "version": 1,
        "limits": {},
        "sessions": {sid: {
            "worktree_cwd": str(tmp_path),
            "updated_at": updated_at,
            "payload": {},
        }},
    }))
    monkeypatch.setenv("CENSUS_STORE", str(store))


def test_claim_success(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)

    resp = client.post(f"/api/card/{card_id}/claim", json={"session_id": "sess-1"})

    assert resp.status_code == 200
    detail = _show(root, card_id)
    assert detail["claimed_by"] == "sess-1"
    assert detail["claim_acked"] is False


def test_claim_missing_session_id_is_400(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)

    resp = client.post(f"/api/card/{card_id}/claim", json={})

    assert resp.status_code == 400
    assert "session_id" in resp.json()["detail"]


def test_claim_empty_session_id_is_400(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)

    resp = client.post(f"/api/card/{card_id}/claim", json={"session_id": ""})

    assert resp.status_code == 400
    assert "session_id" in resp.json()["detail"]


def test_claim_refused_when_live_holder(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second claim by a different session is refused (CLI exit 1) while
    the current holder is live in census — surfaces as the same 400 shape
    every other mutation-error path uses."""
    card_id = _new_card(root)
    run_overseer(root, "claim", card_id, "--session", "sess-live")
    _seed_census(tmp_path, monkeypatch, "sess-live", stale=False)

    resp = client.post(f"/api/card/{card_id}/claim", json={"session_id": "sess-2"})

    assert resp.status_code == 400
    assert "sess-live" in resp.json()["detail"]
    # The original live claim is untouched.
    assert _show(root, card_id)["claimed_by"] == "sess-live"


def test_claim_displaces_stale_holder(
    client: TestClient, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    card_id = _new_card(root)
    run_overseer(root, "claim", card_id, "--session", "sess-stale")
    _seed_census(tmp_path, monkeypatch, "sess-stale", stale=True)

    resp = client.post(f"/api/card/{card_id}/claim", json={"session_id": "sess-new"})

    assert resp.status_code == 200
    assert _show(root, card_id)["claimed_by"] == "sess-new"


def test_unclaim(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)
    run_overseer(root, "claim", card_id, "--session", "sess-1")

    resp = client.post(f"/api/card/{card_id}/unclaim")

    assert resp.status_code == 200
    assert _show(root, card_id)["claimed_by"] is None


def test_unclaim_idempotent(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)

    resp = client.post(f"/api/card/{card_id}/unclaim")

    assert resp.status_code == 200
    assert _show(root, card_id)["claimed_by"] is None


def test_board_response_passes_claim_fields_through(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)
    run_overseer(root, "claim", card_id, "--session", "sess-1")

    resp = client.get("/api/board")

    assert resp.status_code == 200
    cards = {c["id"]: c for c in resp.json()["board"]["cards"]}
    assert cards[card_id]["claimed_by"] == "sess-1"
    assert cards[card_id]["claim_acked"] is False
