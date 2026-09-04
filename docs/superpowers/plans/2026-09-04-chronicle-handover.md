# Chronicle — session handover (2026-09-04)

**Branch:** `feat/session-metrics` · **PR:** https://github.com/ppryde/pip-skills/pull/63 (open, review required, 9+ commits, all pushed)
**Last verified:** 2026-09-04 (second handover) — branch in sync with origin; 67 chronicle + 23 backend (chronicle & sessions) + 87 census tests green.
**Read first:** `docs/superpowers/specs/2026-09-04-chronicle-session-telemetry-design.md` (what/why), then
`docs/superpowers/plans/2026-09-04-chronicle-decoupled-dashboard-and-session-deep-dive.md` (what's next).

## State of the work — everything below is committed, tested, pushed

| Piece | Where | Tests |
|---|---|---|
| chronicle plugin (store, transcript parser, incremental `sync`, report, CLI, hooks, skill, README) | `plugins/chronicle/` | 67 in `tests/chronicle/` (`cd plugins/chronicle && ../../.venv/bin/python -m pytest`) |
| dashboard backend routes `/api/chronicle/{status,summary,sessions,session/{id}}` + `POST /api/chronicle/sync` | `plugins/overseer/dashboard/backend/app/{main,cli_client}.py` | 11 in `backend/tests/test_chronicle.py` |
| Chronicle page, drawer, charts, gauges, artifact list | `plugins/overseer/dashboard/frontend/src/{components,board}/chronicle/` | 856 vitest total; `dist/` rebuilt and committed |

Features shipped on the page: window/scope filter row + Sync; two gauges (cache hit rate with verdict word,
peak context % of inferred 200k/1M window); stat tiles with per-measure hue accents; context/output/peak
per day columns; cache hit rate per day; turns by model; tool leaderboard; artifacts list (distinct pages,
publish counts, links); session-shape quantiles; sortable session table (incl. Peak %, Artifacts).
Drawer: gauges, tiles, context-per-turn line (compaction hairlines, cold-turn rings, idle gaps in
tooltip), **Biggest jumps** table (turn, +delta, context, what landed — tool results by size), artifacts,
tools, subagents.

Real store: `~/.claude/chronicle/sessions.db` — synced with `sync --full` after the last schema change
(52 sessions, 17 distinct artifact pages). Run `sync --full` again after ANY schema/parser change.

## Uncommitted edits in the working tree — NOT this branch's work
`plugins/census/{README.md,scripts/store.py}`, `tests/census/*`, and the census-idle passthrough in
`plugins/overseer/dashboard/backend/app/main.py` (`_census_extras` adds `idle`) + `test_sessions_idle_flag`
in `backend/tests/test_sessions.py` all belong to ANOTHER session's census "idle vs stale" feature.
They pass (run census tests from `plugins/census/` as cwd: `cd plugins/census && ../../.venv/bin/python -m pytest ../../tests/census`),
but do not stage or commit them here. Untracked noise to ignore: `.overseer/`, `.superpowers/`, `scratch/`,
`design_handoff_quest_board/`, `SECURITY.md`, `node_modules/`, `scratchpad_dashboard.log`, `.DS_Store`.

## In flight when handed over
Nothing new since the first handover — the session was reset (`/clear`) before further work. Was mid browser check of the artifacts list + biggest-jumps drawer on the test server. The page
screenshot (`This repo` scope, pip-skills) rendered correctly — artifacts panel shows the empty state
because pip-skills sessions published nothing; switch scope to **All repos** to see the 17 pages.
The drawer's Biggest jumps table has NOT yet been eyeballed in the browser (unit-tested only).

Test server: `serve.py --port 8772 --no-browser` IS still running from this checkout (pid 68792 at last check) (`pkill -f "serve.py --port 8772"`
to stop). Port 8770 holds an OLD dashboard process from 25 Aug — not this build.

## Gotchas learned
- Chrome automation: the first click on the Chronicle nav button after `navigate` lands before React
  hydrates and does nothing — wait ~3s, `find` again, click again.
- Hand-written shell heredocs: run with the repo root as cwd (`cd /Users/philip.pryde/repos/pip-skills`),
  several patches silently no-op'd when cwd drifted into `frontend/`.
- Table alignment: `.chr-num` is left-aligned by the user's explicit choice (headers and cells agree).
- Colour: one hue per MEASURE (`--chr-context/output/peak/cache/turns/tools`), single-hue per chart,
  all validated on parchment `#fbf4e1`. Don't add a second hue inside a chart.
- `tests/census/*` and `plugins/census/*` have uncommitted edits from ANOTHER session — never stage them.
- Artifact titles come from the file stem when the `title` param is absent (the harness names pages from
  `<title>`); favicon/description are coalesced from the first publish of a url.

## Next (user's stated wishes, in order)
1. Finish the browser check of the drawer's Biggest jumps + artifacts, fix anything visual.
2. Session **deep-dive page** (`#chronicle/<id>`) — plan §2. Tool `result_chars`/`result_ts` capture is
   DONE (this session), so the page can start straight away: full-width timeline, jumps with
   attribution, tool cost/latency breakdown, cache story, prompt phases, subagents on the time axis.
3. **Decouple** the dashboard from overseer (plan §1: a `hall` shell plugin with page providers) so
   chronicle's UI works without overseer and vice versa. Do step 1 (registry + capabilities) first.
4. The user's message trailed off: "We also want to pull in the …" — ask what.
5. Deferred: cost per model (pricing table), retention, census-linked liveness.

## Commands
```bash
git checkout feat/session-metrics
.venv/bin/python plugins/chronicle/scripts/cli.py sync            # or sync --full after schema changes
.venv/bin/python plugins/overseer/dashboard/serve.py --port 8772  # then click Chronicle in the top bar
export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH"         # node for the frontend
cd plugins/overseer/dashboard/frontend && npx vitest run && npm run build   # rebuild+commit dist after src changes
```
