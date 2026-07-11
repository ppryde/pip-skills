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
cd frontend && npm install && npm run build
```

The backend's `test_dist_freshness.py` enforces this with a content hash of
`src/**` vs. `dist/.srchash` — see `frontend/README.md` for details.
`frontend/node_modules/` is git-ignored and must never be committed.

## Launch

```bash
.venv/bin/python dashboard/serve.py
```

(or, from a Claude Code session in this repo, run the `/dashboard` command —
see `plugins/overseer/commands/dashboard.md`.)

This resolves `--root` (default: current directory) to the overseer/vigil
state root to serve, builds the FastAPI app via
`backend/app/main.py::create_app`, opens `http://127.0.0.1:8770/` in your
browser, and serves until you Ctrl-C it.

Options:

| Flag | Default | Meaning |
|---|---|---|
| `--root PATH` | `.` | Repo root whose `.workflow/` ledger to serve |
| `--host HOST` | `127.0.0.1` | Bind host — local-only; do not change to `0.0.0.0` unless you understand the exposure |
| `--port PORT` | `8770` | Bind port |
| `--no-browser` | off | Don't auto-open a browser tab |

## Tests

```bash
.venv/bin/python -m pytest dashboard/backend/tests -q   # includes test_serve.py
.venv/bin/python -m ruff check dashboard/serve.py
.venv/bin/python -m mypy dashboard/serve.py --config-file dashboard/backend/pyproject.toml
```

`serve.py`'s own tests never bind a real port or open a real browser —
`uvicorn.run`, `webbrowser.open`, and the scheduling `threading.Timer` are
all patched.
