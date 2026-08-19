---
description: Launch the overseer dashboard — a local FastAPI + browser board view over the ledger (drag/reorder cards, drawers, threshold control). Runtime needs only Python deps; the frontend is a committed build.
argument-hint: [--root PATH] [--port PORT] [--no-browser]
---

Launch the overseer dashboard for the current repo:

```bash
plugins/overseer/dashboard/bringup.sh $ARGUMENTS
```

`bringup.sh` runs a quiet preflight with tick output — checks the venv, probes
the target port (reusing an already-running server instead of colliding, or
refusing a port held by a stranger), asks whether to bind **local machine only**
(`127.0.0.1`, the default) or the **local network** (`0.0.0.0`), and warns if
`frontend/src` has uncommitted changes that mean `dist/` is stale — then execs
`serve.py`, passing every argument straight through. The bind-scope question is
skipped when `--host` is passed explicitly, or when there's no TTY (defaults to
loopback). Relay its ticks and the final URL rather than re-deriving the checks
by hand.

This starts a local-only server (binds `127.0.0.1`, never `0.0.0.0`) at
`http://127.0.0.1:8770/` by default and opens it in the browser. Pass
`--no-browser` to skip opening a tab, `--root <path>` to point at a different
repo root, or `--port <port>` to change the bind port.

Runtime needs only the Python deps (`fastapi`, `uvicorn`) — the frontend
`dist/` is committed, so no `node`/`npm`/Vite build is required to run it.
See `plugins/overseer/dashboard/README.md` for details, including how to
rebuild the frontend if you're changing it.

Stop the server with Ctrl-C when done.
