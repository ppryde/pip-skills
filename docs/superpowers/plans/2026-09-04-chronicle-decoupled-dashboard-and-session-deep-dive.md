# Chronicle — decoupled dashboard shell + session deep dive

**Date:** 2026-09-04
**Status:** Plan (not started). Follows PR #63 (`feat/session-metrics`), which
shipped the chronicle plugin and its page inside overseer's dashboard.
**Goal:** (1) the dashboard UI works with either plugin installed alone —
overseer and chronicle are peers, neither a dependency of the other; (2) a
proper single-session deep-dive page.

---

## 0. Where we are

Today the dashboard (FastAPI backend + React/Vite frontend + `serve.py` +
`bringup.sh`) lives under `plugins/overseer/dashboard/`. Its backend is a
subprocess client of three sibling CLIs, two of them already soft:

| CLI | How it is reached | If absent |
|---|---|---|
| overseer | `run_overseer` (31 call sites in `main.py`) | every board route fails — hard dependency |
| census | `run_census*` → `None` | board degrades (no live sessions) |
| chronicle | `run_chronicle` → `None` | Chronicle page not offered |

The frontend's `App.tsx`/`TopBar.tsx` are board-first: the repo selector,
branch filter, party pill, gold/vanquished pills, threshold, clear dialog and
filter bar all assume a board. Chronicle is a third `view` bolted beside them.

## 1. Target shape: a shell that mounts whatever pages are present

Move the dashboard out of overseer into its own plugin — working name
**`hall`** (the guild hall; every page is a room) — and make overseer and
chronicle *page providers*.

```
plugins/hall/                         # the shell: server, static, page registry
  serve.py  bringup.sh  commands/dashboard.md
  backend/app/{main.py, registry.py, cli_client.py}
  frontend/                          # ONE build, all pages compiled in
plugins/overseer/dashboard/router.py  # board routes, built by the shell if overseer exists
plugins/chronicle/dashboard/router.py # chronicle routes, likewise
```

### Backend
- `registry.py` discovers sibling plugins by path
  (`plugins/<name>/dashboard/router.py`, the same sibling resolution the
  CLI client already uses) and calls `build_router(ctx) -> APIRouter` on
  each that exists. `ctx` carries `launch_root`, `derived_root`,
  `require_token`, `resolve_root`.
- `GET /api/capabilities` → `{"pages": {"board": true|false, "chronicle":
  true|false}, "census": bool}`. The frontend reads this once and shows only
  the pages that exist. No page may 500 because another is missing.
- `_resolve_root`'s allowlist comes from overseer's `repos` discovery today.
  Without overseer, chronicle's own `repos` verb (already shipped) supplies
  the allowlist: the shell asks every provider for `known_roots()` and unions
  them. Board-less roots are display-only for the board (unchanged), valid
  for chronicle scoping.
- `serve_board_api.py` (the LAN board API for dev containers) stays in
  overseer — it is overseer's API, not a page.
- Tokens, loopback gating, cache headers, static mount: move verbatim.

### Frontend
- `App.tsx` becomes a thin shell: capabilities fetch, page tabs, active
  repo selection (persisted as today), and the page outlet. Pages own their
  toolbars: the board-specific TopBar content (party pill, gold, vanquished,
  threshold, filters, clear) moves into a `BoardPage` that renders its own
  bar under the shell tabs; `EpicAtlas` becomes a sub-view of BoardPage;
  Chronicle already owns its filter row.
- The repo selector stays in the shell (both pages scope by root) but its
  option list comes from `/api/repos`, which the shell serves by unioning
  provider roots (board roots flagged `has_board`).
- Hash routing (no router dependency, as today): `#board`, `#atlas`,
  `#chronicle`, `#chronicle/<session id>` for the deep dive. Replace the
  `#design` special case with the same mechanism.
- One Vite build, one committed `dist/`, one `test_dist_freshness` — moved
  to `plugins/hall`. Vitest suites move with their components.

### Marketplace / install story
- `hall` is a new marketplace entry. Installing overseer or chronicle alone
  gives the CLI + hooks; installing hall gives the UI for whichever of the
  two (or both) are present. Overseer's `/overseer:dashboard` command is
  kept as a thin alias that runs hall's `bringup.sh` (deprecation note),
  and hall gets `/hall:dashboard`.
- `bringup.sh` preflight gains a line per provider: "board: overseer found /
  not installed", "chronicle: found / not installed".

### Migration steps (each a PR-sized chunk)
1. **Registry + capabilities in place** (still under overseer): add
   `registry.py`, split `main.py`'s board routes into
   `overseer/dashboard/router.py`, chronicle routes into
   `chronicle/dashboard/router.py`. Tests: shell boots with either router
   absent (monkeypatch the discovery). No file moves yet.
2. **Frontend shell**: `App.tsx` → shell + `BoardPage`; TopBar split;
   capabilities-driven tabs; hash routes. Snapshot-free tests on the tab
   set for each capability combination.
3. **Move**: `git mv plugins/overseer/dashboard/{serve.py,bringup.sh,
   backend,frontend} plugins/hall/`; fix the four `parents[n]` path
   resolutions (`cli_client.py`, `main.py`, `serve.py`, `test_dist_
   freshness.py`) and the READMEs; add the marketplace entry; alias the
   command. `git mv` keeps history readable.
4. **Root union**: `/api/repos` from provider `known_roots()`; chronicle
   scoping works with overseer absent (test with the overseer CLI path
   monkeypatched away).

## 2. Session deep dive (`#chronicle/<id>`)

A full page, reached from the session table (the drawer stays as the quick
look). Two new captures first, then the page.

### Capture (chronicle plugin, additive migration + `sync --full`)
- `tool_calls.result_chars` — length of the matching `tool_result` content
  (the `user` record whose `tool_use_id` matches); `tool_calls.input_chars`
  — length of the `tool_use.input` JSON. Parser change: index `tool_result`
  blocks by id while folding; results usually follow within the same file.
- `tool_calls.result_ts` — the result record's timestamp; latency =
  `result_ts - ts`.
- `turns.prompt_chars` (optional) — length of the human prompt that opened
  the turn's exchange, for prompt-driven jumps.

### Page sections
1. **Header**: title, id, repo/branch, models, started/last/end reason,
   cache hit rate, cold turns; "Open transcript path" copy button.
2. **Context timeline** (full width): context per turn with compaction
   hairlines and cold rings (exists), plus output tokens per turn as a
   second small multiple beneath (one hue each; never dual-axis).
3. **Biggest jumps**: top 10 turns by `Δ context`, each attributed to what
   landed since the previous turn — tool results (name + result_chars),
   the assistant's own output, a prompt — or flagged as post-compaction /
   cold. Click a row → scrolls/highlights that turn on the timeline.
4. **Tool breakdown**: per tool — calls, total result chars ("context
   cost"), median/max latency, share of turns following it. Ranked bars
   on context cost; table for the rest.
5. **Cache story**: hit rate over the session, cold turns with the idle
   gap that preceded each, cache written by TTL.
6. **Phases**: the user's prompts in order (truncated text, time), with
   the turns / tokens / tools spent until the next prompt — where the
   session's effort went.
7. **Subagents**: each agent's turns, context, output, tools, span, shown
   as bars on the parent's time axis.

### Report side
`chronicle session <id> --deep` (or a new verb `dive`) returns the above as
one JSON: `jumps[]`, `tools[]` with cost/latency, `phases[]`, and the
existing series. Keep `session` unchanged for the drawer.

### Frontend
`SessionDeepDive.tsx` under `components/chronicle/`, hash-routed; reuse
`ColumnChart`/`LineChart`/`BarList`; add a `RankedTable` for jumps.

## 3. Order of work

1. Deep-dive **capture** (small, valuable on its own — the drawer's tool
   list gains context cost immediately).
2. Shell **step 1** (registry + capabilities) — low-risk, no moves.
3. Deep-dive **page**.
4. Shell **steps 2–4** (frontend split, move, root union).

Steps 1 and 2 are independent and can be parallel PRs off `main` once #63
merges.

## 4. Deferred / open

- Cost estimates need a pricing table per model (config file, user-owned).
- Retention/pruning of the chronicle store.
- Liveness via census rather than the 15-minute horizon.
- Whether census also becomes a hall page (live fleet) once the shell exists.
