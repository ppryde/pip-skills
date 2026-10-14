"""WF-100 C4: the LAN-only source-IP guard is app-wide (every route), outermost
(before auth), and fails closed on a missing client address. The address table
itself lives with `_is_lan_client` (test_board_service); these go through the app."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def _get(app, ip: str, path: str = "/api/version") -> int:
    return TestClient(app, client=(ip, 50000)).get(path).status_code


def test_dashboard_route_refuses_a_public_ipv4(root: Path) -> None:
    assert _get(create_app(root), "8.8.8.8") == 403


def test_every_dashboard_route_is_guarded_not_just_exec(root: Path) -> None:
    app = create_app(root)
    for path in ("/api/version", "/api/board", "/api/repos", "/"):
        assert _get(app, "8.8.8.8", path) == 403, path


def test_refuses_a_6to4_address_embedding_a_public_ipv4(root: Path) -> None:
    assert _get(create_app(root), "2002:0808:0808::1") == 403  # 8.8.8.8


def test_allows_an_ipv4_mapped_private_address(root: Path) -> None:
    assert _get(create_app(root), "::ffff:192.168.1.5") == 200


def test_allows_loopback_and_docker_bridge(root: Path) -> None:
    app = create_app(root)
    assert _get(app, "127.0.0.1") == 200
    assert _get(app, "172.17.0.2") == 200


def test_cgnat_tailscale_is_refused_by_design(root: Path) -> None:
    # 100.64.0.0/10 is neither private nor loopback. Pinned so widening the
    # guard for one Tailscale setup is a deliberate, visible change.
    assert _get(create_app(root), "100.64.1.2") == 403


def test_guard_runs_before_the_token_gate(root: Path) -> None:
    app = create_app(root, token="s3cret")
    client = TestClient(app, client=("8.8.8.8", 50000))
    resp = client.post("/api/card", json={"title": "x"}, headers={"X-Overseer-Token": "s3cret"})
    assert resp.status_code == 403
    no_token = TestClient(app, client=("8.8.8.8", 50000)).post("/api/card", json={"title": "x"})
    assert no_token.status_code == 403  # not 401: the guard is outermost


def test_missing_client_address_is_refused(root: Path) -> None:
    app = create_app(root)
    sent: list[dict] = []

    async def run() -> None:
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
            "path": "/api/version", "raw_path": b"/api/version", "query_string": b"",
            "headers": [(b"host", b"svc")], "client": None, "server": ("svc", 80),
            "scheme": "http", "root_path": "",
        }

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict) -> None:
            sent.append(message)

        await app(scope, receive, send)

    asyncio.run(run())
    assert sent[0]["status"] == 403


def test_conftest_default_client_is_loopback(root: Path) -> None:
    # No explicit client=: the autouse conftest default keeps the existing
    # suites (which never name a client) on the allowed side of the guard.
    assert TestClient(create_app(root)).get("/api/version").status_code == 200
