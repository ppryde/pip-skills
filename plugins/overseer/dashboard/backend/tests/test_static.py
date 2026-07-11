from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.cli_client import run_overseer
from app.main import create_app


def _client(tmp_path: Path) -> TestClient:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    run_overseer(tmp_path, "init")
    return TestClient(create_app(tmp_path))


def test_root_is_200_placeholder_when_dist_absent(tmp_path: Path) -> None:
    # The real frontend/dist directory does not exist in this checkout yet.
    client = _client(tmp_path)

    resp = client.get("/")

    assert resp.status_code == 200
    assert "Frontend not built" in resp.text


def test_api_board_still_200_when_dist_absent(tmp_path: Path) -> None:
    client = _client(tmp_path)

    resp = client.get("/api/board")

    assert resp.status_code == 200
