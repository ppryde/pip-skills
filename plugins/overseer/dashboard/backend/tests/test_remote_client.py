"""Unit tests for scripts.remote — the container-side httpx client for the
board API's ``--remote`` transport.

httpx 0.28.1's ``ASGITransport`` is async-only and cannot be driven by the
synchronous ``httpx.Client`` that ``exec_remote`` uses (see Task 2's sync
bridge for the same wall). So these tests do not spin up a real
``create_service_app`` and hit it over ASGI transport; instead they use
``httpx.MockTransport`` — a synchronous transport — to intercept the outgoing
``httpx.Request`` and return canned responses. This gives a thorough unit
test of request-building (URL, headers, JSON body) and response/error
mapping. The genuine client<->service round-trip is left to Task 6's
end-to-end smoke test.

Importing ``app.board_service`` is not required here since we never build a
real service app, but importing ``app.main`` (transitively, via other tests
in this suite) is what puts the overseer root on sys.path so ``scripts.remote``
is importable. We import ``scripts.remote`` directly.
"""
from __future__ import annotations

import json

import httpx
import pytest
from scripts import remote


def test_exec_remote_happy_path_builds_request_and_maps_result():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        assert request.url == httpx.URL("http://svc/api/exec")
        assert request.headers.get("x-overseer-token") == "secret"
        body = json.loads(request.content)
        assert body == {"argv": ["new-card", "--title", "Round"], "stdin": None}
        return httpx.Response(
            200, json={"stdout": "WF-001\n", "stderr": "", "returncode": 0}
        )

    transport = httpx.MockTransport(handler)
    res = remote.exec_remote(
        "http://svc", "secret", ["new-card", "--title", "Round"], None,
        transport=transport,
    )
    assert res.stdout == "WF-001\n"
    assert res.stderr == ""
    assert res.returncode == 0
    assert "request" in captured


def test_exec_remote_no_token_omits_header():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "x-overseer-token" not in request.headers
        return httpx.Response(200, json={"stdout": "", "stderr": "", "returncode": 0})

    transport = httpx.MockTransport(handler)
    res = remote.exec_remote("http://svc", None, ["board"], None, transport=transport)
    assert res.returncode == 0


def test_exec_remote_maps_401_to_token_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "bad token"})

    transport = httpx.MockTransport(handler)
    with pytest.raises(remote.RemoteError) as ei:
        remote.exec_remote("http://svc", "wrong", ["board"], None, transport=transport)
    assert "401" in str(ei.value) or "token" in str(ei.value).lower()


def test_exec_remote_maps_403_to_lan_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": "non-LAN caller refused"})

    transport = httpx.MockTransport(handler)
    with pytest.raises(remote.RemoteError) as ei:
        remote.exec_remote("http://svc", None, ["board"], None, transport=transport)
    assert "403" in str(ei.value) or "lan" in str(ei.value).lower()


def test_exec_remote_maps_other_non_200_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    transport = httpx.MockTransport(handler)
    with pytest.raises(remote.RemoteError) as ei:
        remote.exec_remote("http://svc", None, ["board"], None, transport=transport)
    assert "500" in str(ei.value)


def test_exec_remote_malformed_200_body_missing_key():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"stdout": "only this key"})

    transport = httpx.MockTransport(handler)
    with pytest.raises(remote.RemoteError):
        remote.exec_remote("http://svc", None, ["board"], None, transport=transport)


def test_exec_remote_malformed_200_body_not_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json at all")

    transport = httpx.MockTransport(handler)
    with pytest.raises(remote.RemoteError):
        remote.exec_remote("http://svc", None, ["board"], None, transport=transport)


def test_exec_remote_transport_error_wrapped():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    bad = httpx.MockTransport(boom)
    with pytest.raises(remote.RemoteError):
        remote.exec_remote("http://svc", None, ["board"], None, transport=bad)
