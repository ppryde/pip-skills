# overseer dashboard — frontend

A React + Vite + TypeScript single-page app for the overseer dashboard board view.
Hand-rolled `src/styles.css` (no CSS framework), `@dnd-kit` for drag-and-drop, no
state/query library. See `docs/superpowers/specs/2026-07-11-overseer-dashboard-design.md`
for the full design spec.

## Dev setup

Node is managed via nvm and is **not** on the default PATH in this repo/worktree —
prepend it before any `node`/`npm`/`npx` command:

```bash
export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH"
```

Then, from this directory (`plugins/overseer/dashboard/frontend/`):

```bash
npm install
npm run dev       # Vite dev server with HMR — proxies /api/* to a running
                   # FastAPI backend on http://127.0.0.1:8770 (serve.py's
                   # default). Backend on another port? Set OVERSEER_API:
                   #   OVERSEER_API=http://127.0.0.1:8771 npm run dev
```

So the hot-reload loop is: start the backend once
(`python plugins/overseer/dashboard/serve.py --no-browser`), run
`npm run dev`, and edit `src/**` — changes appear in the browser without a
rebuild or server restart. The committed `dist/` (below) is untouched by dev
mode; remember to `npm run build` before committing.

Other scripts:

```bash
npm run test        # vitest run — smoke tests (see "Testing" below)
npx tsc --noEmit    # typecheck only, no build output
npm run build        # production build — see "Build & committed dist" below
```

## Testing

Testing here is deliberately **light**: Vitest + React Testing Library smoke
tests per component/module (board renders the API shape, drag-end dispatch,
expand-to-view fetch, `/move` body mapping, control components, etc.).
Confidence for the full stack rests on:

1. This smoke-test suite (fast, in-process, no browser).
2. The backend pytest suite (`plugins/overseer/dashboard/backend/`), which
   covers the real API contract end-to-end against the overseer/vigil CLIs.
3. The **manual E2E checklist** below, run by hand against a live backend +
   built dist when reviewing a change that touches drag, drawer, or mutation
   flows — this project intentionally does not maintain a heavy browser E2E
   suite (see design spec §7 non-goals).

## Build & committed-dist policy

`frontend/dist/` **is committed** to the repository. The runtime dependency
for actually running the dashboard is the Python backend only — node/npm/Vite
are dev-time tools, not part of the deployed/runtime surface. This means:

- A checkout of this repo can serve the dashboard immediately (the FastAPI
  backend mounts `frontend/dist/` at `/`, falling back to a "not built"
  placeholder only if `dist/` is somehow absent) without anyone needing node
  installed.
- Whenever you change anything under `src/`, you **must** run `npm run build`
  and commit the resulting `frontend/dist/` changes in the same change —
  otherwise the backend's dist-freshness pytest
  (`backend/tests/test_dist_freshness.py`) will fail: it recomputes a content
  hash of `src/**` and compares it to `dist/.srchash`.
- The freshness check is **content-hash only**, never mtime — git does not
  preserve file mtimes across clones/checkouts, so mtime comparisons would be
  meaningless. `npm run build` regenerates `dist/.srchash` automatically as
  its last step (`scripts/srchash.mjs`); just make sure you rebuild before
  committing.
- `node_modules/` is git-ignored (`frontend/.gitignore`) and must never be
  committed.

```bash
npm run build   # tsc && vite build && node scripts/srchash.mjs
```

## Manual E2E checklist

Run this by hand against a live backend (real `overseer`/`vigil` CLIs against
a real `.workflow/` root) whenever a change touches drag, the drawer, or any
mutation control. Each step should complete without a console error and
without a stuck/incorrect card position.

1. **Launch backend** — start the FastAPI backend (serves the committed
   `dist/` at `/`) against a root with some cards in a mix of statuses/stages.
2. **Open board** — load `/` in a browser; confirm all lanes render
   (Backlog, the seven stage columns, Parked, Done — Archive hidden by
   default behind the TopBar toggle) and the context %/threshold show in the
   TopBar.
3. **Drag a card across a stage lane** — drag an eligible card (planned or
   non-blocked in-flight) from one stage column into another; confirm it
   lands in the new column at the dropped position and the move persists
   after a manual Refresh.
4. **Expand a card** — click a card tile (not the drag handle) to open the
   `CardDetailDrawer`; confirm it fetches and renders the full card (sections,
   body, budget, dependencies).
5. **Edit a link (parent/dependency)** — in the drawer's `LinkEditor`, set or
   clear a parent, and add/remove a dependency; confirm the board refreshes
   and the badges update accordingly.
6. **Park / unpark** — park an eligible card via its control; confirm it
   moves to the Parked lane; then unpark it via the Parked-lane menu (not
   drag) and confirm it returns to a stage/Backlog lane per its status.
7. **Block with reason** — use the `StatusMenu` to block a card, supplying a
   reason (required — confirm the UI rejects submission without one);
   confirm the card shows the red BLOCKED badge in whichever lane it lands.
8. **Set threshold and see ctx%** — change the context threshold via
   `ThresholdControl`; confirm the TopBar's ctx% / threshold display updates
   from the refreshed board response.
