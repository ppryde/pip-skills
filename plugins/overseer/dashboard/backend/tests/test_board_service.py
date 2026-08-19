# plugins/overseer/dashboard/backend/tests/test_board_service.py
import asyncio
from pathlib import Path

import httpx

from app.board_service import (
    _is_lan_client,
    _strip_root_flags,
    create_service_app,
)


class _SyncASGIBridge(httpx.BaseTransport):
    """Drives an `httpx.ASGITransport` synchronously.

    httpx dropped sync support from `ASGITransport` (it only implements
    `handle_async_request`; there is no built-in sync-over-ASGI transport
    left in httpx, and pytest-asyncio isn't installed in this backend's
    test env) — so a plain sync `httpx.Client` can no longer drive it
    directly. This bridges each request through `asyncio.run`, preserving
    `ASGITransport`'s `client=(ip, port)` source-IP spoofing (what the LAN
    guard actually needs) while keeping the tests themselves plain sync
    `def test_...` functions.
    """

    def __init__(self, async_transport: httpx.ASGITransport) -> None:
        self._async_transport = async_transport

    async def _do_request(self, request: httpx.Request) -> tuple[httpx.Response, bytes]:
        response = await self._async_transport.handle_async_request(request)
        content = await response.aread()
        return response, content

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        # The async response's body stream can't satisfy a sync Client
        # (`assert isinstance(response.stream, SyncByteStream)`), so the body
        # is fully read inside the event loop and a fresh, sync-compatible
        # Response is reconstructed from its bytes.
        response, content = asyncio.run(self._do_request(request))
        return httpx.Response(
            status_code=response.status_code,
            headers=response.headers,
            content=content,
            request=request,
        )


def _client(app, *, client_ip="172.17.0.2", token=None):
    """httpx client that spoofs the source IP via ASGITransport."""
    async_transport = httpx.ASGITransport(app=app, client=(client_ip, 40000))
    transport = _SyncASGIBridge(async_transport)
    headers = {"X-Overseer-Token": token} if token else {}
    return httpx.Client(transport=transport, base_url="http://svc", headers=headers)


def test_is_lan_client():
    assert _is_lan_client("127.0.0.1")
    assert _is_lan_client("172.17.0.2")     # docker bridge
    assert _is_lan_client("192.168.1.5")
    assert _is_lan_client("169.254.1.1")    # link-local
    assert not _is_lan_client("8.8.8.8")    # public
    assert not _is_lan_client(None)
    assert not _is_lan_client("not-an-ip")


def test_strip_root_flags():
    assert _strip_root_flags(["--root", "/x", "board"]) == ["board"]
    assert _strip_root_flags(["--root=/x", "board"]) == ["board"]
    assert _strip_root_flags(["--remote", "http://h", "claim", "WF-1"]) == ["claim", "WF-1"]
    assert _strip_root_flags(["set-stage", "WF-1", "done"]) == ["set-stage", "WF-1", "done"]


def test_exec_runs_verb_end_to_end(root: Path):
    app = create_service_app(root, token=None)
    with _client(app) as c:
        r = c.post("/api/exec", json={"argv": ["new-card", "--title", "Hi"], "stdin": None})
    assert r.status_code == 200
    body = r.json()
    assert body["returncode"] == 0
    assert "WF-001" in body["stdout"]


def test_exec_relays_nonzero_exit_as_http_200(root: Path):
    app = create_service_app(root, token=None)
    with _client(app) as c:
        # show on a missing card exits non-zero; still an HTTP 200 with the code in the body.
        r = c.post("/api/exec", json={"argv": ["show", "WF-999", "--json"], "stdin": None})
    assert r.status_code == 200
    assert r.json()["returncode"] != 0


def test_exec_ignores_incoming_root(root: Path, tmp_path: Path):
    app = create_service_app(root, token=None)
    bogus = str(tmp_path / "somewhere-else")
    with _client(app) as c:
        r = c.post("/api/exec", json={"argv": ["--root", bogus, "new-card", "--title", "T"], "stdin": None})
    assert r.status_code == 200
    assert r.json()["returncode"] == 0   # pinned root used, bogus --root stripped


def test_lan_guard_refuses_public_caller_even_with_token(root: Path):
    app = create_service_app(root, token="secret")
    with _client(app, client_ip="8.8.8.8", token="secret") as c:
        r = c.post("/api/exec", json={"argv": ["board"], "stdin": None})
    assert r.status_code == 403          # guard runs before auth


def test_token_gate_rejects_missing_token(root: Path):
    app = create_service_app(root, token="secret")
    with _client(app, client_ip="172.17.0.2", token=None) as c:
        r = c.post("/api/exec", json={"argv": ["board"], "stdin": None})
    assert r.status_code == 401


def test_token_gate_allows_matching_token(root: Path):
    app = create_service_app(root, token="secret")
    with _client(app, client_ip="172.17.0.2", token="secret") as c:
        r = c.post("/api/exec", json={"argv": ["new-card", "--title", "Ok"], "stdin": None})
    assert r.status_code == 200
