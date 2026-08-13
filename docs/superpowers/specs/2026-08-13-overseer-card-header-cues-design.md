# Overseer dashboard — card header cues (Workstream A)

**Date:** 2026-08-13
**Status:** design, pending implementation
**Scope:** frontend only (`plugins/overseer/dashboard/frontend/`)

## Motivation

Three small defects/gaps in how a card presents its lifecycle position:

1. A **claimed** card can simultaneously show the **"⚑ Awaiting a hero"** chip —
   a contradiction. The chip keys off *branch absence* as a proxy for
   "unclaimed", but the real claim signal is `claimed_by`. A card that is
   claimed but has no branch yet trips both.
2. The card detail **drawer** shows `stage` only as trailing read-only text
   (`{status} · {stage}`) with no icon, and no visual tie to the board's
   per-lane RPG iconography.
3. The **tiles** carry no stage/lifecycle icon at all, so you cannot tell a
   card's stage at a glance, and there is no motion cue when a card moves.

This workstream is the *labels & stage cues* half of a larger card-visual
effort. The *epic identity & theme* half (epic-vs-normal distinction, and
re-skinning the Epic Atlas expanded box off its legacy indigo paint) is a
separate spec, explored with mockups.

## Non-goals (YAGNI)

- No stage **editing** from the drawer or tile (display-only everywhere).
- No backend / data-model change. No `stage_changed_at` field; no new API
  shape. The frozen board contract is untouched.
- No "In Review" column and no change to lane grouping.
- No per-icon bespoke animation (the icons are single raster PNGs — animation
  is a uniform CSS transform, not internal frame animation).
- No change to the vanquished pill's filtered/unfiltered behaviour.

## Shared foundation: `cardIconKey(card)`

Both the drawer (Change 2) and the tiles (Change 3) need to derive an icon
key from a **card** (today `laneIconKey` only derives one from a `Lane`).

Add `cardIconKey(card: BoardCard): string` to `board/laneIcons.ts`, mirroring
`layout.ts::groupIntoLanes`'s own bucketing so a card and the lane it sits in
can never resolve to different icons:

```
planned  OR (blocked AND stage == null)      → "backlog"
status ∈ {in-flight, blocked} AND stage set  → stage            // e.g. "impl-review" (the axe/etc.)
parked                                        → "parked"
done                                          → "done"
abandoned                                     → "abandoned"
(fallback)                                    → "backlog"
```

Notes:
- Returns the **specific** stage key (e.g. `implementation` → axe), never the
  synthetic `in-progress` collapse key — the whole point is to distinguish
  `plan-review` from `impl-review` etc.
- The existing `iconForKey(key)` already resolves any of these keys to a
  bundled icon URL and falls back to the backlog icon for anything unknown.
- Unit-tested against every `(status, stage)` combination the model permits.

## Change 1 — resolve the "Awaiting a hero" / "claimed" contradiction

**File:** `components/TileShell.tsx` (the branch/awaiting-hero chip block,
currently ~lines 210-224).

**Rule (approach A — `claimed_by` is authoritative):**

```
show "⚑ Awaiting a hero"  ⟺  !card.claimed_by
                              && !card.branch
                              && card.status ∉ {done, abandoned}
```

Only the `!card.claimed_by` clause is added. Effects:
- Claimed card → shows only the "claimed" badge, never "Awaiting a hero".
- Unclaimed, branchless, active card → still "Awaiting a hero" (unchanged).
- `branch` remains the secondary "work has a home" signal (branch chip), so a
  card with a branch shows the branch chip as before.

**Tests:** extend the TileShell tests to cover the claimed-but-branchless case
(asserts no awaiting-hero chip) alongside the existing unclaimed/branchless
(asserts chip present) and done/abandoned (asserts no chip) cases.

## Change 2 — stage icon + label in the drawer (display-only)

**File:** `components/CardDetailDrawer.tsx` (view-mode title row + facts row,
currently ~lines 361-378).

- Render a small lane icon (`iconForKey(cardIconKey(detail))`) immediately
  **before** the `<h2>` title in `.card-drawer__title-row`.
- Render the human stage label (`STAGE_LABELS[detail.stage]`) as a quiet chip
  **after** the title. Omit the chip entirely when `detail.stage` is null (no
  empty "·" artifact).
- **De-duplicate:** drop the trailing `` · {detail.stage} `` from the
  `.card-drawer__status-fact` span (line 377), leaving just `{detail.status}`
  there. Stage's new home is beside the title.
- Display-only — no interaction in the drawer (you are already inside the
  card here, so there is no card-open to override).

**Styling:** icon sized to the title's cap-height (~1.1em), `flex`-aligned in
the title row; stage chip reuses the existing quiet-chip look (not the legacy
indigo). Light/dark both covered.

## Change 3 — stage icon on the tiles: tap-tooltip + 60s glow

**File:** `components/TileShell.tsx` (card header, near the title) + a small
amount of `App`/poll-adjacent state for glow detection.

### 3a. The icon + tap-to-tooltip (overrides card-open)

- Render `iconForKey(cardIconKey(card))` in the tile header, near the title.
- Wrap it in the existing **`InfoTooltip`** component (tap/click-to-toggle
  popover, tap-outside to dismiss — the same idiom already used elsewhere).
- The icon's click handler calls `e.stopPropagation()` so the tap opens the
  tooltip and does **not** bubble to the tile body's `onOpen` (drawer-open) —
  the identical trick the PR chip already uses (`TileShell.tsx:192`).
- Tooltip content: the human label for whatever the icon represents — the
  stage label if `stage` is set, else the status-bucket label
  (Backlog/Parked/Done/Abandoned). One helper, `iconKeyLabel(key)`, maps the
  11 icon keys to display strings (reuses `STAGE_LABELS` for the 7 stages).

### 3b. The 60-second post-change glow (live-only, frontend-only)

- The board already background-polls (`board/useBoard.ts`, paused during
  drags/mutations). On each successful board update, compare each card's
  **current `cardIconKey`** against its previous value, tracked in a ref keyed
  by card id.
- When a card's icon key **changes** between two observations, record
  `glowUntil[cardId] = Date.now() + 60_000` in component state and render the
  glow while `Date.now() < glowUntil`. A single `setTimeout` per newly-glowing
  card clears it (and re-renders) at expiry; no global ticking clock.
- **Trigger = icon-key change** (stage *or* status-bucket transition), NOT
  strictly `stage`. Rationale: `stage` is populated on ~1/90 cards today, so a
  strict-stage trigger would essentially never fire; icon-key change captures
  every visible lifecycle move (planned→done, →parked, plan-review→impl-review,
  …) with the same "something moved" meaning. Narrowing to stage-only later is
  a one-line predicate change.
- **First observation is a baseline, not a change:** the very first poll/mount
  establishes the previous-key map and never glows — you only glow transitions
  you actually witness in an open tab. A reload resets the baseline (accepted
  trade-off: the glow is live-only and does not survive reload; a change that
  happened before load will not glow).
- **Reduced motion:** the glow lives entirely inside
  `@media (prefers-reduced-motion: no-preference)` (the project's existing
  convention — see the checklist keyframes). With reduced motion the icon
  simply updates with no animation.

**Where the glow state lives:** the previous-key ref + `glowUntil` map are
owned at the level that holds the board data and feeds the tiles (App /
board-consumer), and a per-card `glowing: boolean` is threaded into
`TileShell`. Keeping detection in one place (not per-tile) means a tile cannot
miss a change that happened while it was unmounted/rescrolled, and there is a
single source of truth for "what key did this card last have".

## Testing

- `cardIconKey` — unit test across all `(status, stage)` permutations,
  including the `blocked`-with/without-stage split and unknown-stage fallback.
- `iconKeyLabel` — unit test all 11 keys resolve to a non-empty label.
- Change 1 — TileShell chip tests (claimed-but-branchless → no chip).
- Change 3b glow detection — unit-test the pure "did the key change vs the
  previous map" reducer (baseline → no glow; changed → glowUntil set;
  unchanged → untouched) without timers/DOM.
- Existing drawer/tile snapshot/behaviour tests updated for the new icon.

## Mechanics

- Frontend only. Per the committed-dist policy, rebuild `frontend/dist/` and
  commit it in the same change (`npm run build`); `test_dist_freshness.py`
  enforces this.
- No backend, no CLI, no DB.

## Resolved decisions

| Decision | Choice |
|---|---|
| Hero chip authority | Approach A — `claimed_by` wins; add `!claimed_by` clause |
| Stage in drawer | Display-only (icon + label), de-dup the status-fact text |
| Stage on tiles | Icon + tap-tooltip (stopPropagation) + 60s glow |
| Glow persistence | Live-only, frontend-only (no `stage_changed_at`) |
| Glow trigger | Icon-key change (stage *or* status bucket), not strict-stage |
