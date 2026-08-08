from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app.cli_client import run_overseer
from app.main import create_app


def _client(tmp_path: Path, *, dist_dir: Path | None = None) -> TestClient:
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    run_overseer(tmp_path, "init")
    return TestClient(create_app(tmp_path, dist_dir=dist_dir))


def test_root_is_200_placeholder_when_dist_absent(tmp_path: Path) -> None:
    # frontend/dist/ is committed (chunk 7) so the REAL path always exists
    # now; point the mount at a controlled, guaranteed-absent dist dir
    # instead to keep exercising the placeholder path.
    client = _client(tmp_path, dist_dir=tmp_path / "no-such-dist")

    resp = client.get("/")

    assert resp.status_code == 200
    assert "Frontend not built" in resp.text


def test_api_board_still_200_when_dist_absent(tmp_path: Path) -> None:
    client = _client(tmp_path, dist_dir=tmp_path / "no-such-dist")

    resp = client.get("/api/board")

    assert resp.status_code == 200


def test_root_serves_built_index_with_default_dist(tmp_path: Path) -> None:
    """Core deliverable regression guard: the DEFAULT dist_dir (the real,
    committed `frontend/dist/`) serves the built index at `/`, not the
    placeholder.

    This depends on `frontend/dist/` being committed (WF-005 C7) — which it
    now is — so it is a valid permanent test. If `_mount_frontend`'s default
    `__file__`-relative path resolution ever breaks, this fails.
    """
    client = _client(tmp_path)  # default dist_dir -> real committed dist

    resp = client.get("/")

    assert resp.status_code == 200
    # Markers from the built Vite index (see frontend/dist/index.html).
    assert "<title>overseer</title>" in resp.text
    assert '<div id="root">' in resp.text
    # And definitively NOT the "dist absent" placeholder.
    assert "Frontend not built" not in resp.text
