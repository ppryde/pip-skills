# Dashboard "Clear Data" Action Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the overseer dashboard a per-repo destructive "clear data" action (wipe a repo's cards, or its whole central folder) that always takes a recovery backup first and is guarded by a two-step, type-the-label confirmation.

**Architecture:** A new `overseer clear` CLI verb does the real work (backup-first, then wipe), emitting JSON. The dashboard backend exposes `POST /api/repo/clear` that delegates to the verb (mirroring every other mutation) and is loopback-gated for safety on LAN-exposed, unauthenticated servers. The React frontend adds a Clear control beside the repo selector that opens a two-step "dragons" modal.

**Tech Stack:** Python 3.11 + argparse + sqlite3 (CLI); FastAPI + Pydantic (backend); React 18 + TypeScript + Vite + Vitest (frontend).

## Global Constraints

- **Scopes are ONLY `cards` and `repo`.** There is deliberately **no `all`/nuke scope** — clear operates only on the selected repo. (User decision, overriding the spec's A4 "all repos" option.)
- **`--scope cards` = hard `DELETE FROM cards`** (both live + archived rows), preserving identity meta. Recoverable via the backup snapshot. (Not archive.)
- **Second-confirmation string = the repo label**, typed exactly, to enable the final button.
- **Destructive but recoverable:** every clear runs `backup.backup_board(root)` FIRST. A backup failure ABORTS the wipe (never wipe without a snapshot) — unless `--no-backup`.
- **Loopback gate:** `POST /api/repo/clear` returns `403` when the server was bound to a non-loopback host, unless env `OVERSEER_DASHBOARD_ALLOW_REMOTE_DESTRUCTIVE=1` was set at launch.
- **Test isolation:** every test pins overseer env to `tmp_path` (autouse fixtures already do this in both `plugins/overseer/tests/conftest.py` and `plugins/overseer/dashboard/backend/tests/conftest.py`). See CLAUDE.md "Test isolation".
- **Committed Vite build:** any change under `frontend/src/` MUST be followed by `npm run build` and the regenerated `frontend/dist/` committed in the same change, or `backend/tests/test_dist_freshness.py` fails. Node is nvm-managed and NOT on PATH — prefix node/npm commands with `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH"`.
- **Python test runner:** repo-root `.venv` — `/Users/philip.pryde/repos/pip-skills/.venv/bin/python`. Run overseer plugin tests from `plugins/overseer/`; backend tests from `plugins/overseer/dashboard/backend/`.

### JSON contract (the `overseer clear --json` payload — the single source of truth for backend + frontend)

```json
{
  "scope": "cards" | "repo",
  "backup_path": "<absolute path to recovery snapshot>" | null,
  "removed": { "cards": <int> }  |  { "folder": "<path>", "existed": <bool> },
  "label": "<repo label>",
  "noop": <bool>
}
```
- `scope: "cards"` → `removed = {"cards": <rows deleted>}`.
- `scope: "repo"` → `removed = {"folder": "<central_root path>", "existed": <bool>}`.
- No board yet → `noop: true`, `backup_path: null`, and `removed` uses the **scope's own shape** (cards → `{"cards": 0}`; repo → `{"folder": "<central_root path>", "existed": false}`). The noop case never introduces a third `removed` shape.

---

## File Structure

**CLI (Python):**
- Modify `plugins/overseer/scripts/cli.py` — add `cmd_clear` handler + `_print_clear` helper + `clear` subparser.
- Test `plugins/overseer/tests/test_clear.py` — new test module for the verb.

**Backend (Python):**
- Modify `plugins/overseer/dashboard/backend/app/main.py` — add `ClearBody` model, `_is_loopback` helper, `host` param on `create_app`, `POST /api/repo/clear` route.
- Modify `plugins/overseer/dashboard/serve.py` — pass `host=args.host` into `create_app`.
- Modify `plugins/overseer/dashboard/backend/tests/test_serve.py` — update `create_app` call assertions.
- Test `plugins/overseer/dashboard/backend/tests/test_clear_endpoint.py` — new test module for the route.

**Frontend (React/TS):**
- Modify `frontend/src/api/types.ts` — add `ClearResponse`.
- Modify `frontend/src/api/client.ts` — add `clearRepo(root, scope)`.
- Create `frontend/src/components/ClearDialog.tsx` (+ `ClearDialog.test.tsx`) — two-step modal.
- Modify `frontend/src/components/TopBar.tsx` — add a Clear button beside `RepoSelector`.
- Modify `frontend/src/App.tsx` — own dialog open-state + success toast + refresh-after-clear.
- Modify `frontend/src/styles.css` — success-toast + dialog styles.
- Rebuild + commit `frontend/dist/`.

**Version:**
- Bump `overseer` plugin version + marketplace version (locate exact files in the final task).

---

## Task 1: `overseer clear --scope cards` (backup-first card wipe + JSON)

**Files:**
- Modify: `plugins/overseer/scripts/cli.py` (add `_print_clear`, `cmd_clear`, and the `clear` subparser)
- Test: `plugins/overseer/tests/test_clear.py`

**Interfaces:**
- Consumes: `backup.backup_board(repo_root) -> dict` (returns `{"cards","sprint_files","fact_files","usage_lines","dest"}`); `db.board_db_path(repo_root) -> Path`; `_conn(repo_root) -> sqlite3.Connection` (module-cached, closed in `main()`'s finally); `rebuild_index(repo_root, project, now)`; `derive_repo_label(repo_root) -> str | None`; `_now()`.
- Produces: CLI verb `overseer clear --scope {cards,repo} [--yes] [--no-backup] [--json]`; handler `cmd_clear(args) -> int`; helper `_print_clear(args, payload: dict, human: str) -> None`. Emits the JSON contract above.

- [ ] **Step 1: Write the failing test**

Add to a new file `plugins/overseer/tests/test_clear.py`. Mirror `test_cli.py`'s in-process harness (`main(["--root", ...])`).

```python
import json

import pytest

from scripts import config, db
from scripts.cli import main
from scripts.store import state_root


def run(repo, *argv: str) -> int:
    return main(["--root", str(repo), *argv])


@pytest.fixture
def repo(tmp_path):
    assert main(["--root", str(tmp_path), "init"]) == 0
    return tmp_path


def test_clear_cards_deletes_all_cards_and_keeps_identity_meta(repo, capsys):
    run(repo, "new-card", "--title", "A")
    run(repo, "new-card", "--title", "B")
    conn = db.connect(repo, migrate=False)
    schema_before = db.get_meta(conn, "schema_version")
    repo_root_before = db.get_meta(conn, "repo_root")

    assert run(repo, "clear", "--scope", "cards", "--yes", "--json") == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "cards"
    assert payload["removed"]["cards"] == 2
    assert payload["backup_path"]  # a snapshot was taken

    conn = db.connect(repo, migrate=False)
    live, _ = db.load_live_cards(conn)
    assert live == []
    assert db.load_archived_cards(conn) == []
    # identity meta preserved
    assert db.get_meta(conn, "schema_version") == schema_before
    assert db.get_meta(conn, "repo_root") == repo_root_before
    # ledger regenerated (now empty of live cards)
    assert (state_root(repo) / "ledger.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_clear.py -q`
Expected: FAIL — argparse errors with `invalid choice: 'clear'` (verb not registered).

- [ ] **Step 3: Write minimal implementation**

In `plugins/overseer/scripts/cli.py`, add the helper + handler near the other `cmd_*` handlers (e.g. just after `cmd_restore`). `json` and `sys` are already imported in this module; `derive_repo_label`, `rebuild_index`, `_conn`, `_now`, `_close_conns` already exist.

```python
def _print_clear(args: argparse.Namespace, payload: dict, human: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload))
    else:
        print(human)


def cmd_clear(args: argparse.Namespace) -> int:
    import shutil

    from scripts import backup, config
    from scripts.db import board_db_path

    scope = args.scope
    label = derive_repo_label(args.root) or args.root.resolve().name

    # No board yet -> no-op (not an error).
    if not board_db_path(args.root).exists():
        _print_clear(
            args,
            {"scope": scope, "backup_path": None, "removed": {"existed": False},
             "label": label, "noop": True},
            human=f"no overseer board for {label!r}; nothing to clear",
        )
        return 0

    # Confirmation gate (the dashboard always passes --yes).
    if not args.yes:
        if sys.stdin.isatty():
            reply = input(
                f"Clear scope={scope} for {label!r}? Type the repo label to confirm: "
            ).strip()
            if reply != label:
                raise ValueError("confirmation did not match; aborted")
        else:
            raise ValueError("clear requires --yes for non-interactive use")

    # Backup first (recoverable). A failure here ABORTS the wipe.
    backup_path = None
    if not args.no_backup:
        backup_path = backup.backup_board(args.root)["dest"]

    if scope == "cards":
        conn = _conn(args.root)
        deleted = conn.execute("DELETE FROM cards").rowcount
        conn.commit()
        rebuild_index(args.root, args.root.resolve().name, _now())
        removed: dict = {"cards": deleted}
    else:  # scope == "repo"
        folder = config.central_root(args.root)
        _close_conns()  # drop cached conn before removing the folder under it
        existed = folder.exists()
        if existed:
            shutil.rmtree(folder)
        removed = {"folder": str(folder), "existed": existed}

    snap = f" (recovery snapshot: {backup_path})" if backup_path else ""
    _print_clear(
        args,
        {"scope": scope, "backup_path": backup_path, "removed": removed,
         "label": label, "noop": False},
        human=f"cleared scope={scope} for {label!r}{snap}",
    )
    return 0
```

Register the subparser alongside the others in `build_parser()` (near the `backup`/`restore` parsers):

```python
    p = sub.add_parser("clear")
    p.add_argument("--scope", choices=["cards", "repo"], default="repo")
    p.add_argument("--yes", action="store_true",
                   help="skip the interactive confirmation prompt")
    p.add_argument("--no-backup", dest="no_backup", action="store_true",
                   help="do NOT take a recovery snapshot before wiping")
    p.add_argument("--json", action="store_true",
                   help="emit the result as JSON (for the dashboard)")
    p.set_defaults(func=cmd_clear)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_clear.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/cli.py plugins/overseer/tests/test_clear.py
git commit -m "feat(overseer): add clear verb --scope cards (backup-first, JSON)"
```

---

## Task 2: `overseer clear --scope repo`, `--no-backup`, no-op + backup-failure-aborts

**Files:**
- Modify: `plugins/overseer/scripts/cli.py` (already handles `repo` scope from Task 1 — this task adds the tests that pin its behaviour and the edge cases)
- Test: `plugins/overseer/tests/test_clear.py`

**Interfaces:**
- Consumes: everything from Task 1; `config.central_root(repo_root) -> Path`.
- Produces: verified `--scope repo`, `--no-backup`, no-op, and backup-failure-aborts behaviours.

Note: because `test_clear.py`'s env is pinned by the autouse fixture, `config.central_root(repo)` resolves to `OVERSEER_CENTRAL` = `tmp_path/"state"`.

- [ ] **Step 1: Write the failing tests**

Append to `plugins/overseer/tests/test_clear.py`:

```python
def test_clear_repo_removes_central_folder_after_backup(repo, capsys):
    run(repo, "new-card", "--title", "A")
    folder = config.central_root(repo)
    assert folder.exists()

    assert run(repo, "clear", "--scope", "repo", "--yes", "--json") == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["scope"] == "repo"
    assert payload["removed"]["existed"] is True
    assert payload["removed"]["folder"] == str(folder)
    assert payload["backup_path"]
    assert not folder.exists()


def test_clear_no_backup_skips_snapshot(repo, capsys):
    run(repo, "new-card", "--title", "A")
    assert run(repo, "clear", "--scope", "cards", "--yes", "--no-backup", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["backup_path"] is None


def test_clear_is_noop_when_no_board(tmp_path, capsys):
    # A repo root with NO overseer init -> no board.db.
    from tests.factories import git_init
    git_init(tmp_path)
    assert main(["--root", str(tmp_path), "clear", "--scope", "repo", "--yes", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["noop"] is True
    assert payload["backup_path"] is None


def test_clear_aborts_wipe_when_backup_fails(repo, capsys, monkeypatch):
    run(repo, "new-card", "--title", "A")
    folder = config.central_root(repo)

    from scripts import backup
    def boom(*a, **k):
        raise OSError("read-only filesystem")
    monkeypatch.setattr(backup, "backup_board", boom)

    # main() maps OSError-family/ValueError to exit 1 with "error:" on stderr.
    assert main(["--root", str(repo), "clear", "--scope", "repo", "--yes"]) == 1
    assert "error:" in capsys.readouterr().err
    assert folder.exists()  # wipe never happened
```

Note: `git_init` lives in `plugins/overseer/tests/factories.py` (used by `test_cli.py`). Confirm the import path when implementing; if it differs, run `git init` via `subprocess` in the test instead.

- [ ] **Step 2: Run to verify failure/behaviour**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest tests/test_clear.py -q`
Expected: The `repo`/`no-backup`/`noop` tests may already PASS (Task 1 implemented the logic); the backup-failure test confirms the abort. If any fail, fix `cmd_clear` (e.g. ensure `OSError` from backup propagates — `main()` catches `FileNotFoundError`/`ValueError` but NOT bare `OSError`; if the abort test shows exit 0 or an unhandled traceback, wrap the backup call to re-raise as `ValueError`:

```python
    if not args.no_backup:
        try:
            backup_path = backup.backup_board(args.root)["dest"]
        except OSError as exc:
            raise ValueError(f"backup failed, aborting clear: {exc}") from exc
```
)

- [ ] **Step 3: Apply the backup-abort fix if needed** (see Step 2 note). Re-run.

- [ ] **Step 4: Run full overseer suite to check no regressions**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/cli.py plugins/overseer/tests/test_clear.py
git commit -m "feat(overseer): clear --scope repo + no-backup/noop/backup-abort edge cases"
```

---

## Task 3: Plumb bind `host` into `create_app` + `serve.py`

**Files:**
- Modify: `plugins/overseer/dashboard/backend/app/main.py` (add `host` kw-param to `create_app`, capture as `launch_host`)
- Modify: `plugins/overseer/dashboard/serve.py` (pass `host=args.host`)
- Modify: `plugins/overseer/dashboard/backend/tests/test_serve.py` (update assertions)

**Interfaces:**
- Consumes: existing `create_app(root, *, dist_dir=None)`.
- Produces: `create_app(root, *, host: str = "127.0.0.1", dist_dir: Path | None = None)` with `launch_host` captured in the closure for Task 4's route to read.

- [ ] **Step 1: Update the failing test first**

In `plugins/overseer/dashboard/backend/tests/test_serve.py`, the existing `test_main_builds_app_from_resolved_root_and_runs_uvicorn` asserts `fake_create_app.assert_called_once_with(tmp_path.resolve())`. Change it to expect the host kwarg:

```python
    fake_create_app.assert_called_once_with(tmp_path.resolve(), host="127.0.0.1")
```

And in `test_main_passes_through_custom_host`, add an assertion that the custom host reaches `create_app` too:

```python
    fake_create_app.assert_called_once_with(tmp_path.resolve(), host="0.0.0.0")
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest tests/test_serve.py -q`
Expected: FAIL — `create_app` called without `host=`.

- [ ] **Step 3: Implement**

In `serve.py` `main()`, change the app construction:

```python
    app = create_app(root, host=args.host)
```

In `app/main.py`, change the signature and capture the host:

```python
def create_app(root: Path, *, host: str = "127.0.0.1", dist_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="overseer dashboard")
    launch_root = root
    launch_host = host
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest tests/test_serve.py -q`
Expected: PASS. (The `client` fixture calls `create_app(root)` with no host → defaults to loopback, unaffected.)

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/dashboard/backend/app/main.py plugins/overseer/dashboard/serve.py plugins/overseer/dashboard/backend/tests/test_serve.py
git commit -m "feat(overseer-dashboard): plumb bind host into create_app"
```

---

## Task 4: `POST /api/repo/clear` endpoint (delegate + loopback gate)

**Files:**
- Modify: `plugins/overseer/dashboard/backend/app/main.py` (add `ClearBody`, `_is_loopback`, the route)
- Test: `plugins/overseer/dashboard/backend/tests/test_clear_endpoint.py`

**Interfaces:**
- Consumes: `run_overseer(root, *args, json_out=True, timeout=60)`; `CliError`; `_resolve_root(launch_root, _derived_launch_root, root)`; `_mutation_error(exc)`; `launch_host` (Task 3).
- Produces: `POST /api/repo/clear` accepting `{scope, root}`, returning the JSON contract payload; `403` on non-loopback bind without opt-in; `400` on unknown scope.

- [ ] **Step 1: Write the failing tests**

Create `plugins/overseer/dashboard/backend/tests/test_clear_endpoint.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from app.cli_client import run_overseer
from app.main import create_app


def _new_card(root: Path, title: str = "A") -> None:
    run_overseer(root, "new-card", "--title", title)


def test_clear_cards_endpoint_returns_backup_path(client: TestClient, root: Path) -> None:
    _new_card(root)
    resp = client.post("/api/repo/clear", json={"scope": "cards"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"] == "cards"
    assert body["removed"]["cards"] == 1
    assert body["backup_path"]


def test_clear_unknown_scope_is_400(client: TestClient, root: Path) -> None:
    resp = client.post("/api/repo/clear", json={"scope": "everything"})
    assert resp.status_code == 400


def test_clear_is_403_on_non_loopback_without_optin(root: Path) -> None:
    remote = TestClient(create_app(root, host="0.0.0.0"))
    resp = remote.post("/api/repo/clear", json={"scope": "cards"})
    assert resp.status_code == 403


def test_clear_allowed_on_non_loopback_with_optin(root: Path, monkeypatch) -> None:
    monkeypatch.setenv("OVERSEER_DASHBOARD_ALLOW_REMOTE_DESTRUCTIVE", "1")
    remote = TestClient(create_app(root, host="0.0.0.0"))
    resp = remote.post("/api/repo/clear", json={"scope": "cards"})
    assert resp.status_code == 200
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest tests/test_clear_endpoint.py -q`
Expected: FAIL — 404 (route not registered).

- [ ] **Step 3: Implement**

In `app/main.py`, add a module-level model next to `OrderBody`/`ClaimBody` (ensure `import os` is present at the top — add it if missing):

```python
class ClearBody(BaseModel):
    scope: str = "repo"
    root: str | None = None
```

Add a module-level helper near `_mutation_error`:

```python
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", ""}


def _is_loopback(host: str) -> bool:
    return host in _LOOPBACK_HOSTS
```

Inside `create_app` (after the other `@app.post` routes, using the captured `launch_host`):

```python
    @app.post("/api/repo/clear")
    def clear_repo(body: ClearBody) -> dict[str, Any]:
        if body.scope not in ("cards", "repo"):
            raise HTTPException(status_code=400, detail=f"unknown clear scope: {body.scope!r}")
        if not _is_loopback(launch_host) and \
                os.environ.get("OVERSEER_DASHBOARD_ALLOW_REMOTE_DESTRUCTIVE") != "1":
            raise HTTPException(
                status_code=403,
                detail=("destructive clear is disabled on a non-loopback bind; relaunch with "
                        "--host 127.0.0.1 or set OVERSEER_DASHBOARD_ALLOW_REMOTE_DESTRUCTIVE=1"),
            )
        effective = _resolve_root(launch_root, _derived_launch_root, body.root)
        try:
            return run_overseer(
                effective, "clear", "--scope", body.scope, "--yes", "--json",
                json_out=True, timeout=60,
            )
        except CliError as exc:
            raise _mutation_error(exc) from exc
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest tests/test_clear_endpoint.py -q`
Expected: PASS.

- [ ] **Step 5: Run full backend suite**

Run: `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/dashboard/backend/app/main.py plugins/overseer/dashboard/backend/tests/test_clear_endpoint.py
git commit -m "feat(overseer-dashboard): POST /api/repo/clear (delegate + loopback gate)"
```

---

## Task 5: Frontend API client — `clearRepo` + `ClearResponse`

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/client.ts`
- Test: `frontend/src/api/client.test.ts` (create if absent; otherwise append)

**Interfaces:**
- Consumes: the `request<T>(method, url, body?)` wrapper in `client.ts`.
- Produces: `ClearResponse` type; `clearRepo(root: string, scope: "cards" | "repo"): Promise<ClearResponse>`.

- [ ] **Step 1: Write the failing test**

Set node PATH first for all frontend commands: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH"` and `cd plugins/overseer/dashboard/frontend`.

Create `frontend/src/api/client.test.ts`:

```ts
import { describe, it, expect, vi, afterEach } from "vitest";
import { clearRepo } from "./client";

afterEach(() => vi.restoreAllMocks());

describe("clearRepo", () => {
  it("POSTs {root, scope} to /api/repo/clear and returns the parsed body", async () => {
    const payload = { scope: "repo", backup_path: "/tmp/snap", removed: { folder: "/x", existed: true }, label: "demo", noop: false };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } }),
    );

    const res = await clearRepo("/repos/demo", "repo");

    expect(res.backup_path).toBe("/tmp/snap");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/repo/clear");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ root: "/repos/demo", scope: "repo" });
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm run test -- src/api/client.test.ts`
Expected: FAIL — `clearRepo` is not exported.

- [ ] **Step 3: Implement**

Append to `frontend/src/api/types.ts`:

```ts
export interface ClearResponse {
  scope: "cards" | "repo";
  backup_path: string | null;
  removed: Record<string, unknown>;
  label: string;
  noop: boolean;
}
```

Append to `frontend/src/api/client.ts` (import `ClearResponse` from `./types` alongside existing type imports). Note: pass `{root, scope}` in the BODY directly (do NOT use `withRoot` — the clear target is the modal's selected repo, carried explicitly):

```ts
export function clearRepo(root: string, scope: "cards" | "repo"): Promise<ClearResponse> {
  return request<ClearResponse>("POST", "/api/repo/clear", { root, scope });
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npm run test -- src/api/client.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit** (dist rebuild happens in Task 7 — no src UI change yet, but run build at the end)

```bash
git add plugins/overseer/dashboard/frontend/src/api/types.ts plugins/overseer/dashboard/frontend/src/api/client.ts plugins/overseer/dashboard/frontend/src/api/client.test.ts
git commit -m "feat(overseer-dashboard): frontend clearRepo api client"
```

---

## Task 6: `ClearDialog` two-step "dragons" modal

**Files:**
- Create: `frontend/src/components/ClearDialog.tsx`
- Test: `frontend/src/components/ClearDialog.test.tsx`
- Modify: `frontend/src/styles.css` (dialog styles — reuse `.party-overlay`/`.party-sheet` conventions)

**Interfaces:**
- Consumes: `clearRepo(root, scope)` (Task 5); `ClearResponse`.
- Produces: `ClearDialog` component:
  ```ts
  interface ClearDialogProps {
    repoLabel: string;
    repoRoot: string;
    cardCount: number;
    onClose: () => void;
    onCleared: (res: ClearResponse) => void;
  }
  ```
  Behaviour: step 1 chooses scope (`repo` default, `cards` option) and shows counts + "a recovery snapshot will be taken first"; step 2 requires typing `repoLabel` to enable "Slay it"; on success calls `onCleared(res)` then `onClose()`; on error shows an inline error and stays open.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/ClearDialog.test.tsx`. Model on `StatusMenu.test.tsx` (mock the api client, assert positive + negative-guard paths):

```tsx
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

vi.mock("../api/client", () => ({ clearRepo: vi.fn() }));
import { clearRepo } from "../api/client";
import ClearDialog from "./ClearDialog";

const CLEARED = { scope: "repo", backup_path: "/tmp/snap", removed: {}, label: "demo", noop: false };

function open() {
  const onClose = vi.fn();
  const onCleared = vi.fn();
  render(<ClearDialog repoLabel="demo" repoRoot="/repos/demo" cardCount={3} onClose={onClose} onCleared={onCleared} />);
  return { onClose, onCleared };
}

afterEach(() => vi.restoreAllMocks());

it("shows step 1 with the card count and a Press on button", () => {
  open();
  expect(screen.getByText(/Dragons be here/i)).toBeInTheDocument();
  expect(screen.getByText(/3/)).toBeInTheDocument();
});

it("the final Slay it button is disabled until the repo label is typed exactly", () => {
  open();
  fireEvent.click(screen.getByRole("button", { name: /press on/i }));
  const slay = screen.getByRole("button", { name: /slay it/i });
  expect(slay).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/type the repo label/i), { target: { value: "wrong" } });
  expect(slay).toBeDisabled();
  fireEvent.change(screen.getByLabelText(/type the repo label/i), { target: { value: "demo" } });
  expect(slay).toBeEnabled();
});

it("Slay it calls clearRepo with the selected scope then onCleared", async () => {
  vi.mocked(clearRepo).mockResolvedValue(CLEARED as never);
  const { onCleared } = open();
  fireEvent.click(screen.getByRole("button", { name: /press on/i }));
  fireEvent.change(screen.getByLabelText(/type the repo label/i), { target: { value: "demo" } });
  fireEvent.click(screen.getByRole("button", { name: /slay it/i }));
  await waitFor(() => expect(clearRepo).toHaveBeenCalledWith("/repos/demo", "repo"));
  await waitFor(() => expect(onCleared).toHaveBeenCalledWith(CLEARED));
});

it("Turn back closes without calling clearRepo", () => {
  const { onClose } = open();
  fireEvent.click(screen.getByRole("button", { name: /turn back/i }));
  expect(onClose).toHaveBeenCalled();
  expect(clearRepo).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npm run test -- src/components/ClearDialog.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `ClearDialog.tsx`**

Follow `PartyOverlay.tsx`'s backdrop conventions (outer `.party-overlay` with `onClick={onClose}`, inner `.party-sheet` `role="dialog"` with `stopPropagation`, Escape-to-close). Use a new class hook `clear-dialog` for specific styling if wanted.

```tsx
import { useEffect, useState } from "react";
import { clearRepo } from "../api/client";
import type { ClearResponse } from "../api/types";

interface ClearDialogProps {
  repoLabel: string;
  repoRoot: string;
  cardCount: number;
  onClose: () => void;
  onCleared: (res: ClearResponse) => void;
}

export default function ClearDialog({ repoLabel, repoRoot, cardCount, onClose, onCleared }: ClearDialogProps) {
  const [step, setStep] = useState<1 | 2>(1);
  const [scope, setScope] = useState<"cards" | "repo">("repo");
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function slay() {
    setBusy(true);
    setError(null);
    try {
      const res = await clearRepo(repoRoot, scope);
      onCleared(res);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  const scopeSummary =
    scope === "repo"
      ? `everything for “${repoLabel}” (board + sprints + usage + knowledge)`
      : `all ${cardCount} card(s) for “${repoLabel}” (identity kept)`;

  return (
    <div className="party-overlay" onClick={onClose}>
      <div className="party-sheet clear-dialog" role="dialog" aria-label="Clear repository data" onClick={(e) => e.stopPropagation()}>
        <button type="button" className="party-close" aria-label="Close" onClick={onClose}>×</button>
        {step === 1 ? (
          <>
            <h2>🐉 Dragons be here — are you sure you wish to proceed?</h2>
            <fieldset className="clear-scope">
              <legend>What to clear</legend>
              <label><input type="radio" name="scope" checked={scope === "repo"} onChange={() => setScope("repo")} /> Everything (full repo folder)</label>
              <label><input type="radio" name="scope" checked={scope === "cards"} onChange={() => setScope("cards")} /> Cards only</label>
            </fieldset>
            <p>This will remove {scopeSummary}.</p>
            <p>A recovery snapshot will be taken first — undo with <code>overseer restore</code>.</p>
            <div className="clear-actions">
              <button type="button" onClick={onClose}>Turn back</button>
              <button type="button" className="danger" onClick={() => setStep(2)}>Press on</button>
            </div>
          </>
        ) : (
          <>
            <h2>Very. Big. Dragons!</h2>
            <p>To confirm, type the repo label <strong>{repoLabel}</strong> below.</p>
            <label>
              Type the repo label
              <input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
            </label>
            {error && <p className="clear-error" role="alert">{error}</p>}
            <div className="clear-actions">
              <button type="button" onClick={() => setStep(1)} disabled={busy}>Back</button>
              <button type="button" className="danger" disabled={typed !== repoLabel || busy} onClick={slay}>
                {busy ? "Slaying…" : "Slay it"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

Add minimal styles to `frontend/src/styles.css` (reuse existing `.party-overlay`/`.party-sheet`; add `.clear-dialog .danger { background:#b00020; color:#fff; }`, `.clear-actions { display:flex; gap:.5rem; justify-content:flex-end; }`, `.clear-error { color:#b00020; }`, `.clear-scope label { display:block; }`).

- [ ] **Step 4: Run to verify it passes**

Run: `npm run test -- src/components/ClearDialog.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/components/ClearDialog.tsx plugins/overseer/dashboard/frontend/src/components/ClearDialog.test.tsx plugins/overseer/dashboard/frontend/src/styles.css
git commit -m "feat(overseer-dashboard): ClearDialog two-step dragons modal"
```

---

## Task 7: Wire Clear control into TopBar + success toast + dist rebuild

**Files:**
- Modify: `frontend/src/components/TopBar.tsx` (Clear button beside `RepoSelector`)
- Modify: `frontend/src/App.tsx` (own `clearOpen` + success-toast state; render `ClearDialog`; refresh board+repos after clear)
- Modify: `frontend/src/styles.css` (success toast — mirror `.board-toast`, success variant)
- Rebuild + commit: `frontend/dist/`

**Interfaces:**
- Consumes: `ClearDialog` (Task 6); `selectedRepo` (`repos.find(r => r.root === activeRoot)`), `board?.cards`, the repo-list refresh (`useRepos`) and board refresh (`useBoard`) already in `App.tsx`.
- Produces: a visible Clear button; a success toast showing `res.backup_path` with restore hint; board+repo refresh after a clear.

- [ ] **Step 1: Add a `onClear` callback prop to TopBar and render the button**

In `TopBar.tsx`, add `onClear?: () => void` to its props and render a button beside `<RepoSelector .../>` (line ~143):

```tsx
<RepoSelector repos={repos} activeRoot={activeRoot} onSelect={onSelectRepo} />
{onClear && (
  <button type="button" className="topbar-clear danger" onClick={onClear} title="Clear this repo's data">
    Clear…
  </button>
)}
```

- [ ] **Step 2: Own dialog + toast state in App.tsx**

In `App.tsx`, add state and handlers, pass `onClear` to `TopBar`, and render the dialog + toast:

```tsx
const [clearOpen, setClearOpen] = useState(false);
const [clearToast, setClearToast] = useState<string | null>(null);
const selectedRepo = repos.find((r) => r.root === activeRoot) ?? null;

// pass to TopBar: onClear={selectedRepo ? () => setClearOpen(true) : undefined}

{clearOpen && selectedRepo && (
  <ClearDialog
    repoLabel={selectedRepo.label}
    repoRoot={selectedRepo.root}
    cardCount={board?.cards.length ?? 0}
    onClose={() => setClearOpen(false)}
    onCleared={(res) => {
      setClearToast(
        res.noop
          ? `Nothing to clear for ${res.label}.`
          : `Cleared ${res.label}. Recovery snapshot: ${res.backup_path ?? "(none)"} — restore with \`overseer restore\`.`,
      );
      refreshRepos();   // useRepos refresh fn — confirm its exact name when implementing
      refreshBoard();   // useBoard refresh fn — confirm its exact name when implementing
    }}
  />
)}
{clearToast && (
  <div className="board-toast board-toast--success" role="status">
    {clearToast}
    <button type="button" className="board-toast__dismiss" onClick={() => setClearToast(null)}>dismiss</button>
  </div>
)}
```

Note: confirm the actual refresh function names exported by `useRepos`/`useBoard` (the explorer identified `useBoard` exposes board + `mutate`; there is a reload mechanism — inspect and use the real names, e.g. a `reload()`/`refresh()` or re-invoking the hook's fetch). If no imperative refresh exists, trigger it the same way an existing action does (e.g. `mutate`) or add a lightweight `reload()` to the hook.

- [ ] **Step 3: Add success-toast style**

In `frontend/src/styles.css`, near `.board-toast` (~line 707) add a success variant:

```css
.board-toast--success { background: #1b5e20; }
```

- [ ] **Step 4: Run the full frontend test suite**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npm run test`
Expected: all pass (including existing TopBar/App tests — update any snapshot/assertion that the new button breaks).

- [ ] **Step 5: Rebuild the committed dist**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npm run build`
Then verify freshness gate: `cd ../backend && ../../../../.venv/bin/python -m pytest tests/test_dist_freshness.py -q`
Expected: PASS (`dist/.srchash` regenerated).

- [ ] **Step 6: Commit (src + dist together)**

```bash
git add plugins/overseer/dashboard/frontend/src plugins/overseer/dashboard/frontend/dist
git commit -m "feat(overseer-dashboard): Clear control in TopBar + success toast + dist"
```

---

## Task 8: Version bumps + docs

**Files:**
- Modify: overseer plugin manifest version (locate: `plugins/overseer/.claude-plugin/plugin.json` or `plugin.json` — grep for the current version string) + marketplace manifest.
- Modify: dashboard README (`plugins/overseer/dashboard/frontend/README.md` and/or backend README) — document the Clear action + the `OVERSEER_DASHBOARD_ALLOW_REMOTE_DESTRUCTIVE` opt-in + `overseer clear` verb.

**Interfaces:** none (metadata + docs).

- [ ] **Step 1: Locate the version files**

Run: `grep -rn '"version"' plugins/overseer/.claude-plugin plugins/overseer/plugin.json .claude-plugin 2>/dev/null` (adjust to what exists) and find the marketplace manifest (grep for the last marketplace version, e.g. `1.1.2`).

- [ ] **Step 2: Bump versions** — minor bump for overseer (new command + endpoint + UI); patch/minor for marketplace, matching the repo's established scheme (see recent commits like `v0.12.1` / `marketplace v1.1.2`).

- [ ] **Step 3: Document** — add a short "Clear data" section to the dashboard docs: what the two scopes do, that a backup is always taken first (restore with `overseer restore`), and the loopback gate + opt-in env for LAN binds. Document the `overseer clear` CLI verb in the CLI's help/README.

- [ ] **Step 4: Full verification sweep**

```bash
cd plugins/overseer && ../../.venv/bin/python -m pytest -q
cd dashboard/backend && ../../../../.venv/bin/python -m pytest -q
export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd ../frontend && npm run test
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(overseer): bump version + document clear-data action (WF-052)"
```

---

## Self-Review notes (author)

- **Spec coverage:** A1 CLI verb → Tasks 1–2; A2 endpoint → Task 4; A3 frontend two-step gate → Tasks 6–7; A4 loopback gate → Tasks 3–4; A5 edge cases (no board / backup-failure / refresh) → Tasks 2 & 7. `all` scope deliberately dropped per user decision. Cards = hard delete (Global Constraints). Typed confirm = repo label (Task 6).
- **Type consistency:** JSON contract fixed once in Global Constraints; `ClearResponse` (TS) and the CLI payload match field-for-field; `clearRepo(root, scope)` signature identical in Tasks 5–7.
- **Open discovery items flagged inline (not placeholders):** exact `useRepos`/`useBoard` refresh fn names (Task 7 Step 2), `git_init` import path (Task 2), and version-file locations (Task 8) — each has an explicit "confirm/locate" instruction because they depend on code the implementer will have open.
