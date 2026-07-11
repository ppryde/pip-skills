---
description: Launch the overseer dashboard — a local FastAPI + browser board view over the ledger (drag/reorder cards, drawers, threshold control). Runtime needs only Python deps; the frontend is a committed build.
argument-hint: [--root PATH] [--port PORT] [--no-browser]
---

Launch the overseer dashboard for the current repo:

```bash
.venv/bin/python plugins/overseer/dashboard/serve.py $ARGUMENTS
```

This starts a local-only server (binds `127.0.0.1`, never `0.0.0.0`) at
`http://127.0.0.1:8770/` by default and opens it in the browser. Pass
`--no-browser` to skip opening a tab, `--root <path>` to point at a different
repo root, or `--port <port>` to change the bind port.

Runtime needs only the Python deps (`fastapi`, `uvicorn`) — the frontend
`dist/` is committed, so no `node`/`npm`/Vite build is required to run it.
See `plugins/overseer/dashboard/README.md` for details, including how to
rebuild the frontend if you're changing it.

Stop the server with Ctrl-C when done.
