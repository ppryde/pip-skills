# Overseer dashboard mutations + rudimentary auth (PR3)

**Date:** 2026-08-10
**Epic:** WF-055 (overseer parity for ledger-poc 377-card migration)
**Cards:** F5 create (WF-062) · F6 edit title/body (WF-063) · F7 delete/abandon (WF-064) · deferred F1 label-editor control
**Branch:** `feat/overseer-dashboard-mutations` (base `ea61f28`)

## Purpose

The dashboard can read the board and perform status/priority/label/parent/order
mutations, but cannot **create**, **edit the title/body of**, or **abandon** a
card from the UI — three parity gaps against the CLI. This PR closes them, folds
in the label-editor control deferred from F1, and adds a **rudimentary token
gate** so the mutation surface is not wide-open when the server is bound beyond
loopback.

## Scope

In scope:
- CLI: `set-field --title` / `--body` (the only new CLI surface).
- Backend: `POST /api/card` (create), `POST /api/card/{id}` (edit title/body),
  abandon via the existing `POST /api/card/{id}/move {status: "abandoned"}`
  (see Decision #3 — no new endpoint), and a token gate over all mutating
  routes.
- Frontend: create control, drawer title/body edit, drawer abandon (with
  confirm), drawer label editor, and client-side token handling.

Out of scope (later bundles): search/filter (PR4); links, pull-children, colour
registry, ledger scale, archived-parent epics (PR5). No hard-delete verb —
`abandon` is the reversible removal (decision below).

## Decisions (approved)

1. **Soft-delete only.** F7 uses the existing `abandon` verb (reversible archive,
   `_close` → `db.archive_card`). No new irreversible hard-delete primitive.
2. **Token-gate keyed on token presence, not per-request client IP.** When no
   token is in effect (default: loopback bind, no env var) mutations are open —
   current behaviour and every existing test preserved. The moment a token
   exists (non-loopback bind, or opt-in via env) *all* clients, loopback
   included, must present it. Simpler and coherent; does not leak trust to any
   local process.
3. **Abandon reuses the existing `POST /api/card/{id}/move {status:
   "abandoned"}` path — no dedicated `/abandon` endpoint.** The original plan
   below called for a standalone endpoint mirroring `/park`/`/unpark`; during
   implementation that was dropped as needless duplication — `/move` already
   dispatches `status: "abandoned"` to the `abandon` verb (see
   `_MOVE_STATUS_VERBS` in `dashboard/backend/app/main.py`, exercised by
   `test_move_status_dispatch_parked_and_abandoned`), so a second endpoint
   would just be two request paths to the same effect. DRYer; kept the
   frontend to one abandon call site (`move(id, {status: "abandoned"})`, no
   separate `client.abandonCard`).

## Architecture

Three layers, mirroring the proven F1 split. The backend remains a pure CLI
client (`app.cli_client`) — it never imports overseer internals.

### Layer A — CLI core (`scripts/cli.py`, `cmd_set_field`)

Extend the `set-field` parser and command with two flags:

- `--title`: when given, empty string is **rejected** (`error: title cannot be
  empty`, exit 1) — title is required and non-nullable. Non-empty sets
  `card.title`.
- `--body`: when given, sets `card.body` to the value verbatim, including `""`
  (clears the body) — matching how `--repo`/`--parent` accept empty to clear.

Both follow the existing `if args.X is not None:` guard style so an omitted flag
is a no-op. `card.updated` already bumps at the end of `cmd_set_field`.

`new-card` (create) and `abandon` (soft-delete) are unchanged — they already
exist and do exactly what F5/F7 need.

### Layer B — backend API (`dashboard/backend/app/main.py`)

New request models:

```python
class CreateBody(BaseModel):
    title: str
    complexity: str | None = None
    labels: list[str] = []
    goal: str | None = None

class EditBody(BaseModel):
    title: str | None = None
    body: str | None = None
```

New endpoints (all token-gated — see Layer B auth):

- `POST /api/card` (create):
  - `title` required and non-empty → else 400 before shelling.
  - Shells `new-card --title <t>` plus `--complexity/--labels/--goal` when given.
  - `new-card` prints the minted id to stdout; capture it (`json_out=False`,
    strip) and return `{"card_id": <id>, **_board_response(effective)}`.
  - Duplicate id (only possible via jira/linear, not exposed here) → `_mutation_error`.
- `POST /api/card/{id}` (edit title/body):
  - `EditBody` with **at least one** of `title`/`body` set → else 400
    (`"title or body required"`).
  - `title` present but empty → 400 (`"title cannot be empty"`), before shelling.
  - Shells `set-field {id}` with `--title`/`--body` for whichever were provided.
- Abandon: no new route. The existing `POST /api/card/{id}/move` already
  dispatches `{"status": "abandoned"}` to the `abandon` verb via
  `_MOVE_STATUS_VERBS` (see Decision #3) — shells `abandon {id}`, returns
  `_board_response`. Confirm is client-side.

Create and edit reuse the existing `check_id`, `_resolve_root`, `_mutate`, and
`_mutation_error` machinery — same as abandon's pre-existing `/move` path.

**Auth gate.** `create_app(root, *, host="127.0.0.1", dist_dir=None,
token: str | None = None)` gains `token`. A FastAPI dependency —
`require_token` — is attached to **every mutating route** (the new three plus
all existing POSTs: order, priority, labels, parent, depends, park, unpark,
claim, unclaim, move, config/threshold, repo/clear):

- `token is None` → dependency is a no-op (gate inactive). Default path;
  existing tests and local use unchanged.
- `token` set → the request must carry header `X-Overseer-Token` equal to
  `token`; absent or mismatched → **401** (`"missing or invalid dashboard
  token"`). Fail closed.

The gate is a `Depends(...)` that reads the request header and compares with
`hmac.compare_digest` (constant-time). Reads (`GET /api/board`,
`/api/repos`, `/api/sessions`, `/api/card/{id}`) are **not** gated — anonymous
viewing stays allowed.

The existing loopback gate on `repo/clear`
(`OVERSEER_DASHBOARD_ALLOW_REMOTE_DESTRUCTIVE`) is retained and stacks with the
token gate — clear remains the most-guarded verb.

**Serve entrypoint** (wherever `create_app` is invoked for `serve`): resolve the
token as `os.environ.get("OVERSEER_DASHBOARD_TOKEN")` → else, when the bind host
is **non-loopback**, auto-generate `secrets.token_urlsafe(24)` and print it in
the serve banner (`dashboard token: <token>`). Pure-loopback default with no env
var → `token=None` → no friction. `create_app` itself never reads the env — the
token is passed in — so the gate is trivially unit-testable.

**Documented non-goal:** this does not defend a token-free loopback bind against
DNS-rebinding / CSRF from a malicious local web page. That is the pre-existing
posture; it is stated plainly here rather than implied away.

### Layer C — frontend

- **Create control** — a "＋ new card" affordance (top bar or lane header) opens
  a minimal form: title (required), complexity (optional select), labels
  (optional), goal (optional). Submit → `client.createCard(...)` →
  `POST /api/card` → board refreshes and (nice-to-have) the new card is focused.
- **Edit control** — in `CardDetailDrawer`, title and body become editable
  (inline or an edit toggle) with an explicit Save → `client.editCard(id,
  {title?, body?})` → `POST /api/card/{id}`.
- **Abandon control** — in the drawer, a destructive action behind a confirm
  ("Abandon this card? It will be archived.") → the existing `client.move(id,
  {status: "abandoned"})` → `POST /api/card/{id}/move`. No dedicated
  `abandonCard` client function or endpoint (Decision #3) — DRYer to route
  through the move client that already exists for park/unpark/etc.
- **Label editor (F1 fold-in)** — in the drawer, an editable labels control
  wired to the *existing* `client.setLabels(id, labels)` →
  `POST /api/card/{id}/labels`. No backend change; this is the deferred F1
  control finally given a UI.
- **Token handling** — the API client sends `X-Overseer-Token` from
  `localStorage` on every mutation when present. On a mutation `401`, prompt once
  for the token, store it in `localStorage`, and retry the request. Default local
  use (gate inactive) never triggers a prompt.
- **`useBoard.mutate` opt-in `{ rethrow: true }`** (user-adjudicated addition,
  not in the original plan) — `mutate`'s default behaviour swallows a
  rejection into the shared board-level error banner and still resolves,
  which is wrong for the new create/edit forms: a failed create or edit needs
  to surface INLINE, next to the form, with the user's input still intact,
  not just as a global banner while the dialog/drawer silently closes and
  drops the draft. Callers opt in per call — `NewCardDialog.submit()` and
  `CardDetailDrawer.saveEdit()` both pass `{ rethrow: true }` and own a local
  `try/catch` + inline error state; every other mutation (priority, labels,
  move, claim, …) keeps the default swallow-into-global-banner behaviour
  unchanged.

## Data flow

Browser → backend endpoint → `require_token` dependency → `_resolve_root`
(allowlist) → `check_id` → `run_overseer(<verb>...)` subprocess → CLI writes via
the single-writer store → `_board_response` re-reads and returns the refreshed
board. Unchanged from every existing mutation except the added dependency and
the create-path id capture.

## Error handling

- Empty/missing title (create and edit) → 400 before any subprocess runs.
- Edit with neither title nor body → 400.
- Bad/glob id → `check_id` → 400 (existing).
- Unknown root → 400 (existing `_resolve_root`).
- CLI failure / timeout → `_mutation_error` → 400 / 504 (existing).
- Missing/invalid token on a gated mutation → 401.
- Frontend: 401 → token prompt + retry; other errors surface as today.

## Testing

- **CLI** (`tests/overseer/test_cli.py`): `set-field --title` sets title;
  `--title ""` → exit 1 non-empty guard; `--body` sets body; `--body ""` clears;
  omitted flags are no-ops.
- **Backend** (`dashboard/backend/tests/test_mutations.py`):
  - create: happy (returns `card_id` + board, card present), missing/empty title
    → 400.
  - edit: title only, body only, both, empty title → 400, neither → 400.
  - abandon: card moves to archived/abandoned; board reflects it.
  - **gate:** app built with `token=None` → mutation open (existing tests hold);
    app built with a token → mutation with no header → 401, wrong header → 401,
    correct header → 200; a **read** endpoint stays 200 without a token.
- **Frontend** (vitest): create form submit calls client + refreshes; drawer
  title/body edit + save; abandon confirm gating the call; label editor calls
  `setLabels`; token flow — mutation `401` triggers prompt, stores token, retries
  with header.
- **Dist freshness**: rebuild `frontend/dist` via the nvm node path
  (`PATH=$HOME/.nvm/versions/node/v22.22.1/bin ...`) and confirm
  `test_dist_freshness` passes.

## Review protocol

Per the work-stream directive: subagent-driven implementation (TDD); then DUAL
blind review — one Opus/Fable + one Sonnet, independent — adjudicated by the
user; scoped re-review of fixes; then PR. Log vigil/handover/session-limit use in
the worklog.
