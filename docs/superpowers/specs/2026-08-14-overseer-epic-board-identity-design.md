# Overseer dashboard — epic identity on the board (Workstream B, part 1)

**Date:** 2026-08-14
**Status:** design, pending implementation
**Scope:** frontend only (`plugins/overseer/dashboard/frontend/`)

## Motivation

On the swimlane board an epic is marked only by `.epic-card { border-left: 3px solid accent }` — a hairline — and, since Workstream A, it wears the exact same two-row tile as every normal quest, so epics barely stand out. The epic's "expand" control only highlights its children across lanes (via legacy-indigo `.epic-card__expand`); there is no way to see an epic's sub-quests in place on the board.

This pass gives a board epic a real visual identity and an inline sub-quest log. (Re-theming the *Atlas* view's `AtlasRailCard` expanded box — the originally-flagged legacy-indigo one — is a separate, later pass. This is board-only.)

Design locked via the visual companion. The agreed shape:

```
┌──────────────────────────────────────┐  ← seal-crest epic
│ 🗺 WF-086                       ★★★★ │  row 1: stage icon · id · stars
│ ⚑ hero assigned  P1        🪙 8.4k/20k│  row 2: hero · priority · coins (SUM)
│ The Epic Atlas — campaign trails      │  title
│ ─────────────────────────────────────│
│ 7 / 12 quests            ▾ sub-quests │  bottom bar: counts · expand
│ ┌ quest log (inset parchment) ───────┐│  (only when expanded)
│ │ ✓ Journey-view epic card    Aug 10 ││
│ │ ⚔ Monsters on the trail AT HAND ★★★││
│ │ ◦ Down-atlas orientation        ★  ││
│ │ ⛔ Legendary loot drops         ★★ ││
│ └───────────────────────────────────┘│
└──────────────────────────────────────┘
      ⚔  ← wax-seal emblem, top-right corner
```

## Non-goals (YAGNI)

- No backend/data-model change. Children are derived client-side from the existing board payload (`c.parent === epic.id`).
- No change to the Atlas view / `AtlasRailCard` (its expanded box re-theme is a later pass).
- No new expand state machine — reuse the existing `highlightedEpicId` / `onToggleEpicHighlight` as the epic's expand toggle.
- No shared `<SubquestList>` extraction with `AtlasRailCard` in this pass (revisit when the Atlas box is re-themed).
- Normal (non-epic) tiles are completely unchanged.

## Visual treatment (the "this is an epic" chrome)

All on `.epic-card` (the `variantClassName` TileShell already applies for epics) — no TileShell structural change:

- **Wax-seal emblem** — a `.epic-card::after` pseudo-element: a ~30px circle, top-right (`top:-9px; right:-9px`), radial-gradient red (`#ea7d73`→`#a83228`), 2px dark-red border, white ⚔ glyph centred, small drop shadow. Requires `.epic-card { position: relative }`.
- **Accent edge** — keep the left border but make it the gold seal-stroke: `border-left: 4px solid var(--qb-gold-coin-stroke)` (`#b5851f`).
- **Warmer body** — `.epic-card` background a touch warmer than a normal tile (e.g. `#f7ecd6`) so an epic reads as parchment-of-import, not indigo.

## Coins = rollup sum (row 2)

The epic keeps coins in the usual row-2 spot, but shows the **rollup** (sum across children), not the epic's own budget. In `TileShell`, when `card.is_epic && card.rollup`, render the coins from the rollup instead of the per-status budget logic:

```tsx
const coins =
  card.is_epic && card.rollup
    ? <BudgetMeter budget={{ estimate: card.rollup.estimate, actual: card.rollup.actual }} />
    : /* existing done/parked/active logic, unchanged */;
```

`BudgetMeter` already renders `🪙 {actual} / {estimate}` — so an epic reads `🪙 8.4k / 20k`. Normal cards are untouched.

## Bottom bar + expanded quest log (EpicCard's `children` slot)

`EpicCard` composes `TileShell` and passes its epic-specific content as `children` (rendered after the title). This **replaces** the current `.epic-card__rollup` line. It also **retires** the legacy-indigo `.epic-card__expand` header chip — the expand toggle now lives in the bottom bar.

`EpicCard` gains a new prop `childCards: BoardCard[]` (the epic's children) and needs the whole-board `cardsById` map to resolve each child's blocked state (mirrors `AtlasRailCard`).

**Bottom bar** (`.epic-card__foot`, always shown): a top dashed rule, then:
- `.epic-card__count` — `{rollup.done} / {rollup.total} quests` (left)
- `.epic-card__expand` — the toggle (right, `margin-left:auto`): `▸ sub-quests` collapsed / `▾ sub-quests` expanded. A real `<button>` (keyboard/aria `aria-expanded`), `stopPropagation` so it never opens the drawer. Only rendered when the epic has children.

**Expanded quest log** (`.epic-card__subquests`, shown when `expanded && hasChildren`): an inset-parchment `<ul>` (`background:#efe1c2`, inset shadow, never indigo). Children ordered by `orderChildrenForTrail` (done → in-progress → todo — the SAME order the Atlas trail uses, so board and atlas agree). Each row mirrors `AtlasRailCard`'s row semantics:
  - glyph: `✓` done · `†` abandoned · `⛔` blocked (todo with open deps) · `⚔` in-progress ("AT HAND") · `◦` todo
  - title: struck-through + faded for done/abandoned
  - right: a date stamp (`formatDateStamp` of `updated`) for done/abandoned, else the star-weight (`weightOf`)
  - in-progress rows show a small `AT HAND` tag

Reuse the existing helpers: `orderChildrenForTrail`, `statusGroupOf`, `weightOf`, `openDependencies` (from `board/atlasTrailLayout`), `formatDateStamp`/`parseCalendarDate` (from `board/atlasGeometry`).

## Threading the children

`EpicCard` needs its `childCards`; the board has all cards, `Lane` does not. Compute once at the board level and thread down (mirrors how `glowingIds` is threaded):

- `Board.tsx`: `const childrenByEpic = useMemo(() => groupChildrenByEpic(board.cards), [board.cards])` — a `Map<epicId, BoardCard[]>`, plus a `cardsById: Map<string, BoardCard>`. Pass both to each `<Lane>`.
- `Lane.tsx`: accept `childrenByEpic: Map<string, BoardCard[]>` and `cardsById: Map<string, BoardCard>`; for an epic card pass `childCards={childrenByEpic.get(card.id) ?? []}` and `cardsById={cardsById}` to `<EpicCard>`.
- New helper `groupChildrenByEpic(cards): Map<string, BoardCard[]>` in `board/` (pure, unit-tested).

## Expand behaviour — inline list AND cross-lane dimming (both)

The expand toggle (`highlightedEpicId === card.id`) does **both**, on the one toggle:
1. renders the epic's inline sub-quest quest-log (new, this spec), and
2. keeps the existing cross-lane child-highlight — dimming every non-child card across all lanes (unchanged).

So no existing behaviour is removed: the `highlightedEpicId` / `onToggleEpicHighlight` wiring in `Board`/`Lane` and the dimming logic stay exactly as they are; this pass only *adds* the inline list (and the bottom-bar toggle that drives the same state). (Decided at the user-review gate.)

## Testing

- `groupChildrenByEpic` — unit test: groups by `parent`, epics with no children → absent/empty, non-epic parents included correctly.
- `EpicCard` — RTL tests: renders the seal (via class), the rollup-based coins on row 2, the `N / M quests` count, the expand button only when there are children; expanding renders the sub-quest rows with the right glyph/strike/date-or-weight per child status; the expand click does not open the drawer (`stopPropagation`).
- `TileShell` — epic coins use rollup, not budget (a `is_epic` card with a rollup renders `actual/estimate` from the rollup); non-epic coins unchanged.
- Update existing `EpicCard` tests for the retired `.epic-card__rollup` line and the new bottom bar. The cross-lane child-highlight/dimming is KEPT — its existing `Board`/`Lane` tests stay green unchanged.

## Mechanics

- Frontend only. Rebuild + commit `frontend/dist/` in the same change; `test_dist_freshness` enforces it.
- This work builds directly on Workstream A (the two-row tile layout and the TileShell rollup-coins hook), which is unmerged in PR #56 (`overseer-card-header-cues`). So it **continues on that same branch / PR** — it cannot branch off raw `main` (the code it edits isn't there yet). It's the same "overseer board card UI" rolling bundle.

## Resolved decisions

| Decision | Choice |
|---|---|
| Epic distinction | Wax-seal crest (`::after`) + gold accent edge + warmer body |
| Coins | Rollup sum (`actual / estimate`) in the usual row-2 spot |
| Bottom bar | `N / M quests` count + `▸/▾ sub-quests` expand toggle |
| Expanded box | Inset-parchment quest log, trail-ordered rows, Atlas row semantics |
| Expand behaviour | Inline list AND cross-lane child-highlight (both kept) |
| Atlas `AtlasRailCard` | Out of scope — later pass |
