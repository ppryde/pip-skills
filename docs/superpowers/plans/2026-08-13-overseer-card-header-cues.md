# Card Header Cues Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the "Awaiting a hero"/"claimed" contradiction and add a lifecycle-stage icon (drawer + tiles) with a tap-tooltip and a 60-second post-change glow.

**Architecture:** One shared `cardIconKey(card)` helper mirrors the board's own lane bucketing so a card and its lane never show different icons. The drawer gets a static icon; tiles get an interactive icon (tap → tooltip via a generalized `InfoTooltip`, click stops propagation so the card doesn't open) plus a glow driven by an App-level hook that diffs each card's icon key across background polls. Frontend only — no backend or data-model change.

**Tech Stack:** React + TypeScript (Vite), Vitest for unit tests, hand-drawn PNG lane icons bundled by Vite.

## Global Constraints

- **Frontend only.** No backend, CLI, DB, or API-shape change. The frozen board contract is untouched.
- **Node/npm are via nvm, not on the default PATH.** Every build/test command must first run:
  `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH"`
- **All commands run from the repo root** `/Users/philip.pryde/repos/pip-skills` unless a `cd` is shown.
- **Frontend dir:** `plugins/overseer/dashboard/frontend`. Run a single test file with:
  `cd plugins/overseer/dashboard/frontend && npx vitest run <path-relative-to-frontend>`
- **Committed-dist policy:** `frontend/dist/` is committed. Do NOT rebuild it per task — the final task rebuilds it once and commits it, and the backend `test_dist_freshness.py` gate verifies `dist/.srchash` matches `src/**`. Intermediate task commits are src + tests only.
- **Reduced motion:** any animation lives inside `@media (prefers-reduced-motion: no-preference)` (existing project convention — see the checklist keyframes in `styles.css`).
- **Icon resolver is `laneIcon(key)`** (in `board/laneIcons.ts`); `STAGE_LABELS` is exported from `board/layout.ts`.

---

### Task 1: `cardIconKey` + `iconKeyLabel` helpers

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/src/board/laneIcons.ts`
- Test: `plugins/overseer/dashboard/frontend/src/board/laneIcons.test.ts` (create if absent)

**Interfaces:**
- Consumes: `laneIcon(key)`, `STAGES`/`STAGE_LABELS` from `board/layout.ts`, `BoardCard`/`Stage` from `api/types`.
- Produces:
  - `cardIconKey(card: BoardCard): string` — the icon key for a card, mirroring `groupIntoLanes` bucketing.
  - `iconKeyLabel(key: string): string` — human label for any of the 11 icon keys.

- [ ] **Step 1: Write the failing test**

Create/extend `src/board/laneIcons.test.ts`. Reuse the `card()` builder pattern from `board/vanquished.test.ts` (full `BoardCard` literal), adding `stage` where needed:

```ts
import { describe, expect, it } from "vitest";
import { cardIconKey, iconKeyLabel } from "./laneIcons";
import type { BoardCard, Stage, Status } from "../api/types";

function card(status: Status, stage: Stage | null = null): BoardCard {
  return {
    id: "WF-X", title: "x", status, stage, complexity: null, priority: null,
    sprint: null, parent: null, depends_on: [], order: 10,
    budget: { estimate: null, actual: 0 }, is_epic: false, ready: true,
    rollup: null, created: "", updated: "", labels: [], links: [],
    body: "", checklist: [], pr: null, repo: null, branch: null,
    claimed_by: null,
  } as BoardCard;
}

describe("cardIconKey", () => {
  it("planned -> backlog", () => expect(cardIconKey(card("planned"))).toBe("backlog"));
  it("blocked with no stage -> backlog", () =>
    expect(cardIconKey(card("blocked", null))).toBe("backlog"));
  it("in-flight with a stage -> that stage", () =>
    expect(cardIconKey(card("in-flight", "impl-review"))).toBe("impl-review"));
  it("blocked with a stage -> that stage", () =>
    expect(cardIconKey(card("blocked", "implementation"))).toBe("implementation"));
  it("parked -> parked", () => expect(cardIconKey(card("parked"))).toBe("parked"));
  it("done -> done", () => expect(cardIconKey(card("done"))).toBe("done"));
  it("abandoned -> abandoned", () => expect(cardIconKey(card("abandoned"))).toBe("abandoned"));
  it("done ignores a lingering stage -> done", () =>
    expect(cardIconKey(card("done", "verification"))).toBe("done"));
});

describe("iconKeyLabel", () => {
  it("labels a stage key", () => expect(iconKeyLabel("impl-review")).toBe("Impl Review"));
  it("labels a bucket key", () => expect(iconKeyLabel("backlog")).toBe("Backlog"));
  it("labels every icon key non-empty", () => {
    for (const k of ["backlog","bootstrap","planning","plan-review","implementation",
      "impl-review","verification","awaiting-merge","done","parked","abandoned","in-progress"])
      expect(iconKeyLabel(k).length).toBeGreaterThan(0);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run src/board/laneIcons.test.ts`
Expected: FAIL — `cardIconKey`/`iconKeyLabel` are not exported.

- [ ] **Step 3: Implement the helpers**

Append to `src/board/laneIcons.ts` (imports `STAGE_LABELS`, `STAGES` from `./layout` — add to the existing import if needed; `BoardCard` from `../api/types`):

```ts
import type { BoardCard } from "../api/types";
import { STAGE_LABELS, STAGES } from "./layout";

/** A card's icon key, mirroring layout.ts::groupIntoLanes bucketing exactly
 * so a card and the lane it sits in never resolve different icons. Returns
 * the SPECIFIC stage key for active staged cards (e.g. "implementation" ->
 * axe), never the synthetic "in-progress" collapse key. */
export function cardIconKey(card: BoardCard): string {
  if (card.status === "planned" || (card.status === "blocked" && card.stage == null))
    return "backlog";
  if (
    card.stage != null &&
    (card.status === "in-flight" || card.status === "blocked") &&
    (STAGES as string[]).includes(card.stage)
  )
    return card.stage;
  if (card.status === "parked") return "parked";
  if (card.status === "done") return "done";
  if (card.status === "abandoned") return "abandoned";
  return "backlog"; // defensive fallback, matches groupIntoLanes
}

/** Human label for any of the 11 icon keys — stage keys reuse STAGE_LABELS,
 * bucket keys get their lane label. */
const BUCKET_LABELS: Record<string, string> = {
  backlog: "Backlog",
  parked: "Parked",
  done: "Done",
  abandoned: "Abandoned",
  "in-progress": "In Progress",
};
export function iconKeyLabel(key: string): string {
  return (STAGE_LABELS as Record<string, string>)[key] ?? BUCKET_LABELS[key] ?? key;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run src/board/laneIcons.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/board/laneIcons.ts plugins/overseer/dashboard/frontend/src/board/laneIcons.test.ts
git commit -m "feat(overseer-dashboard): cardIconKey + iconKeyLabel helpers"
```

---

### Task 2: Fix the "Awaiting a hero" / "claimed" contradiction

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/src/components/TileShell.tsx` (~lines 210-224)
- Test: `plugins/overseer/dashboard/frontend/src/components/TileShell.test.tsx` (extend if present; else create)

**Interfaces:**
- Consumes: `BoardCard.claimed_by`, `.branch`, `.status`.
- Produces: none (behavioural change only).

- [ ] **Step 1: Write the failing test**

Add to the TileShell test file (use React Testing Library, matching existing component tests; render a tile and query for the chip text):

```tsx
it("hides Awaiting-a-hero when the card is claimed", () => {
  render(<TileShell card={card({ claimed_by: "sess-1", branch: null, status: "in-flight" })} />);
  expect(screen.queryByText(/Awaiting a hero/i)).toBeNull();
  expect(screen.getByText(/claimed/i)).toBeInTheDocument();
});

it("shows Awaiting-a-hero when unclaimed and branchless", () => {
  render(<TileShell card={card({ claimed_by: null, branch: null, status: "planned" })} />);
  expect(screen.getByText(/Awaiting a hero/i)).toBeInTheDocument();
});
```

(Use the file's existing `card({...})` override helper; if none exists, build a full `BoardCard` as in Task 1.)

- [ ] **Step 2: Run to verify the first test fails**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run src/components/TileShell.test.tsx`
Expected: the claimed-but-branchless test FAILS (chip currently shows).

- [ ] **Step 3: Add the claim guard**

In `TileShell.tsx`, change the awaiting-hero condition (currently `card.status !== "done" && card.status !== "abandoned"`) to also require no claim:

```tsx
{card.branch ? (
  <span className="branch-chip" title={card.branch}>⑃ {card.branch}</span>
) : (
  !card.claimed_by &&
  card.status !== "done" &&
  card.status !== "abandoned" && (
    <span className="awaiting-hero-chip" title="No adventurer has claimed this quest yet">
      ⚑ Awaiting a hero
    </span>
  )
)}
```

- [ ] **Step 4: Run to verify both tests pass**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run src/components/TileShell.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/components/TileShell.tsx plugins/overseer/dashboard/frontend/src/components/TileShell.test.tsx
git commit -m "fix(overseer-dashboard): claimed card no longer shows Awaiting a hero"
```

---

### Task 3: Stage icon + label in the drawer (display-only)

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/src/components/CardDetailDrawer.tsx` (~lines 361-378)
- Modify: `plugins/overseer/dashboard/frontend/src/styles.css` (title-row + stage chip)

**Interfaces:**
- Consumes: `cardIconKey`, `laneIcon` (laneIcons), `STAGE_LABELS` (layout).
- Produces: none.

- [ ] **Step 1: Add the icon + stage chip to the title row**

In `CardDetailDrawer.tsx`, import `{ cardIconKey, laneIcon }` from `../board/laneIcons` and `{ STAGE_LABELS }` from `../board/layout` (extend existing imports). In the view-mode title row (the non-editing branch, `.card-drawer__title-row`), render the icon before the `<h2>` and a stage chip after it:

```tsx
<div className="card-drawer__title-row">
  <img className="card-drawer__lifecycle-icon" src={laneIcon(cardIconKey(detail))} alt="" aria-hidden="true" />
  <h2 className="card-drawer__title">{detail.title}</h2>
  {detail.stage && (
    <span className="card-drawer__stage-chip">{STAGE_LABELS[detail.stage]}</span>
  )}
  <Button variant="neutral" onClick={() => setEditing(true)} disabled={inFlight}>Edit</Button>
</div>
```

- [ ] **Step 2: Remove the now-duplicated stage text from the facts line**

In the same file, change the status-fact span from `{detail.status}{detail.stage ? ` · ${detail.stage}` : ""}` to just `{detail.status}` (drop the ` · stage` suffix).

- [ ] **Step 3: Add styles**

Append to `styles.css`:

```css
.card-drawer__lifecycle-icon { width: 1.4em; height: 1.4em; flex: none; }
.card-drawer__stage-chip {
  font-size: 0.7rem; padding: 0.05rem 0.4rem; border-radius: 4px;
  background: var(--qb-chip-bg, rgba(0,0,0,0.06)); color: inherit;
}
@media (prefers-color-scheme: dark) {
  .card-drawer__stage-chip { background: rgba(255,255,255,0.08); }
}
```

(If `.card-drawer__title-row` is not already `display:flex; align-items:center; gap`, add those so the icon/chip align with the title.)

- [ ] **Step 4: Verify the app compiles and the drawer renders**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS / no type errors. If a drawer snapshot test exists, update it.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/components/CardDetailDrawer.tsx plugins/overseer/dashboard/frontend/src/styles.css
git commit -m "feat(overseer-dashboard): stage icon + label beside the drawer title"
```

---

### Task 4: Generalize `InfoTooltip` to accept a custom trigger

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/src/components/InfoTooltip.tsx`
- Test: `plugins/overseer/dashboard/frontend/src/components/InfoTooltip.test.tsx` (create if absent)

**Interfaces:**
- Produces: `InfoTooltipProps` gains `trigger?: React.ReactNode` (default: `<InfoIcon />`) and `triggerClassName?: string`; the trigger's click now calls `e.stopPropagation()`.

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import InfoTooltip from "./InfoTooltip";

describe("InfoTooltip custom trigger", () => {
  it("renders a custom trigger and toggles the bubble", () => {
    render(<InfoTooltip label="stage" trigger={<span>ICON</span>}>Impl Review</InfoTooltip>);
    fireEvent.click(screen.getByText("ICON"));
    expect(screen.getByRole("tooltip")).toHaveTextContent("Impl Review");
  });
  it("stops click propagation to a parent handler", () => {
    const parent = vi.fn();
    render(<div onClick={parent}><InfoTooltip label="s" trigger={<span>ICON</span>}>x</InfoTooltip></div>);
    fireEvent.click(screen.getByText("ICON"));
    expect(parent).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run src/components/InfoTooltip.test.tsx`
Expected: FAIL (`trigger` prop ignored / parent handler fires).

- [ ] **Step 3: Generalize the component**

Edit `InfoTooltip.tsx`:

```tsx
export interface InfoTooltipProps {
  label: string;
  children: React.ReactNode;
  /** Custom trigger content (default: the info glyph). The trigger is a
   * <button>; its click toggles the bubble AND stops propagation so a
   * tooltip inside a clickable parent (e.g. a card tile whose body opens a
   * drawer) does not also fire the parent's onClick. */
  trigger?: React.ReactNode;
  triggerClassName?: string;
}
```

In render, replace the trigger button:

```tsx
<button
  type="button"
  className={"info-tooltip__trigger" + (triggerClassName ? " " + triggerClassName : "")}
  aria-label={label}
  aria-expanded={open}
  onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
>
  {trigger ?? <InfoIcon />}
</button>
```

Destructure `trigger` and `triggerClassName` in the props. Existing call sites (no `trigger`) keep the info glyph — unchanged behaviour.

- [ ] **Step 4: Run to verify pass**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run src/components/InfoTooltip.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/components/InfoTooltip.tsx plugins/overseer/dashboard/frontend/src/components/InfoTooltip.test.tsx
git commit -m "feat(overseer-dashboard): InfoTooltip accepts a custom trigger + stops propagation"
```

---

### Task 5: Interactive lifecycle icon on every tile

Renders the icon inside `TileShell` (so both `CardTile` and `EpicCard` get it), wrapped in the generalized `InfoTooltip`. Replaces `CardTile`'s mobile-only `showStage` icon.

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/src/components/TileShell.tsx` (header; add `glowing` prop — wired in Task 6)
- Modify: `plugins/overseer/dashboard/frontend/src/components/CardTile.tsx` (remove `showStage` + its `headerExtra` icon)
- Modify: `plugins/overseer/dashboard/frontend/src/components/Lane.tsx` (stop passing `showStage`)
- Modify: `plugins/overseer/dashboard/frontend/src/styles.css`
- Test: `TileShell.test.tsx`

**Interfaces:**
- Consumes: `cardIconKey`, `laneIcon`, `iconKeyLabel` (laneIcons); generalized `InfoTooltip`.
- Produces: `TileShellProps` gains `glowing?: boolean` (default false). `CardTileProps.showStage` is removed.

- [ ] **Step 1: Write the failing test**

```tsx
it("renders a lifecycle icon whose tooltip names the bucket", () => {
  render(<TileShell card={card({ status: "done", stage: null })} />);
  const trigger = screen.getByLabelText("Done"); // aria-label = iconKeyLabel
  fireEvent.click(trigger);
  expect(screen.getByRole("tooltip")).toHaveTextContent("Done");
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run src/components/TileShell.test.tsx`
Expected: FAIL (no such element yet).

- [ ] **Step 3: Render the icon in TileShell**

In `TileShell.tsx`: add `glowing = false` to the destructured props and `glowing?: boolean` to `TileShellProps`. Import `{ cardIconKey, laneIcon, iconKeyLabel }` from `../board/laneIcons` and `InfoTooltip` from `./InfoTooltip`. At the START of `.card-tile__header` (before the id span):

```tsx
<InfoTooltip
  label={iconKeyLabel(cardIconKey(card))}
  triggerClassName="card-tile__lifecycle-trigger"
  trigger={
    <img
      className={"card-tile__lifecycle-icon" + (glowing ? " is-glowing" : "")}
      src={laneIcon(cardIconKey(card))}
      alt=""
      aria-hidden="true"
    />
  }
>
  {iconKeyLabel(cardIconKey(card))}
</InfoTooltip>
```

- [ ] **Step 4: Remove the old mobile-only stage icon**

- In `CardTile.tsx`: delete the `showStage` prop (from `CardTileProps` and the destructure) and the `headerExtra={ showStage && card.stage ? <img .../> : undefined }` block (drop `headerExtra` entirely from CardTile's `<TileShell>`). Remove now-unused imports (`stageIcon`, `STAGE_LABELS`) if they are no longer referenced.
- In `Lane.tsx`: remove the `showStage={...}` prop passed to `<CardTile>`.

- [ ] **Step 5: Add styles**

Append to `styles.css`:

```css
.card-tile__lifecycle-trigger {
  background: none; border: none; padding: 0; margin-right: 0.25rem;
  cursor: pointer; line-height: 0; display: inline-flex; align-items: center;
}
.card-tile__lifecycle-icon { width: 18px; height: 18px; }
@media (prefers-reduced-motion: no-preference) {
  .card-tile__lifecycle-icon.is-glowing { animation: lifecycle-glow 1.6s ease-in-out infinite; }
  @keyframes lifecycle-glow {
    0%, 100% { filter: drop-shadow(0 0 0 transparent); }
    50% { filter: drop-shadow(0 0 5px var(--card-accent-fill)); }
  }
}
```

- [ ] **Step 6: Run tests + typecheck**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS. Update any CardTile/Lane test that referenced `showStage`.

- [ ] **Step 7: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/components/TileShell.tsx plugins/overseer/dashboard/frontend/src/components/CardTile.tsx plugins/overseer/dashboard/frontend/src/components/Lane.tsx plugins/overseer/dashboard/frontend/src/styles.css plugins/overseer/dashboard/frontend/src/components/TileShell.test.tsx
git commit -m "feat(overseer-dashboard): interactive lifecycle icon on every tile (replaces mobile-only showStage)"
```

---

### Task 6: 60-second post-change glow (live, frontend-only)

**Files:**
- Create: `plugins/overseer/dashboard/frontend/src/board/useIconKeyGlow.ts`
- Test: `plugins/overseer/dashboard/frontend/src/board/useIconKeyGlow.test.ts`
- Modify: `App.tsx`, `components/Board.tsx`, `components/Lane.tsx`, `components/CardTile.tsx`, `components/EpicCard.tsx`

**Interfaces:**
- Produces:
  - `changedIconKeys(prev: Map<string,string>, next: Map<string,string>): string[]` — pure diff.
  - `useIconKeyGlow(cards: BoardCard[]): Set<string>` — ids currently glowing.
- Consumes: `cardIconKey` (Task 1). Threads `glowingIds: Set<string>` App→Board→Lane, and `glowing: boolean` Lane→CardTile/EpicCard→TileShell (mirrors how `activeBranch` becomes per-card `branchDimmed`/`branchSpotlight` in `Lane.tsx`).

- [ ] **Step 1: Write the failing test for the pure diff**

```ts
import { describe, expect, it } from "vitest";
import { changedIconKeys } from "./useIconKeyGlow";

describe("changedIconKeys", () => {
  it("reports ids whose key changed", () => {
    const prev = new Map([["a", "planning"], ["b", "done"]]);
    const next = new Map([["a", "implementation"], ["b", "done"]]);
    expect(changedIconKeys(prev, next)).toEqual(["a"]);
  });
  it("a newly-seen id is not a change (no prior key)", () => {
    expect(changedIconKeys(new Map(), new Map([["a", "done"]]))).toEqual([]);
  });
  it("no change -> empty", () => {
    const m = new Map([["a", "done"]]);
    expect(changedIconKeys(m, new Map([["a", "done"]]))).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run src/board/useIconKeyGlow.test.ts`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement the hook**

Create `src/board/useIconKeyGlow.ts`:

```ts
import { useEffect, useRef, useState } from "react";
import type { BoardCard } from "../api/types";
import { cardIconKey } from "./laneIcons";

const GLOW_MS = 60_000;

/** Pure: ids present in `next` whose key differs from `prev` (a first-seen id,
 * absent from `prev`, is a baseline, NOT a change). */
export function changedIconKeys(
  prev: Map<string, string>,
  next: Map<string, string>,
): string[] {
  const out: string[] = [];
  for (const [id, key] of next) {
    const before = prev.get(id);
    if (before !== undefined && before !== key) out.push(id);
  }
  return out;
}

/** Ids whose cardIconKey changed within the last GLOW_MS, observed live across
 * board updates (polls/mutations feed new `cards` arrays). The first observation
 * is a baseline and never glows; a reload starts a fresh baseline. */
export function useIconKeyGlow(cards: BoardCard[]): Set<string> {
  const prevKeys = useRef<Map<string, string> | null>(null);
  const [glowUntil, setGlowUntil] = useState<Map<string, number>>(new Map());

  useEffect(() => {
    const nextKeys = new Map(cards.map((c) => [c.id, cardIconKey(c)]));
    const prev = prevKeys.current;
    prevKeys.current = nextKeys;
    if (prev === null) return; // baseline
    const changed = changedIconKeys(prev, nextKeys);
    if (changed.length === 0) return;
    const until = Date.now() + GLOW_MS;
    setGlowUntil((m) => {
      const nextMap = new Map(m);
      for (const id of changed) nextMap.set(id, until);
      return nextMap;
    });
  }, [cards]);

  useEffect(() => {
    if (glowUntil.size === 0) return;
    const soonest = Math.min(...glowUntil.values());
    const t = setTimeout(() => {
      setGlowUntil((m) => {
        const now = Date.now();
        const kept = new Map<string, number>();
        for (const [id, until] of m) if (until > now) kept.set(id, until);
        return kept;
      });
    }, Math.max(0, soonest - Date.now()));
    return () => clearTimeout(t);
  }, [glowUntil]);

  const now = Date.now();
  const active = new Set<string>();
  for (const [id, until] of glowUntil) if (until > now) active.add(id);
  return active;
}
```

- [ ] **Step 4: Run to verify the diff tests pass**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run src/board/useIconKeyGlow.test.ts`
Expected: PASS.

- [ ] **Step 5: Thread `glowingIds` down to the tiles**

- `App.tsx`: `const glowingIds = useIconKeyGlow(board?.cards ?? []);` (import the hook). Pass `glowingIds={glowingIds}` to `<Board .../>`.
- `Board.tsx`: add `glowingIds: Set<string>` to its props; pass `glowingIds={glowingIds}` to each `<Lane .../>`.
- `Lane.tsx`: add `glowingIds: Set<string>` to its props. In the card `.map` (where `branchDimmed`/`branchSpotlight` are computed), add `const glowing = glowingIds.has(card.id);` and pass `glowing={glowing}` to both `<EpicCard .../>` and `<CardTile .../>`.
- `CardTile.tsx` and `EpicCard.tsx`: add `glowing?: boolean` (default false) to props and pass it straight to `<TileShell glowing={glowing} .../>`.

- [ ] **Step 6: Run full suite + typecheck**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS / no type errors.

- [ ] **Step 7: Commit**

```bash
git add plugins/overseer/dashboard/frontend/src/board/useIconKeyGlow.ts plugins/overseer/dashboard/frontend/src/board/useIconKeyGlow.test.ts plugins/overseer/dashboard/frontend/src/App.tsx plugins/overseer/dashboard/frontend/src/components/Board.tsx plugins/overseer/dashboard/frontend/src/components/Lane.tsx plugins/overseer/dashboard/frontend/src/components/CardTile.tsx plugins/overseer/dashboard/frontend/src/components/EpicCard.tsx
git commit -m "feat(overseer-dashboard): 60s lifecycle-icon glow on stage/status change"
```

---

### Task 7: Rebuild committed dist + full verification

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/dist/**` (generated)

- [ ] **Step 1: Full frontend test + typecheck + lint**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npx vitest run && npx tsc --noEmit && npm run lint`
Expected: all PASS. (If `npm run lint` is not defined, skip it.)

- [ ] **Step 2: Rebuild the committed dist**

Run: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH" && cd plugins/overseer/dashboard/frontend && npm run build`
Expected: `dist/` rebuilt, `dist/.srchash` updated.

- [ ] **Step 3: Verify the dist-freshness gate passes**

Run: `.venv/bin/python -m pytest plugins/overseer/dashboard/backend/tests/test_dist_freshness.py -q`
Expected: PASS (dist matches src hash).

- [ ] **Step 4: Smoke-test in the running app**

Refresh the dashboard at `http://127.0.0.1:8770/` (or relaunch via `plugins/overseer/dashboard/bringup.sh`). Confirm: tiles show a lifecycle icon; tapping it opens a tooltip and does NOT open the card; a claimed card shows no "Awaiting a hero"; the drawer shows the icon + stage chip beside the title.

- [ ] **Step 5: Commit the dist**

```bash
git add plugins/overseer/dashboard/frontend/dist
git commit -m "build(overseer-dashboard): rebuild dist for card header cues"
```

---

## Self-Review

**Spec coverage:**
- Change 1 (hero/claimed) → Task 2. ✓
- Change 2 (drawer icon + label, de-dup) → Task 3. ✓
- Change 3a (tile icon + tap-tooltip, stopPropagation) → Tasks 4 + 5. ✓
- Change 3b (60s glow, icon-key change, live-only, reduced-motion) → Task 6. ✓
- Shared `cardIconKey` → Task 1. ✓
- Committed-dist rebuild → Task 7. ✓
- Non-goals (no editing, no backend field, no In-Review column) — none introduced. ✓

**Type consistency:** `cardIconKey`/`iconKeyLabel` (Task 1) used identically in Tasks 3, 5, 6. `laneIcon` (not `iconForKey`) used throughout. `glowing?: boolean` added to TileShell in Task 5 and supplied in Task 6. `glowingIds: Set<string>` consistent App→Board→Lane. `InfoTooltip` `trigger`/`triggerClassName` (Task 4) consumed in Task 5.

**Placeholder scan:** no TBD/TODO; every code + test step carries real content.
