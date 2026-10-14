# overseer dashboard

A local, interactive board view over the overseer ledger: drag-and-drop
cards across lanes, expand a card for full detail, edit links/priority, and
set the context threshold — all backed by the real `overseer`/`vigil` CLIs.
See `docs/superpowers/specs/2026-07-11-overseer-dashboard-design.md` for the
full design spec (this README is the practical "how do I run/build it"
summary).

Local only, single-user, no auth (see the design spec's non-goals) — the
launcher binds `127.0.0.1` and is not meant to be exposed beyond localhost.

## Layout

```
dashboard/
├── serve.py        # launcher: builds the FastAPI app + runs uvicorn + opens a browser
├── backend/        # FastAPI app: JSON API + serves frontend/dist/ (see backend/README.md)
└── frontend/        # React/Vite source that BUILDS to frontend/dist/ (see frontend/README.md)
```

## Runtime deps vs dev-only

**Running** the dashboard needs only Python deps, declared in
`backend/pyproject.toml`:

- `fastapi`
- `uvicorn[standard]`

**Building/changing** the frontend needs dev-only tooling that is *not*
required to run the dashboard: `node` + `npm` (Vite, React, TypeScript,
`@dnd-kit`, Vitest). See `frontend/README.md` for the node/nvm setup.

This split exists because `frontend/dist/` is **committed** (see below) —
a checkout of this repo can serve the full dashboard with nothing but a
Python environment; node is only needed if you're changing the UI itself.

## Committed-dist policy

`frontend/dist/` is committed to the repository, not gitignored or built at
serve time. `serve.py` / the backend never invoke `npm`/`vite` — they only
read the already-built `dist/` off disk (falling back to a small "frontend
not built" placeholder if it's ever absent, e.g. in a stripped-down checkout).

If you change anything under `frontend/src/`, you must rebuild and commit
`dist/` in the same change:

```bash
export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH"   # node via nvm, not on default PATH
cd frontend && npm ci && npm run build
```

The backend's `test_dist_freshness.py` enforces this with a content hash of
`src/**` vs. `dist/.srchash` — see `frontend/README.md` for details.
`frontend/node_modules/` is git-ignored and must never be committed.

## Launch

Run from the repo root:

```bash
.venv/bin/python plugins/overseer/dashboard/serve.py
```

For a quieter start with preflight tick output — reuses an already-running
server instead of colliding on the port, asks whether to bind local-machine-only
(`127.0.0.1`, default) or the local network (`0.0.0.0`), and warns if `dist/` is
stale — use the launcher (it passes every flag through to `serve.py`, and skips
the bind-scope question when `--host` is given or there's no TTY):

```bash
plugins/overseer/dashboard/bringup.sh
```

(or, from a Claude Code session in this repo, run the `/dashboard` command —
which now wraps `bringup.sh`; see `plugins/overseer/commands/dashboard.md`.)

This resolves `--root` (default: current directory) to the overseer/vigil
state root to serve, builds the FastAPI app via
`backend/app/main.py::create_app`, opens `http://127.0.0.1:8770/` in your
browser, and serves until you Ctrl-C it.

For a dev container that needs to reach a board living on the host, use the
same server bound to `0.0.0.0` — see "Remote access from a dev container".

Options:

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | `.` | Repo root whose `.workflow/` ledger to serve |
| `--host HOST` | `127.0.0.1` | Bind host — local-only; do not change to `0.0.0.0` unless you understand the exposure |
| `--port PORT` | `8770` | Bind port |
| `--no-browser` | off | Don't auto-open a browser tab |
| `--replace` | off | If the recorded dashboard is still answering (on any port), stop it and take over (otherwise the launch refuses) |

## Chronicle page (optional)

When the `chronicle` plugin sits beside overseer (`plugins/chronicle`), the
top bar gains a **Chronicle** button next to the Board|Atlas coins: session
telemetry (per-turn token usage, context growth, prompts, tool calls,
subagents, compactions, duration) read from chronicle's own account-scoped
SQLite store — never from `board.db`.

**Several Claude accounts.** `overseer claude-dirs add ~/.claude-personal` lists a second
account's config dir in the machine config (`<primary>/overseer/config.json`, or the
`CLAUDE_CONFIG_DIRS` env). The dashboard then discovers boards under every listed dir, merges
each account's census store so a personal-account session on the same repo is one more live
session (each tagged `config_dir`), and chronicle syncs every account's transcripts. Rate-limit
pills stay the primary account's. Creation of a new board still lands under the primary.

The page is pull-only: while it shows
and the tab is in the foreground it syncs quietly on open and once a minute,
and its **Sync** button (`POST /api/chronicle/sync`) forces one. Sync asks
chronicle to reconcile its store with the transcripts on disk, ingesting
only files that moved; it is not token-gated, since it writes only what the
transcripts already say. Reads (`GET /api/chronicle/{status,summary,sessions,session/{id}}`)
take the same validated `root` as `/api/board`, or `scope=all` for the whole
account. Every route degrades to an "unavailable" shape when the plugin is
absent, and the button is simply not rendered. See `../../chronicle/README.md`.

## Remote access from a dev container

An `overseer` CLI running **inside a Docker dev container** can read and write
the board (`board.db`) that lives on the **host** by pointing at this same
server bound to `0.0.0.0`. There is one server and one port (8770): the
dashboard and a token-gated `POST /api/exec` passthrough that runs the real
host CLI and relays its output.

> **BREAKING (overseer 0.30.0).** The separate board API service
> (`serve_board_api.py`, port **8771**) is gone, and `OVERSEER_DASHBOARD_TOKEN`
> no longer opens exec. Re-point containers at `:8770` and give them the exec
> token (below). `BOARD_API.md` is deleted; this section replaces it.

### Run on the host

```bash
.venv/bin/python plugins/overseer/dashboard/serve.py --root /path/to/host/repo --host 0.0.0.0
# prints: exec token: /path/to/host/repo/.overseer/remote-token
```

The exec token is minted on every bind (loopback too), persisted `0600` at
`<root>/.overseer/remote-token`, and **never printed**: the launcher prints the
file's path or `exec token: from OVERSEER_REMOTE_TOKEN`, and the dashboard log
(`<CLAUDE_CONFIG_DIR>/overseer/dashboard.log`, `0600`) holds neither token.
To choose it yourself, set **`OVERSEER_REMOTE_TOKEN`** (at least 16 characters;
shorter is refused at launch) in the server's environment. Precedence: that
variable, then the token file, then a freshly minted one. The file is only
trusted if it is a regular file owned by the server's uid with no group/other
bits and `.overseer` is not a symlink; otherwise it is replaced. Env-pinned
tokens do not survive the SessionStart auto-restart's inherited environment
reliably, so rely on the file for long-lived servers.

A dashboard recorded as `127.0.0.1` stays unreachable from containers: relaunch
once with `--host 0.0.0.0 --replace`.

### Point the container at it

```bash
export OVERSEER_REMOTE=http://host.docker.internal:8770
export OVERSEER_REMOTE_TOKEN=<contents of .overseer/remote-token>
```

A container that mounts the repo needs no `OVERSEER_REMOTE_TOKEN`: the CLI
reads `.overseer/remote-token` itself. On Linux, run the container with
`--add-host=host.docker.internal:host-gateway`. The container's `overseer`
needs `httpx` (imported only on the `--remote` path). Verify with
`overseer --remote http://host.docker.internal:8770 board`; the same against
`:8771` must now fail to connect.

With the two variables set, `overseer` verbs and hook invocations in the
container forward to the host board. Interactive verbs (`clear`) must pass
`--yes`. `--file` / `--text-file` are read in the container and sent as
`--text -` stdin.

### Reaching another repo's board

By default every container call lands on the board pinned when the server
started. A container that works in a *different* repo names it by **label**:

```bash
export OVERSEER_REMOTE_REPO=pip-skills   # a repo label, never a path
```

Unset, nothing is sent and the pinned board is used. Set, the host resolves the
label against every watched **live** board on the machine (all accounts;
`overseer repos` lists them), runs the CLI with that repo as `--root` and that
board as `OVERSEER_CENTRAL`, and the child cannot pick another. The label is
validated on the client (`letters, digits . _ -`, up to 100): a malformed value
is a hard error before any request, never silently dropped. `pretool-hook`
forwards with the same label.

| Answer | Meaning | Remedy |
|---|---|---|
| 400 | not a label (empty, a path, odd characters) | fix `OVERSEER_REMOTE_REPO` |
| 404 | no live board has that label; the message lists the valid ones. There is **no fallback** to the pinned board, and an archived repo is a 404 too | pick a listed label; a repo with no `board.db` yet is not listed (`init` is denied remotely, run it on the host) |
| 409 | two live boards share the label (the message names both roots), or the server itself is pinned by `OVERSEER_CENTRAL`/`OVERSEER_DB` | add an alias in the host's machine config, `"aliases": {"wayflyer-old": "~/repos/old/wayflyer"}`, and set `OVERSEER_REMOTE_REPO=wayflyer-old`; for the env pin, start the server without those variables |
| 503 | the overseer plugin lies inside the *target* repo (the same check as for the pinned repo, run against the resolved root) | run the dashboard from an installed plugin outside every mounted repo |

Aliases win over a discovered label of the same name (the alias is owner
config, the label comes from a `.git` a container can write); a clash is logged
once and shadows the label. An alias that names no live discovered board, or is
not a valid label, is ignored with a warning. `overseer repos` shows each
repo's aliases.

Tokens: a container that mounts the *launch* repo reads `.overseer/remote-token`
itself. A container that mounts only some other repo has no such file there (the
server never writes token files into other repos), so give it
`OVERSEER_REMOTE_TOKEN` in its environment.

The token plus a label is a master key to every live board on the machine. The
label is a routing hint chosen by the container, which controls its own `.git`;
it is not an identity. Every other guard applies unchanged to labelled calls:
the LAN guard, the token, the denied verbs (`bootstrap` and `dispatch-prep`
included), argv sanitising, the hardened git environment, the secret strip and
read-only archives. Known limits: a repo with boards in two live accounts
resolves to the first-listed one (cure: `overseer merge-boards` or move the
backup into `archive_dirs`); exec never translates paths, so the machine
config's `path_map` plays no part; a discovered root swapped for a symlink
needs host filesystem control and is accepted. A writable mount of a repo also
exposes its `.overseer/config.json` and `.git` to the container, which
the pin makes harmless for *board* selection but not for the repo identity
residual below.

### Migration from the old service

| Before | After |
|---|---|
| `OVERSEER_REMOTE=http://host:8771` | `http://host:8770`; port 8771 is retired |
| `OVERSEER_DASHBOARD_TOKEN` opened exec | it never does; exec uses `OVERSEER_REMOTE_TOKEN` or `.overseer/remote-token` |
| token printed at launch | never printed; exec token in `.overseer/remote-token`, a minted dashboard token (non-loopback only) in `.overseer/dashboard-token` |
| Tailscale reachable | refused (the guard is LAN-only, see below) |
| archived board copies reachable | `archive_dirs` (and `backup`/`archive` path segments) are never exec targets; the dashboard shows them as `[archived]`, read-only |
| a repo with boards in two live accounts | the first-listed account's board wins; `overseer merge-boards` on the host is the cure |
| `bootstrap`, `dispatch-prep` over `--remote` | refused (403, follow-up WF-300); run them on the host, or do `new-card`, a local `git worktree add`, `set-field ID --worktree <path> --branch <branch>`, `set-stage`. A host-side `dispatch-prep` cannot see a container worktree path |
| a value starting `--file`, `--text-file`, `--brief-file` (e.g. `--filename`) | refused with 403 by design |

**Archive dirs.** A config dir is archived if it is listed in `archive_dirs`
(machine config) or any resolved path segment is `backup`, `backups`,
`archive` or `archives` (case-insensitive). The primary dir
(`CLAUDE_CONFIG_DIR`) is never archived. Misfire: a *live* dir whose path has
such a segment is wrongly treated as archived; rename or move it.

### Security and threat table

Two guards apply to every route: the **app-wide LAN source guard** (any caller
that is not private, loopback or link-local gets `403` before auth, regardless
of bind; no override) and, for `/api/exec`, the **exec token**. GET routes are
not token-gated, so on a `0.0.0.0` bind any LAN device can read boards. The
dashboard's own mutation gate is separate from the exec token: unarmed on a
loopback bind, armed on any other bind or whenever `OVERSEER_DASHBOARD_TOKEN`
is set, with its **own** token (the browser UI asks for it once and stores it).
Without the env var, a non-loopback bind mints that token into its own file,
`<root>/.overseer/dashboard-token` (`0600`, same hardened writer as the exec
token, reused across restarts while trusted); the launcher prints the file's
**path**, never the token, so paste its contents into the UI. Set
`OVERSEER_DASHBOARD_TOKEN` to choose one instead (no file is written).
`OVERSEER_REMOTE_TOKEN` never arms the gate, and the dashboard token never
opens exec; the two secrets live in separate files. `/api/repo/clear` stays refused off loopback
without `OVERSEER_DASHBOARD_ALLOW_REMOTE_DESTRUCTIVE=1`, and exec denies
`clear`. Never expose this server beyond your LAN.

| What | Allowed or refused | Notes |
|---|---|---|
| Exec verbs | Denylist (`_DENIED_VERBS`); a parity test classifies every parser verb as allowed or denied, so a new verb fails the suite until it is classified | `--root`, `--remote`, `--dir`, `--central`, `--backup-dir` are stripped; abbreviations are off on every sub-parser |
| Denied verbs | `init`, `backup`, `restore`, `clear`, `claude-dirs`, `merge-boards`, the `*-hook` verbs except `pretool-hook` (whose `cwd` is pinned to the served root), `bootstrap`, `dispatch-prep` | the two git-running verbs answer 403 naming the verb and WF-300 |
| Host path options | `--file`, `--text-file`, `--brief-file` (prefix, and `=` forms): 403 | the client inlines `--file`/`--text-file` as stdin before sending |
| Git | No git in container-writable trees except the hardened lookups (`rev-parse --git-common-dir`, `rev-parse --verify`: hooks and fsmonitor off, `GIT_CONFIG_*`/`GIT_SSH*` dropped, never touching index or worktree) | an AST scan pins which files may call git |
| Child process | Board pinned to the one the host chose (`OVERSEER_CENTRAL`); env stripped of `OVERSEER_REMOTE*`, `OVERSEER_DASHBOARD_TOKEN` and anything named `*TOKEN*`/`*SECRET*`/`*KEY*`/`*PASSWORD*`, `AWS_`/`GH_`/`GITHUB_` (keeping `CENSUS_`/`CHRONICLE_`) | 1 MiB body cap, 4 concurrent children (busy 503), 30 s timeout, NUL in argv or stdin 400 |
| Dashboard token | Env, else a minted `0600` file `.overseer/dashboard-token` (non-loopback binds only); a symlinked `.overseer` is refused (the run then uses an unreadable in-memory token) | never printed, separate from the exec token |
| Token | Fail-closed: no token configured means `503` for everyone; a wrong or non-ASCII header is `401`; env token at least 16 chars and non-empty | independent of the dashboard token |
| LAN guard | Private, loopback, link-local (IPv6: ULA, mapped and 6to4 judged by the embedded IPv4) pass | **CGNAT `100.64.0.0/10` and Tailscale addresses are refused, on purpose**; use a Tailscale-reachable bind behind your own ACLs, or change the guard deliberately |
| Archives | Never an exec target, never adopted by the CLI; the dashboard opens them read-only (`mode=ro&immutable=1`) and every POST on one is `403` | see residual 3 |
| Browser tab, DNS rebinding | A cross-site POST to exec needs the custom header (preflight) and the token; DNS rebinding can still read boards and use tokenless loopback mutations | pre-existing; a Host allowlist is a follow-up |

**The token holder is the master key.** Whoever holds the exec token (and any
container mounting the repo already does) can run the allowed verbs on **every
live board on the machine**, across accounts, by owner decision.

Residuals, accepted and documented:

1. **`.git` file redirect.** A container that rewrites the served root's `.git`
   into a `gitdir:` file pointing at a repo with a `commondir` file controls
   the output of `rev-parse --git-common-dir`, which feeds repo identity,
   labelling and the `.workflow/` migration: host files under an arbitrary
   directory's `.workflow/` could be imported into the shared board and a board
   mislabelled. No code runs. Worktrees use `.git` files legitimately, so it is
   not blocked.
2. **Writable plugin dir.** If the host's installed overseer (or a dev
   `--plugin-dir` checkout) is container-writable, the container can edit code
   the host runs. Only a dev checkout *inside the served repo* is detected
   (exec answers 503); an install under another mounted path is not. Run the
   dashboard from the marketplace cache, outside any mount.
3. **Stale archive read.** Archives are opened `immutable=1`, which ignores the
   `-wal`: a copied archive with an uncheckpointed WAL reads stale.
4. **Environment and config.** The child inherits the dashboard's non-secret
   looking environment (launch from a clean env); a rw-mounted container can
   edit `.overseer/config.json` (`worktree_dir`, `backup_dir`) and the token
   file; `set-field --worktree/--branch` store container-supplied strings.
5. **Git-scan blind spots.** The test that pins which files may call git is
   coarse by design and does not see an asyncio subprocess, `os` imported under
   another name, `pty` / `pexpect`, a bytes-literal `b"git"` or a concatenated
   `"gi" + "t"`. None is accidental: each needs deliberate code in this repo,
   which review catches.

## Clear data

A "Clear data" control in the dashboard settings wipes the served repo's
overseer state via `POST /api/repo/clear`, which shells out to
`overseer clear --scope {cards,repo} --yes --json` (see
`../README.md#overseer-clear` for the CLI verb). Two scopes:

- **Cards** — deletes every card, keeping the central folder and the repo's
  identity/meta intact.
- **Repo** — removes the whole central per-repo folder (board, sprints,
  usage, knowledge).

A recovery snapshot is **always** taken first (unless the CLI is run
directly with `--no-backup`, which the dashboard never does) — undo with
`overseer restore`. The UI gates the action behind a two-step "dragons"
confirmation modal: step 1 picks the scope and previews what will be
removed, step 2 only unlocks the destructive button once you've typed the
exact repo label — a deliberate speed bump, not a security boundary.

The real boundary is server-side: `/api/repo/clear` is refused with a 403
unless the dashboard was launched bound to loopback (`127.0.0.1`/`::1`/
`localhost`). To allow it on a non-loopback bind (e.g. serving over a LAN
address), set `OVERSEER_DASHBOARD_ALLOW_REMOTE_DESTRUCTIVE=1` in the
server's environment — an explicit, deliberate opt-in, since this endpoint
can delete an entire repo's tracked work.

## Updating a running dashboard (redeploy)

A running server reads static files off disk per request, and each build
emits content-hashed asset filenames — so **frontend changes never need a
server restart**. To pick up a merged frontend change on the checkout the
server serves from:

```bash
git pull        # in the worktree/checkout the server was launched from
# then just refresh the browser tab
```

A restart (Ctrl-C, relaunch `serve.py`) is only needed when **backend
Python** changes — `serve.py` runs uvicorn without `--reload`, and the app
is built once at startup.

### Restart-on-stale (WF-053)

The server stamps itself **once the bind succeeds** — pid, host, port, root,
version and how to relaunch — at `<CLAUDE_CONFIG_DIR>/overseer/.dashboard.json`,
removed on clean shutdown, and answers `GET /api/version` with what it is
actually running. A launch that cannot bind never claims the stamp, so it
cannot take a healthy server's record down with it.

Overseer's SessionStart hook reads the stamp and, only when a server is
**really there** and running an **older** version than the installed plugin,
restarts it with the same host, port and root (never opening a browser),
leaving one line in the session: `overseer dashboard restarting 0.21.0 →
0.22.0`.

"Really there" means it **answers `GET /api/version`** — a live pid is not
enough. A record survives a reboot, after which its pid may belong to an
unrelated process; killing that and starting a dashboard in its place would
be two things this must never do. A pid that is alive but silent is treated
as not running: the stale stamp is deleted and nothing is signalled. The
same rule governs `serve.py --replace`.

The version the hook compares is what the live server reports; the stamp only
fills in an answer that omits it. Versions parse leading-dotted-numeric only,
so `0.22.0-rc1` is release `0.22.0` and sorts *below* the `0.22.0` it
precedes.

The kill and relaunch run in a **detached worker**, so the hook returns at
once and a session start never waits on a SIGTERM — hence "restarting", not
"restarted". If that worker stops the old server and then cannot start the
new one, it leaves a note that the next session's hook reports as
`overseer dashboard restart FAILED …`; a dashboard that is down is never
silently down. Everything else fails open — any error is a silent no-op.

It never starts a dashboard that was not running and never downgrades.
Several sessions starting together are debounced by a short-lived lock (the
worker's, released when it finishes, and taken over atomically if it goes
stale), so one of them does the restart. A LAN-bound server comes back
LAN-bound; note that its generated dashboard token changes on restart unless
`OVERSEER_DASHBOARD_TOKEN` is set in the environment the hook runs in. The exec
token does not change: it is read back from `.overseer/remote-token`. Output
of the relaunched server goes to `<CLAUDE_CONFIG_DIR>/overseer/dashboard.log`.

## Hot reload (dev)

For UI work, skip the rebuild-refresh loop entirely: `npm run dev` serves
`frontend/src/` with Vite HMR and proxies `/api/*` to a running backend
(default `http://127.0.0.1:8770`; override with `OVERSEER_API` for another
port). Edits under `src/` appear in the browser instantly.

```bash
.venv/bin/python plugins/overseer/dashboard/serve.py --no-browser   # backend, once
cd plugins/overseer/dashboard/frontend && npm run dev               # HMR at :5173
# backend on a non-default port?
OVERSEER_API=http://127.0.0.1:9000 npm run dev
```

Dev mode never touches the committed `dist/` — the committed-dist policy
above still applies before committing. See `frontend/README.md` for the
full dev setup.

## Tests

Run from the repo root:

```bash
.venv/bin/python -m pytest plugins/overseer/dashboard/backend/tests -q   # includes test_serve.py
.venv/bin/python -m ruff check plugins/overseer/dashboard/serve.py
.venv/bin/python -m mypy plugins/overseer/dashboard/serve.py --config-file plugins/overseer/dashboard/backend/pyproject.toml
```

`serve.py`'s own tests never bind a real port or open a real browser —
`uvicorn.run`, `webbrowser.open`, and the scheduling `threading.Timer` are
all patched.
