# Overseer Remote Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the overseer CLI + hooks inside a Docker dev container read and write a `board.db` that lives on the host, over a LAN-only HTTP service.

**Architecture:** A standalone host service reuses the dashboard's `create_app` (frontend mount disabled) for the identical `/api/*` surface, adds a LAN-only source-IP guard and a token-gated `POST /api/exec` passthrough. The container's `overseer --remote <url>` forwards its whole argv + stdin to `/api/exec`, which runs the real host `cli.py` against a pinned root and relays stdout/stderr/exit code. The host CLI stays the single writer of `board.db`.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, httpx, pydantic, argparse, `ipaddress` (stdlib), pytest.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-19-overseer-remote-client-design.md`.
- **No MCP / FastMCP** — the writer is the overseer CLI, not an agent.
- **LAN-only (hard requirement):** the service must never answer a remote, non-LAN caller. Enforce with a source-IP allowlist middleware (`ipaddress` `is_private or is_loopback or is_link_local`; unparseable/absent → reject) *in front of* the token gate. No escape-hatch env var.
- **Single writer preserved:** only the host `cli.py` process touches `board.db`/`.workflow/`; the service shells it (no direct board access), exactly like `app.cli_client`.
- **`/api/exec` runs a fixed binary** (`scripts/cli.py`) with an argv **list** (never a shell string), token-gated, and exists **only** on the standalone service — never via `create_app` (the dashboard must not offer it).
- **Token env var:** `OVERSEER_REMOTE_TOKEN` (symmetric both sides), header `X-Overseer-Token`, constant-time compare.
- **Test isolation:** every test pins `CLAUDE_CONFIG_DIR`/`OVERSEER_DB`/`OVERSEER_CENTRAL` into `tmp_path` (autouse fixtures already do this in both suites — do not touch real `~/.claude*`).
- **Interpreter:** `/Users/philip.pryde/repos/pip-skills/.venv/bin/python` (poetry is unusable here).
- **Test commands:**
  - Backend suite: `cd plugins/overseer/dashboard/backend && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest <file> -v`
  - Overseer CLI suite: `cd plugins/overseer && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest -k <expr> -v` (testpaths is pinned to `../../tests/overseer`)
- **Commit** after every task.

---

### Task 1: Refactor `create_app` — extractable token gate + skippable frontend mount

Two behaviour-preserving changes to `main.py` so the standalone service can reuse the app: lift `require_token` to a module-level factory, and make the frontend mount optional.

**Files:**
- Modify: `plugins/overseer/dashboard/backend/app/main.py`
- Test: `plugins/overseer/dashboard/backend/tests/test_create_app_reuse.py` (new)

**Interfaces:**
- Produces: `make_require_token(token: str | None) -> Callable[..., None]` — builds the FastAPI header dependency (inert when `token is None`).
- Produces: `create_app(root, *, host="127.0.0.1", dist_dir=None, token=None, mount_frontend=True) -> FastAPI` — when `mount_frontend=False`, no `/` static mount or placeholder route is registered.

- [ ] **Step 1: Write the failing test**

```python
# plugins/overseer/dashboard/backend/tests/test_create_app_reuse.py
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app, make_require_token


def test_make_require_token_inert_when_none():
    dep = make_require_token(None)
    assert dep(None) is None            # no token in effect -> allow
    assert dep("anything") is None


def test_make_require_token_rejects_wrong_token():
    import pytest
    from fastapi import HTTPException

    dep = make_require_token("secret")
    assert dep("secret") is None        # correct -> allow
    with pytest.raises(HTTPException) as ei:
        dep("wrong")
    assert ei.value.status_code == 401
    with pytest.raises(HTTPException):
        dep(None)


def test_mount_frontend_false_has_no_catch_all(root: Path):
    app = create_app(root, mount_frontend=False)
    client = TestClient(app)
    # /api/board still works...
    assert client.get("/api/board").status_code == 200
    # ...but an unknown non-API path is a real 404, not the SPA placeholder/dist.
    assert client.get("/definitely-not-a-route").status_code == 404


def test_mount_frontend_true_still_serves_catch_all(root: Path):
    app = create_app(root, mount_frontend=True, dist_dir=Path("/nonexistent-dist"))
    client = TestClient(app)
    # dist absent -> placeholder catch-all answers 200 (unchanged behaviour).
    assert client.get("/some-spa-path").status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/overseer/dashboard/backend && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest tests/test_create_app_reuse.py -v`
Expected: FAIL — `make_require_token` does not exist; `create_app` has no `mount_frontend` kwarg.

- [ ] **Step 3: Write minimal implementation**

In `main.py`, add the module-level factory (near the top-level helpers, after imports):

```python
def make_require_token(token: str | None) -> Callable[..., None]:
    """Build the FastAPI dependency that gates mutating routes.

    Inactive when ``token`` is None (loopback bind, no env var) — preserves the
    pre-auth open behaviour and every existing test. When a token exists, the
    request must carry a matching ``X-Overseer-Token`` header (constant-time
    compare) or the request is refused 401.
    """
    def require_token(x_overseer_token: str | None = Header(default=None)) -> None:
        if token is None:
            return
        supplied = x_overseer_token or ""
        if not hmac.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="missing or invalid dashboard token")

    return require_token
```

In `create_app`, replace the inline `def require_token(...)` closure with:

```python
    require_token = make_require_token(token)
```

Change the signature and the final mount call:

```python
def create_app(root: Path, *, host: str = "127.0.0.1", dist_dir: Path | None = None,
               token: str | None = None, mount_frontend: bool = True) -> FastAPI:
```

```python
    if mount_frontend:
        _mount_frontend(app, dist_dir)

    return app
```

- [ ] **Step 4: Run the new test + the whole backend suite (regression guard)**

Run: `cd plugins/overseer/dashboard/backend && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest -v`
Expected: PASS — the new file passes and **every existing backend test still passes** (the refactor is behaviour-preserving).

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/dashboard/backend/app/main.py plugins/overseer/dashboard/backend/tests/test_create_app_reuse.py
git commit -m "refactor(overseer-dashboard): extract make_require_token + optional frontend mount"
```

---

### Task 2: The standalone service — LAN guard + `/api/exec`

`board_service.py` builds on `create_app(mount_frontend=False)`, adds the LAN-only middleware and the token-gated exec passthrough.

**Files:**
- Create: `plugins/overseer/dashboard/backend/app/board_service.py`
- Test: `plugins/overseer/dashboard/backend/tests/test_board_service.py` (new)

**Interfaces:**
- Consumes: `create_app(..., mount_frontend=False)`, `make_require_token` (Task 1).
- Produces: `create_service_app(root: Path, *, host="0.0.0.0", token: str | None = None) -> FastAPI`.
- Produces: `ExecRequest{argv: list[str], stdin: str | None}`, `ExecResult{stdout: str, stderr: str, returncode: int}`.
- Produces (module helpers, tested directly): `_is_lan_client(host: str | None) -> bool`, `_strip_root_flags(argv: list[str]) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# plugins/overseer/dashboard/backend/tests/test_board_service.py
from pathlib import Path

import httpx
import pytest

from app.board_service import (
    create_service_app,
    _is_lan_client,
    _strip_root_flags,
)


def _client(app, *, client_ip="172.17.0.2", token=None):
    """httpx client that spoofs the source IP via ASGITransport."""
    transport = httpx.ASGITransport(app=app, client=(client_ip, 40000))
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/overseer/dashboard/backend && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest tests/test_board_service.py -v`
Expected: FAIL — `app.board_service` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# plugins/overseer/dashboard/backend/app/board_service.py
"""Standalone overseer board API service — HTTP board access for a dev container.

Reuses the dashboard's ``create_app`` (frontend mount disabled) so the ``/api/*``
surface is identical, then adds:
  - a LAN-only source-IP guard (never answer a remote, non-LAN caller), and
  - ``POST /api/exec``, a token-gated passthrough that runs the real overseer
    CLI on the host against a PINNED root — the mechanism the container's
    ``overseer --remote`` forwards every verb/hook to.

The host CLI stays the single writer of board.db; this service only shells it,
exactly as the dashboard backend's cli_client already does.
"""
from __future__ import annotations

import ipaddress
import subprocess
import sys
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.main import create_app, make_require_token

# backend/app/board_service.py -> parents: [0]=app [1]=backend [2]=dashboard [3]=overseer
_OVERSEER_CLI = Path(__file__).resolve().parents[3] / "scripts" / "cli.py"
_EXEC_TIMEOUT = 30


class ExecRequest(BaseModel):
    argv: list[str]
    stdin: str | None = None


class ExecResult(BaseModel):
    stdout: str
    stderr: str
    returncode: int


def _is_lan_client(host: str | None) -> bool:
    """True only for a private/loopback/link-local source address.

    Guarantees the service never answers a remote, non-LAN caller even when
    bound to 0.0.0.0. An absent/unparseable client is rejected (safe default).
    """
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def _strip_root_flags(argv: list[str]) -> list[str]:
    """Drop any --root/--remote (and their values) from a forwarded argv.

    A container root path is meaningless on the host, and a forwarded --remote
    must never recurse. The service injects its own pinned root instead.
    """
    out: list[str] = []
    skip = False
    for tok in argv:
        if skip:
            skip = False
            continue
        if tok in ("--root", "--remote"):
            skip = True
            continue
        if tok.startswith("--root=") or tok.startswith("--remote="):
            continue
        out.append(tok)
    return out


def create_service_app(root: Path, *, host: str = "0.0.0.0", token: str | None = None) -> FastAPI:
    app = create_app(root, host=host, token=token, mount_frontend=False)
    pinned_root = root.resolve()
    require_token = make_require_token(token)

    @app.middleware("http")
    async def _lan_only(request: Request, call_next):
        client = request.client.host if request.client else None
        if not _is_lan_client(client):
            return JSONResponse(status_code=403, content={"detail": "non-LAN caller refused"})
        return await call_next(request)

    @app.post("/api/exec", dependencies=[Depends(require_token)])
    def exec_cli(req: ExecRequest) -> ExecResult:
        argv = _strip_root_flags(req.argv)
        try:
            proc = subprocess.run(
                [sys.executable, str(_OVERSEER_CLI), "--root", str(pinned_root), *argv],
                input=req.stdin,
                capture_output=True,
                text=True,
                timeout=_EXEC_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="overseer CLI timed out")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"cannot run overseer CLI: {exc}")
        return ExecResult(stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)

    return app
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/overseer/dashboard/backend && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest tests/test_board_service.py -v`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/dashboard/backend/app/board_service.py plugins/overseer/dashboard/backend/tests/test_board_service.py
git commit -m "feat(overseer): standalone board API service — LAN guard + token-gated /api/exec"
```

---

### Task 3: Launcher `serve_board_api.py`

A thin uvicorn launcher mirroring `serve.py`: resolve the token, build the service app, run it. Binds `0.0.0.0` (LAN guard does the real protection) on a distinct port.

**Files:**
- Create: `plugins/overseer/dashboard/serve_board_api.py`
- Test: `plugins/overseer/dashboard/backend/tests/test_serve_board_api.py` (new)

**Interfaces:**
- Consumes: `create_service_app` (Task 2), `LOOPBACK_HOSTS` from `app.main`.
- Produces: `resolve_remote_token(host: str) -> str | None`, `parse_args(argv) -> argparse.Namespace`, `main(argv) -> int`.

- [ ] **Step 1: Write the failing test**

```python
# plugins/overseer/dashboard/backend/tests/test_serve_board_api.py
import importlib.util
from pathlib import Path

# Load the launcher module by path (it lives above the backend package).
_LAUNCHER = Path(__file__).resolve().parents[2] / "serve_board_api.py"
_spec = importlib.util.spec_from_file_location("serve_board_api", _LAUNCHER)
serve_board_api = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(serve_board_api)


def test_resolve_remote_token_env_wins(monkeypatch):
    monkeypatch.setenv("OVERSEER_REMOTE_TOKEN", "fixed")
    assert serve_board_api.resolve_remote_token("0.0.0.0") == "fixed"
    assert serve_board_api.resolve_remote_token("127.0.0.1") == "fixed"


def test_resolve_remote_token_autogen_on_non_loopback(monkeypatch):
    monkeypatch.delenv("OVERSEER_REMOTE_TOKEN", raising=False)
    tok = serve_board_api.resolve_remote_token("0.0.0.0")
    assert tok and len(tok) >= 20


def test_resolve_remote_token_none_on_loopback(monkeypatch):
    monkeypatch.delenv("OVERSEER_REMOTE_TOKEN", raising=False)
    assert serve_board_api.resolve_remote_token("127.0.0.1") is None


def test_parse_args_defaults():
    args = serve_board_api.parse_args([])
    assert args.host == "0.0.0.0"
    assert args.port == 8771
    assert args.root == "."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/overseer/dashboard/backend && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest tests/test_serve_board_api.py -v`
Expected: FAIL — file not found / module missing.

- [ ] **Step 3: Write minimal implementation**

```python
# plugins/overseer/dashboard/serve_board_api.py
"""Launcher for the standalone overseer board API service (dev-container access).

Wires ``backend/app/board_service.py::create_service_app`` up to uvicorn. Unlike
the dashboard launcher this is meant to be reachable from a Docker dev container,
so it binds 0.0.0.0 by default and REQUIRES a token on a non-loopback bind
(auto-generated + printed when OVERSEER_REMOTE_TOKEN isn't set). A LAN-only
source guard (in the app) refuses any non-LAN caller regardless of bind.

Usage (from the repo root):
    python plugins/overseer/dashboard/serve_board_api.py [--root PATH] [--host HOST] [--port PORT]
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

import uvicorn

_BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.board_service import create_service_app  # noqa: E402 (after sys.path setup)
from app.main import LOOPBACK_HOSTS  # noqa: E402

DEFAULT_PORT = 8771
REMOTE_TOKEN_ENV = "OVERSEER_REMOTE_TOKEN"


def resolve_remote_token(host: str) -> str | None:
    """The token in effect for this bind: env wins, else auto-gen on a
    non-loopback bind, else None (a pure-loopback bind may stay token-free)."""
    env = os.environ.get(REMOTE_TOKEN_ENV)
    if env:
        return env
    if host not in LOOPBACK_HOSTS:
        return secrets.token_urlsafe(24)
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="serve_board_api.py")
    parser.add_argument("--root", default=".")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = Path(args.root).resolve()
    token = resolve_remote_token(args.host)
    app = create_service_app(root, host=args.host, token=token)
    if token:
        print(f"board API token: {token}")
    print(f"serving board API for {root} on http://{args.host}:{args.port}/  (LAN-only)")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/overseer/dashboard/backend && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest tests/test_serve_board_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/dashboard/serve_board_api.py plugins/overseer/dashboard/backend/tests/test_serve_board_api.py
git commit -m "feat(overseer): serve_board_api launcher — 0.0.0.0 bind, token on non-loopback"
```

---

### Task 4: Container-side client `scripts/remote.py`

The httpx POST half. Lazy-importable (httpx only) so it runs in a minimal container overseer install.

**Files:**
- Create: `plugins/overseer/scripts/remote.py`
- Test: `plugins/overseer/dashboard/backend/tests/test_remote_client.py` (new — lives in the backend suite so both `app.board_service` and `scripts.remote` import cleanly, and a real service app is available for the round-trip)

**Interfaces:**
- Produces: `RemoteResult{stdout: str, stderr: str, returncode: int}` (dataclass), `RemoteError(Exception)`.
- Produces: `exec_remote(url: str, token: str | None, argv: list[str], stdin: str | None, *, transport=None) -> RemoteResult`. `transport` is an optional `httpx` transport for tests; production passes `None` (real HTTP).

- [ ] **Step 1: Write the failing test**

```python
# plugins/overseer/dashboard/backend/tests/test_remote_client.py
from pathlib import Path

import httpx
import pytest

from app.board_service import create_service_app  # importing app also puts overseer root on sys.path
from scripts import remote


def _transport(app, client_ip="172.17.0.2"):
    return httpx.ASGITransport(app=app, client=(client_ip, 40000))


def test_exec_remote_round_trip(root: Path):
    app = create_service_app(root, token=None)
    res = remote.exec_remote(
        "http://svc", None, ["new-card", "--title", "Round"], None,
        transport=_transport(app),
    )
    assert res.returncode == 0
    assert "WF-001" in res.stdout


def test_exec_remote_sends_token_and_maps_401(root: Path):
    app = create_service_app(root, token="secret")
    with pytest.raises(remote.RemoteError) as ei:
        remote.exec_remote("http://svc", "wrong", ["board"], None, transport=_transport(app))
    assert "401" in str(ei.value) or "token" in str(ei.value).lower()


def test_exec_remote_maps_403_for_non_lan(root: Path):
    app = create_service_app(root, token=None)
    with pytest.raises(remote.RemoteError) as ei:
        remote.exec_remote("http://svc", None, ["board"], None,
                           transport=_transport(app, client_ip="8.8.8.8"))
    assert "403" in str(ei.value) or "lan" in str(ei.value).lower()


def test_exec_remote_transport_error_wrapped():
    def boom(*a, **k):
        raise httpx.ConnectError("nope")

    bad = httpx.MockTransport(boom)
    with pytest.raises(remote.RemoteError):
        remote.exec_remote("http://svc", None, ["board"], None, transport=bad)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/overseer/dashboard/backend && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest tests/test_remote_client.py -v`
Expected: FAIL — `scripts.remote` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# plugins/overseer/scripts/remote.py
"""HTTP client for the overseer board API service (the ``--remote`` transport).

``overseer --remote <url>`` forwards its whole argv (and any hook stdin) to the
host's ``/api/exec``, which runs the real CLI there and returns
stdout/stderr/exit code. This module is the container-side half: a thin httpx
POST. Kept dependency-light (httpx only) so it runs in a minimal dev-container
overseer install; it is imported lazily, so a local (non-remote) CLI never needs
httpx installed.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

_TIMEOUT = 35


@dataclass
class RemoteResult:
    stdout: str
    stderr: str
    returncode: int


class RemoteError(Exception):
    """Transport-level failure (unreachable host, refused, malformed response)."""


def exec_remote(url: str, token: str | None, argv: list[str], stdin: str | None,
                *, transport: httpx.BaseTransport | None = None) -> RemoteResult:
    headers = {"X-Overseer-Token": token} if token else {}
    payload = {"argv": argv, "stdin": stdin}
    endpoint = f"{url.rstrip('/')}/api/exec"
    try:
        with httpx.Client(transport=transport, timeout=_TIMEOUT) as client:
            resp = client.post(endpoint, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise RemoteError(f"cannot reach overseer board API at {url}: {exc}") from exc
    if resp.status_code == 401:
        raise RemoteError("overseer board API rejected the token (401) — check OVERSEER_REMOTE_TOKEN")
    if resp.status_code == 403:
        raise RemoteError("overseer board API refused this caller (403) — must be on the LAN")
    if resp.status_code != 200:
        raise RemoteError(f"overseer board API error {resp.status_code}: {resp.text[:200]}")
    try:
        data = resp.json()
        return RemoteResult(stdout=data["stdout"], stderr=data["stderr"], returncode=data["returncode"])
    except (ValueError, KeyError) as exc:
        raise RemoteError(f"malformed response from overseer board API: {exc}") from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/overseer/dashboard/backend && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest tests/test_remote_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/remote.py plugins/overseer/dashboard/backend/tests/test_remote_client.py
git commit -m "feat(overseer): scripts/remote.py — httpx client for the board API --remote transport"
```

---

### Task 5: `overseer --remote` dispatch in the CLI

Wire the global `--remote` flag and short-circuit `main()` to forward instead of running locally.

**Files:**
- Modify: `plugins/overseer/scripts/cli.py` (`build_parser`, `main`; add `_run_remote`, `_forwardable_argv`)
- Test: `tests/overseer/test_remote_dispatch.py` (new)

**Interfaces:**
- Consumes: `scripts.remote.exec_remote`, `scripts.remote.RemoteResult`, `scripts.remote.RemoteError` (Task 4).
- Produces: `build_parser()` now defines a global `--remote` (default `$OVERSEER_REMOTE`); `main(argv)` forwards when `--remote` is set, relaying stdout/stderr and returning the remote exit code.

- [ ] **Step 1: Write the failing test**

```python
# tests/overseer/test_remote_dispatch.py
import sys

import pytest

from scripts.cli import main
from scripts import remote


def test_remote_forwards_argv_and_relays(monkeypatch, capsys):
    seen = {}

    def fake_exec(url, token, argv, stdin, **kw):
        seen.update(url=url, token=token, argv=argv, stdin=stdin)
        return remote.RemoteResult(stdout="WF-001\n", stderr="", returncode=0)

    monkeypatch.setattr(remote, "exec_remote", fake_exec)
    monkeypatch.setenv("OVERSEER_REMOTE_TOKEN", "tok")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)  # no stdin to read

    rc = main(["--remote", "http://host.docker.internal:8771", "board"])

    assert rc == 0
    assert seen["url"] == "http://host.docker.internal:8771"
    assert seen["token"] == "tok"
    assert seen["argv"] == ["board"]          # --remote stripped, verb forwarded
    assert "WF-001" in capsys.readouterr().out


def test_remote_relays_nonzero_exit(monkeypatch):
    monkeypatch.setattr(remote, "exec_remote",
                        lambda *a, **k: remote.RemoteResult(stdout="", stderr="boom\n", returncode=2))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert main(["--remote", "http://h", "show", "WF-9"]) == 2


def test_remote_does_not_touch_local_board(monkeypatch, tmp_path):
    # If dispatch went local, cmd_board would run against OVERSEER_DB. Assert the
    # remote path is taken instead (fake called), never the local func.
    called = {"remote": False}

    def fake_exec(*a, **k):
        called["remote"] = True
        return remote.RemoteResult(stdout="", stderr="", returncode=0)

    monkeypatch.setattr(remote, "exec_remote", fake_exec)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setenv("OVERSEER_DB", str(tmp_path / "never-created.db"))

    assert main(["--remote", "http://h", "board"]) == 0
    assert called["remote"] is True
    assert not (tmp_path / "never-created.db").exists()   # local board never opened


def test_remote_transport_error_returns_1(monkeypatch, capsys):
    def boom(*a, **k):
        raise remote.RemoteError("cannot reach")

    monkeypatch.setattr(remote, "exec_remote", boom)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    assert main(["--remote", "http://h", "board"]) == 1
    assert "cannot reach" in capsys.readouterr().err


def test_remote_env_default(monkeypatch):
    monkeypatch.setattr(remote, "exec_remote",
                        lambda *a, **k: remote.RemoteResult("", "", 0))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setenv("OVERSEER_REMOTE", "http://from-env")
    seen = {}
    monkeypatch.setattr(remote, "exec_remote",
                        lambda url, *a, **k: seen.setdefault("url", url) or remote.RemoteResult("", "", 0))
    assert main(["board"]) == 0
    assert seen["url"] == "http://from-env"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/overseer && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest -k remote_dispatch -v`
Expected: FAIL — `--remote` is not a recognised argument.

- [ ] **Step 3: Write minimal implementation**

In `build_parser()`, add the global flag alongside `--root`/`--session-id`:

```python
    parser.add_argument(
        "--remote",
        default=os.environ.get("OVERSEER_REMOTE"),
        help="Forward this command to a remote overseer board API at URL "
             "(default: $OVERSEER_REMOTE). Runs the verb on the host board.",
    )
```

Add the helpers near `main` (module scope):

```python
def _forwardable_argv(raw_argv: list[str]) -> list[str]:
    """Strip the --remote flag (and its value) from raw argv before forwarding,
    so the host never re-forwards. --root is left for the host to strip/replace
    with its pinned root."""
    out: list[str] = []
    skip = False
    for tok in raw_argv:
        if skip:
            skip = False
            continue
        if tok == "--remote":
            skip = True
            continue
        if tok.startswith("--remote="):
            continue
        out.append(tok)
    return out


def _run_remote(url: str, raw_argv: list[str]) -> int:
    """Forward the whole command to the host board API and relay the result."""
    from scripts import remote  # lazy: httpx only needed on the remote path
    token = os.environ.get("OVERSEER_REMOTE_TOKEN")
    forward = _forwardable_argv(raw_argv)
    stdin = None if sys.stdin.isatty() else sys.stdin.read()
    try:
        res = remote.exec_remote(url, token, forward, stdin)
    except remote.RemoteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if res.stdout:
        sys.stdout.write(res.stdout)
    if res.stderr:
        sys.stderr.write(res.stderr)
    return res.returncode
```

Modify `main()` to capture raw argv and short-circuit before local dispatch:

```python
def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        args = parser.parse_args(raw)
    except SystemExit as exc:  # argparse --help (0) or usage error (2)
        return 0 if not exc.code else 1
    if getattr(args, "remote", None):
        return _run_remote(args.remote, raw)
    try:
        result: int = args.func(args)
        return result
    except (CardParseError, FactParseError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        _close_conns()
```

(Ensure `os` and `sys` are imported at the top of `cli.py` — they already are.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/overseer && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest -k remote_dispatch -v`
Expected: PASS.

- [ ] **Step 5: Run the full overseer CLI suite (regression guard)**

Run: `cd plugins/overseer && /Users/philip.pryde/repos/pip-skills/.venv/bin/python -m pytest -v`
Expected: PASS — the new `--remote` global does not disturb any existing verb (its default is `None`/`$OVERSEER_REMOTE`, so local dispatch is unchanged when unset).

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/scripts/cli.py tests/overseer/test_remote_dispatch.py
git commit -m "feat(overseer): overseer --remote forwards verbs+hooks to the host board API"
```

---

### Task 6: Docs — service + dev-container setup, and end-to-end smoke

Document how to run the service on the host and point a container at it, and prove the full path once by hand.

**Files:**
- Create: `plugins/overseer/dashboard/BOARD_API.md`
- Modify: `plugins/overseer/dashboard/README.md` (add a short pointer to `BOARD_API.md`)

- [ ] **Step 1: Write `BOARD_API.md`**

Cover, concisely:
- **What it is** — a LAN-only HTTP service so an overseer CLI in a dev container writes to the host board. Not the dashboard; no `dist/`; no MCP.
- **Run on the host:**
  ```bash
  /Users/philip.pryde/repos/pip-skills/.venv/bin/python \
    plugins/overseer/dashboard/serve_board_api.py --root /path/to/host/repo
  # prints: board API token: <TOKEN>   (auto-generated on the 0.0.0.0 bind)
  ```
- **Point the container at it** — set in the container's environment:
  ```bash
  export OVERSEER_REMOTE=http://host.docker.internal:8771
  export OVERSEER_REMOTE_TOKEN=<TOKEN>
  ```
  On Linux, run the container with `--add-host=host.docker.internal:host-gateway`.
- **Use it** — every overseer verb/hook now targets the host board:
  ```bash
  overseer board
  overseer set-stage WF-1 done
  ```
  (Interactive verbs like `clear` must pass `--yes`.)
- **Security** — LAN-only source guard (rejects any non-private/loopback/link-local caller with 403, before auth) + `X-Overseer-Token`. Never expose this beyond the LAN; there is no override for the LAN guard.
- **httpx** — the container's overseer install needs `httpx` (imported only on the `--remote` path).

- [ ] **Step 2: Add the README pointer**

Add a short paragraph under the dashboard README's serving section:

```markdown
For a dev container that needs to reach a board living on the host, run the
LAN-only board API service instead — see `BOARD_API.md`.
```

- [ ] **Step 3: End-to-end smoke (manual, documented in the commit)**

In one terminal: start the service against a scratch repo root; note the printed token. In another (simulating the container, but locally over loopback which the LAN guard also allows):

```bash
OVERSEER_REMOTE=http://127.0.0.1:8771 OVERSEER_REMOTE_TOKEN=<TOKEN> \
  /Users/philip.pryde/repos/pip-skills/.venv/bin/python \
  plugins/overseer/scripts/cli.py new-card --title "smoke via remote"
# expect: WF-00N printed, exit 0; the card appears in the host board.
```

Confirm the card landed on the host board (`overseer --root /path/to/host/repo board`).

- [ ] **Step 4: Commit**

```bash
git add plugins/overseer/dashboard/BOARD_API.md plugins/overseer/dashboard/README.md
git commit -m "docs(overseer): board API service + dev-container setup (BOARD_API.md)"
```

---

## Self-Review

**Spec coverage:**
- §3 passthrough mechanism → Task 2 (`/api/exec`) + Task 5 (`--remote` forward).
- §4 components: `main.py` refactor → Task 1; `board_service.py` → Task 2; launcher → Task 3; `scripts/remote.py` → Task 4; `cli.py --remote` → Task 5.
- §5 `/api/exec` shape (ExecRequest/ExecResult, strip `--root`/`--remote`, non-zero exit as body/HTTP 200, timeout→504) → Task 2.
- §6 data flow (hook via stdin) → Task 5 (`_run_remote` reads stdin when not a tty) + Task 2 (`input=req.stdin`).
- §7 auth (`OVERSEER_REMOTE_TOKEN`, `X-Overseer-Token`, resolve on non-loopback) → Task 1 (`make_require_token`), Task 3 (`resolve_remote_token`); LAN-only guard → Task 2 (`_is_lan_client` + middleware).
- §8 error handling (exit-code relay, transport failure, timeout) → Tasks 2, 4, 5.
- §9 testing (router regression, exec, LAN guard via ASGITransport, client round-trip, `--remote` dispatch, isolation) → tests in Tasks 1–5.
- §10 out-of-scope (MCP, service launcher polish) → not built (correct).

**Placeholder scan:** none — every step has concrete code/commands.

**Type consistency:** `ExecRequest{argv, stdin}` / `ExecResult{stdout, stderr, returncode}` (Task 2) match the client's payload + `RemoteResult` fields (Task 4) and the dispatch's use (Task 5). `make_require_token`, `create_service_app`, `resolve_remote_token`, `exec_remote` signatures are referenced consistently across tasks.
