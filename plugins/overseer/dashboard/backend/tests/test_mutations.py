from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.cli_client import run_overseer


def _new_card(root: Path, title: str = "T") -> str:
    out: str = run_overseer(root, "new-card", "--title", title, "--complexity", "S")
    return out.strip()


def _show(root: Path, card_id: str) -> dict:
    return run_overseer(root, "show", card_id, "--json", json_out=True)  # type: ignore[no-any-return]


def test_order(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)

    resp = client.post(f"/api/card/{card_id}/order", json={"order": 7})

    assert resp.status_code == 200
    assert resp.json()["board"]["cards"][0]["order"] == 7
    assert _show(root, card_id)["order"] == 7


def test_priority_set_and_clear(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)

    resp = client.post(f"/api/card/{card_id}/priority", json={"priority": "P1"})
    assert resp.status_code == 200
    assert _show(root, card_id)["priority"] == "P1"

    resp = client.post(f"/api/card/{card_id}/priority", json={"priority": None})
    assert resp.status_code == 200
    assert _show(root, card_id)["priority"] is None


def test_parent_set_and_clear(client: TestClient, root: Path) -> None:
    parent_id = _new_card(root, "Parent")
    card_id = _new_card(root, "Child")

    resp = client.post(f"/api/card/{card_id}/parent", json={"parent": parent_id})
    assert resp.status_code == 200
    assert _show(root, card_id)["parent"] == parent_id

    resp = client.post(f"/api/card/{card_id}/parent", json={"parent": None})
    assert resp.status_code == 200
    assert _show(root, card_id)["parent"] is None


def test_depends_on_and_off(client: TestClient, root: Path) -> None:
    other_id = _new_card(root, "Other")
    card_id = _new_card(root, "Depender")

    resp = client.post(f"/api/card/{card_id}/depends", json={"on": other_id, "off": None})
    assert resp.status_code == 200
    assert _show(root, card_id)["depends_on"] == [other_id]

    resp = client.post(f"/api/card/{card_id}/depends", json={"on": None, "off": other_id})
    assert resp.status_code == 200
    assert _show(root, card_id)["depends_on"] == []


def test_depends_requires_on_or_off(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)

    resp = client.post(f"/api/card/{card_id}/depends", json={})

    assert resp.status_code == 400
    assert "on or off" in resp.json()["detail"]


def test_park_and_unpark(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)

    resp = client.post(f"/api/card/{card_id}/park")
    assert resp.status_code == 200
    assert _show(root, card_id)["status"] == "parked"

    resp = client.post(f"/api/card/{card_id}/unpark")
    assert resp.status_code == 200
    assert _show(root, card_id)["status"] == "planned"


def test_move_set_stage(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)

    resp = client.post(f"/api/card/{card_id}/move", json={"stage": "planning"})

    assert resp.status_code == 200
    assert _show(root, card_id)["stage"] == "planning"


def test_move_done(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)

    resp = client.post(f"/api/card/{card_id}/move", json={"status": "done"})

    assert resp.status_code == 200
    # done archives the card; the board still lists it, now with status "done".
    cards = {c["id"]: c for c in resp.json()["board"]["cards"]}
    assert cards[card_id]["status"] == "done"


def test_move_blocked_without_reason_is_400(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)

    resp = client.post(f"/api/card/{card_id}/move", json={"status": "blocked"})

    assert resp.status_code == 400
    assert "reason" in resp.json()["detail"]


def test_move_blocked_with_reason_ok(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)

    resp = client.post(
        f"/api/card/{card_id}/move", json={"status": "blocked", "reason": "waiting on X"}
    )

    assert resp.status_code == 200
    assert _show(root, card_id)["status"] == "blocked"


def test_threshold(client: TestClient, root: Path) -> None:
    resp = client.post("/api/config/threshold", json={"value": 60})

    assert resp.status_code == 200
    assert resp.json()["context"]["threshold"] == 60


def test_get_unknown_card_is_404(client: TestClient) -> None:
    resp = client.get("/api/card/NOPE-999")

    assert resp.status_code == 404


def test_bad_move_is_400_with_detail(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)

    resp = client.post(f"/api/card/{card_id}/move", json={"status": "not-a-status"})

    assert resp.status_code == 400
    assert "not-a-status" in resp.json()["detail"]


def test_move_unblock_is_stage_derived(client: TestClient, root: Path) -> None:
    """Documented subtle edge: overseer has no unified set-status verb, so
    `/move` with status in-flight/planned both dispatch to `unblock`, whose
    resulting status is stage-derived — a staged card comes back in-flight
    even when the client explicitly requested "planned"."""
    card_id = _new_card(root)
    run_overseer(root, "set-stage", card_id, "planning")
    run_overseer(root, "block", card_id, "--reason", "waiting on X")

    resp = client.post(f"/api/card/{card_id}/move", json={"status": "in-flight"})
    assert resp.status_code == 200
    cards = {c["id"]: c for c in resp.json()["board"]["cards"]}
    assert cards[card_id]["status"] == "in-flight"
    assert _show(root, card_id)["status"] == "in-flight"

    # Re-block, then request "planned" — the card still has a stage, so the
    # actual resulting status is STILL in-flight, not the requested "planned".
    run_overseer(root, "block", card_id, "--reason", "waiting again")

    resp = client.post(f"/api/card/{card_id}/move", json={"status": "planned"})
    assert resp.status_code == 200
    cards = {c["id"]: c for c in resp.json()["board"]["cards"]}
    assert cards[card_id]["status"] == "in-flight"
    assert _show(root, card_id)["status"] == "in-flight"


def test_move_status_dispatch_parked_and_abandoned(client: TestClient, root: Path) -> None:
    """Exercises the status->verb dispatch dict directly (not the dedicated
    /park route) for the "parked" and "abandoned" entries."""
    parked_id = _new_card(root, "Parked")

    resp = client.post(f"/api/card/{parked_id}/move", json={"status": "parked"})

    assert resp.status_code == 200
    cards = {c["id"]: c for c in resp.json()["board"]["cards"]}
    assert cards[parked_id]["status"] == "parked"
    assert _show(root, parked_id)["status"] == "parked"

    abandoned_id = _new_card(root, "Abandoned")

    resp = client.post(f"/api/card/{abandoned_id}/move", json={"status": "abandoned"})

    assert resp.status_code == 200
    # abandon archives the card; the board still lists it, now "abandoned".
    cards = {c["id"]: c for c in resp.json()["board"]["cards"]}
    assert cards[abandoned_id]["status"] == "abandoned"
