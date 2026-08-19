# Overseer Remote Client — HTTP board access from a dev container

**Date:** 2026-08-19
**Status:** Design approved, pending implementation plan
**Topic:** Let the overseer CLI (and its hooks) running inside a Docker dev
container read and write a `board.db` that lives on the host machine, over HTTP.

---

## 1. Problem & context

Overseer's card store is a per-repo SQLite `board.db` under
`$CLAUDE_CONFIG_DIR/overseer/<repo-label>/` on the host. Every writer — the
CLI, its hooks, the dashboard backend — reaches it by opening that file
directly on the local filesystem (`scripts/db.py::connect`).

That breaks the moment the work moves into a **Docker dev container**: the
container cannot see the host's `board.db`, and mounting the SQLite file over a
bind-mount for concurrent writers is unsafe. The user's actual goal, stated
plainly: **serve the board on the host, and let overseer inside the dev
container send updates to it.**

The writer inside the container is the **overseer CLI and its hooks**
(`claim`, `set-stage`, `checklist-sync-hook`, `claim-stop-hook`, the
orchestration driver) — *not* a Claude agent calling MCP tools. That single
fact sets the whole shape below: the deliverable is a CLI `--remote` mode plus
a host-side HTTP service, and **not** an MCP server.

### What already exists (do not rebuild)

The dashboard backend (`backend/app/main.py`) is *already* an HTTP API over the
board: FastAPI, pydantic bodies for every mutation, ~20 `/api/*` routes, and a
token gate (`require_token`, header `X-Overseer-Token`, constant-time compare,
inert when no token is set). It never touches `board.db` directly — it
subprocesses the CLI via `backend/app/cli_client.py`, preserving overseer's
single-writer invariant. The token can already auto-generate on a non-loopback
bind (`serve.py::resolve_token`).

So the server-side HTTP surface is largely built; it is just coupled to the
dashboard app (which also serves the frontend `dist/`). This design reuses that
surface and adds the missing container→host mechanism.

## 2. Goals & non-goals

### Goals
- `overseer --remote <url> <verb> [args]` inside the container runs the verb
  against the host's board and returns the same stdout/stderr/exit code as a
  local run.
- All ~45 verbs **and** the 3 stdin-reading hooks work remotely, with no
  per-verb plumbing.
- The host's real `cli.py` remains the **only** process that touches
  `board.db` and `.workflow/` (single-writer preserved).
- A standalone host service, decoupled from the dashboard's `dist/`-serving
  app, that also answers the existing `/api/*` REST reads for curl/scripts.
- Token-gated, reachable from the container (`host.docker.internal`).

### Non-goals
- **No MCP / FastMCP.** The writer is the CLI, not an agent calling tools;
  an MCP surface is off the critical path and is explicitly dropped (YAGNI).
  If ad-hoc agent tool access is ever wanted, `FastMCP.from_fastapi()` over the
  shared router is a cheap later add — but not now.
- No interactive verbs over the wire (`clear` prompts): remote callers pass
  `--yes`, exactly as orchestration already does.
- No streaming; board operations are small request/response exchanges.
- File-based state (sprints/usage/knowledge under `.workflow/`) is not given
  its own transport — it rides the same `/api/exec` passthrough for free,
  executing against host state.

## 3. Architecture

```
┌─ HOST machine ────────────────────────┐         ┌─ DEV CONTAINER ──────────────┐
│  board.db  (source of truth)          │         │  overseer CLI + hooks        │
│  overseer CLI ── local db.py ──┐      │         │  overseer --remote URL <verb>│
│                                │      │  HTTP   │        │                     │
│  board_service.py (FastAPI)    │      │◄────────┤        ▼                     │
│    POST /api/exec ──subprocess─┘      │  token  │  scripts/remote.py (httpx)   │
│    /api/* shared router (reads)       │         │  host.docker.internal:PORT   │
│    binds 0.0.0.0 + X-Overseer-Token   │         │                              │
└───────────────────────────────────────┘         └──────────────────────────────┘
```

The load-bearing mechanism is a single token-gated **`POST /api/exec`** on the
host: `--remote` forwards the whole argv + stdin, the host runs the real
`cli.py`, and stdout/stderr/exit code are relayed back. This covers every verb
and hook with zero per-verb work, and keeps the host CLI as the sole writer.

### Why passthrough, not per-verb REST
- **Total coverage for free** — all verbs, all 3 hooks (via forwarded stdin),
  and file-based state, with nothing to maintain as verbs are added.
- **Single-writer preserved** — identical trust model to the dashboard's
  existing `cli_client`, which already subprocesses `cli.py` per endpoint;
  `/api/exec` just generalises it to any verb.
- **Root mapping solved** — the container's `--root /workspace/...` path does
  not exist on the host, so the service is pinned to the host repo root and
  strips/replaces the incoming `--root`. The container never reasons about host
  paths.

The trade-off accepted: `/api/exec` is RPC-shaped, not a RESTful resource. It
is powerful, so it is token-gated and runs a **fixed** binary (`cli.py`) with an
argv **list** (never a shell string), and lives **only** on `board_service`,
never on the dashboard.

## 4. Components

| File | Change | Purpose |
|---|---|---|
| `backend/app/board_api.py` | **NEW** | `build_board_router(...)` → an `APIRouter` holding the existing `/api/*` read+mutation routes and their pydantic models, extracted from `main.py`. One source of truth for the REST surface. |
| `backend/app/main.py` | **MODIFY** | Dashboard `create_app` mounts `build_board_router(...)` instead of defining routes inline. Behaviour identical; existing backend tests must stay green (regression guard). |
| `backend/app/board_service.py` | **NEW** entrypoint | Standalone FastAPI app: mounts the shared router **and** adds `POST /api/exec`. Token-gated, binds `0.0.0.0`, pins `--root` to the host repo, no `dist/` serving. CLI args `--root`/`--host`/`--port`. |
| `scripts/remote.py` | **NEW** | Thin `httpx` client: `exec_remote(url, token, argv, stdin) -> ExecResult(stdout, stderr, returncode)`. Sends `X-Overseer-Token`. |
| `scripts/cli.py` | **MODIFY** | New global `--remote URL` (env `OVERSEER_REMOTE`), token from `OVERSEER_REMOTE_TOKEN`. In `main()`, if remote is set, short-circuit before local dispatch: read stdin, forward argv (minus `--remote*`) to `remote.exec_remote`, print returned streams, return returned exit code. Otherwise unchanged. |

### The router extraction (the delicate part)
`main.py`'s routes are closures over `launch_root`, `_derived_launch_root`,
`require_token`, and helpers (`_mutate`, `_board_response`, `_resolve_root`,
`_mutation_error`). `build_board_router` must take these as parameters (or a
small context object) so both `create_app` and `board_service` wire identical
behaviour. Success criterion: the existing dashboard-backend test suite passes
unchanged after the extraction.

`/api/exec` is **not** part of the shared router — the dashboard UI has no
business offering arbitrary CLI exec. It is defined on `board_service` only.

## 5. Endpoint: `POST /api/exec`

Request (pydantic `ExecRequest`):
```json
{ "argv": ["set-stage", "WF-1", "done"], "stdin": null }
```
Response (pydantic `ExecResult`):
```json
{ "stdout": "...", "stderr": "", "returncode": 0 }
```
- `require_token` gates it (same `X-Overseer-Token` dependency as mutations).
- The service runs `[sys.executable, cli.py, "--root", <pinned host root>, *argv]`
  with `input=stdin`, `capture_output=True`, a timeout, and **no shell**.
- Any `--root`/`--remote` present in the incoming `argv` is stripped before the
  pinned host root is injected (a container root path is meaningless on the
  host, and remote-inside-remote must not recurse).
- The endpoint returns HTTP 200 with the CLI's own `returncode` in the body
  (a non-zero CLI exit is a normal result, not an HTTP error); transport/spawn
  failures map to 5xx.

## 6. Data flow (a hook write)

1. Container: `claim-stop-hook` fires; overseer runs with `OVERSEER_REMOTE` set,
   hook JSON on stdin.
2. `cli.main()` sees `--remote`/env, reads stdin, calls
   `remote.exec_remote(url, token, ["claim-stop-hook"], stdin_bytes)`.
3. Host `board_service` `/api/exec` validates the token, runs
   `cli.py --root <host root> claim-stop-hook` with the stdin piped in.
4. Host CLI mutates `board.db` locally, prints, exits (say) 0.
5. Response `{stdout, stderr, returncode:0}` → container prints the streams and
   `main()` returns 0, so the hook behaves exactly as a local hook would.

## 7. Auth & Docker networking

- **Token** — reuse the `require_token` dependency and the *logic* of
  `serve.py::resolve_token`, generalised to a single dedicated env var,
  **`OVERSEER_REMOTE_TOKEN`**: if set it wins; else the service auto-generates a
  token on a non-loopback bind and prints it in its banner; a pure-loopback bind
  with no env var stays token-free. Both sides read the same
  `OVERSEER_REMOTE_TOKEN` (service = the expected value, client = the value to
  send as `X-Overseer-Token`) — symmetric and unambiguous. `resolve_token`
  itself is either parameterised to accept the env-var name or a thin sibling is
  added; the plan decides which, but the observable behaviour is as above.
- **Reachability** — host service binds `0.0.0.0`; the container reaches it at
  `host.docker.internal:PORT` (Docker Desktop on macOS/Windows; on Linux add
  `--add-host=host.docker.internal:host-gateway`). Container config:
  `OVERSEER_REMOTE=http://host.docker.internal:PORT` plus the token. Documented
  in the service README.

## 8. Error handling & edge cases

- **Exit codes relayed faithfully** — hooks depend on them (`claim-stop-hook`
  etc.); the body's `returncode` becomes `main()`'s return value.
- **Hooks / stdin** — carried in `ExecRequest.stdin`, fed to the host `cli.py`.
- **Interactive verbs** — unsupported remotely; callers pass `--yes` (already
  standard for orchestration). Documented, not enforced.
- **Timeouts** — client and server timeouts (mirror `cli_client`'s default);
  a timeout maps to a clear error + non-zero exit, never a silent hang.
- **Transport failure** — unreachable host / bad token surfaces a clear stderr
  message and a non-zero exit, distinguishable from a CLI-level failure.
- **Security** — fixed binary, argv list (no shell), token-gated, exec endpoint
  absent from the dashboard. Same trust model as today's `cli_client`.

## 9. Testing

All tests pin `CLAUDE_CONFIG_DIR`/`OVERSEER_DB`/`OVERSEER_CENTRAL` into
`tmp_path` per the repo's test-isolation rule — no test may touch real
`~/.claude*` state.

- **Router extraction** — the existing dashboard-backend suite passes unchanged
  (the regression guard); move/retarget tests only as needed.
- **`board_service` / `/api/exec`** — runs a real verb end-to-end and returns
  its stdout+exit; token gate rejects a missing/wrong token (401); the incoming
  `--root` is stripped and the pinned host root is used; a non-zero CLI exit is
  returned as body `returncode`, HTTP 200.
- **`remote.py`** — client posts the right shape and header; parses
  `ExecResult`; against a live `TestClient` for a round-trip.
- **`cli --remote` dispatch** — `main(["--remote", url, "board"])` forwards the
  argv, relays streams + exit code, and does **not** open a local `board.db`.

## 10. Out of scope / follow-ups

- MCP surface via `FastMCP.from_fastapi()` (only if ad-hoc agent access is later
  wanted).
- A `bringup.sh`-style quiet launcher for `board_service` (mirror the
  dashboard's existing launcher).
- Any change to how the dashboard itself is served.
