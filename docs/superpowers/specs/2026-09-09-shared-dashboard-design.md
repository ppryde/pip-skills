# A shared dashboard: chronicle standing alone, bundled with either plugin

**Date:** 2026-09-09
**Plugins:** `overseer`, `chronicle` (dashboard, hooks, CLI surface)
**Status:** Draft (design) — approved in brainstorming; open questions at the end must be settled before building.

## Problem

The dashboard lives in `plugins/overseer/dashboard/`. Chronicle's UI — fourteen
components and ~4,100 lines — lives inside it, under
`frontend/src/components/chronicle/`, with 92 `Chronicle*` types in
`api/types.ts`. So:

- **Chronicle cannot stand alone.** Installing it without overseer gets you a
  CLI and a SQLite store and no way to look at either.
- **Chronicle's UI cannot ship without an overseer release**, since its page
  is in overseer's tree.
- **The overseer→chronicle seam exists on the backend but not in the
  artefact.** `chronicle_installed()` probes, `run_chronicle` soft-degrades,
  the tab hides — but the page still compiles into the bundle every board user
  downloads. (PR #70 code-split it; the source is still in overseer's tree.)

And one live bug underneath all of it:

**Cross-plugin discovery has never worked for an installed plugin.**
`cli_client.py:31-33` finds vigil, census and chronicle by walking up four
parents to `plugins/`. True of a repo checkout; false once installed, because
the marketplace inserts a version directory:

```
repo       plugins/overseer/dashboard/backend/app/  → parents[4] = plugins/     ✓
installed  cache/…/overseer/0.15.0/…/backend/app/   → parents[4] = …/overseer/  ✗
```

Anyone who installed overseer from the marketplace has never seen the Chronicle
page, and the vigil and census integrations are dead too. `parents[3]` (the
plugin's own root) is correct in both layouts; only these three sibling lines
are wrong. The test added in #69 cannot catch it — it runs in the checkout,
where it passes.

## Goal

Install **chronicle alone** → a dashboard with the Chronicle page.
Install **overseer alone** → a dashboard with Board and Atlas.
Install **both** → one dashboard, every page, the UI stored once and served
from whichever copy is newest.

## Design overview

1. **One source of truth** at repo root `dashboard/`; each plugin carries a
   *generated, hash-checked* copy.
2. **Layout-independent discovery** replacing the three `parents[4]` lines —
   which fixes the shipped bug on its own.
3. **A launcher that negotiates**: reuse a running dashboard if there is one,
   else serve the highest version present.
4. **Symmetrical degradation**: overseer's routes learn the contract
   chronicle's already have.
5. **A CLI contract integer**, so dashboard↔CLI version skew is legible rather
   than silently empty.
6. **WF-053 generalised** from "overseer's version" to "the best dashboard
   available", so an already-running old server self-heals.

Non-goals, deliberately: splitting `main.py` into per-plugin routers, and
splitting `styles.css` (8,904 lines). Both are real; neither is needed for
chronicle to stand alone.

---

## B1. Source layout and vendoring

```
dashboard/                       ← the only copy anyone edits
  VERSION                        ← semver for the dashboard itself
  frontend/  backend/

plugins/overseer/dashboard/      ← generated
plugins/chronicle/dashboard/     ← generated
```

`make vendor` builds the frontend once and copies `dist/` plus `backend/` into
both plugin directories. `dashboard/VERSION` is the dashboard's own version,
independent of either plugin's — it is what the launcher compares.

**A sync test fails the build if either copy drifts.** This extends the
existing `test_dist_freshness` idea (which hashes frontend sources into
`dist/.srchash`) to cover the vendored backend `.py` files as well. The copies
are generated and verified, never maintained by hand.

**Cost, stated plainly:** `dist/` is 1.1 MB, so the repo carries 2.2 MB rather
than 1.1 MB, and 1,500 lines of backend Python exist twice on disk. In
exchange the 16,219 lines of frontend source live in exactly one place.

## B2. Discovery (fixes the shipped bug)

One helper replaces `_VIGIL_CLI` / `_CENSUS_CLI` / `_CHRONICLE_CLI`:

```python
def find_plugin(name: str) -> Path | None:
    """The root of a sibling plugin, in either layout, or None.

    Walks up from this file; at each level looks for a sibling `name/`
    holding either `scripts/cli.py` (repo checkout) or
    `<version>/scripts/cli.py` (marketplace cache — highest version wins).
    """
```

No new state, no hooks, no registry, so no chicken-and-egg: a plugin does not
have to have run before it can be found. Version comparison uses the existing
`version_tuple` in `dashboard_record.py`.

**This lands first, as its own PR.** It is a bug fix that stands on its own
merit, everything below depends on it, and it should not wait behind a
restructure.

## B3. The launcher

Both plugins gain a `dashboard` skill running the same launcher:

1. Discover every installed plugin carrying `dashboard/VERSION`.
2. If a dashboard is **already listening** — the WF-053 record plus a live
   `GET /api/version` probe — open that and stop. This is the "only if it
   doesn't already exist" rule. The launcher does not judge whether the
   running one is stale: that is WF-053's job (B6), which restarts it on the
   next session start. Two mechanisms racing to restart the same server is
   exactly the situation WF-053's lock exists to avoid.
3. Otherwise exec the **highest** `VERSION` found, whichever plugin it came
   from.

The serving copy then discovers plugins for itself, so navigation is driven by
what is actually on disk. No page manifest to keep in step: install chronicle
only and the Chronicle tab is the only one; install both and you get one
dashboard with everything.

## B4. Symmetrical degradation

`run_overseer` learns the contract `run_chronicle` already has: a missing
plugin, a timeout, a non-zero exit or unparseable JSON all yield "unavailable",
never a 500. Board, card and sprint routes return an `available: false` shape.
The frontend already hides a tab on `installed: false`; that path simply gains
a second consumer.

## B5. CLI contract version

The dashboard talks to plugins by subprocess, so the contract that matters is
each **CLI's JSON output**, not the plugin's marketing version. Update one
plugin and not the other and a new dashboard may call an old CLI, or an old
dashboard may read a new one.

- Every plugin CLI reports **both** `contract: <int>` and its own `version` in
  `status --json`. The contract is bumped **only** when the CLI's JSON output
  changes incompatibly; the version is carried so a message can name what is
  actually installed.
- The vendored dashboard declares what it needs, e.g.
  `requires: {"overseer": 3, "chronicle": 2}`.
- On mismatch that plugin's pages say **"this dashboard needs a newer overseer
  (installed: 0.23.0)"** rather than rendering blank. The message names the
  installed version, never a required one — the dashboard knows the contract
  integer it needs, not which plugin release first satisfied it.

Without this, B4's degradation turns a version skew into a silently empty
board, which is worse than an error because nothing names the cause.

## B6. WF-053 generalised

`docs/superpowers/specs/2026-08-09-dashboard-server-version-restart-design.md`
already solves "the running server is older than what is installed": `serve.py`
stamps a record, a SessionStart hook probes `GET /api/version`, and restarts in
place when running < installed. Never downgrades, never auto-starts one that
was not running, fails open, detached worker, lock against concurrent sessions.

Two changes make it true across plugins rather than nearly-true:

1. `installed` is `plugin_version()` today — overseer's own. It becomes **the
   highest dashboard `VERSION` across all discovered plugins**.
2. The restart worker relaunches from `record["serve"]`, the path it started
   with. It must **re-discover** instead, or it will faithfully relaunch the
   old copy for ever.

## Edge cases

- **Update one plugin while the dashboard runs.** The running server pinned its
  plugin CLI paths at import, and old cache version directories persist (all of
  `0.10.0`–`0.15.0` are present and `.in_use` on the machine this was written
  on). So it keeps talking to the versions it booted with rather than mixing
  old UI with new data. The next session start restarts it from the best copy.
- **A version directory vanishes mid-run.** `run_*` already turns `OSError`
  into "unavailable". Fails safe.
- **The update bumps a contract.** The running old dashboard shows
  "chronicle is newer than this dashboard understands" for that window; the
  restart hook resolves it at the next session start. It self-heals and never
  lies.
- **Both plugins vendor the same `VERSION`.** Ties break on plugin name, so the
  choice is deterministic across launches.
- **Downgrade.** WF-053 never downgrades; that is preserved.
- **Neither plugin's CLI is discoverable** (a broken install). The dashboard
  still serves and every page reports unavailable, rather than failing to boot.

## Testing

- **Vendor sync** — the generated copies match `dashboard/`; the build fails if
  either drifts.
- **Discovery in both layouts** — a fabricated cache tree (`name/<version>/…`)
  and a fabricated checkout tree (`plugins/name/…`), including highest-version
  selection. This is the gap that let the bug ship, so it is the test that
  matters most.
- **Degradation** — with overseer undiscoverable, every board route returns
  `available: false` and no 500.
- **Contract mismatch** — a CLI reporting a lower contract than required
  produces the "update it" shape, not empty data.
- **Launcher** — reuses a live server; picks the highest version; ties break
  deterministically.
- **Restart worker** — re-discovers rather than reusing the recorded path.

## Rollout order

1. **Discovery fix** (B2) — own PR, own merge. Restores Chronicle, vigil and
   census for every marketplace install.
2. **Extract to `dashboard/` + vendoring** (B1) — mechanical move plus the sync
   test; no behaviour change.
3. **Degradation + contract** (B4, B5).
4. **Launcher + WF-053 generalisation** (B3, B6).
5. **chronicle gains its `dashboard` skill** — the point of the exercise.

## Open questions (resolve before build)

1. **Does the marketplace prune old cache versions?** The design leans on old
   version directories surviving for the duration of a run. Observed to be true
   here; not verified as a guarantee. If they can be pruned, the fallback is
   already safe (`OSError` → unavailable) but the "stable, not mixed" claim
   weakens to "degrades cleanly".
2. **Where does `.dashboard.json` live when overseer is absent?** It is at
   `<config>/overseer/.dashboard.json` today. A chronicle-only install has no
   overseer directory. Either the record moves to a neutral path
   (`<config>/dashboard.json`) with a migration, or chronicle writes into the
   `overseer/` directory, which is odd but harmless.
3. **Which plugin owns the port default?** Both launchers must agree, or two
   installs fight over 8765.
4. **Does `census` get the same treatment?** It is discovered by the identical
   broken walk and is fixed by B2, but it contributes no page of its own.

## Version impact

`chronicle` minor (gains a dashboard skill and a served UI); `overseer` minor
(dashboard moves to a vendored copy); marketplace minor. The discovery fix in
step 1 is a patch to `overseer` on its own.
