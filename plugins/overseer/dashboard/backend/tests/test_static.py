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


def test_index_shell_is_not_cached(tmp_path: Path) -> None:
    """The SPA shell must be `no-store` — a cached index.html keeps pointing
    browsers at old, since-removed hashed bundles, silently showing a stale UI
    on a plain reload (WF-085 review kept hitting this)."""
    client = _client(tmp_path)  # real committed dist -> text/html shell

    resp = client.get("/")

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"


def test_hashed_assets_are_immutable(tmp_path: Path) -> None:
    """Content-hashed bundles under /assets/ never change under a given URL, so
    they stay long-lived + immutable (the counterpart to the shell being
    `no-store`)."""
    client = _client(tmp_path)
    index = client.get("/").text
    # Pull a real hashed asset URL out of the built index (e.g. /assets/index-XXXX.js).
    import re

    m = re.search(r'/assets/[A-Za-z0-9._-]+\.(?:js|css)', index)
    assert m, "expected a hashed /assets/ reference in the built index"

    resp = client.get(m.group(0))

    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=31536000, immutable"
