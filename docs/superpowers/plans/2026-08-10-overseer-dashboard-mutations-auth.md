# Overseer Dashboard Mutations + Rudimentary Auth (PR3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the dashboard create cards, edit a card's title/body, and abandon a card (with a confirm), fold in the deferred F1 label-editor control, and add a rudimentary token gate over all mutating routes.

**Architecture:** Three layers mirroring the proven F1 split. Layer A adds the only new CLI surface (`set-field --title/--body`). Layer B adds two endpoints (`POST /api/card`, `POST /api/card/{id}`) plus a token-gate dependency over every mutating route; abandon reuses the existing `/move status=abandoned` path. Layer C adds frontend controls and client-side token handling. The backend stays a pure CLI client — it never imports overseer internals.

**Tech Stack:** Python 3.9 / argparse CLI + SQLite store; FastAPI + pydantic backend (pure `subprocess` CLI client); React + TypeScript + Vite frontend; pytest (backend + repo-root `tests/overseer`); vitest (frontend).

## Global Constraints

- **Backend is a CLI client only** — never `import scripts.*` internals for mutations; every write goes through `run_overseer(root, <verb>, ...)`. (Sole allowed exception already in place: `derive_repo_root`/`derive_repo_label` pure path helpers.)
- **Reads are never gated** — `GET /api/board`, `/api/repos`, `/api/sessions`, `/api/card/{id}` stay anonymous. Only mutations (POSTs) get the token dependency.
- **Gate keys on token presence, not client IP** — `create_app(..., token=None)` → gate inactive (default; preserves every existing test). Token set → mutation requires header `X-Overseer-Token` == token, else **401**.
- **Soft-delete only** — F7 uses the existing reversible `abandon` (via `move`); no hard-delete primitive.
- **Test isolation** — reuse the existing autouse conftest fixtures; never write outside `tmp_path`. (See repo `CLAUDE.md` "Test isolation".)
- **Run commands** — repo-root `tests/overseer`: `cd plugins/overseer && ../../.venv/bin/python -m pytest -q`. Backend: `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest -q`. Frontend: `cd plugins/overseer/dashboard/frontend && npm test`. Dist rebuild: `cd plugins/overseer/dashboard/frontend && PATH=$HOME/.nvm/versions/node/v22.22.1/bin:$PATH npm run build`.
- **Commit style** — end messages with the repo's `Co-Authored-By` / `Claude-Session` trailers.

---

## File Structure

- `plugins/overseer/scripts/cli.py` — MODIFY: `set-field` parser (~1458) + `cmd_set_field` (~455) gain `--title`/`--body`.
- `tests/overseer/test_cli.py` — MODIFY: set-field title/body tests.
- `plugins/overseer/dashboard/backend/app/main.py` — MODIFY: `require_token` dependency, `token` param on `create_app`, `CreateBody`/`EditBody` models, `POST /api/card`, `POST /api/card/{id}`, attach dependency to all mutating routes.
- `plugins/overseer/dashboard/backend/tests/test_mutations.py` — MODIFY: create/edit/gate tests.
- `plugins/overseer/dashboard/serve.py` — MODIFY: resolve token (env → auto-gen on non-loopback → banner), pass to `create_app`.
- `plugins/overseer/dashboard/backend/tests/test_serve.py` — MODIFY: token-resolution tests.
- `plugins/overseer/dashboard/frontend/src/api/client.ts` — MODIFY: token header + 401 prompt/retry in `request()`; add `createCard`, `editCard`.
- `plugins/overseer/dashboard/frontend/src/api/client.test.ts` — MODIFY: client tests.
- `plugins/overseer/dashboard/frontend/src/api/types.ts` — MODIFY: `CreateCardBody`, `EditCardBody`, `CreateCardResponse` types.
- `plugins/overseer/dashboard/frontend/src/components/LabelEditor.tsx` (+ `.test.tsx`) — CREATE: editable labels control.
- `plugins/overseer/dashboard/frontend/src/components/NewCardDialog.tsx` (+ `.test.tsx`) — CREATE: create-card modal.
- `plugins/overseer/dashboard/frontend/src/components/CardDetailDrawer.tsx` — MODIFY: title/body edit + LabelEditor wiring.
- `plugins/overseer/dashboard/frontend/src/components/StatusMenu.tsx` (+ `.test.tsx`) — MODIFY: confirm before abandon.
- `plugins/overseer/dashboard/frontend/src/components/TopBar.tsx` (+ `.test.tsx`) — MODIFY: "＋ new card" button + dialog wiring.
- `plugins/overseer/dashboard/frontend/dist/**` — REBUILD (Task 11).

---

## Task 1: CLI — `set-field --title` / `--body`

**Files:**
- Modify: `plugins/overseer/scripts/cli.py` (parser ~1458, `cmd_set_field` ~455)
- Test: `tests/overseer/test_cli.py`

**Interfaces:**
- Produces: `overseer set-field <id> --title <str>` (empty → exit 1, `error: title cannot be empty`); `overseer set-field <id> --body <str>` (empty string clears body). Omitted flags are no-ops. Backend Task 3/4 shell these.

- [ ] **Step 1: Write failing tests** in `tests/overseer/test_cli.py` (add to the class holding `test_set_field_pr`, ~line 186):

```python
def test_set_field_title(self, repo):
    run(repo, "new-card", "--title", "Old")
    assert run(repo, "set-field", "WF-001", "--title", "New title") == 0
    assert _card(repo).title == "New title"

def test_set_field_empty_title_rejected(self, repo, capsys):
    run(repo, "new-card", "--title", "Old")
    assert run(repo, "set-field", "WF-001", "--title", "") == 1
    assert "title cannot be empty" in capsys.readouterr().err
    assert _card(repo).title == "Old"  # unchanged

def test_set_field_body_set_and_clear(self, repo):
    run(repo, "new-card", "--title", "T")
    assert run(repo, "set-field", "WF-001", "--body", "## Goal\nShip it") == 0
    assert _card(repo).body == "## Goal\nShip it"
    assert run(repo, "set-field", "WF-001", "--body", "") == 0
    assert _card(repo).body == ""
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest ../../tests/overseer/test_cli.py -q -k "set_field_title or empty_title or body_set_and_clear"`
Expected: FAIL (argparse rejects `--title`/`--body` → exit 2, or attribute missing).

- [ ] **Step 3: Add parser flags** — in the `set-field` parser block (~line 1458), after `p.add_argument("--priority")`:

```python
    p.add_argument("--title", help="new card title (non-empty)")
    p.add_argument("--body", help="new card body (markdown); empty string clears")
```

- [ ] **Step 4: Handle them in `cmd_set_field`** — inside `cmd_set_field` (~line 455), before `card.updated = _now()`:

```python
    if args.title is not None:
        if not args.title.strip():
            print("error: title cannot be empty", file=sys.stderr)
            return 1
        card.title = args.title
    if args.body is not None:
        card.body = args.body
```

- [ ] **Step 5: Run to verify pass**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest ../../tests/overseer/test_cli.py -q -k "set_field_title or empty_title or body_set_and_clear"`
Expected: PASS. Then run the full file to confirm no regressions: `../../.venv/bin/python -m pytest ../../tests/overseer/test_cli.py -q`.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/scripts/cli.py tests/overseer/test_cli.py
git commit -m "feat(overseer): set-field --title/--body (WF-063 CLI core)"
```

---

## Task 2: Backend — token gate

**Files:**
- Modify: `plugins/overseer/dashboard/backend/app/main.py`
- Test: `plugins/overseer/dashboard/backend/tests/test_mutations.py`

**Interfaces:**
- Produces: `create_app(root, *, host="127.0.0.1", dist_dir=None, token: str | None = None)`. When `token` is set, every mutating route requires header `X-Overseer-Token == token` else HTTP 401 (`"missing or invalid dashboard token"`). Reads ungated. Consumed by Tasks 3, 4, 5.

- [ ] **Step 1: Write failing tests** in `test_mutations.py`. Add a helper that builds a token-gated client and the gate tests:

```python
from app.main import create_app  # add to imports

def _gated_client(root: Path, token: str = "s3cret") -> TestClient:
    return TestClient(create_app(root, token=token))

def test_gate_open_when_no_token(client: TestClient, root: Path) -> None:
    card_id = _new_card(root)
    # default `client` fixture builds create_app(root) with token=None
    assert client.post(f"/api/card/{card_id}/park").status_code == 200

def test_gate_rejects_missing_token(root: Path) -> None:
    card_id = _new_card(root)
    gc = _gated_client(root)
    resp = gc.post(f"/api/card/{card_id}/park")
    assert resp.status_code == 401

def test_gate_rejects_wrong_token(root: Path) -> None:
    card_id = _new_card(root)
    gc = _gated_client(root)
    resp = gc.post(f"/api/card/{card_id}/park", headers={"X-Overseer-Token": "nope"})
    assert resp.status_code == 401

def test_gate_accepts_correct_token(root: Path) -> None:
    card_id = _new_card(root)
    gc = _gated_client(root)
    resp = gc.post(f"/api/card/{card_id}/park", headers={"X-Overseer-Token": "s3cret"})
    assert resp.status_code == 200

def test_gate_leaves_reads_open(root: Path) -> None:
    gc = _gated_client(root)
    assert gc.get("/api/board").status_code == 200  # no token, still 200
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest tests/test_mutations.py -q -k gate`
Expected: FAIL (missing-token/wrong-token return 200 today; `token=` kwarg unknown).

- [ ] **Step 3: Implement the gate** in `main.py`. Add imports at top (`hmac`, `Depends`, `Header`, `Request` are the pieces; `hmac` for constant-time compare):

```python
import hmac
from fastapi import Depends, FastAPI, Header, HTTPException
```

Change the signature and build the dependency inside `create_app`:

```python
def create_app(root: Path, *, host: str = "127.0.0.1", dist_dir: Path | None = None,
               token: str | None = None) -> FastAPI:
    app = FastAPI(title="overseer dashboard")
    ...
    def require_token(x_overseer_token: str | None = Header(default=None)) -> None:
        """Gate mutating routes when a token is in effect.

        Inactive when ``token`` is None (default: loopback bind, no env var) —
        preserves the pre-auth open behaviour and every existing test. When a
        token exists, the request must carry a matching ``X-Overseer-Token``
        header (constant-time compare) or the mutation is refused 401. Reads
        never depend on this.
        """
        if token is None:
            return
        supplied = x_overseer_token or ""
        if not hmac.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="missing or invalid dashboard token")
```

- [ ] **Step 4: Attach the dependency to every mutating route.** Add `dependencies=[Depends(require_token)]` to each mutating decorator. The full set: `set_order`, `set_priority`, `set_labels`, `set_parent`, `set_depends`, `park_card`, `unpark_card`, `claim_card`, `unclaim_card`, `move_card`, `set_threshold`, `clear_repo`, plus the new `create_card`/`edit_card` (Tasks 3/4). Example:

```python
    @app.post("/api/card/{card_id}/park", dependencies=[Depends(require_token)])
    def park_card(card_id: str, root: str | None = None) -> dict[str, Any]:
        ...
```

Leave all four GET routes (`get_board`, `get_repos`, `get_sessions`, `get_card`) untouched.

- [ ] **Step 5: Run to verify pass**

Run: `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest tests/test_mutations.py -q`
Expected: PASS (gate tests green; all pre-existing mutation tests still green because the default `client` fixture passes `token=None`).

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/dashboard/backend/app/main.py plugins/overseer/dashboard/backend/tests/test_mutations.py
git commit -m "feat(overseer-dashboard): token gate over mutating routes (rudimentary auth)"
```

---

## Task 3: Backend — `POST /api/card` (create)

**Files:**
- Modify: `plugins/overseer/dashboard/backend/app/main.py`
- Test: `plugins/overseer/dashboard/backend/tests/test_mutations.py`

**Interfaces:**
- Consumes: `require_token` (Task 2), `_resolve_root`, `_board_response`, `_mutation_error`, `run_overseer`.
- Produces: `POST /api/card` body `{title (required, non-empty), complexity?, labels?, goal?}` → `{"card_id": <id>, "board": ..., "context": ..., "limits": ...}`. Consumed by frontend Task 6 (`createCard`).

- [ ] **Step 1: Write failing tests** in `test_mutations.py`:

```python
def test_create_card(client: TestClient, root: Path) -> None:
    resp = client.post("/api/card", json={"title": "Fresh card", "complexity": "M"})
    assert resp.status_code == 200
    new_id = resp.json()["card_id"]
    assert new_id  # minted id echoed
    assert _show(root, new_id)["title"] == "Fresh card"
    assert new_id in {c["id"] for c in resp.json()["board"]["cards"]}

def test_create_card_with_labels(client: TestClient, root: Path) -> None:
    resp = client.post("/api/card", json={"title": "Tagged", "labels": ["policy", "arch"]})
    assert resp.status_code == 200
    assert _show(root, resp.json()["card_id"])["labels"] == ["policy", "arch"]

def test_create_card_missing_title(client: TestClient, root: Path) -> None:
    assert client.post("/api/card", json={"complexity": "S"}).status_code == 422  # pydantic required

def test_create_card_empty_title(client: TestClient, root: Path) -> None:
    assert client.post("/api/card", json={"title": "  "}).status_code == 400
```

- [ ] **Step 2: Run to verify fail**

Run: `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest tests/test_mutations.py -q -k create`
Expected: FAIL (404/405 — route absent).

- [ ] **Step 3: Add the model** near the other `BaseModel`s in `main.py`:

```python
class CreateBody(BaseModel):
    title: str
    complexity: str | None = None
    labels: list[str] = []
    goal: str | None = None
```

- [ ] **Step 4: Add the endpoint** inside `create_app` (near the other card routes):

```python
    @app.post("/api/card", dependencies=[Depends(require_token)])
    def create_card(body: CreateBody, root: str | None = None) -> dict[str, Any]:
        if not body.title.strip():
            raise HTTPException(status_code=400, detail="title cannot be empty")
        effective = _resolve_root(launch_root, _derived_launch_root, root)
        args = ["new-card", "--title", body.title]
        if body.complexity:
            args += ["--complexity", body.complexity]
        if body.labels:
            args += ["--labels", ",".join(body.labels)]
        if body.goal:
            args += ["--goal", body.goal]
        try:
            out = run_overseer(effective, *args)
        except CliError as exc:
            raise _mutation_error(exc) from exc
        card_id = out.strip()
        return {"card_id": card_id, **_board_response(effective)}
```

- [ ] **Step 5: Run to verify pass**

Run: `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest tests/test_mutations.py -q -k create`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/dashboard/backend/app/main.py plugins/overseer/dashboard/backend/tests/test_mutations.py
git commit -m "feat(overseer-dashboard): POST /api/card create endpoint (WF-062)"
```

---

## Task 4: Backend — `POST /api/card/{id}` (edit title/body)

**Files:**
- Modify: `plugins/overseer/dashboard/backend/app/main.py`
- Test: `plugins/overseer/dashboard/backend/tests/test_mutations.py`

**Interfaces:**
- Consumes: `require_token`, `_resolve_root`, `_mutate`, `check_id`, `run_overseer` (Task 1's `set-field --title/--body`).
- Produces: `POST /api/card/{id}` body `{title?, body?}` (≥1 required; empty title → 400) → board response. Consumed by frontend Task 6 (`editCard`).

- [ ] **Step 1: Write failing tests** in `test_mutations.py`:

```python
def test_edit_title(client: TestClient, root: Path) -> None:
    cid = _new_card(root)
    resp = client.post(f"/api/card/{cid}", json={"title": "Renamed"})
    assert resp.status_code == 200
    assert _show(root, cid)["title"] == "Renamed"

def test_edit_body(client: TestClient, root: Path) -> None:
    cid = _new_card(root)
    resp = client.post(f"/api/card/{cid}", json={"body": "## Goal\nnew body"})
    assert resp.status_code == 200
    assert _show(root, cid)["body"] == "## Goal\nnew body"

def test_edit_title_and_body(client: TestClient, root: Path) -> None:
    cid = _new_card(root)
    resp = client.post(f"/api/card/{cid}", json={"title": "Both", "body": "x"})
    assert resp.status_code == 200
    detail = _show(root, cid)
    assert detail["title"] == "Both" and detail["body"] == "x"

def test_edit_empty_title_rejected(client: TestClient, root: Path) -> None:
    cid = _new_card(root)
    assert client.post(f"/api/card/{cid}", json={"title": ""}).status_code == 400

def test_edit_requires_a_field(client: TestClient, root: Path) -> None:
    cid = _new_card(root)
    assert client.post(f"/api/card/{cid}", json={}).status_code == 400
```

- [ ] **Step 2: Run to verify fail**

Run: `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest tests/test_mutations.py -q -k edit`
Expected: FAIL (route absent).

- [ ] **Step 3: Add the model:**

```python
class EditBody(BaseModel):
    title: str | None = None
    body: str | None = None
```

- [ ] **Step 4: Add the endpoint** inside `create_app`:

```python
    @app.post("/api/card/{card_id}", dependencies=[Depends(require_token)])
    def edit_card(card_id: str, body: EditBody, root: str | None = None) -> dict[str, Any]:
        if body.title is None and body.body is None:
            raise HTTPException(status_code=400, detail="title or body required")
        if body.title is not None and not body.title.strip():
            raise HTTPException(status_code=400, detail="title cannot be empty")
        effective = _resolve_root(launch_root, _derived_launch_root, root)

        def do() -> None:
            check_id(card_id)
            args = ["set-field", card_id]
            if body.title is not None:
                args += ["--title", body.title]
            if body.body is not None:
                args += ["--body", body.body]
            run_overseer(effective, *args)

        return _mutate(do, effective)
```

Note: register this AFTER `get_card` (`GET /api/card/{card_id}`) — distinct methods so order is not a conflict, but keep the card routes grouped.

- [ ] **Step 5: Run to verify pass**

Run: `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest tests/test_mutations.py -q`
Expected: PASS (whole file).

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/dashboard/backend/app/main.py plugins/overseer/dashboard/backend/tests/test_mutations.py
git commit -m "feat(overseer-dashboard): POST /api/card/{id} edit title/body (WF-063)"
```

---

## Task 5: Serve — resolve token (env → auto-gen on non-loopback → banner)

**Files:**
- Modify: `plugins/overseer/dashboard/serve.py`
- Test: `plugins/overseer/dashboard/backend/tests/test_serve.py`

**Interfaces:**
- Consumes: `create_app(..., token=...)` (Task 2).
- Produces: `serve.resolve_token(host: str) -> str | None` — env `OVERSEER_DASHBOARD_TOKEN` if set; else `secrets.token_urlsafe(24)` when `host` is non-loopback; else `None`. `main()` passes it to `create_app` and prints it when set.

- [ ] **Step 1: Write failing tests** in `test_serve.py`:

```python
def test_resolve_token_none_on_loopback_without_env(monkeypatch) -> None:
    monkeypatch.delenv("OVERSEER_DASHBOARD_TOKEN", raising=False)
    assert serve.resolve_token("127.0.0.1") is None

def test_resolve_token_env_wins(monkeypatch) -> None:
    monkeypatch.setenv("OVERSEER_DASHBOARD_TOKEN", "fixed-tok")
    assert serve.resolve_token("127.0.0.1") == "fixed-tok"

def test_resolve_token_autogen_on_non_loopback(monkeypatch) -> None:
    monkeypatch.delenv("OVERSEER_DASHBOARD_TOKEN", raising=False)
    tok = serve.resolve_token("0.0.0.0")
    assert tok and len(tok) >= 20

def test_main_passes_token_to_create_app(monkeypatch) -> None:
    monkeypatch.setenv("OVERSEER_DASHBOARD_TOKEN", "abc123")
    captured = {}
    def fake_create_app(root, *, host, token=None):
        captured["token"] = token
        return MagicMock()
    monkeypatch.setattr(serve, "create_app", fake_create_app)
    monkeypatch.setattr(serve.uvicorn, "run", MagicMock())
    serve.main(["--no-browser"])
    assert captured["token"] == "abc123"
```

- [ ] **Step 2: Run to verify fail**

Run: `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest tests/test_serve.py -q -k "token"`
Expected: FAIL (`resolve_token` absent; `create_app` gets no token).

- [ ] **Step 3: Implement** in `serve.py`. Add imports:

```python
import os
import secrets
```

Add the helper and constant:

```python
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def resolve_token(host: str) -> str | None:
    """The dashboard token in effect for this bind, or None (gate off).

    Explicit ``OVERSEER_DASHBOARD_TOKEN`` always wins. Otherwise a token is
    auto-generated ONLY for a non-loopback bind — exposing the mutation
    surface beyond localhost must not be tokenless. A pure loopback bind with
    no env var stays token-free (the common single-user case).
    """
    env = os.environ.get("OVERSEER_DASHBOARD_TOKEN")
    if env:
        return env
    if host not in _LOOPBACK_HOSTS:
        return secrets.token_urlsafe(24)
    return None
```

Wire it into `main()`:

```python
    token = resolve_token(args.host)
    app = create_app(root, host=args.host, token=token)
    url = f"http://{args.host}:{args.port}/"
    print(f"overseer dashboard serving {root} at {url}")
    if token:
        print(f"dashboard token (send as X-Overseer-Token header): {token}")
```

- [ ] **Step 4: Run to verify pass**

Run: `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest tests/test_serve.py -q`
Expected: PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/dashboard/serve.py plugins/overseer/dashboard/backend/tests/test_serve.py
git commit -m "feat(overseer-dashboard): serve resolves + prints token; non-loopback binds are never tokenless"
```

---

## Task 6: Frontend client — token handling + `createCard`/`editCard`

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/src/api/client.ts`, `src/api/types.ts`
- Test: `plugins/overseer/dashboard/frontend/src/api/client.test.ts`

**Interfaces:**
- Produces:
  - `createCard(body: CreateCardBody): Promise<CreateCardResponse>` → `POST /api/card`.
  - `editCard(id: string, body: EditCardBody): Promise<BoardResponse>` → `POST /api/card/{id}`.
  - `request()` now sends `X-Overseer-Token` from `localStorage["overseer_dashboard_token"]` when present, and on a 401 prompts once (`window.prompt`), stores, and retries.
- Consumed by Tasks 7–10.

- [ ] **Step 1: Add types** to `src/api/types.ts`:

```typescript
export interface CreateCardBody {
  title: string;
  complexity?: string | null;
  labels?: string[];
  goal?: string | null;
}

export interface EditCardBody {
  title?: string;
  body?: string;
}

export interface CreateCardResponse extends BoardResponse {
  card_id: string;
}
```

- [ ] **Step 2: Write failing tests** in `src/api/client.test.ts` (follow the existing fetch-mock style used by the `setLabels` tests):

```typescript
it("createCard POSTs {title,...} to /api/card and returns card_id", async () => {
  const fetchMock = mockFetchOnce({ card_id: "WF-9", board: { cards: [] }, context: {}, limits: null });
  const res = await client.createCard({ title: "New", complexity: "M" });
  expect(fetchMock).toHaveBeenCalledWith("/api/card", expect.objectContaining({ method: "POST" }));
  expect(JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string)).toEqual({
    title: "New", complexity: "M",
  });
  expect(res.card_id).toBe("WF-9");
});

it("editCard POSTs {title,body} to /api/card/{id}", async () => {
  const fetchMock = mockFetchOnce({ board: { cards: [] }, context: {}, limits: null });
  await client.editCard("WF-1", { title: "T", body: "B" });
  expect(fetchMock).toHaveBeenCalledWith("/api/card/WF-1", expect.objectContaining({ method: "POST" }));
});

it("sends X-Overseer-Token header when one is stored", async () => {
  localStorage.setItem("overseer_dashboard_token", "tok-1");
  const fetchMock = mockFetchOnce({ board: { cards: [] }, context: {}, limits: null });
  await client.park("WF-1");
  const headers = (fetchMock.mock.calls[0][1] as RequestInit).headers as Record<string, string>;
  expect(headers["X-Overseer-Token"]).toBe("tok-1");
});

it("on 401 prompts for a token, stores it, and retries once", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({ detail: "x" }), statusText: "" })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ board: { cards: [] }, context: {}, limits: null }) });
  vi.stubGlobal("fetch", fetchMock);
  vi.spyOn(window, "prompt").mockReturnValue("pasted-tok");
  await client.park("WF-1");
  expect(fetchMock).toHaveBeenCalledTimes(2);
  expect(localStorage.getItem("overseer_dashboard_token")).toBe("pasted-tok");
  const retryHeaders = (fetchMock.mock.calls[1][1] as RequestInit).headers as Record<string, string>;
  expect(retryHeaders["X-Overseer-Token"]).toBe("pasted-tok");
});
```

(Match `mockFetchOnce`/`vi.stubGlobal` to whatever the file already uses; reset `localStorage` in `beforeEach`.)

- [ ] **Step 3: Run to verify fail**

Run: `cd plugins/overseer/dashboard/frontend && npm test -- client.test`
Expected: FAIL (`createCard`/`editCard` undefined; no token header).

- [ ] **Step 4: Implement** in `client.ts`. Add the token constant + a header helper, and thread it through `request()`:

```typescript
const TOKEN_KEY = "overseer_dashboard_token";

function authHeaders(): Record<string, string> {
  const tok = localStorage.getItem(TOKEN_KEY);
  return tok ? { "X-Overseer-Token": tok } : {};
}
```

Rework `request()` so it merges auth headers and retries once on 401:

```typescript
async function request<T>(method: "GET" | "POST", url: string, body?: unknown): Promise<T> {
  const send = async (): Promise<Response> => {
    const headers: Record<string, string> = { ...authHeaders() };
    const init: RequestInit = { method, headers };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    return fetch(url, init);
  };

  let res = await send();
  if (res.status === 401) {
    const tok = window.prompt("This dashboard requires a token. Paste it:");
    if (tok) {
      localStorage.setItem(TOKEN_KEY, tok);
      res = await send();
    }
  }
  if (!res.ok) {
    let detail: string | undefined;
    try {
      detail = ((await res.json()) as { detail?: string })?.detail;
    } catch {
      /* non-JSON */
    }
    throw new Error(detail ?? res.statusText);
  }
  return (await res.json()) as T;
}
```

Add the two wrappers (near `setLabels`):

```typescript
export function createCard(body: CreateCardBody): Promise<CreateCardResponse> {
  return request<CreateCardResponse>("POST", withRoot("/api/card"), body);
}

export function editCard(id: string, body: EditCardBody): Promise<BoardResponse> {
  return request<BoardResponse>("POST", withRoot(`/api/card/${id}`), body);
}
```

Add `CreateCardBody, EditCardBody, CreateCardResponse` to the type import block.

- [ ] **Step 5: Run to verify pass**

Run: `cd plugins/overseer/dashboard/frontend && npm test -- client.test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/api/client.ts plugins/overseer/dashboard/frontend/src/api/types.ts plugins/overseer/dashboard/frontend/src/api/client.test.ts
git commit -m "feat(overseer-dashboard): client createCard/editCard + X-Overseer-Token header w/ 401 retry"
```

---

## Task 7: Frontend — `LabelEditor` component + drawer wiring (F1 fold-in)

**Files:**
- Create: `plugins/overseer/dashboard/frontend/src/components/LabelEditor.tsx` (+ `.test.tsx`)
- Modify: `plugins/overseer/dashboard/frontend/src/components/CardDetailDrawer.tsx` (~line 274, replacing the read-only `LabelChips`)

**Interfaces:**
- Consumes: `setLabels` (existing client), `LabelChips` (existing display).
- Produces: `<LabelEditor labels={string[]} onSave={(labels: string[]) => Promise<void>} />` — shows chips, an add-input, and per-chip remove; calls `onSave` with the full new set (full-replace semantics).

- [ ] **Step 1: Write failing test** `LabelEditor.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import LabelEditor from "./LabelEditor";

it("adds a label and calls onSave with the full set", async () => {
  const onSave = vi.fn().mockResolvedValue(undefined);
  render(<LabelEditor labels={["policy"]} onSave={onSave} />);
  fireEvent.change(screen.getByPlaceholderText(/add label/i), { target: { value: "arch" } });
  fireEvent.keyDown(screen.getByPlaceholderText(/add label/i), { key: "Enter" });
  await waitFor(() => expect(onSave).toHaveBeenCalledWith(["policy", "arch"]));
});

it("removes a label and calls onSave without it", async () => {
  const onSave = vi.fn().mockResolvedValue(undefined);
  render(<LabelEditor labels={["policy", "arch"]} onSave={onSave} />);
  fireEvent.click(screen.getByRole("button", { name: /remove policy/i }));
  await waitFor(() => expect(onSave).toHaveBeenCalledWith(["arch"]));
});
```

- [ ] **Step 2: Run to verify fail**

Run: `cd plugins/overseer/dashboard/frontend && npm test -- LabelEditor`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement** `LabelEditor.tsx`:

```tsx
import { useState } from "react";

interface Props {
  labels: string[];
  onSave: (labels: string[]) => Promise<void>;
}

export default function LabelEditor({ labels, onSave }: Props) {
  const [draft, setDraft] = useState("");

  const commit = async (next: string[]) => {
    await onSave(next);
  };

  const add = async () => {
    const v = draft.trim();
    if (!v || labels.includes(v)) {
      setDraft("");
      return;
    }
    setDraft("");
    await commit([...labels, v]);
  };

  return (
    <div className="label-editor">
      {labels.map((lb) => (
        <span key={lb} className="label-editor__chip">
          {lb}
          <button
            type="button"
            aria-label={`remove ${lb}`}
            onClick={() => commit(labels.filter((x) => x !== lb))}
          >
            ×
          </button>
        </span>
      ))}
      <input
        placeholder="add label…"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            void add();
          }
        }}
      />
    </div>
  );
}
```

- [ ] **Step 4: Wire into the drawer.** In `CardDetailDrawer.tsx`, import `LabelEditor` and `setLabels`, and replace the read-only `<LabelChips labels={detail.labels} .../>` (~line 274) with:

```tsx
<LabelEditor
  labels={detail.labels ?? []}
  onSave={async (labels) => {
    await setLabels(detail.id, labels);
    onMutated();
  }}
/>
```

(`onMutated` is the drawer's existing refetch closure — see the C6 mutation-control comment ~line 107. Use whatever its in-scope name is.)

- [ ] **Step 5: Run to verify pass**

Run: `cd plugins/overseer/dashboard/frontend && npm test -- LabelEditor CardDetailDrawer`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/components/LabelEditor.tsx plugins/overseer/dashboard/frontend/src/components/LabelEditor.test.tsx plugins/overseer/dashboard/frontend/src/components/CardDetailDrawer.tsx
git commit -m "feat(overseer-dashboard): editable label control in card drawer (F1 fold-in, WF-058)"
```

---

## Task 8: Frontend — drawer title/body edit

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/src/components/CardDetailDrawer.tsx` (title ~232, body ~380-431)
- Test: `plugins/overseer/dashboard/frontend/src/components/CardDetailDrawer.test.tsx`

**Interfaces:**
- Consumes: `editCard` (Task 6), the drawer's `onMutated` refetch closure.
- Produces: an edit affordance that reveals title + body inputs and a Save that calls `editCard(detail.id, {title, body})` then `onMutated()`.

- [ ] **Step 1: Write failing test** in `CardDetailDrawer.test.tsx` (mock the `editCard` client fn — match the file's existing client-mock approach):

```tsx
it("edits title and body and saves via editCard", async () => {
  const editCard = vi.spyOn(client, "editCard").mockResolvedValue(BOARD_RESPONSE);
  renderDrawer({ ...detail, id: "WF-1", title: "Old", body: "old body" });
  fireEvent.click(screen.getByRole("button", { name: /edit/i }));
  fireEvent.change(screen.getByLabelText(/title/i), { target: { value: "New title" } });
  fireEvent.change(screen.getByLabelText(/body/i), { target: { value: "new body" } });
  fireEvent.click(screen.getByRole("button", { name: /save/i }));
  await waitFor(() =>
    expect(editCard).toHaveBeenCalledWith("WF-1", { title: "New title", body: "new body" }),
  );
});
```

- [ ] **Step 2: Run to verify fail**

Run: `cd plugins/overseer/dashboard/frontend && npm test -- CardDetailDrawer`
Expected: FAIL (no edit button).

- [ ] **Step 3: Implement.** Add edit state to the drawer and an Edit/Save toggle. Sketch (adapt to the component's existing structure and JSX):

```tsx
const [editing, setEditing] = useState(false);
const [titleDraft, setTitleDraft] = useState(detail.title);
const [bodyDraft, setBodyDraft] = useState(detail.body);

// reset drafts when the shown card changes
useEffect(() => {
  setTitleDraft(detail.title);
  setBodyDraft(detail.body);
  setEditing(false);
}, [detail.id, detail.title, detail.body]);

const saveEdit = async () => {
  await editCard(detail.id, { title: titleDraft, body: bodyDraft });
  setEditing(false);
  onMutated();
};
```

Render: when `editing`, replace the `<h2>` title (~232) with `<input aria-label="title" .../>` and the body block (~380-431) with `<textarea aria-label="body" .../>`, plus a Save button calling `saveEdit`; otherwise show the existing read views plus an "Edit" button.

- [ ] **Step 4: Run to verify pass**

Run: `cd plugins/overseer/dashboard/frontend && npm test -- CardDetailDrawer`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/components/CardDetailDrawer.tsx plugins/overseer/dashboard/frontend/src/components/CardDetailDrawer.test.tsx
git commit -m "feat(overseer-dashboard): edit card title/body in drawer (WF-063)"
```

---

## Task 9: Frontend — confirm before abandon

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/src/components/StatusMenu.tsx` (~line 55, the abandon action)
- Test: `plugins/overseer/dashboard/frontend/src/components/StatusMenu.test.tsx` (~line 64, existing abandon test)

**Interfaces:**
- Consumes: existing `move(id, {status:"abandoned"})`.
- Produces: the abandon ("Forsake") action now requires a confirm (`window.confirm`) before it calls `move`; declining is a no-op.

- [ ] **Step 1: Update/extend the test** in `StatusMenu.test.tsx`. Keep the existing "abandon calls move" behavior but gate it on confirm:

```tsx
it("abandon asks for confirmation before calling move", () => {
  const move = vi.fn();
  vi.spyOn(window, "confirm").mockReturnValue(false);
  renderMenu({ move });
  fireEvent.click(screen.getByRole("button", { name: /forsake/i }));
  expect(move).not.toHaveBeenCalled();  // declined

  (window.confirm as unknown as vi.Mock).mockReturnValue(true);
  fireEvent.click(screen.getByRole("button", { name: /forsake/i }));
  expect(move).toHaveBeenCalledWith("WF-1", { status: "abandoned" });
});
```

(Adjust `renderMenu`/prop wiring to match the existing test at line 64.)

- [ ] **Step 2: Run to verify fail**

Run: `cd plugins/overseer/dashboard/frontend && npm test -- StatusMenu`
Expected: FAIL (abandon fires without confirm).

- [ ] **Step 3: Implement.** Wrap the abandon handler (~line 55) with a confirm:

```tsx
// abandon (Forsake) — destructive archive, guard with a confirm.
if (!window.confirm("Forsake this card? It will be archived (reversible via unblock).")) return;
await mutate(() => move(cardId, { status: "abandoned" }));
```

- [ ] **Step 4: Run to verify pass**

Run: `cd plugins/overseer/dashboard/frontend && npm test -- StatusMenu`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/components/StatusMenu.tsx plugins/overseer/dashboard/frontend/src/components/StatusMenu.test.tsx
git commit -m "feat(overseer-dashboard): confirm before abandon/forsake (WF-064)"
```

---

## Task 10: Frontend — `NewCardDialog` + TopBar "＋ new card" button

**Files:**
- Create: `plugins/overseer/dashboard/frontend/src/components/NewCardDialog.tsx` (+ `.test.tsx`)
- Modify: `plugins/overseer/dashboard/frontend/src/components/TopBar.tsx` (+ `.test.tsx`)

**Interfaces:**
- Consumes: `createCard` (Task 6). Mirror the existing `ClearDialog.tsx` modal pattern for open/close/escape handling.
- Produces: `<NewCardDialog open onClose onCreated />` with title (required) + complexity + labels + goal inputs; Create calls `createCard(...)`, then `onCreated()` (board refresh) + `onClose()`.

- [ ] **Step 1: Write failing test** `NewCardDialog.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import NewCardDialog from "./NewCardDialog";
import * as client from "../api/client";

it("creates a card from the form and calls onCreated", async () => {
  const spy = vi.spyOn(client, "createCard").mockResolvedValue({
    card_id: "WF-9", board: { cards: [] }, context: {}, limits: null,
  } as never);
  const onCreated = vi.fn();
  const onClose = vi.fn();
  render(<NewCardDialog open onClose={onClose} onCreated={onCreated} />);
  fireEvent.change(screen.getByLabelText(/title/i), { target: { value: "Fresh" } });
  fireEvent.click(screen.getByRole("button", { name: /create/i }));
  await waitFor(() => expect(spy).toHaveBeenCalledWith(expect.objectContaining({ title: "Fresh" })));
  await waitFor(() => expect(onCreated).toHaveBeenCalled());
});

it("disables Create when the title is empty", () => {
  render(<NewCardDialog open onClose={vi.fn()} onCreated={vi.fn()} />);
  expect(screen.getByRole("button", { name: /create/i })).toBeDisabled();
});
```

- [ ] **Step 2: Run to verify fail**

Run: `cd plugins/overseer/dashboard/frontend && npm test -- NewCardDialog`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement** `NewCardDialog.tsx` (modeled on `ClearDialog.tsx`):

```tsx
import { useState } from "react";
import { createCard } from "../api/client";
import type { CreateCardBody } from "../api/types";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export default function NewCardDialog({ open, onClose, onCreated }: Props) {
  const [title, setTitle] = useState("");
  const [complexity, setComplexity] = useState("");
  const [labels, setLabels] = useState("");
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const submit = async () => {
    if (!title.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const body: CreateCardBody = { title: title.trim() };
      if (complexity) body.complexity = complexity;
      if (labels.trim()) body.labels = labels.split(",").map((s) => s.trim()).filter(Boolean);
      if (goal.trim()) body.goal = goal.trim();
      await createCard(body);
      onCreated();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="dialog-backdrop" role="dialog" aria-label="New card">
      <div className="dialog">
        <label>Title<input aria-label="title" value={title} onChange={(e) => setTitle(e.target.value)} /></label>
        <label>Complexity
          <select aria-label="complexity" value={complexity} onChange={(e) => setComplexity(e.target.value)}>
            <option value="">—</option><option>S</option><option>M</option><option>L</option><option>XL</option>
          </select>
        </label>
        <label>Labels<input aria-label="labels" value={labels} onChange={(e) => setLabels(e.target.value)} placeholder="comma,separated" /></label>
        <label>Goal<textarea aria-label="goal" value={goal} onChange={(e) => setGoal(e.target.value)} /></label>
        {error && <p className="dialog__error">{error}</p>}
        <div className="dialog__actions">
          <button type="button" onClick={onClose}>Cancel</button>
          <button type="button" onClick={submit} disabled={busy || !title.trim()}>Create</button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Wire into TopBar.** Add a "＋ New card" button that opens the dialog; on `onCreated`, call the board-refresh prop TopBar already receives (match its existing refresh/`onMutated` prop). Add a TopBar test asserting the button renders the dialog.

- [ ] **Step 5: Run to verify pass**

Run: `cd plugins/overseer/dashboard/frontend && npm test -- NewCardDialog TopBar`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/components/NewCardDialog.tsx plugins/overseer/dashboard/frontend/src/components/NewCardDialog.test.tsx plugins/overseer/dashboard/frontend/src/components/TopBar.tsx plugins/overseer/dashboard/frontend/src/components/TopBar.test.tsx
git commit -m "feat(overseer-dashboard): new-card dialog + TopBar create button (WF-062)"
```

---

## Task 11: Rebuild dist + full green + freshness

**Files:**
- Rebuild: `plugins/overseer/dashboard/frontend/dist/**`

- [ ] **Step 1: Full frontend suite**

Run: `cd plugins/overseer/dashboard/frontend && npm test`
Expected: all green.

- [ ] **Step 2: Rebuild committed dist via the nvm node path**

Run: `cd plugins/overseer/dashboard/frontend && PATH=$HOME/.nvm/versions/node/v22.22.1/bin:$PATH npm run build`

- [ ] **Step 3: Backend suite incl. dist freshness**

Run: `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest -q`
Expected: all green, including `test_dist_freshness`.

- [ ] **Step 4: Overseer suite**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest -q`
Expected: all green.

- [ ] **Step 5: Commit the rebuilt dist**

```bash
git add plugins/overseer/dashboard/frontend/dist
git commit -m "chore(overseer-dashboard): rebuild dist for PR3 mutations + auth"
```

---

## Self-review notes

- **Spec coverage:** F5 create → Tasks 3, 6, 10. F6 edit title/body → Tasks 1, 4, 6, 8. F7 abandon+confirm → Task 9 (reuses existing `move`; **spec deviation** — no dedicated `/abandon` endpoint, because `/move status=abandoned` already abandons; DRYer, flagged for review). F1 label-editor fold-in → Task 7. Token gate → Tasks 2, 5, 6. Documented CSRF/DNS-rebind non-goal → carried in spec; no code.
- **Type consistency:** `create_app(..., token=None)` (Task 2) matches `serve.resolve_token`/`main` (Task 5) and the gated-client tests. `CreateBody`/`EditBody` (backend) mirror `CreateCardBody`/`EditCardBody`/`CreateCardResponse` (frontend). `createCard`/`editCard`/`setLabels` names are stable across Tasks 6–10.
- **Placeholder scan:** frontend JSX sketches (Tasks 8, 10) are marked "adapt to existing structure" deliberately — the exact drawer/TopBar JSX must follow in-file patterns; the client calls, prop contracts, and test assertions are concrete.
```
