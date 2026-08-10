from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.cli_client import run_overseer
from app.main import create_app


def _new_card(root: Path, title: str = "T") -> str:
    out: str = run_overseer(root, "new-card", "--title", title, "--complexity", "S")
    return out.strip()


def _show(root: Path, card_id: str) -> dict:
    return run_overseer(root, "show", card_id, "--json", json_out=True)  # type: ignore[no-any-return]


def _gated_client(root: Path, token: str = "s3cret") -> TestClient:
    return TestClient(create_app(root, token=token))


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


def test_labels_set_and_clear(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)

    resp = client.post(f"/api/card/{card_id}/labels", json={"labels": ["policy", "architecture"]})
    assert resp.status_code == 200
    assert _show(root, card_id)["labels"] == ["policy", "architecture"]
    cards = {c["id"]: c for c in resp.json()["board"]["cards"]}
    assert cards[card_id]["labels"] == ["policy", "architecture"]

    resp = client.post(f"/api/card/{card_id}/labels", json={"labels": []})
    assert resp.status_code == 200
    assert _show(root, card_id)["labels"] == []


def test_labels_unknown_card_is_400(client: TestClient) -> None:
    resp = client.post("/api/card/NOPE-999/labels", json={"labels": ["policy"]})

    assert resp.status_code == 400


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


def test_gate_open_when_no_token(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)
    # default `client` fixture builds create_app(root) with token=None
    assert client.post(f"/api/card/{card_id}/park").status_code == 200


def test_gate_rejects_missing_token(root: Path) -> None:
    card_id = _new_card(root)
    gc = _gated_client(root)
    resp = gc.post(f"/api/card/{card_id}/park")
    assert resp.status_code == 401


def test_gate_rejects_wrong_token(root: Path) -> None:
    card_id = _new_card(root)
    gc = _gated_client(root)
    resp = gc.post(f"/api/card/{card_id}/park", headers={"X-Overseer-Token": "nope"})
    assert resp.status_code == 401


def test_gate_accepts_correct_token(root: Path) -> None:
    card_id = _new_card(root)
    gc = _gated_client(root)
    resp = gc.post(f"/api/card/{card_id}/park", headers={"X-Overseer-Token": "s3cret"})
    assert resp.status_code == 200


def test_gate_leaves_reads_open(root: Path) -> None:
    gc = _gated_client(root)
    assert gc.get("/api/board").status_code == 200  # no token, still 200


def test_create_card(client: TestClient, root: Path) -> None:
    resp = client.post("/api/card", json={"title": "Fresh card", "complexity": "M"})
    assert resp.status_code == 200
    new_id = resp.json()["card_id"]
    assert new_id  # minted id echoed
    assert _show(root, new_id)["title"] == "Fresh card"
    assert new_id in {c["id"] for c in resp.json()["board"]["cards"]}


def test_create_card_with_labels(client: TestClient, root: Path) -> None:
    resp = client.post("/api/card", json={"title": "Tagged", "labels": ["policy", "arch"]})
    assert resp.status_code == 200
    assert _show(root, resp.json()["card_id"])["labels"] == ["policy", "arch"]


def test_create_card_missing_title(client: TestClient, root: Path) -> None:
    assert client.post("/api/card", json={"complexity": "S"}).status_code == 422  # pydantic required


def test_create_card_empty_title(client: TestClient, root: Path) -> None:
    assert client.post("/api/card", json={"title": "  "}).status_code == 400


def test_edit_title(client: TestClient, root: Path) -> None:
    cid = _new_card(root)
    resp = client.post(f"/api/card/{cid}", json={"title": "Renamed"})
    assert resp.status_code == 200
    assert _show(root, cid)["title"] == "Renamed"


def test_edit_body(client: TestClient, root: Path) -> None:
    cid = _new_card(root)
    resp = client.post(f"/api/card/{cid}", json={"body": "## Goal\nnew body"})
    assert resp.status_code == 200
    assert _show(root, cid)["body"] == "## Goal\nnew body"


def test_edit_title_and_body(client: TestClient, root: Path) -> None:
    cid = _new_card(root)
    resp = client.post(f"/api/card/{cid}", json={"title": "Both", "body": "x"})
    assert resp.status_code == 200
    detail = _show(root, cid)
    assert detail["title"] == "Both" and detail["body"] == "x"


def test_edit_empty_title_rejected(client: TestClient, root: Path) -> None:
    cid = _new_card(root)
    assert client.post(f"/api/card/{cid}", json={"title": ""}).status_code == 400


def test_edit_requires_a_field(client: TestClient, root: Path) -> None:
    cid = _new_card(root)
    assert client.post(f"/api/card/{cid}", json={}).status_code == 400
