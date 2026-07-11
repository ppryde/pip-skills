from __future__ import annotations

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
    # No transcript in a tmp root -> vigil reports no live pct.
    assert body["context"]["pct"] is None
