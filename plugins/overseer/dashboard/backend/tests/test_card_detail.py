from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.cli_client import run_overseer


def test_get_card_200_with_sections_and_body(client: TestClient, root: Path) -> None:
    card_id = run_overseer(
        root, "new-card", "--title", "Detail card", "--complexity", "M", "--goal", "Ship it"
    ).strip()

    resp = client.get(f"/api/card/{card_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == card_id
    assert body["title"] == "Detail card"
    assert "sections" in body
    assert "## Goal" in body["sections"]
    assert "body" in body


def test_get_card_unknown_is_404(client: TestClient) -> None:
    resp = client.get("/api/card/NOPE-999")

    assert resp.status_code == 404
