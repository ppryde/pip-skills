# Handoff: The Epic Atlas — epic-progress page for the Quest Board dashboard

## Overview
A **new page** for the overseer dashboard (a sibling view to the board, not a re-theme of it):
a gantt-esque **epic progress** view in the established Quest Board guild style. Each epic is a
**campaign trail** — a hand-wobbled dotted path marching left-to-right across a real calendar
axis. Child quests are **waypoints** cleared along the trail, the live position is a gold **party
token** standing at today, and at the end of every trail waits the epic's **beast** (a doodle
boss face, borrowed from the Boss Ledger exploration) — slain with X-eyes the day the epic
completes. Epic metadata lives in a **left rail of quest cards** speaking the board's existing
card-tile language.

## About the Design File
`Epic Atlas — Campaign Trails.html` in this folder is a **design reference created in HTML** — a
self-contained working prototype (fonts embedded, sample data, working sub-quest expand). It is
**not** production code to paste in. Recreate the look inside the dashboard frontend
(`plugins/overseer/dashboard/frontend`), using its existing React component structure, token
vocabulary (`--qb-*` in `src/styles.css`), fonts, and data layer. The prototype's invented sample
sagas (WF-027 "Re-theme the Guild Board", beasts "The Tiny-Screen Terror", etc.) are throwaway —
wire the page to the real board payload.

Two earlier explorations (`scratch/epic-atlas-mockups/`) are context, not targets: mockup 01 is
the superseded floating-tag variant of this page; mockup 03 (Boss Ledger) is where the beast
faces come from.

## Fidelity
**High-fidelity for the visual language** — every colour, font, radius, and shadow is an existing
`--qb-*` token or is specified below; match them exactly. **Medium-fidelity for trail geometry** —
the sine-wobble amplitude/frequency and beast placement may be tuned so real data lays out well,
provided the hand-drawn character survives.

## Terminology mapping (theme layer only — keep original data keys/routes)
| Original | Themed label | Notes |
|---|---|---|
| Epic (`is_epic: true` card) | a **Saga** / campaign trail | |
| Epic's child cards | **Waypoints** on the trail | one ✓ circle per done child |
| Epic completion | the **Beast** is vanquished (X-eyes) | beast face waits at trail's end |
| Card `created` date | the **camp** ⛺ (trailhead) | |
| Today | **TODAY** signpost (dashed rose line + pennant) | |
| Rollup `done/total` | quests cleared + rail progress bar | |
| Token actuals | **Gold** 🪙 (existing coin language) | |
| `depends_on` | **Locked behind** 🔒 chip (existing) | |
| `status: parked` | **camped — on hold** (party pitches ⛺ mid-trail) | |
| Future / remaining work | **uncharted ground** (faded sparse dots) | pace-projected, never a promise |
| Complexity | rarity **stars** | reuse `board/rarityStars.ts` |

## Screen layout
Full-height page under the existing sticky topbar (reuse the board's topbar; add view navigation —
see Interactions). Then a horizontally-scrollable chart region (`min-width` ~1120px):

- **Axis row** — `grid-template-columns: 264px 1fr`; empty rail cell + a day axis with weekly
  ticks (Silkscreen, 10px, letter-spacing 1px, `--qb-ink-400`), bottom border `2px dashed
  --qb-line-dashed`. The prototype uses a fixed 5-week window; production should derive the
  window from min(created)..max(today, last updated) padded ~2 days each side.
- **Saga rows** — same two-column grid, separated by `1.5px dashed --qb-line-dashed-2`.
  - **Rail (left, 264px):** one quest card per epic (spec below), vertically centred.
  - **Lane (right):** `position: relative; min-height: 104px`, containing one SVG trail. The lane
    grows with its rail card (expanded sub-quests) and the trail re-centres.
- **TODAY signpost** — one absolutely-positioned dashed rose line (`2px dashed #A8506B`, ~.75
  opacity) spanning all rows, topped by a pennant flag (rose fill, `--qb-radius-pennant`,
  Silkscreen white text "⚑ TODAY", hard shadow `0 3px 0 #8C3E56`).
- **Legend + data footnote** — small `--qb-ink-500`/`--qb-ink-400` lines under the chart
  (see prototype copy; keep the honesty note about projection).

### Rail quest card
Same sticker language as the board's card tiles:
- White card, `2px solid <accent-border>`, alternating asymmetric radius `--qb-radius-card-a`/`-b`
  by row parity, hard shadow `0 3px 0 <accent-cardshadow>`, hover lift `translateY(-3px)` (120ms,
  reduced-motion opt-in).
- Header row: `WF-id` (Silkscreen 9px, `--qb-ink-400`) + rarity stars (filled
  `--qb-gold-chip-border`, empty `--qb-star-empty`).
- Title (Baloo 2 600, 16px, `--qb-ink-900`); done epics strikethrough `--qb-ink-500` on
  `--qb-parchment-muted`.
- **"vs <Beast>"** line (Patrick Hand, `--qb-ink-400`) — the epic's beast name (see Beasts).
- Meta row: "n/m quests" · gold chip 🪙 (`--qb-gold-chip-text`) · optional 🔒 locked-behind chip
  (`--qb-locked-chip-bg`/`-text`) · **sub-quests expand button** (Role-A wobble button,
  `--qb-btn-*` system) when the epic has children.
- Progress track (7px, `--qb-progress-track`) with accent fill at `done/total`.
- **Expanded sub-quest list**: dashed-top-border section; per row a 14px rounded checkbox
  (done = accent fill + white ✓, todo = `2px solid --qb-line-dashed`), title (strikethrough when
  done), right-aligned Silkscreen date stamp (`--qb-ink-300`).
- Parked epics: `--qb-parchment-muted-2` bg, dashed border (matches board's parked tiles).

### Trail (SVG, one per lane)
- Path: gentle sine wobble (amplitude ~12px, wavelength ~300px, per-row phase seed so no two
  trails match), stroke = column-family accent fill, `stroke-width 3.5`, `stroke-linecap round`,
  `stroke-dasharray 1 9` (dotted ink).
- **Camp ⛺** at trail start (= epic `created`).
- **Waypoints**: r-8 circles at each done child's `updated` date — accent fill, darker accent
  stroke, white ✓, `<title>` tooltip "quest cleared · <date>".
- **Party token** (in-flight only): r-12 gold coin circle (`--qb-gold-coin-fill`/`-stroke`) with ⚔,
  standing at today; gentle bob animation (1.6s, reduced-motion opt-in); tooltip "the party —
  n/m quests cleared".
- **Uncharted ground** (in-flight only): continuation of the trail, `stroke-dasharray 1 16`,
  opacity .4, from today to a pace-projected end (elapsed ÷ done × remaining, clamped to the
  window). This is explicitly a guess — the footnote must say so.
- **Parked**: no projection (a camped party has no pace). Second ⛺ + "camped — on hold" label at
  the last-touched date; the beast waits a fixed ~5% of lane width beyond.
- **Beast** at trail's end: ~48px doodle SVG face (blob ellipse rotated −3°, dot eyes, grumpy
  mouth + teeth, optional horns; outline `#2C2015` — the one new colour, from the boss-plaque
  family). Alive = darker accent hue, waiting past the uncharted ground; slain (epic done) =
  accent fill, X-eyes, smile, with "+<gold> gold" (Patrick Hand, `--qb-gold-chip-text`) beside it.
  Tooltip: "<Beast> awaits (k quests stand between)" / "<Beast> — vanquished!".

## Beasts
Beast names are flavour derived **deterministically** from the epic card (stable across renders,
no storage): hash the card id into two small curated word lists, e.g. "The <epithet> <noun>"
("The Tiny-Screen Terror", "The Unmapped Vast", "The Lingering Shade"). Same hashing pattern as
`board/labelColor.ts`. Horns on/off and face hue also derive from the hash. Keep the generator
in its own tested module (`board/beastName.ts`) so a future per-epic override field can win over
the hash.

## Interactions & Behavior
- **Reach the page**: a view toggle in the topbar (Board | Atlas) using the existing Role-B
  tab treatment (`--qb-tab-*` T1 gold underline). The Atlas respects the topbar's repo/branch
  selection and the filter bar where applicable.
- **Expand sub-quests**: rail-card button toggles the child checklist; the row grows, trail
  re-centres. Multiple epics may be expanded at once (`expandedEpics: Set<string>` — the page's
  only new state; everything else derives from the existing board payload).
- **Open detail**: clicking a rail card's body opens the existing card-detail drawer for that
  epic (same `onOpen` contract as board tiles); the expand button stopPropagations (same pattern
  as `EpicCard.tsx`).
- **Tooltips**: waypoints, party token, and beast carry `<title>` tooltips with real dates/counts.
- **Motion**: party bob, card hover lift — all inside `prefers-reduced-motion: no-preference`.
- **Empty state**: no epics → parchment invitation, e.g. "No sagas yet — give a quest children
  and it becomes a campaign." (plain, directive, in-world).
- **Responsive**: the chart region is the page's one horizontal scroller (board's mobile rule).
  A dedicated mobile pass (rail collapse) is out of scope for the first card — note it, don't
  build it.

## Data mapping (all from the existing board payload — no new endpoints)
- Epics: `cards` where `is_epic`; children: `cards` where `parent === epic.id`.
- Trail start = epic `created`; waypoint positions = each done child's `updated` date.
- Walked trail end = today (in-flight), last child `updated` (done), epic `updated` (parked).
- Rollup fraction, counts = `rollup.done/total`; gold = `formatTokens(budget.actual)` (and
  children's actuals roll up already).
- 🔒 chip = `depends_on` (non-done targets only); stars = complexity via `rarityStars`.
- **No due dates exist in the ledger** — nothing on this page may imply a deadline. Projection is
  visual flavour at .4 opacity with an honest footnote.

## Design tokens
No new token groups. Reuses: page/panel parchments, ink scale, accent families (per the epic's
own stage/status, same mapping as `cardAccent.ts`), gold chip set, locked chip set, progress
track, pennant radius, wobble buttons, Silkscreen/Baloo 2/Patrick Hand/Gaegu stacks. New
declarations needed:
- `--qb-beast-ink: #2c2015` — beast outline / plaque-shadow ink (from the Boss Ledger family).
- (optional) `--qb-trail-dot: 1 9` / `--qb-trail-dot-uncharted: 1 16` if the team prefers
  dasharrays as tokens.

## Assets
- Fonts: already local (`src/assets/fonts`), no additions.
- Beast faces: inline SVG, generated — no raster assets.
- Emoji (⛺ ⚔ 🪙 ⚑): consistent with the board's existing sparing emoji use; swap for inline SVG
  where the board already has an icon.

## Files
- `Epic Atlas — Campaign Trails.html` — the chosen prototype: rail cards, trails, waypoints,
  party token, beasts, working sub-quest expand, TODAY signpost, legend + data footnote.
