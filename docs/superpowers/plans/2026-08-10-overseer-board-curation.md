# Overseer Board Curation (search + filters, PR4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a client-side filter bar to the dashboard — text search (id/title/body, matched epic reveals its family), a tri-state label filter (exclude-wins/include-OR, default-hide `future`), and priority/complexity dropdowns — with state persisted to localStorage.

**Architecture:** One backend line (add `body` to the board payload) then a pure filter core (`board/cardFilter.ts`) + a persisted state hook (`board/useCardFilter.ts`) + two thin components (`FilterBar`, `LabelFilterPopover`), wired in `App` which computes the visible-id set and passes it to `Board` to filter by membership.

**Tech Stack:** Python CLI (`scripts/board.py`); React + TypeScript + Vite; vitest; pytest.

## Global Constraints

- **Almost all frontend.** The ONLY backend change is `"body": card.body` in `scripts/board.py`'s card whitelist. No new endpoints, no CLI verbs, no server-side filtering.
- **Filter predicate (verbatim from spec):**
  - `searchMatch(c)`: query empty → true; else case-insensitive substring of the trimmed query in `c.id`, `c.title`, or `c.body`.
  - `passesLabels(c)`: exclude-wins (`excludes ∩ c.labels ≠ ∅ → false`), then include-OR (`includes ≠ ∅ ∧ includes ∩ c.labels = ∅ → false`).
  - `passesPriority`/`passesComplexity`: null → pass; else strict equality.
  - No query → `show = passesLabels ∧ passesPriority ∧ passesComplexity`.
  - Query present → `show(c) = isMatchedParent(c) ∨ (c.parent ∧ isMatchedParent(parent(c))) ∨ (searchMatch(c) ∧ passesFilters(c))`, where `isMatchedParent(c) = searchMatch(c) ∧ c has ≥1 child`.
- **Default filter state:** `{ query:"", includeLabels:[], excludeLabels:["future"], priority:null, complexity:null }`. `clear` resets to THIS (not empty). `future` starts excluded.
- **Persistence key:** `localStorage["overseer_board_filter"]`; corrupt/absent → default (try/catch).
- **Run commands:** frontend `cd plugins/overseer/dashboard/frontend && PATH=$HOME/.nvm/versions/node/v22.22.1/bin:$PATH npm test [-- <file>]`; `…npx tsc --noEmit`; CLI tests pathless `cd plugins/overseer && ../../.venv/bin/python -m pytest -q`; backend `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest -q`; dist rebuild `…npm run build`.
- **Commit trailers:** end every commit with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_019MauNUBEVQLRKSrDqDnFV3`.

---

## File Structure

- `plugins/overseer/scripts/board.py` — MODIFY: add `"body": card.body` to the card dict (~line 71-90).
- `tests/overseer/test_board.py` (or the board_data test home) — MODIFY: assert `body` in each card.
- `plugins/overseer/dashboard/frontend/src/api/types.ts` — MODIFY: add `body: string` to `BoardCard`.
- `plugins/overseer/dashboard/frontend/src/board/cardFilter.ts` (+ `.test.ts`) — CREATE: pure filter logic.
- `plugins/overseer/dashboard/frontend/src/board/useCardFilter.ts` (+ `.test.ts`) — CREATE: state + localStorage.
- `plugins/overseer/dashboard/frontend/src/components/LabelFilterPopover.tsx` (+ `.test.tsx`) — CREATE.
- `plugins/overseer/dashboard/frontend/src/components/FilterBar.tsx` (+ `.test.tsx`) — CREATE.
- `plugins/overseer/dashboard/frontend/src/App.tsx` — MODIFY: own `useCardFilter`, render `FilterBar`, compute `visibleCardIds`, pass to `Board`.
- `plugins/overseer/dashboard/frontend/src/components/Board.tsx` — MODIFY: accept `visibleIds: Set<string>`, render only member cards.
- `plugins/overseer/dashboard/frontend/src/styles.css` — MODIFY: `.filter-bar` + popover styling (reuse `--qb-*` tokens).
- `dist/**` — REBUILD (final task).

---

## Task 1: Backend — `body` in the board payload

**Files:**
- Modify: `plugins/overseer/scripts/board.py` (card dict ~71-90)
- Test: `tests/overseer/test_board.py`

**Interfaces:**
- Produces: each board card dict now has `"body": <str>`. Consumed by Task 2 (`BoardCard.body`).

- [ ] **Step 1: Write the failing test** in `tests/overseer/test_board.py` (match the file's existing board_data test style — it builds a repo, adds a card with a body, calls `board_data`):

```python
def test_board_data_includes_body(tmp_repo):
    # create a card with a known body, then read board_data
    # (use the file's existing helper to add a card; then:)
    data = board_data(tmp_repo)
    card = next(c for c in data["cards"] if c["id"] == "WF-001")
    assert "body" in card
    assert card["body"]  # non-empty for a card created with a goal/body
```

(Adapt `tmp_repo`/card-creation to the existing fixtures in that test file.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd plugins/overseer && ../../.venv/bin/python -m pytest -q -k board_data_includes_body`
Expected: FAIL (`"body"` not in card).

- [ ] **Step 3: Add the field** in `board.py`, in the card dict (after `"title": card.title,`):

```python
                "body": card.body,
```

- [ ] **Step 4: Run to verify pass** — same command → PASS. Then run the whole board test module + the full CLI suite pathless to confirm no regression.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/scripts/board.py tests/overseer/test_board.py
git commit -m "feat(overseer): include card body in board payload (F2 search prep, WF-059)"
```

---

## Task 2: `cardFilter.ts` — pure filter core

**Files:**
- Modify: `src/api/types.ts` (add `body` to `BoardCard`)
- Create: `src/board/cardFilter.ts`, `src/board/cardFilter.test.ts`

**Interfaces:**
- Consumes: `BoardCard` (now with `body`).
- Produces:
  - `interface FilterState { query: string; includeLabels: string[]; excludeLabels: string[]; priority: string | null; complexity: string | null; }`
  - `export const DEFAULT_FILTER: FilterState` = `{ query:"", includeLabels:[], excludeLabels:["future"], priority:null, complexity:null }`
  - `export function distinctLabels(cards: BoardCard[]): string[]` (sorted, unique)
  - `export function visibleCardIds(cards: BoardCard[], state: FilterState): Set<string>`
  - Consumed by Tasks 3, 5, 6.

- [ ] **Step 1: Add `body` to `BoardCard`** in `src/api/types.ts` (with a short doc comment, near `labels`):

```ts
  /** Card body markdown — included in the board payload for client-side
   * search (F2). Always present (possibly ""). */
  body: string;
```

- [ ] **Step 2: Write failing tests** in `src/board/cardFilter.test.ts` (build minimal cards with a helper). Cover the predicate exhaustively:

```ts
import { describe, it, expect } from "vitest";
import { visibleCardIds, distinctLabels, DEFAULT_FILTER } from "./cardFilter";
import type { BoardCard, FilterState } from "../api/types"; // FilterState re-exported from cardFilter — import from there if not in types

const card = (o: Partial<BoardCard> & { id: string }): BoardCard => ({
  id: o.id, title: o.title ?? o.id, body: o.body ?? "", status: "planned",
  stage: null, complexity: o.complexity ?? null, priority: o.priority ?? null,
  sprint: null, parent: o.parent ?? null, depends_on: [], order: 0,
  budget: { estimate: null, actual: 0 }, is_epic: false, ready: true,
  rollup: null, created: "", updated: "", checklist: [], labels: o.labels ?? [],
});
const ids = (cards: BoardCard[], s: FilterState) => [...visibleCardIds(cards, s)].sort();
const F = (o: Partial<FilterState>): FilterState => ({ ...DEFAULT_FILTER, excludeLabels: [], ...o });

it("empty filter shows everything", () => {
  const cs = [card({ id: "A" }), card({ id: "B" })];
  expect(ids(cs, F({}))).toEqual(["A", "B"]);
});
it("search matches id/title/body, case-insensitive", () => {
  const cs = [card({ id: "A", title: "Frobnicate" }), card({ id: "B", body: "see the FROB" }), card({ id: "C", title: "nope" })];
  expect(ids(cs, F({ query: "frob" }))).toEqual(["A", "B"]);
});
it("exclude wins over include", () => {
  const cs = [card({ id: "A", labels: ["x", "y"] })];
  expect(ids(cs, F({ includeLabels: ["x"], excludeLabels: ["y"] }))).toEqual([]);
});
it("include is an OR across active labels", () => {
  const cs = [card({ id: "A", labels: ["x"] }), card({ id: "B", labels: ["z"] }), card({ id: "C", labels: ["y"] })];
  expect(ids(cs, F({ includeLabels: ["x", "y"] }))).toEqual(["A", "C"]);
});
it("priority + complexity are strict equality when set", () => {
  const cs = [card({ id: "A", priority: "P0", complexity: "L" }), card({ id: "B", priority: "P1", complexity: "L" })];
  expect(ids(cs, F({ priority: "P0" }))).toEqual(["A"]);
  expect(ids(cs, F({ complexity: "L" }))).toEqual(["A", "B"]);
});
it("a search-matched epic reveals ALL its children, bypassing an active label filter", () => {
  const cs = [
    card({ id: "EPIC", title: "Migration epic" }),
    card({ id: "K1", parent: "EPIC", labels: ["future"] }),
    card({ id: "K2", parent: "EPIC", labels: ["ui"] }),
    card({ id: "OTHER", title: "unrelated" }),
  ];
  // exclude future is active, but EPIC matches → its children (incl. future one) all show
  expect(ids(cs, F({ query: "migration", excludeLabels: ["future"] }))).toEqual(["EPIC", "K1", "K2"]);
});
it("a non-parent direct match still must pass the active filters", () => {
  const cs = [card({ id: "A", title: "frob", labels: ["future"] })];
  expect(ids(cs, F({ query: "frob", excludeLabels: ["future"] }))).toEqual([]); // gated out
  expect(ids(cs, F({ query: "frob" }))).toEqual(["A"]); // no exclude → shows
});
it("default filter hides `future` cards", () => {
  const cs = [card({ id: "A", labels: ["future"] }), card({ id: "B" })];
  expect(ids(cs, DEFAULT_FILTER)).toEqual(["B"]);
});
it("distinctLabels is sorted + unique", () => {
  expect(distinctLabels([card({ id: "A", labels: ["z", "a"] }), card({ id: "B", labels: ["a", "m"] })])).toEqual(["a", "m", "z"]);
});
```

- [ ] **Step 3: Run to verify they fail**

Run: `cd plugins/overseer/dashboard/frontend && PATH=$HOME/.nvm/versions/node/v22.22.1/bin:$PATH npm test -- src/board/cardFilter.test.ts`
Expected: FAIL (module missing).

- [ ] **Step 4: Implement** `src/board/cardFilter.ts`:

```ts
import type { BoardCard } from "../api/types";

export interface FilterState {
  query: string;
  includeLabels: string[];
  excludeLabels: string[];
  priority: string | null;
  complexity: string | null;
}

export const DEFAULT_FILTER: FilterState = {
  query: "",
  includeLabels: [],
  excludeLabels: ["future"],
  priority: null,
  complexity: null,
};

export function distinctLabels(cards: BoardCard[]): string[] {
  const set = new Set<string>();
  for (const c of cards) for (const l of c.labels) set.add(l);
  return [...set].sort();
}

function searchMatch(c: BoardCard, q: string): boolean {
  if (!q) return true;
  const n = q.toLowerCase();
  return (
    c.id.toLowerCase().includes(n) ||
    c.title.toLowerCase().includes(n) ||
    c.body.toLowerCase().includes(n)
  );
}

function passesFilters(c: BoardCard, s: FilterState): boolean {
  const labels = new Set(c.labels);
  if (s.excludeLabels.some((l) => labels.has(l))) return false;
  if (s.includeLabels.length > 0 && !s.includeLabels.some((l) => labels.has(l))) return false;
  if (s.priority !== null && c.priority !== s.priority) return false;
  if (s.complexity !== null && c.complexity !== s.complexity) return false;
  return true;
}

export function visibleCardIds(cards: BoardCard[], state: FilterState): Set<string> {
  const q = state.query.trim();
  const out = new Set<string>();
  if (!q) {
    for (const c of cards) if (passesFilters(c, state)) out.add(c.id);
    return out;
  }
  // parent id -> has children?
  const hasChildren = new Set<string>();
  for (const c of cards) if (c.parent) hasChildren.add(c.parent);
  const isMatchedParent = (c: BoardCard) => searchMatch(c, q) && hasChildren.has(c.id);
  const matchedParentIds = new Set<string>();
  for (const c of cards) if (isMatchedParent(c)) matchedParentIds.add(c.id);

  for (const c of cards) {
    if (matchedParentIds.has(c.id)) out.add(c.id); // matched epic anchor
    else if (c.parent && matchedParentIds.has(c.parent)) out.add(c.id); // its children
    else if (searchMatch(c, q) && passesFilters(c, state)) out.add(c.id); // other direct matches, gated
  }
  return out;
}
```

(Re-export `FilterState` from `types.ts` or keep it here and import from `cardFilter` in later tasks — pick one and be consistent; the tests above import `FilterState` from `../api/types`, so re-export it there, or change the test import to `./cardFilter`.)

- [ ] **Step 5: Run to verify pass** — same command → all green. Run `npx tsc --noEmit`.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/api/types.ts plugins/overseer/dashboard/frontend/src/board/cardFilter.ts plugins/overseer/dashboard/frontend/src/board/cardFilter.test.ts
git commit -m "feat(overseer-dashboard): pure cardFilter (search + tri-state labels + priority/complexity, WF-059/060/061)"
```

---

## Task 3: `useCardFilter.ts` — state + localStorage

**Files:**
- Create: `src/board/useCardFilter.ts`, `src/board/useCardFilter.test.ts`

**Interfaces:**
- Consumes: `FilterState`, `DEFAULT_FILTER` (Task 2).
- Produces: `useCardFilter()` → `{ filter: FilterState; setQuery(q); cycleLabel(label); setPriority(p); setComplexity(c); clear(); }`. `cycleLabel` advances neutral → include → exclude → neutral keeping the two arrays disjoint. Persists to `localStorage["overseer_board_filter"]`. Consumed by Task 6.

- [ ] **Step 1: Write failing tests** `src/board/useCardFilter.test.ts` (use `@testing-library/react`'s `renderHook`, `act`; clear localStorage in `beforeEach`):

```ts
it("defaults to future-excluded", () => {
  const { result } = renderHook(() => useCardFilter());
  expect(result.current.filter.excludeLabels).toEqual(["future"]);
});
it("cycleLabel goes neutral -> include -> exclude -> neutral", () => {
  const { result } = renderHook(() => useCardFilter());
  act(() => result.current.cycleLabel("ui"));
  expect(result.current.filter.includeLabels).toContain("ui");
  act(() => result.current.cycleLabel("ui"));
  expect(result.current.filter.excludeLabels).toContain("ui");
  expect(result.current.filter.includeLabels).not.toContain("ui");
  act(() => result.current.cycleLabel("ui"));
  expect(result.current.filter.includeLabels).not.toContain("ui");
  expect(result.current.filter.excludeLabels).not.toContain("ui");
});
it("clear resets to default (future excluded)", () => {
  const { result } = renderHook(() => useCardFilter());
  act(() => { result.current.setQuery("x"); result.current.cycleLabel("ui"); result.current.clear(); });
  expect(result.current.filter).toEqual({ query: "", includeLabels: [], excludeLabels: ["future"], priority: null, complexity: null });
});
it("persists to and restores from localStorage", () => {
  const { result, unmount } = renderHook(() => useCardFilter());
  act(() => result.current.setPriority("P0"));
  unmount();
  const { result: r2 } = renderHook(() => useCardFilter());
  expect(r2.current.filter.priority).toBe("P0");
});
it("falls back to default on corrupt localStorage", () => {
  localStorage.setItem("overseer_board_filter", "{not json");
  const { result } = renderHook(() => useCardFilter());
  expect(result.current.filter).toEqual(DEFAULT_FILTER);
});
```

- [ ] **Step 2: Run to verify fail** — `npm test -- src/board/useCardFilter.test.ts` → FAIL.

- [ ] **Step 3: Implement** `useCardFilter.ts`:

```ts
import { useCallback, useEffect, useState } from "react";
import { DEFAULT_FILTER, type FilterState } from "./cardFilter";

const KEY = "overseer_board_filter";

function load(): FilterState {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return DEFAULT_FILTER;
    return { ...DEFAULT_FILTER, ...(JSON.parse(raw) as Partial<FilterState>) };
  } catch {
    return DEFAULT_FILTER;
  }
}

export function useCardFilter() {
  const [filter, setFilter] = useState<FilterState>(load);
  useEffect(() => {
    try { localStorage.setItem(KEY, JSON.stringify(filter)); } catch { /* ignore */ }
  }, [filter]);

  const setQuery = useCallback((query: string) => setFilter((f) => ({ ...f, query })), []);
  const setPriority = useCallback((priority: string | null) => setFilter((f) => ({ ...f, priority })), []);
  const setComplexity = useCallback((complexity: string | null) => setFilter((f) => ({ ...f, complexity })), []);
  const clear = useCallback(() => setFilter(DEFAULT_FILTER), []);
  const cycleLabel = useCallback((label: string) => setFilter((f) => {
    const inc = new Set(f.includeLabels), exc = new Set(f.excludeLabels);
    if (!inc.has(label) && !exc.has(label)) inc.add(label);        // neutral -> include
    else if (inc.has(label)) { inc.delete(label); exc.add(label); } // include -> exclude
    else exc.delete(label);                                         // exclude -> neutral
    return { ...f, includeLabels: [...inc], excludeLabels: [...exc] };
  }), []);

  return { filter, setQuery, setPriority, setComplexity, clear, cycleLabel };
}
```

- [ ] **Step 4: Run to verify pass** — green + `tsc --noEmit`.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/board/useCardFilter.ts plugins/overseer/dashboard/frontend/src/board/useCardFilter.test.ts
git commit -m "feat(overseer-dashboard): useCardFilter state + localStorage persistence"
```

---

## Task 4: `LabelFilterPopover.tsx` — tri-state chips

**Files:**
- Create: `src/components/LabelFilterPopover.tsx`, `src/components/LabelFilterPopover.test.tsx`

**Interfaces:**
- Consumes: `labelColor` (existing `board/labelColor.ts`), `FilterState`.
- Produces: `<LabelFilterPopover labels={string[]} includeLabels={string[]} excludeLabels={string[]} onCycle={(label:string)=>void} onClose={()=>void} />` — renders each label as a chip whose visual state is neutral / include / exclude, `aria-label` like `"ui: neutral"`; clicking calls `onCycle`. Closes on Escape / outside-click (mirror an existing popover idiom, e.g. how a menu/popover already closes in the codebase).

- [ ] **Step 1: Write failing test** `LabelFilterPopover.test.tsx`:

```tsx
it("renders a chip per label and cycles on click", () => {
  const onCycle = vi.fn();
  render(<LabelFilterPopover labels={["ui", "api"]} includeLabels={[]} excludeLabels={["future"]} onCycle={onCycle} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: /^ui/i }));
  expect(onCycle).toHaveBeenCalledWith("ui");
});
it("reflects include/exclude state on the chip", () => {
  render(<LabelFilterPopover labels={["ui", "future"]} includeLabels={["ui"]} excludeLabels={["future"]} onCycle={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByRole("button", { name: /ui.*includ/i })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /future.*exclud/i })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify fail** — `npm test -- LabelFilterPopover` → FAIL.

- [ ] **Step 3: Implement** the component. Each chip: `state = includeLabels.includes(l) ? "include" : excludeLabels.includes(l) ? "exclude" : "neutral"`; class `label-filter-chip label-filter-chip--<state> label-chip--<labelColor(l)>`; `aria-label={\`${l}: ${state}\`}`; onClick → `onCycle(l)`. Wrap in a `.label-filter-popover` container; add an Escape keydown + outside-click handler calling `onClose` (copy the pattern from an existing popover/dialog in the repo). Include a small legend (✓ include / ✕ exclude) if trivial.

- [ ] **Step 4: Run to verify pass** — green + `tsc`.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/components/LabelFilterPopover.tsx plugins/overseer/dashboard/frontend/src/components/LabelFilterPopover.test.tsx
git commit -m "feat(overseer-dashboard): tri-state label filter popover (WF-060)"
```

---

## Task 5: `FilterBar.tsx` — the filter row

**Files:**
- Create: `src/components/FilterBar.tsx`, `src/components/FilterBar.test.tsx`
- Modify: `src/styles.css` (`.filter-bar` + popover styling)

**Interfaces:**
- Consumes: `FilterState` + the `useCardFilter` setters, `distinctLabels`, `LabelFilterPopover`, and `visibleCount`/`totalCount` numbers.
- Produces: `<FilterBar filter={FilterState} labels={string[]} visibleCount={number} totalCount={number} isDefault={boolean} onQuery onCycleLabel onPriority onComplexity onClear />`. Renders search input, Priority `<select>` (None/P0-P4), Complexity `<select>` (None/S/M/L/XL), a Labels button (badge = include+exclude count) toggling the popover, and a right-aligned `"{visibleCount} of {totalCount}"` + a Clear button (disabled when `isDefault`).

- [ ] **Step 1: Write failing tests** `FilterBar.test.tsx`:

```tsx
it("typing in search calls onQuery", () => {
  const onQuery = vi.fn();
  render(<FilterBar {...base} onQuery={onQuery} />);
  fireEvent.change(screen.getByLabelText(/search/i), { target: { value: "frob" } });
  expect(onQuery).toHaveBeenCalledWith("frob");
});
it("choosing a priority calls onPriority with the value (null for None)", () => {
  const onPriority = vi.fn();
  render(<FilterBar {...base} onPriority={onPriority} />);
  fireEvent.change(screen.getByLabelText(/priority/i), { target: { value: "P0" } });
  expect(onPriority).toHaveBeenCalledWith("P0");
  fireEvent.change(screen.getByLabelText(/priority/i), { target: { value: "" } });
  expect(onPriority).toHaveBeenCalledWith(null);
});
it("shows visible/total and disables Clear when default", () => {
  render(<FilterBar {...base} visibleCount={5} totalCount={20} isDefault={true} />);
  expect(screen.getByText(/5 of 20/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /clear/i })).toBeDisabled();
});
it("Labels button toggles the popover", () => {
  render(<FilterBar {...base} labels={["ui"]} />);
  fireEvent.click(screen.getByRole("button", { name: /labels/i }));
  expect(screen.getByRole("button", { name: /^ui/i })).toBeInTheDocument();
});
```

(Define a `base` props object in the test with no-op handlers + `filter: DEFAULT_FILTER`.)

- [ ] **Step 2: Run to verify fail** — FAIL.

- [ ] **Step 3: Implement** `FilterBar.tsx` per the interface; local `useState` for popover open. Priority `<select>` maps `""` → `null` in its onChange. Labels button shows `labels` count badge from `filter.includeLabels.length + filter.excludeLabels.length`.

- [ ] **Step 4: Add CSS** in `styles.css`: a `.filter-bar` flex row (matching the board's aesthetic; reuse `--qb-btn-*` for the Labels/Clear buttons like the Role A pattern, and the existing input/select styling used by e.g. `.new-card-field` or the topbar selects), plus `.label-filter-popover` / `.label-filter-chip--include|exclude|neutral`. Keep the danger-free neutral palette.

- [ ] **Step 5: Run to verify pass** — green + `tsc`.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/components/FilterBar.tsx plugins/overseer/dashboard/frontend/src/components/FilterBar.test.tsx plugins/overseer/dashboard/frontend/src/styles.css
git commit -m "feat(overseer-dashboard): filter bar (search + priority/complexity + labels + count/clear, WF-061)"
```

---

## Task 6: Wire into `App` + `Board`

**Files:**
- Modify: `src/App.tsx`, `src/components/Board.tsx`

**Interfaces:**
- Consumes: `useCardFilter` (Task 3), `visibleCardIds`/`distinctLabels` (Task 2), `FilterBar` (Task 5).
- Produces: `Board` gains a `visibleIds: Set<string>` prop and renders only member cards.

- [ ] **Step 1: Write failing integration test** in `src/App.test.tsx` (or `Board.test.tsx`) — with a mocked board containing an epic + children and an unrelated card, typing the epic's title in the search shows the epic + its children and hides the unrelated card:

```tsx
it("searching an epic's title reveals its children and hides unrelated cards", async () => {
  // render App with a mocked getBoard returning EPIC + K1(child) + OTHER
  // type "migration" into the search box
  // assert EPIC, K1 visible; OTHER not in the document
});
```

(Follow `App.test.tsx`'s existing mocking of the client/board.)

- [ ] **Step 2: Run to verify fail** — FAIL (no filter bar / no filtering).

- [ ] **Step 3: Board — accept `visibleIds` and filter.** In `Board.tsx`, add `visibleIds: Set<string>` to its props, and at the top of the render (before laying cards into lanes) filter `board.cards` to `board.cards.filter((c) => visibleIds.has(c.id))`. Use that filtered list everywhere Board currently reads `board.cards` for card placement (keep sprints/quarantined/party logic intact). Epics still group their (visible) children.

- [ ] **Step 4: App — own the filter + render the bar.** In `App.tsx`:

```tsx
const { filter, setQuery, setPriority, setComplexity, clear, cycleLabel } = useCardFilter();
const allCards = board?.cards ?? [];
const labels = useMemo(() => distinctLabels(allCards), [allCards]);
const visibleIds = useMemo(() => visibleCardIds(allCards, filter), [allCards, filter]);
const isDefaultFilter = /* deep-equal filter to DEFAULT_FILTER */;
```

Render `<FilterBar .../>` directly below `<TopBar/>` (inside `.board-region` top, or between TopBar and main), wired to the setters, `labels`, `visibleCount={visibleIds.size}`, `totalCount={allCards.length}`, `isDefault={isDefaultFilter}`. Pass `visibleIds` to `<Board visibleIds={visibleIds} .../>`. Only render the FilterBar when a real board is present (not unbegun/loading).

- [ ] **Step 5: Run to verify pass** — integration test green; full `npm test` green; `tsc --noEmit` clean.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/App.tsx plugins/overseer/dashboard/frontend/src/components/Board.tsx plugins/overseer/dashboard/frontend/src/App.test.tsx
git commit -m "feat(overseer-dashboard): wire filter bar into App + Board (WF-059/060/061)"
```

---

## Task 7: Rebuild dist + full green + freshness

- [ ] **Step 1:** full frontend suite — `…npm test` → all green.
- [ ] **Step 2:** rebuild — `…npm run build`.
- [ ] **Step 3:** backend suite incl. freshness — `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest -q` → green incl. `test_dist_freshness`.
- [ ] **Step 4:** CLI suite — `cd plugins/overseer && ../../.venv/bin/python -m pytest -q` → green.
- [ ] **Step 5:** commit dist —

```bash
git add plugins/overseer/dashboard/frontend/dist
git commit -m "chore(overseer-dashboard): rebuild dist for PR4 board curation"
```

---

## Self-review notes

- **Spec coverage:** F2 search (id/title/body + parent-reveal) → Tasks 1, 2, 6. F3 tri-state labels (exclude-wins/include-OR, default-hide future) → Tasks 2, 3, 4. F4 priority/complexity → Tasks 2, 5. Persistence → Task 3. Filter bar UI → Task 5. Body-in-payload → Task 1.
- **Type consistency:** `FilterState`/`DEFAULT_FILTER`/`visibleCardIds`/`distinctLabels` (Task 2) are consumed unchanged by Tasks 3/5/6. `BoardCard.body` (Task 2) matches `board.py`'s `"body"` (Task 1). `useCardFilter`'s returned setter names (`setQuery`/`cycleLabel`/`setPriority`/`setComplexity`/`clear`) match FilterBar's handler wiring (Task 6). `Board`'s new `visibleIds: Set<string>` prop matches `visibleCardIds`'s return type.
- **Placeholder scan:** the pure-logic tasks (2, 3) carry complete code; the UI tasks (4, 5, 6) give exact interfaces + test assertions + key snippets and defer only in-file JSX/CSS idiom to the implementer (marked as such), consistent with PR3.
