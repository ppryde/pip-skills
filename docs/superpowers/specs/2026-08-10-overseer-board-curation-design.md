# Overseer dashboard board curation — search + filters (PR4)

**Date:** 2026-08-10
**Epic:** WF-055 (overseer parity for ledger-poc 377-card migration)
**Cards:** F2 search (WF-059) · F3 label filter (WF-060) · F4 priority/complexity filters (WF-061)
**Branch:** `feat/overseer-board-curation` (base `3febf95`)

## Purpose

With 377 cards the board is unnavigable without curation. This PR adds
client-side **text search**, a tri-state **label filter** (include/exclude), and
**priority/complexity** dropdowns — the parity gaps F2–F4. No backend or CLI
changes: the board payload already carries id/title/body/labels/priority/
complexity/parent.

## Scope

In scope (almost all frontend, plus one tiny backend whitelist line):
- **Backend (one line):** add `body` to the board payload card whitelist
  (`scripts/board.py`) — the board list currently omits it (detail-only), so
  client-side body search is impossible without it. Payload grows ~850 KB raw
  (~+100–150 KB gzipped) at 377 cards — negligible for a localhost tool (no
  network; parse cost a few ms). If a future deployment binds remotely with huge
  boards, a server-side search endpoint is the follow-up; not needed now.
- A **filter bar** row below the top bar.
- Text search across id/title/body, where matching an epic reveals its children.
- Tri-state label filter (neutral → include → exclude), exclude-wins, include-OR,
  default-excluding `future`.
- Priority and complexity dropdowns.
- Filter state persisted to `localStorage`.

Out of scope: PR5 items (links, pull-children, colour registry, ledger scale,
archived-parent epics). No backend/CLI change. No server-side filtering.

## Decisions (approved)

1. **Dedicated filter bar** below the top bar (not inline, not a single popover)
   — search + priority/complexity inline, a Labels popover, and a live
   "N of M · clear" readout.
2. **Default-exclude `future` hard-coded but toggleable** — the `future` chip
   starts in the exclude state and can be cycled back like any other; no config
   read.
3. **Persist filters in `localStorage`** — survive reload and the 5s poll.
4. **A search-matched parent reveals its whole family, bypassing the other
   filters** — the parent-reveal is an override, but non-parent direct matches
   still pass the active filters, and filters remain the sole gate when no
   search is active (see the predicate below).

## Architecture

One backend line, then three small frontend units plus wiring. The logic core is
pure and heavily unit-tested; the components are thin.

### `scripts/board.py` — add `body` to the card whitelist (backend)

`board_data` builds each card dict from an explicit whitelist (currently
id/title/status/…/labels but **not** body). Add `"body": card.body`. This is the
only backend change; it does not alter any existing field. The frontend board
`Card` type gains `body: string` to match (the detail `CardDetail` already has
it).

### `board/cardFilter.ts` — pure filter logic (the core)

```ts
export interface FilterState {
  query: string;
  includeLabels: string[];   // serialisable; Sets built internally
  excludeLabels: string[];
  priority: string | null;   // "P0".."P4" or null
  complexity: string | null; // "S"|"M"|"L"|"XL" or null
}

export function visibleCardIds(cards: Card[], state: FilterState): Set<string>;
export function distinctLabels(cards: Card[]): string[]; // sorted, for the popover
```

Predicates:
- `searchMatch(c)` — `query` empty → `true`; else case-insensitive substring of
  the trimmed query in `c.id`, `c.title`, or `c.body`.
- `passesLabels(c)` — `if excludeLabels ∩ c.labels ≠ ∅ → false` (exclude wins);
  then `if includeLabels ≠ ∅ ∧ includeLabels ∩ c.labels = ∅ → false` (include is
  an OR); else `true`. (Empty label set on a card ⇒ excluded by any active
  include, passes when only excludes are active.)
- `passesPriority(c)` — `priority` null → true; else `c.priority === priority`.
- `passesComplexity(c)` — `complexity` null → true; else `c.complexity === complexity`.
- `passesFilters(c) = passesLabels ∧ passesPriority ∧ passesComplexity`.

Combined visibility:
- **No query** (`query.trim() === ""`): `show(c) = passesFilters(c)`.
- **Query present**: let `isMatchedParent(c) = searchMatch(c) ∧ c has ≥1 child`.
  ```
  show(c) =
      isMatchedParent(c)                       // the matched epic anchor (bypass filters)
    ∨ (c.parent ∧ isMatchedParent(parent(c)))  // its children (bypass filters) — F2 + Decision 4
    ∨ (searchMatch(c) ∧ passesFilters(c))      // any other direct match still gated
  ```
  This reveals a matched epic + all its children regardless of the other filters
  (no orphaned children, since the anchor is force-shown), while a non-parent
  direct hit must still pass the active filters, and filters stay meaningful.

`visibleCardIds` returns the set; the child match uses a `parent → matched?`
lookup built once per call (O(n)).

### `board/useCardFilter.ts` — state + persistence

A hook holding `FilterState`, initialised from `localStorage["overseer_board_filter"]`
(falling back to `{ query:"", includeLabels:[], excludeLabels:["future"],
priority:null, complexity:null }`) and writing back on every change. Exposes
setters (`setQuery`, `cycleLabel(label)`, `setPriority`, `setComplexity`,
`clear`). `clear` resets to the default (i.e. back to `future`-excluded, not
empty). `cycleLabel` advances neutral → include → exclude → neutral, keeping the
two Sets disjoint.

### `components/FilterBar.tsx`

The row rendered below the top bar: a search `<input aria-label="search">`, a
Priority `<select>` (None / P0–P4), a Complexity `<select>` (None / S / M / L /
XL), a **Labels ▾** button (opens the popover, badge = active-label count), and a
right-aligned **"{visible} of {total} · Clear"** (Clear disabled when the state
already equals the default). Receives `filter` state + setters + `distinctLabels`
+ the visible/total counts.

### `components/LabelFilterPopover.tsx`

Distinct labels as tri-state chips reusing `labelColor` for colour; each chip
shows its state (neutral / include ✓ / exclude ✕) and cycles on click via
`cycleLabel`. The `future` chip renders in its default exclude state. Closes on
outside-click / Escape (mirror the existing popover/dialog idiom).

### Wiring — `Board.tsx` / `App.tsx`

`App` owns `useCardFilter` and `useBoard`; computes `distinctLabels(cards)` and
`visibleCardIds(cards, filter)`; renders `FilterBar` below `TopBar`; passes the
visible set to `Board`, which renders only visible cards (epics still group their
revealed children). Lanes/party/other board mechanics unchanged.

## Data flow

`useBoard` → cards → `distinctLabels` + `visibleCardIds(cards, filterState)` →
`Board` renders the visible subset. Filter state changes are local React state
mirrored to `localStorage`; no network calls. The 5s board poll replaces
`cards`; the filter re-applies to the fresh list automatically.

## Error / edge handling

- Empty board / no labels → popover shows an empty state; counts read "0 of 0".
- A persisted label that no longer exists on any card → simply never matches;
  harmless (kept in state, not shown as a chip).
- Corrupt/absent `localStorage` value → fall back to the default state (try/catch
  around parse).
- Query with regex/glob metacharacters → treated as a literal substring (no regex).

## Testing

- **Backend** (`tests/overseer/test_board.py` or the board_data test home): assert
  `board_data` now includes `body` on each card (and existing fields unchanged).
- **`board/cardFilter.test.ts`** (the core): searchMatch across id/title/body;
  exclude-wins; include-OR; include+exclude interaction; priority/complexity
  equality; empty-query = filters-only; `isMatchedParent` reveal (epic match
  shows children while an active label/priority filter would otherwise hide
  them); non-parent direct match still gated; `distinctLabels` sorted/unique;
  default `future`-excluded hides `future` cards.
- **`board/useCardFilter.test.ts`**: default state, `cycleLabel` tri-state
  progression + Set disjointness, `clear` resets to default (future-excluded),
  localStorage round-trip + corrupt-value fallback.
- **Component tests**: FilterBar (search input, dropdowns, count readout, Clear
  enabled/disabled), LabelFilterPopover (chip cycle + colour), and one
  integration test through `Board`/`App` (typing an epic's title reveals its
  children).
- **Dist rebuild** via the nvm node path + `test_dist_freshness`.

## Review protocol

Subagent-driven (TDD); DUAL blind final review (Opus + Sonnet) adjudicated by the
user; scoped re-review of fixes; dist rebuild; then PR. Follows the WF-055
work-stream conventions.
