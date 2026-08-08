"""Chunk 3 exit check: routes registered, GET /api/board 200s on an inited empty tmp root."""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.cli_client import run_overseer
from app.main import create_app


def test_get_board_200_on_empty_inited_root(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    run_overseer(tmp_path, "init")

    client = TestClient(create_app(tmp_path))
    resp = client.get("/api/board")

    assert resp.status_code == 200
    body = resp.json()
    assert "board" in body
    assert "cards" in body["board"]
    assert "context" in body
