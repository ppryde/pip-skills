# Epic Board Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give a board epic a wax-seal visual identity, rollup-sum coins, a bottom bar (quest count + expand), and an inline quest-log of its sub-quests — while keeping the existing cross-lane child-highlight.

**Architecture:** All frontend. `EpicCard` (which composes the shared `TileShell`) grows a bottom bar + inline sub-quest list rendered in TileShell's `children` slot; the epic gets its children threaded `Board → Lane → EpicCard`. The seal/edge/tint are pure CSS on `.epic-card`. Coins for an epic come from its `rollup` instead of its own budget, via a small `TileShell` branch. Sub-quest rows reuse the Atlas trail helpers so board and atlas agree.

**Tech Stack:** React + TypeScript (Vite), Vitest + React Testing Library.

## Global Constraints

- **Frontend only.** No backend/CLI/DB/API change. Children derived client-side from `c.parent === epic.id`.
- **Node/npm via nvm, NOT on default PATH.** Prefix every build/test command with:
  `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH"`
- **All commands from repo root** `/Users/philip.pryde/repos/pip-skills` unless a `cd` is shown. Frontend dir: `plugins/overseer/dashboard/frontend`. Single test file: `cd plugins/overseer/dashboard/frontend && npx vitest run <path>`.
- **Committed-dist policy:** do NOT rebuild `dist/` per task — the final task rebuilds once and commits; `test_dist_freshness.py` gates it.
- **KEEP the cross-lane child-highlight** (`highlightedEpicId` dimming) exactly as-is — this pass only ADDS the inline list; it removes nothing from `Board`/`Lane`'s highlight wiring.
- **Reuse, don't reinvent:** `orderChildrenForTrail`, `statusGroupOf`, `weightOf`, `openDependencies` (`board/atlasTrailLayout`); `formatDateStamp`, `parseCalendarDate` (`board/atlasGeometry`). `statusGroupOf(card)` returns `"done" | "in-progress" | "todo"`.
- Branch: continue on `overseer-card-header-cues` (PR #56) — this builds on unmerged Workstream A.

---

### Task 1: `groupChildrenByEpic` helper

**Files:**
- Create: `plugins/overseer/dashboard/frontend/src/board/epicChildren.ts`
- Test: `plugins/overseer/dashboard/frontend/src/board/epicChildren.test.ts`

**Interfaces:**
- Produces: `groupChildrenByEpic(cards: BoardCard[]): Map<string, BoardCard[]>` — keyed by parent id; only entries that actually have children exist.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";
import { groupChildrenByEpic } from "./epicChildren";
import type { BoardCard } from "../api/types";

function card(id: string, parent: string | null = null): BoardCard {
  return {
    id, title: id, status: "planned", stage: null, complexity: null, priority: null,
    sprint: null, parent, depends_on: [], order: 1, budget: { estimate: null, actual: 0 },
    is_epic: false, ready: true, rollup: null, created: "", updated: "", labels: [],
    links: [], body: "", checklist: [], pr: null, claimed_by: null,
  } as BoardCard;
}

describe("groupChildrenByEpic", () => {
  it("groups children under their parent id", () => {
    const m = groupChildrenByEpic([card("E1"), card("A", "E1"), card("B", "E1"), card("C")]);
    expect(m.get("E1")?.map((c) => c.id)).toEqual(["A", "B"]);
  });
  it("omits parents with no children", () => {
    const m = groupChildrenByEpic([card("E1"), card("E2")]);
    expect(m.has("E1")).toBe(false);
    expect(m.size).toBe(0);
  });
  it("preserves input order within a parent", () => {
    const m = groupChildrenByEpic([card("B", "E1"), card("A", "E1")]);
    expect(m.get("E1")?.map((c) => c.id)).toEqual(["B", "A"]);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run src/board/epicChildren.test.ts`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

Create `src/board/epicChildren.ts`:

```ts
import type { BoardCard } from "../api/types";

/** Groups every card that has a `parent` under that parent id, preserving
 * input order. Parents with no children get no entry (so `.has(id)` is a
 * cheap "does this epic have children" check). Pure — no board knowledge
 * beyond the `parent` field. */
export function groupChildrenByEpic(cards: BoardCard[]): Map<string, BoardCard[]> {
  const byParent = new Map<string, BoardCard[]>();
  for (const c of cards) {
    if (c.parent == null) continue;
    const list = byParent.get(c.parent);
    if (list) list.push(c);
    else byParent.set(c.parent, [c]);
  }
  return byParent;
}
```

- [ ] **Step 4: Run to verify pass**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run src/board/epicChildren.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/board/epicChildren.ts plugins/overseer/dashboard/frontend/src/board/epicChildren.test.ts
git commit -m "feat(overseer-dashboard): groupChildrenByEpic helper"
```

---

### Task 2: Epic coins come from the rollup

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/src/components/TileShell.tsx` (the `coins` const, added in Workstream A)
- Test: `plugins/overseer/dashboard/frontend/src/components/TileShell.test.tsx`

**Interfaces:** none new — behavioural. An `is_epic` card with a `rollup` renders coins as `rollup.actual / rollup.estimate`; non-epics unchanged.

- [ ] **Step 1: Write the failing test**

Add to `TileShell.test.tsx` (reuse the file's `card()` override + `renderTile` harness):

```tsx
it("an epic's coins come from the rollup, not its own budget", () => {
  const { container } = renderTile(
    card({
      id: "WF-EPIC", is_epic: true,
      budget: { estimate: 100, actual: 50 },
      rollup: { done: 7, total: 12, estimate: 20000, actual: 8400 },
    })
  );
  // BudgetMeter renders formatTokens(actual) / formatTokens(estimate)
  expect(container.querySelector(".budget-meter__value")?.textContent).toContain("8.4k");
  expect(container.querySelector(".budget-meter__value")?.textContent).toContain("20k");
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run src/components/TileShell.test.tsx`
Expected: FAIL (epic shows budget 50/100, not rollup 8.4k/20k).

- [ ] **Step 3: Branch the coins const on epics**

In `TileShell.tsx`, change the `coins` computation so an epic with a rollup uses it. Prepend the epic branch to the existing conditional:

```tsx
const coins =
  card.is_epic && card.rollup ? (
    <BudgetMeter budget={{ estimate: card.rollup.estimate, actual: card.rollup.actual }} />
  ) : card.status === "done" ? (
    /* …existing done branch, unchanged… */
  ) : card.status === "parked" ? (
    /* …existing parked branch, unchanged… */
  ) : (
    <BudgetMeter budget={card.budget} />
  );
```

(Leave the done/parked/else branches exactly as they are — only the leading `card.is_epic && card.rollup ?` clause is new.)

- [ ] **Step 4: Run to verify pass**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run src/components/TileShell.test.tsx && npx tsc --noEmit`
Expected: PASS, tsc clean.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/components/TileShell.tsx plugins/overseer/dashboard/frontend/src/components/TileShell.test.tsx
git commit -m "feat(overseer-dashboard): epic tile coins come from the rollup sum"
```

---

### Task 3: EpicCard — seal, bottom bar, inline quest log

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/src/components/EpicCard.tsx`
- Modify: `plugins/overseer/dashboard/frontend/src/styles.css`
- Test: `plugins/overseer/dashboard/frontend/src/components/EpicCard.test.tsx` (create)

**Interfaces:**
- Consumes: `orderChildrenForTrail`, `statusGroupOf`, `weightOf`, `openDependencies` (`board/atlasTrailLayout`); `formatDateStamp`, `parseCalendarDate` (`board/atlasGeometry`).
- Produces: `EpicCardProps` gains `childCards?: BoardCard[]` (default `[]`) and `cardsById?: Map<string, BoardCard>` (default `new Map()`). Retires the `.epic-card__rollup` line and the `.epic-card__expand` header chip.

- [ ] **Step 1: Write the failing test**

Create `src/components/EpicCard.test.tsx`. EpicCard renders `TileShell` which needs a dnd-kit context — wrap in `DndContext` + `SortableContext` (copy the harness from `CardTile.test.tsx`/`TileShell.test.tsx`). Build a full `BoardCard` (see Task 1's `card()`), set `is_epic:true` and a `rollup`.

```tsx
it("shows the quest count and expands the sub-quest log", () => {
  const epic = card({ id: "WF-086", is_epic: true, rollup: { done: 1, total: 2, estimate: 20000, actual: 8400 } });
  const kids = [
    card({ id: "K1", parent: "WF-086", status: "done", updated: "2026-08-10" }),
    card({ id: "K2", parent: "WF-086", status: "planned", complexity: "L" }),
  ];
  const onToggle = vi.fn();
  const { rerender } = renderEpic(
    <EpicCard card={epic} childCards={kids} expanded={false} onToggleExpand={onToggle} />
  );
  expect(screen.getByText("1 / 2 quests")).toBeInTheDocument();
  const btn = screen.getByRole("button", { name: /sub-quests/i });
  fireEvent.click(btn);
  expect(onToggle).toHaveBeenCalledWith("WF-086");
  // collapsed → rows absent
  expect(screen.queryByText("K2")).toBeNull();
  // expanded → rows present, done row struck (has --done class), todo shows weight
  rerender(<EpicCard card={epic} childCards={kids} expanded={true} onToggleExpand={onToggle} />);
  expect(screen.getByText("K2")).toBeInTheDocument();
});

it("shows no expand toggle when the epic has no children", () => {
  const epic = card({ id: "WF-0", is_epic: true, rollup: { done: 0, total: 0, estimate: null, actual: 0 } });
  renderEpic(<EpicCard card={epic} childCards={[]} expanded={false} onToggleExpand={vi.fn()} />);
  expect(screen.queryByRole("button", { name: /sub-quests/i })).toBeNull();
});
```

Provide a `renderEpic` helper mirroring the existing tile harness (DndContext + SortableContext wrapping `{ui}`).

- [ ] **Step 2: Run to verify it fails**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run src/components/EpicCard.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Rewrite EpicCard's children slot**

Replace the body of `EpicCard.tsx` with the new structure. Full file:

```tsx
import type { BoardCard } from "../api/types";
import {
  orderChildrenForTrail,
  statusGroupOf,
  weightOf,
  openDependencies,
} from "../board/atlasTrailLayout";
import { formatDateStamp, parseCalendarDate } from "../board/atlasGeometry";
import TileShell from "./TileShell";

export interface EpicCardProps {
  card: BoardCard;
  accentKey?: string;
  expanded: boolean;
  onToggleExpand: (id: string) => void;
  dimmed?: boolean;
  highlighted?: boolean;
  branchDimmed?: boolean;
  branchSpotlight?: boolean;
  glowing?: boolean;
  dragDisabled?: boolean;
  onOpen?: (id: string) => void;
  colorRegistry?: Record<string, string>;
  /** The epic's own child cards (Board derives these via groupChildrenByEpic). */
  childCards?: BoardCard[];
  /** Whole-board id→card map, to resolve each child's blocked state. */
  cardsById?: Map<string, BoardCard>;
}

/**
 * Board epic tile. Composes the shared TileShell (so it inherits the two-row
 * header, rollup-sum coins, seal/edge via `.epic-card`) and ADDS, in the
 * children slot, a bottom bar (quest count + expand toggle) and — when
 * expanded — an inline quest-log of the epic's sub-quests. The expand toggle
 * drives the SAME `expanded`/`onToggleExpand` state that also highlights the
 * epic's children across lanes (Board/Lane, unchanged).
 */
function EpicCard({
  card,
  accentKey,
  expanded,
  onToggleExpand,
  dimmed = false,
  highlighted = false,
  branchDimmed = false,
  branchSpotlight = false,
  glowing = false,
  dragDisabled = false,
  onOpen,
  colorRegistry,
  childCards = [],
  cardsById = new Map(),
}: EpicCardProps) {
  const rollup = card.rollup;
  const hasChildren = childCards.length > 0;
  const ordered = hasChildren ? orderChildrenForTrail(childCards) : [];

  return (
    <TileShell
      card={card}
      accentKey={accentKey}
      variantClassName="epic-card"
      dimmed={dimmed}
      highlighted={highlighted}
      branchDimmed={branchDimmed}
      branchSpotlight={branchSpotlight}
      glowing={glowing}
      dragDisabled={dragDisabled}
      onOpen={onOpen}
      colorRegistry={colorRegistry}
    >
      <div className="epic-card__foot">
        {rollup && (
          <span className="epic-card__count">
            {rollup.done} / {rollup.total} quests
          </span>
        )}
        {hasChildren && (
          <button
            type="button"
            className="epic-card__expand"
            aria-expanded={expanded}
            onClick={(e) => {
              // Distinct from opening the drawer — expanding drives the epic's
              // sub-quest log AND its cross-lane child highlight.
              e.stopPropagation();
              onToggleExpand(card.id);
            }}
          >
            {expanded ? "▾" : "▸"} sub-quests
          </button>
        )}
      </div>

      {expanded && hasChildren && (
        <ul className="epic-card__subquests">
          {ordered.map((child) => {
            const done = child.status === "done";
            const abandoned = child.status === "abandoned";
            const group = statusGroupOf(child); // "done" | "in-progress" | "todo"
            const inProgress = group === "in-progress";
            const blocked = group === "todo" && openDependencies(child, cardsById).length > 0;

            const glyph = done ? "✓" : abandoned ? "†" : blocked ? "⛔" : inProgress ? "⚔" : "◦";
            const stamp =
              done || abandoned
                ? formatDateStamp(parseCalendarDate(child.updated))
                : "★".repeat(weightOf(child));

            const rowClassName = [
              "epic-card__subquest",
              done ? "epic-card__subquest--done" : "",
              abandoned ? "epic-card__subquest--abandoned" : "",
              inProgress ? "epic-card__subquest--prog" : "",
              blocked ? "epic-card__subquest--blocked" : "",
            ]
              .filter(Boolean)
              .join(" ");

            return (
              <li key={child.id} className={rowClassName}>
                <span className="epic-card__subquest-glyph" aria-hidden="true">
                  {glyph}
                </span>
                <span className="epic-card__subquest-title">
                  {child.title}
                  {inProgress && <span className="epic-card__athand">AT HAND</span>}
                </span>
                <span className="epic-card__subquest-meta">{stamp}</span>
              </li>
            );
          })}
        </ul>
      )}
    </TileShell>
  );
}

export default EpicCard;
```

- [ ] **Step 4: Restyle `.epic-card` (seal + edge + warmer) and add the bottom bar / quest-log CSS**

In `styles.css`, replace the existing `.epic-card`, `.epic-card__expand`, and `.epic-card__rollup` rules (currently ~lines 2881-2900, legacy indigo) with:

```css
/* Epic identity: gold accent edge, warmer parchment body, and a wax-seal
   emblem in the top-right corner. `position: relative` anchors the seal. */
.epic-card {
  position: relative;
  border-left: 4px solid var(--qb-gold-coin-stroke);
  background: #f7ecd6;
}
.epic-card::after {
  content: "⚔";
  position: absolute;
  top: -9px;
  right: -9px;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #ea7d73, #a83228);
  color: #fff;
  border: 2px solid #7a1f14;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35);
  text-align: center;
  line-height: 30px;
  font-size: 14px;
  pointer-events: none;
}

/* Bottom bar: quest count (left) + sub-quest expand toggle (right). */
.epic-card__foot {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 9px;
  padding-top: 6px;
  border-top: 1px dashed var(--qb-line-dashed);
  font-size: 0.7rem;
}
.epic-card__count {
  color: var(--qb-status-done-strong);
  font-weight: 700;
}
.epic-card__expand {
  margin-left: auto;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font: inherit;
  font-weight: 700;
  color: #7a5a1a;
}

/* Inline quest log — inset parchment, never indigo. */
.epic-card__subquests {
  list-style: none;
  margin: 8px 0 0;
  padding: 5px 8px;
  font-size: 0.7rem;
  background: #efe1c2;
  border-radius: 6px;
  box-shadow: inset 0 1px 3px rgba(120, 90, 40, 0.16);
}
.epic-card__subquest {
  display: flex;
  gap: 7px;
  align-items: baseline;
  padding: 3px 0;
  color: #4a4033;
  border-bottom: 1px dashed rgba(150, 120, 70, 0.28);
}
.epic-card__subquest:last-child { border-bottom: none; }
.epic-card__subquest-glyph { width: 14px; text-align: center; flex: none; }
.epic-card__subquest--done .epic-card__subquest-title { text-decoration: line-through; opacity: 0.65; }
.epic-card__subquest--done { color: var(--qb-status-done-strong); }
.epic-card__subquest--prog .epic-card__subquest-glyph,
.epic-card__subquest--prog .epic-card__athand { color: var(--qb-status-in-progress-strong); }
.epic-card__subquest--blocked .epic-card__subquest-glyph { color: var(--qb-status-blocked-strong); }
.epic-card__subquest-title { flex: 1; }
.epic-card__athand {
  margin-left: 6px;
  font-size: 0.55rem;
  font-weight: 700;
  letter-spacing: 0.5px;
}
.epic-card__subquest-meta { margin-left: auto; flex: none; color: #9a8a6c; font-size: 0.6rem; }
```

(If `--qb-line-dashed` or `--qb-gold-coin-stroke` don't resolve, grep `styles.css` for the correct token name and use it — do not hard-code a hex where a token exists.)

- [ ] **Step 5: Run tests + typecheck**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS / clean. If `Board.test.tsx` asserted the old `.epic-card__rollup` text (e.g. "7/12 done"), update it to the new `N / M quests` count — do not weaken it.

- [ ] **Step 6: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/components/EpicCard.tsx plugins/overseer/dashboard/frontend/src/components/EpicCard.test.tsx plugins/overseer/dashboard/frontend/src/styles.css plugins/overseer/dashboard/frontend/src/components/Board.test.tsx
git commit -m "feat(overseer-dashboard): epic seal + bottom bar + inline sub-quest log"
```

---

### Task 4: Thread children Board → Lane → EpicCard

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/src/components/Board.tsx`
- Modify: `plugins/overseer/dashboard/frontend/src/components/Lane.tsx`

**Interfaces:**
- Consumes: `groupChildrenByEpic` (Task 1); `EpicCard`'s `childCards`/`cardsById` (Task 3).
- Produces: `LaneProps` gains `childrenByEpic: Map<string, BoardCard[]>` and `cardsById: Map<string, BoardCard>`.

- [ ] **Step 1: Board computes and passes the maps**

In `Board.tsx`: import `groupChildrenByEpic` from `../board/epicChildren` and `useMemo` (already used). Compute once:

```tsx
const childrenByEpic = useMemo(() => groupChildrenByEpic(board.cards), [board.cards]);
const cardsById = useMemo(
  () => new Map(board.cards.map((c) => [c.id, c])),
  [board.cards]
);
```

Pass both to each `<Lane>` in the `visibleLanes.map` (alongside `glowingIds`):

```tsx
childrenByEpic={childrenByEpic}
cardsById={cardsById}
```

- [ ] **Step 2: Lane accepts and forwards them**

In `Lane.tsx`: add to `LaneProps`:

```tsx
childrenByEpic: Map<string, BoardCard[]>;
cardsById: Map<string, BoardCard>;
```

Import `BoardCard` from `../api/types` if not already. Destructure both in the component signature. In the epic branch of the card `.map`, pass them to `<EpicCard>`:

```tsx
childCards={childrenByEpic.get(card.id) ?? []}
cardsById={cardsById}
```

(Leave the `CardTile` branch untouched.)

- [ ] **Step 3: Run full suite + typecheck**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS / clean. If a `Board`/`Lane` render test constructs `<Lane>` directly without the new required props, pass `childrenByEpic={new Map()} cardsById={new Map()}` there.

- [ ] **Step 4: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/components/Board.tsx plugins/overseer/dashboard/frontend/src/components/Lane.tsx
git commit -m "feat(overseer-dashboard): thread epic children Board -> Lane -> EpicCard"
```

---

### Task 5: Rebuild committed dist + verify

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/dist/**` (generated)

- [ ] **Step 1: Full test + typecheck + lint**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run && npx tsc --noEmit && npm run lint`
Expected: all PASS (skip lint if no such script).

- [ ] **Step 2: Rebuild dist**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npm run build`

- [ ] **Step 3: Dist-freshness gate**

Run: `.venv/bin/python -m pytest plugins/overseer/dashboard/backend/tests/test_dist_freshness.py -q`
Expected: PASS.

- [ ] **Step 4: Smoke-test in the running app**

Refresh `http://127.0.0.1:8770/` (or relaunch via `plugins/overseer/dashboard/bringup.sh`). Confirm: an epic card shows the wax seal + gold edge + warmer body; row-2 coins read the rollup sum; the bottom bar shows `N / M quests` + `▸ sub-quests`; expanding shows the quest-log rows AND still dims non-child cards across lanes.

- [ ] **Step 5: Commit dist**

```bash
git add plugins/overseer/dashboard/frontend/dist
git commit -m "build(overseer-dashboard): rebuild dist for epic board identity"
```

---

## Self-Review

**Spec coverage:**
- Seal crest + gold edge + warmer body → Task 3 (CSS). ✓
- Rollup-sum coins on row 2 → Task 2. ✓
- Bottom bar (count + expand) → Task 3. ✓
- Inline quest-log, trail-ordered, Atlas row semantics → Task 3. ✓
- Children threaded Board→Lane→EpicCard + `groupChildrenByEpic` → Tasks 1 + 4. ✓
- Cross-lane highlight KEPT → nothing removed from Board/Lane highlight wiring (Task 4 only adds props). ✓
- Retire `.epic-card__rollup` + legacy indigo `.epic-card__expand` → Task 3. ✓
- Committed-dist rebuild → Task 5. ✓
- Atlas `AtlasRailCard` untouched → no task edits it. ✓

**Type consistency:** `groupChildrenByEpic(cards): Map<string, BoardCard[]>` (Task 1) consumed identically in Board (Task 4) and its result feeds `EpicCard.childCards` (Task 3). `cardsById: Map<string, BoardCard>` consistent Board→Lane→EpicCard. `statusGroupOf` values `"done"|"in-progress"|"todo"` used exactly. `EpicCardProps.childCards`/`cardsById` optional with defaults, so Task 3 tests render without Board.

**Placeholder scan:** no TBD/TODO; every code + test step carries real content.
