# Dashboard Markdown Rendering + Live Task Checklists Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render card markdown properly (with a rendered↔source toggle) and surface each card's task checklist on board tiles — status-styled, animated, live via polling.

**Architecture:** Feature 1 is frontend-only: a `MarkdownView` wrapper (react-markdown + remark-gfm) replaces raw `<p>` text in the drawer, plus a drawer-level segmented toggle. Feature 2 spans three layers: overseer core gains a `checklist` Card field (round-trip-safe) surfaced in `board --json`/`show --json`; the dashboard backend passes it through untouched; the frontend renders a 5-row fade-masked "focus window" on tiles, the full list in the drawer, and polls the board every 5s (paused during drags/mutations).

**Tech Stack:** React 18 + TypeScript + Vitest/RTL (frontend); Python 3.11 + FastAPI + pytest (backend); overseer core CLI (Python, no deps).

**Spec:** `docs/superpowers/specs/2026-07-12-dashboard-md-checklist-design.md` — binding for all requirements.

## Global Constraints

- Node: `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH"`; npm from `plugins/overseer/dashboard/frontend/`.
- Frontend gates: `npm run test`, `npx tsc --noEmit`. Python gates (worktree venv `/Users/philip.pryde/repos/pip-skills/.claude/worktrees/overseer-orchestration/.venv/bin/python`): `-m pytest` from the touched plugin dir, plus `-m ruff check .` and `-m mypy scripts/` for `plugins/overseer/`.
- **Committed-dist rule:** EVERY commit touching `frontend/src/**` (test files included — they are srchash inputs) bundles a fresh `npm run build` `dist/` incl. `dist/.srchash` in the SAME commit.
- No interactive element may contain another (TileShell invariant). Tile checklist rows must not be interactive.
- No new mutation endpoints; dashboard never writes ledger files.
- Statuses styled: `in_progress`, `completed`; anything else renders as pending.
- Commit trailers on every commit:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_01Xab9YwAUXi72X9JrMFPArJ`

---

### Task 1: MarkdownView + rendered↔source drawer toggle

**Files:**
- Create: `plugins/overseer/dashboard/frontend/src/components/MarkdownView.tsx`
- Create: `plugins/overseer/dashboard/frontend/src/components/MarkdownView.test.tsx`
- Modify: `plugins/overseer/dashboard/frontend/src/components/CardDetailDrawer.tsx` (body block, lines ~207-220)
- Modify: `plugins/overseer/dashboard/frontend/src/components/CardDetailDrawer.test.tsx` (toggle tests)
- Modify: `plugins/overseer/dashboard/frontend/src/styles.css` (`.md-view`, `.card-drawer__viewtoggle`, `.card-drawer__source`)
- Modify: `package.json` + `package-lock.json` (new deps)

**Interfaces:**
- Produces: `MarkdownView({ text }: { text: string })` — renders markdown to React elements inside `<div className="md-view">`. Used by Task 1 only, but Task 3's drawer checklist section sits ABOVE the body block this task touches — keep the body block self-contained.

- [ ] **Step 1: Install deps** — `npm install react-markdown remark-gfm` (from `frontend/`). Confirm both land in `package.json` dependencies.

- [ ] **Step 2: Write failing MarkdownView tests** (`MarkdownView.test.tsx`):

```tsx
import { render, screen } from "@testing-library/react";
import MarkdownView from "./MarkdownView";

describe("MarkdownView", () => {
  it("renders bold, lists and GFM task-list checkboxes", () => {
    render(<MarkdownView text={"**bold**\n\n- item\n- [x] done task"} />);
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.getAllByRole("listitem").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("checkbox", { checked: true })).toBeDisabled();
  });

  it("never executes raw HTML in card text", () => {
    const { container } = render(
      <MarkdownView text={'<script>window.__pwned = true</script><img src=x onerror="x">'} />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("clamps headings inside .md-view", () => {
    const { container } = render(<MarkdownView text={"# Big"} />);
    expect(container.querySelector(".md-view h1")).not.toBeNull();
  });
});
```

- [ ] **Step 3: Run to verify failure** — `npx vitest run src/components/MarkdownView.test.tsx`. Expected: FAIL (module not found).

- [ ] **Step 4: Implement MarkdownView**:

```tsx
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** The one place markdown rendering is configured. Raw HTML is inert by
 * default (react-markdown skips it) — do not add rehype-raw. */
function MarkdownView({ text }: { text: string }) {
  return (
    <div className="md-view">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

export default MarkdownView;
```

- [ ] **Step 5: Verify MarkdownView tests pass**, then write failing drawer toggle tests in `CardDetailDrawer.test.tsx` (match its existing mock/fixture idiom — it already mocks `getCard`):

```tsx
it("defaults to rendered view and toggles to verbatim source", async () => {
  // fixture detail: body "# Goal\nDo the *thing*", sections {goal: "Do the *thing*"}
  // open drawer, await load
  expect(screen.getByRole("button", { name: /rendered/i })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("thing").tagName).toBe("EM"); // rendered markdown
  await user.click(screen.getByRole("button", { name: /source/i }));
  const pre = screen.getByTestId("card-source");
  expect(pre.tagName).toBe("PRE");
  expect(pre).toHaveTextContent("# Goal");   // verbatim body incl. sigils
  expect(screen.queryByText("thing")?.tagName).not.toBe("EM");
});

it("resets to rendered when the drawer reopens", async () => {
  // toggle to source, close drawer, reopen same card → rendered active again
});
```

- [ ] **Step 6: Implement the toggle in CardDetailDrawer** — local state `const [view, setView] = useState<"rendered" | "source">("rendered")`, reset via the existing card-open effect (`useEffect(... setView("rendered") ..., [cardId])`). Replace the body block:

```tsx
<div className="card-drawer__viewtoggle" role="group" aria-label="Body view">
  <button type="button" aria-pressed={view === "rendered"} onClick={() => setView("rendered")}>Rendered</button>
  <button type="button" aria-pressed={view === "source"} onClick={() => setView("source")}>Source</button>
</div>
<div className="card-drawer__body">
  {view === "source" ? (
    <pre className="card-drawer__source" data-testid="card-source">{detail.body}</pre>
  ) : sectionEntries.length > 0 ? (
    sectionEntries.map(([heading, text]) => (
      <section key={heading} className="card-drawer__section">
        <h3 className="card-drawer__section-heading">{sectionLabel(heading)}</h3>
        <MarkdownView text={text} />
      </section>
    ))
  ) : (
    <MarkdownView text={detail.body} />
  )}
</div>
```

- [ ] **Step 7: Styles** — `.md-view` heading clamp (`h1,h2 { font-size: 1rem }`, `h3+ { font-size: .9rem }`), `pre/code` monospace + `overflow-x: auto`; `.card-drawer__source` monospace, pre-wrap; `.card-drawer__viewtoggle` segmented buttons with `[aria-pressed="true"]` active style. Check dark theme (existing CSS uses media/data-theme pattern — match it).

- [ ] **Step 8: Full gates** — `npm run test` (all green), `npx tsc --noEmit` clean.

- [ ] **Step 9: Build + commit** — `npm run build`; single commit: src + tests + styles + package.json + lockfile + `dist/`. Message: `feat(overseer-dashboard): render card markdown with rendered/source toggle`.

---

### Task 2: Overseer core — checklist field, round-trip, board/show JSON

**Files:**
- Modify: `plugins/overseer/scripts/models.py` (Card dataclass + `from_text` + serializer — find the `to_text`/frontmatter-emit counterpart in the same file)
- Modify: `plugins/overseer/scripts/board.py` (`board_data` card dict)
- Modify: `plugins/overseer/scripts/cli.py` (`cmd_show` detail dict, ~line 431)
- Test: `plugins/overseer/tests/test_models.py`, `plugins/overseer/tests/test_board.py` (or this plugin's equivalents — match existing test file layout)
- Test: `plugins/overseer/dashboard/backend/tests/test_board.py` (one passthrough test)

**Interfaces:**
- Produces: `Card.checklist: list[dict]` — each entry `{"task": str, "subject": str, "status": str}`; `board_data` cards and `show --json` gain `"checklist": [...]`. Task 3 consumes this shape as TS type `ChecklistEntry { task: string; subject: string; status: string }`.

**CRITICAL round-trip requirement:** card writes serialize from the dataclass. Without the field, ANY CLI mutation erases `checklist:` frontmatter (latent bug for the sync spec). A regression test proving mutation-preserves-checklist is mandatory.

- [ ] **Step 1: Failing model tests**:

```python
def test_checklist_parses_and_round_trips(tmp_path):
    text = CARD_TEMPLATE_WITH(  # match existing test fixture idiom
        "checklist:\n"
        "  - {task: '7', subject: write tests, status: in_progress}\n"
        "  - {task: '8', subject: implement, status: pending}\n"
    )
    card = Card.from_text(text)
    assert card.checklist == [
        {"task": "7", "subject": "write tests", "status": "in_progress"},
        {"task": "8", "subject": "implement", "status": "pending"},
    ]
    assert "checklist:" in card.to_text()  # survives re-serialization

def test_checklist_malformed_entries_dropped():
    # non-list checklist -> [] ; non-dict entries dropped; entries missing
    # task/subject/status dropped; status VALUES pass through verbatim
    ...

def test_mutation_preserves_checklist(tmp_path):
    # write card file with checklist, run set-field --order via cmd/store path,
    # reload file: checklist frontmatter still present
    ...
```

- [ ] **Step 2: Run to verify failure** (checklist attr missing). **Step 3: Implement** — `checklist: list[dict] = field(default_factory=list)` on Card; in `from_text`, defensive parse (spec: non-list → `[]`; keep only dicts having all of `task`/`subject`/`status`, coerce values with `str()`; status verbatim); emit in the frontmatter serializer only when non-empty (keeps existing card files byte-stable). **Step 4: board.py** — add `"checklist": card.checklist` to the card dict; document key in the `board_data` docstring shape comment. **cli.py cmd_show** — add `"checklist": card.checklist` to `data`.

- [ ] **Step 5: Backend passthrough test** (`dashboard/backend/tests/test_board.py`) — extend an existing board fixture card with checklist frontmatter; assert the API response carries it verbatim. No backend code change expected (it shells `board --json`).

- [ ] **Step 6: Gates** — overseer: pytest + ruff + `mypy scripts/`; dashboard backend: pytest. All green.

- [ ] **Step 7: Commit** — `feat(overseer): checklist frontmatter on cards — parse, round-trip, board/show JSON`. (No frontend files → no dist rebuild.)

---

### Task 3: Tile focus window + drawer checklist + status styles/animations

**Files:**
- Create: `plugins/overseer/dashboard/frontend/src/board/checklistWindow.ts` + `checklistWindow.test.ts`
- Create: `plugins/overseer/dashboard/frontend/src/components/ChecklistRows.tsx` + `ChecklistRows.test.tsx`
- Modify: `plugins/overseer/dashboard/frontend/src/api/types.ts` (BoardCard + CardDetail gain `checklist: ChecklistEntry[]`)
- Modify: `plugins/overseer/dashboard/frontend/src/components/TileShell.tsx` (render window under title, inside the non-interactive body)
- Modify: `plugins/overseer/dashboard/frontend/src/components/CardDetailDrawer.tsx` (full list section above body)
- Modify: `plugins/overseer/dashboard/frontend/src/styles.css`
- Modify: `Board.test.tsx` / `TileShell.test.tsx` (integration)

**Interfaces:**
- Consumes: `ChecklistEntry` shape from Task 2.
- Produces: `checklistWindow(entries: ChecklistEntry[], max = 5): { visible: ChecklistEntry[]; activeIndex: number | null }` (activeIndex = index within `visible`); `<ChecklistRows entries={...} windowed={boolean} />` used by both tile (windowed) and drawer (full).

- [ ] **Step 1: Failing checklistWindow tests** — active = first `in_progress`, else first non-`completed`, else last entry; window of `max` centred on active, clamped to list bounds; lists ≤ max returned whole; `activeIndex` correct after clamping; empty list → `{visible: [], activeIndex: null}`.

- [ ] **Step 2: Implement checklistWindow** (pure, no React):

```ts
export interface ChecklistEntry { task: string; subject: string; status: string; }

export function checklistWindow(entries: ChecklistEntry[], max = 5) {
  if (entries.length === 0) return { visible: [], activeIndex: null };
  let active = entries.findIndex((e) => e.status === "in_progress");
  if (active === -1) active = entries.findIndex((e) => e.status !== "completed");
  if (active === -1) active = entries.length - 1;
  const half = Math.floor(max / 2);
  const start = Math.max(0, Math.min(active - half, entries.length - max));
  const visible = entries.slice(start, start + max);
  return { visible, activeIndex: active - start };
}
```

- [ ] **Step 3: Failing ChecklistRows tests** — status classes (`--pending` for anything not in_progress/completed, incl. unknown values), completed rows have strikethrough class + check glyph, in_progress row has pulse class, appear animation class on rows whose task id is new since last render (track prev ids with a ref), no interactive elements rendered (assert no `button/a/[role]` inside), windowed mode applies edge-fade container class.

- [ ] **Step 4: Implement ChecklistRows** — `<ul className={windowed ? "checklist checklist--windowed" : "checklist"}>`; row `<li className={"checklist__row checklist__row--" + bucket(status) + (isNew ? " checklist__row--appear" : "")}>` with glyph span (`○ / ● / ✓`) + subject span (ellipsized). `bucket(s) = s === "in_progress" || s === "completed" ? s : "pending"`.

- [ ] **Step 5: Wire into TileShell** — under the title row, inside the plain (non-interactive) body: `{card.checklist?.length > 0 && <ChecklistRows entries={checklistWindow(card.checklist).visible} windowed />}` (pass activeIndex if styling needs it). Empty checklist → renders nothing (no reserved space). Extend Board.test integration: tile shows windowed subjects; clicking a row still opens the drawer (it's inert content inside the body).

- [ ] **Step 6: Drawer section** — above the body/toggle block: full `<ChecklistRows entries={detail.checklist} />` under an h3 "Tasks", only when non-empty.

- [ ] **Step 7: Styles + motion** — edge fade via `mask-image: linear-gradient(transparent, black 20%, black 80%, transparent)` on `.checklist--windowed`; `--appear` fade/slide-in keyframes (~200ms); `--in_progress` soft opacity pulse (~2s ease-in-out infinite) on the glyph, green accent (validate contrast in both themes; reuse existing status-colour variables if present); ALL motion inside `@media (prefers-reduced-motion: no-preference)` so reduce = instant. Recentre slide: CSS `transition: transform` on the list is sufficient (v1 keeps it simple — window recompute + appear classes carry the effect).

- [ ] **Step 8: Gates + build + commit** — full `npm run test`, `tsc --noEmit`, backend pytest (dist freshness), `npm run build`, ONE commit incl. dist: `feat(overseer-dashboard): live task checklist on tiles — focus window, status styles, motion`.

---

### Task 4: Board polling with drag/mutation pause

**Files:**
- Modify: `plugins/overseer/dashboard/frontend/src/board/useBoard.ts`
- Modify: `plugins/overseer/dashboard/frontend/src/board/useBoard.test.ts` (or wherever its tests live — find them first)

**Interfaces:**
- Consumes: existing `refresh()`, `inFlight` from useBoard; the drag-active signal (find how Board tracks an in-flight drag — dnd-kit `onDragStart`/`onDragEnd`; useBoard may need a `dragActive` ref setter exported to Board, or poll gating can live where both signals exist).
- Produces: no new public API beyond (if needed) `setDragActive(active: boolean)`.

- [ ] **Step 1: Failing tests (fake timers)** — mount → advance 5s → one extra `getBoard` call; advance 15s → three; while `inFlight` true → no poll call at the tick; while drag active → no poll call; unmount → timers cleared (advance after unmount adds no calls); a rejected poll leaves previous board data intact and logs nothing user-facing.

- [ ] **Step 2: Implement** — `useEffect` with `setInterval(5000)`; each tick: `if (inFlightRef.current || dragActiveRef.current) return; void refresh().catch(() => {})`. Reuse the existing epoch/staleness guards in useBoard (it already has an epoch mechanism per line ~89 — poll refreshes must respect it identically to manual refresh). Wire `dragActive` from Board's existing dnd handlers.

- [ ] **Step 3: Gates + build + commit** — full frontend gates + backend pytest, `npm run build`, commit incl. dist: `feat(overseer-dashboard): poll board every 5s, paused during drags and mutations`.

---

## Final

- Whole-feature review over the 4-task range, then push to PR #25.
- Ledger entries per task in `.superpowers/sdd/progress.md`.
