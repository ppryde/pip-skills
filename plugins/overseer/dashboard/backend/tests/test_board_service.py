# plugins/overseer/dashboard/backend/tests/test_board_service.py
import asyncio
import subprocess
from pathlib import Path

import httpx

from app import board_service
from app.board_service import (
    _invoked_verb,
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


def test_is_lan_client_ipv6_allows_only_loopback_linklocal_ula():
    for ok in ("::1", "fe80::1", "fd00::1", "fc00::1"):
        assert _is_lan_client(ok), ok
    for bad in ("2001:0:4136:e378:8000:63bf:3fff:fdd2",   # Teredo
                "2001:db8::1", "2001:10::1",
                "64:ff9b::808:808",                        # NAT64
                "2606:4700::1"):
        assert not _is_lan_client(bad), bad


def test_is_lan_client_checks_the_ipv4_inside_a_6to4_address():
    # 2002::/16 is "private" to ipaddress, but the address embeds an IPv4.
    assert not _is_lan_client("2002:0808:0808::1")   # 8.8.8.8
    assert _is_lan_client("2002:c0a8:0105::1")       # 192.168.1.5


def test_strip_root_flags():
    assert _strip_root_flags(["--root", "/x", "board"]) == ["board"]
    assert _strip_root_flags(["--root=/x", "board"]) == ["board"]
    assert _strip_root_flags(["--remote", "http://h", "claim", "WF-1"]) == ["claim", "WF-1"]
    assert _strip_root_flags(["set-stage", "WF-1", "done"]) == ["set-stage", "WF-1", "done"]


def test_strip_root_flags_also_strips_path_override_flags():
    # Host-path flags on the admin verbs must never reach the subprocess.
    assert _strip_root_flags(["--dir", "/x", "backup"]) == ["backup"]
    assert _strip_root_flags(["--dir=/x", "backup"]) == ["backup"]
    assert _strip_root_flags(["--central", "/x", "init"]) == ["init"]
    assert _strip_root_flags(["--central=/x", "init"]) == ["init"]
    assert _strip_root_flags(["--backup-dir", "/x", "init"]) == ["init"]
    assert _strip_root_flags(["--backup-dir=/x", "init"]) == ["init"]


def test_invoked_verb():
    assert _invoked_verb(["board"]) == "board"
    assert _invoked_verb(["set-stage", "WF-1", "done"]) == "set-stage"
    assert _invoked_verb(["--session-id", "s", "claim", "WF-1"]) == "claim"
    assert _invoked_verb(["--session-id=s", "board"]) == "board"
    assert _invoked_verb([]) is None


def test_invoked_verb_skips_every_value_taking_global_option():
    # Guard the coupling with cli.py: a new global option that takes a value
    # must be skipped by _invoked_verb, or its value reads as the verb and a
    # denied verb slips past. --root/--remote never get this far (stripped).
    import importlib.util
    import sys

    cli_path = board_service._OVERSEER_CLI
    sys.path.insert(0, str(cli_path.parents[1]))
    try:
        spec = importlib.util.spec_from_file_location("overseer_cli_for_guard", cli_path)
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
    finally:
        sys.path.pop(0)
    parser = cli.build_parser()
    for action in parser._actions:
        if not action.option_strings or action.nargs == 0:
            continue  # positional, or a flag with no value (-h)
        opt = action.option_strings[0]
        if opt in board_service._STRIPPED_FLAGS:
            continue
        assert _invoked_verb([opt, "x", "clear"]) == "clear", opt


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


def test_denied_verbs_return_403_without_running_subprocess(root: Path, monkeypatch):
    # If the denylist ever let a call through, this would blow up loudly instead
    # of silently running the destructive verb.
    app = create_service_app(root, token=None)  # build BEFORE patching (app init shells git)

    def _explode(*a, **k):  # pragma: no cover - must never be reached
        raise AssertionError("subprocess.run must not be called for a denied verb")

    monkeypatch.setattr(board_service.subprocess, "run", _explode)
    denied = (
        ["clear", "--yes"],
        ["init"],
        ["backup", "--dir", "/tmp/x"],
        ["restore", "--dir", "/tmp/x"],
    )
    with _client(app) as c:
        for argv in denied:
            r = c.post("/api/exec", json={"argv": argv, "stdin": None})
            assert r.status_code == 403, argv
            assert "not permitted" in r.json()["detail"]


def test_denied_clear_leaves_board_intact(root: Path):
    # End-to-end: a card exists, `clear` is refused (403), the card survives.
    app = create_service_app(root, token=None)
    with _client(app) as c:
        made = c.post("/api/exec", json={"argv": ["new-card", "--title", "Keep"], "stdin": None})
        assert made.status_code == 200 and made.json()["returncode"] == 0
        cleared = c.post("/api/exec", json={"argv": ["clear", "--yes", "--scope", "cards"], "stdin": None})
        assert cleared.status_code == 403
        board = c.post("/api/exec", json={"argv": ["board", "--json"], "stdin": None})
    assert board.status_code == 200
    assert "WF-001" in board.json()["stdout"]  # the card was never wiped


def test_abbreviated_root_flag_does_not_override_pinned_root(root: Path, tmp_path: Path):
    # `--roo` slips past the exact-match stripper, but allow_abbrev=False makes
    # argparse reject it -> non-zero returncode, and no board.db under the bogus
    # root (the pinned root is used / the abbreviation never resolved to --root).
    bogus = tmp_path / "evil-root"
    bogus.mkdir()
    app = create_service_app(root, token=None)
    with _client(app) as c:
        r = c.post(
            "/api/exec",
            json={"argv": ["--roo", str(bogus), "new-card", "--title", "x"], "stdin": None},
        )
    assert r.status_code == 200
    assert r.json()["returncode"] != 0          # argparse rejected --roo
    assert not (bogus / "board.db").exists()     # no board created under bogus root


def test_exec_timeout_maps_to_504(root: Path, monkeypatch):
    app = create_service_app(root, token=None)  # build BEFORE patching (app init shells git)

    def _timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="overseer", timeout=30)

    monkeypatch.setattr(board_service.subprocess, "run", _timeout)
    with _client(app) as c:
        r = c.post("/api/exec", json={"argv": ["board"], "stdin": None})
    assert r.status_code == 504


def test_exec_oserror_maps_to_500(root: Path, monkeypatch):
    app = create_service_app(root, token=None)  # build BEFORE patching (app init shells git)

    def _oserror(*a, **k):
        raise OSError("no such interpreter")

    monkeypatch.setattr(board_service.subprocess, "run", _oserror)
    with _client(app) as c:
        r = c.post("/api/exec", json={"argv": ["board"], "stdin": None})
    assert r.status_code == 500


def test_exec_does_not_inherit_overseer_remote(root: Path, monkeypatch):
    # An exported OVERSEER_REMOTE would re-supply the --remote the strip removed.
    monkeypatch.setenv("OVERSEER_REMOTE", "http://127.0.0.1:1")
    monkeypatch.setenv("OVERSEER_REMOTE_TOKEN", "t")
    app = create_service_app(root, token=None)
    with _client(app) as c:
        r = c.post("/api/exec", json={"argv": ["new-card", "--title", "Local"], "stdin": None})
    assert r.json()["returncode"] == 0
    assert "WF-001" in r.json()["stdout"]
    with _client(app) as c:
        shown = c.post("/api/exec", json={"argv": ["show", "WF-001", "--json"], "stdin": None})
    assert "Local" in shown.json()["stdout"]   # the LOCAL board was mutated
