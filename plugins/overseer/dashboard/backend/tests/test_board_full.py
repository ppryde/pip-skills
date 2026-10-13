"""WF-281: the CLI's `board --json` is slim by default; the dashboard asks for --full
so the board still carries each card's body (client-side search) and checklist."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.cli_client import run_overseer


def test_board_cards_keep_body_and_checklist(client: TestClient, root: Path) -> None:
    run_overseer(root, "new-card", "--title", "Slim?", "--goal", "searchable goal text")

    [card] = client.get("/api/board").json()["board"]["cards"]

    assert "searchable goal text" in card["body"]
    assert card["checklist"] == []
