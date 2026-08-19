# Overseer remote token — auto-share through the mounted repo

**Date:** 2026-08-19
**Status:** Design approved, pending implementation plan
**Topic:** Remove the manual copy of `OVERSEER_REMOTE_TOKEN` from host to dev
container by sharing it as a gitignored file in the mounted repo.

---

## 1. Problem & context

The remote board client (PR #58) protects the host's token-gated `/api/exec`
with `OVERSEER_REMOTE_TOKEN`: the host launcher (`serve_board_api.py`)
auto-generates a token on a non-loopback bind and prints it; the operator must
copy it into the container's `OVERSEER_REMOTE_TOKEN`. That hand-off is the only
manual step in the container→host flow, and the token regenerates every launch,
so the copy must be redone after each restart.

The dev container **mounts the host repo** (confirmed). So the host and
container can see the same file — we can distribute the token through the
filesystem instead of by hand, without weakening the token's protection.

## 2. Goals & non-goals

### Goals
- Zero manual token copying: the operator sets only
  `OVERSEER_REMOTE=http://host.docker.internal:PORT` in the container.
- The token is **stable across host restarts** (persisted, not regenerated).
- `OVERSEER_REMOTE_TOKEN` env still works and takes precedence (explicit
  override, backward compatible).
- No change to the security posture: the token still gates `/api/exec`, the
  LAN guard still runs first.

### Non-goals
- No change to the LAN guard, `/api/exec`, or the token *check* — only how the
  token is *distributed*.
- No auto-discovery of the URL (the host can't know the container's view of its
  address, e.g. `host.docker.internal`); `OVERSEER_REMOTE` stays an env var.
- Loopback binds stay tokenless — no token, no file written.

## 3. Design

A gitignored token file at **`<repo>/.overseer/remote-token`** is the shared
channel. The host writes it; the container reads it via the mount.

### Token resolution (both sides: env → file → default)
- **Host** (`serve_board_api.py::resolve_remote_token(host, root)`):
  `OVERSEER_REMOTE_TOKEN` env → (loopback bind → `None`) → existing
  `<root>/.overseer/remote-token` → else generate `secrets.token_urlsafe(24)`
  **and persist it** to that file (mode `0600`). Persisting makes the token
  stable across restarts, so a long-running container never goes stale.
- **Container** (`cli.py::_run_remote(url, raw_argv, root)`):
  `OVERSEER_REMOTE_TOKEN` env → `<root>/.overseer/remote-token` → `None`.
  Because the repo is mounted, this is the exact file the host wrote.

### Shared location helper (single source of truth)
A stdlib-only module `plugins/overseer/scripts/remote_token.py` owns the path
and the read/write, so host and container never disagree:
- `remote_token_path(root) -> Path` = `Path(root) / ".overseer" / "remote-token"`.
- `read_remote_token(root) -> str | None` — returns the stripped token, or
  `None` if the file is missing/empty/unreadable (never raises).
- `write_remote_token(root, token) -> Path` — creates `.overseer/` if needed,
  writes the token, `chmod 0600`.

It is stdlib-only (no httpx) so reading a token never drags in the HTTP client;
`cli._run_remote` imports it alongside the (httpx-carrying) `scripts.remote`,
and `serve_board_api` imports it to persist.

### Data flow (no copy)
1. Host: `serve_board_api.py --root <repo>` on a non-loopback bind →
   `resolve_remote_token` finds no env and no file → generates a token, writes
   `<repo>/.overseer/remote-token` (0600), prints the path.
2. Container: operator sets only `OVERSEER_REMOTE=http://host.docker.internal:PORT`.
3. Container: `overseer --remote ... <verb>` → `_run_remote` finds no env token
   → reads `<repo>/.overseer/remote-token` (the mounted file) → sends it as
   `X-Overseer-Token`. Authenticated, nothing copied.
4. Host restart: the file already exists → the same token is reused → the
   container keeps working with no change.

## 4. Components

| File | Change | Purpose |
|---|---|---|
| `scripts/remote_token.py` | **NEW** (stdlib) | `remote_token_path` / `read_remote_token` / `write_remote_token` — the shared location + IO. |
| `serve_board_api.py` | **MODIFY** | `resolve_remote_token(host, root)`: env → loopback None → existing file → generate+persist(0600). `main()` passes `root`, prints the token-file path. |
| `scripts/cli.py` | **MODIFY** | `_run_remote(url, raw_argv, root)`: token = env → `read_remote_token(root)` → None. `main()` passes `args.root`. |
| `.gitignore` | **MODIFY** | Add `.overseer/remote-token`. |

## 5. Security

- The secret now lives in a `0600`, **gitignored** file in the repo —
  comparable exposure to printing it to the operator's terminal, readable by
  exactly the mounted container user that needs it. The one new risk
  (accidental commit) is closed by the `.gitignore` entry.
- The token still gates `/api/exec`; the LAN-only source guard still runs first;
  the check (`X-Overseer-Token`, constant-time) is unchanged.
- Loopback binds remain tokenless and write no file.
- `write_remote_token` opens with `0600` and re-`chmod`s in case the file
  pre-existed with looser permissions.

## 6. Testing

All tests pin `CLAUDE_CONFIG_DIR`/`OVERSEER_DB`/`OVERSEER_CENTRAL` to `tmp_path`
per the repo isolation rule; the token file lives under a `tmp_path` root.

- **`remote_token.py`** — `remote_token_path` shape; `read` returns None for
  missing/empty file and the value for a present one; `write` creates
  `.overseer/`, round-trips, and the file is mode `0600`.
- **`serve_board_api.resolve_remote_token(host, root)`** — env wins (no file
  written); loopback → None (no file); non-loopback + no file → generates,
  returns it, and the file now exists with that value at 0600; non-loopback +
  existing file → returns the file's token unchanged (stable across restarts);
  env still wins over a present file.
- **`cli._run_remote`** — with the env unset and a token file under the CLI's
  `--root`, the token from the file is sent to `exec_remote`; env still wins
  over the file; neither present → token `None`.

## 7. Out of scope / follow-ups
- URL auto-discovery (`OVERSEER_REMOTE`) — host cannot know the container's
  address; unchanged.
- Any change to the exec surface, LAN guard, or token check.
