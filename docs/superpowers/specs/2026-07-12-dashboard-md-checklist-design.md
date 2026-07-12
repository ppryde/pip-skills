# Overseer Dashboard — Markdown Rendering + Live Task Checklists — Design Spec

**Date:** 2026-07-12
**Status:** Approved design (user approved both features; "spec it and ship it")
**Surface:** `plugins/overseer/dashboard/` (frontend + one small backend addition)
**Related:** `2026-07-12-overseer-task-checklist-sync-design.md` (defines the `checklist:`
frontmatter this dashboard work renders; the sync side is NOT part of this build)

## Context

Two dashboard gaps, both user-requested after first live use:

1. Card body/sections are markdown source rendered as plain `<p>` text — headings, lists, and
   checkboxes arrive as raw sigils. Editing is deliberately deferred (render-only v1), but the UI
   must keep a seam where edit mode later slots in.
2. The approved card↔task sync spec makes each card's `checklist:` frontmatter the durable
   projection of its live Claude Code tasks — and the dashboard should surface that: tasks visible
   on tiles, styled by status, with motion that makes the board feel alive.

Discoveries that shaped the design (verified in code, not assumed):

- The board payload is a **curated projection** (`BoardCard` in `api/types.ts`); it does not carry
  frontmatter through, so `checklist` needs explicit backend serialization. "Zero new plumbing"
  from the sync spec was optimistic.
- The board has **no polling** — refresh is manual (TopBar) + refresh-on-mutation. Live task
  appearance therefore requires an auto-refresh loop, and it must pause during drags: the final
  WF-005 review documented a drag/refresh race (spurious reconcile toast) that polling would
  otherwise surface constantly.
- The `checklist` CLI verb / sync hook do not exist yet. This build renders the spec'd shape and
  shows nothing until sync lands. Fixtures make it testable now.
- All mutations remain out of scope: no new write endpoints; this is a read/render feature.

## Feature 1 — Markdown rendering with a rendered ↔ source toggle

### Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Renderer | `react-markdown` + `remark-gfm` (new runtime deps) | Renders to React elements — **no `innerHTML` anywhere**, raw HTML in card text is inert by default (agents write these files; XSS posture matters). GFM covers task lists/tables/strikethrough that real cards contain. ~35KB gzip on a 204KB bundle. |
| Rejected | `marked`+DOMPurify (innerHTML seam, sanitizer to maintain), hand-rolled regex renderer (markdown edge-case tar pit) | |
| Edit mode | **Deferred.** v1 is render-only; the toggle is the seam edit mode later fills. | User decision. |
| Toggle | One drawer-level control: `Rendered / Source`. Default Rendered; resets to Rendered on each drawer open (component state, not persisted). | |
| Source view | `detail.body` verbatim in a read-only monospace `<pre>` — the true file source, NOT the re-joined section splits. | Lossless; exactly what edit mode will later make writable. |
| Rendered view | Existing per-section layout (`sectionEntries` → h3 label + content), but content goes through a new `MarkdownView` component instead of `<p>`. No-sections fallback renders `detail.body` through `MarkdownView`. | |

### Component

`src/components/MarkdownView.tsx` — thin wrapper over `ReactMarkdown` with `remark-gfm`; the ONE
place plugins and rendering config live. Class-scoped styles (`.md-view`) clamp heading sizes so a
stray `#` inside a card cannot dwarf the drawer chrome; code blocks/pre get `overflow-x: auto`.
Both themes styled.

### Toggle markup

Two real sibling `<button>`s (segmented control) in the drawer body header. Honours the
no-nested-interactive invariant established in the TileShell restructure (no interactive element
may contain another). `aria-pressed` on the active segment.

### Tests

- Markdown renders: bold, list, GFM task-list checkbox each produce the right elements.
- Toggle: Source shows `detail.body` verbatim (monospace `<pre>`); toggling back re-renders.
- Default is Rendered; reopening the drawer resets to Rendered.
- **Security regression:** `<script>` / raw HTML in card text renders as inert text, never as
  elements.
- No-sections fallback renders body through MarkdownView.

## Feature 2 — Live task checklists on cards

### Data plumbing (backend)

- Board endpoint: each card gains `checklist: [{task: str, subject: str, status: str}, ...]`,
  read from the card's `checklist:` frontmatter. Absent/malformed frontmatter → `[]`; entries
  that are not dicts or lack `task`/`subject`/`status` are dropped (defensive, never 500). Status
  VALUES are passed through verbatim — semantic validation is the frontend's styling fallback.
- Card-detail endpoint gains the same field (drawer shows the full list).
- Statuses passed through verbatim; the frontend treats anything other than
  `in_progress`/`completed` as pending-styled. (`deleted` never appears — the sync verb removes
  those entries.)
- Backend tests: fixture cards with checklists (happy path, absent, malformed variants).

### Tile viewport (the focus window)

- Up to **5 task rows** on the tile, auto-centred on the **active task**: the first `in_progress`
  entry, else the first `pending` (the "you are here" boundary), else the tail (all completed).
- Outermost visible rows fade via CSS gradient mask — reads as a scroller peeking at the live spot
  in a longer list. Windowing is a **pure function** `checklistWindow(entries, max=5) →
  {visible, activeIndex}` in `src/board/` — unit-testable without rendering.
- Passive: no scroll interaction on the tile; the whole tile still opens the drawer (row content
  must not introduce interactive elements — preserves the no-nested-interactive invariant).
- Row = status glyph + task subject, one line, ellipsized.
- Cards with an empty checklist render exactly as today (no reserved space).

### Status styling & motion

- `pending`: muted. `in_progress`: green accent + soft breathing pulse. `completed`: dimmed +
  strikethrough + check glyph.
- New rows (task id not present at previous render) fade/slide in. Active-task changes re-centre
  the window with a short slide. Implementation detail (CSS transition vs keyed animation) is the
  implementer's choice, but appearance/recentre must be observable as class hooks for tests.
- **`prefers-reduced-motion: reduce` disables pulse and slides** (instant state changes).
- Colours validated in both light and dark themes.

### Liveness (polling)

- `useBoard` gains an interval poll: `refresh()` every **5s**.
- **Paused while:** a drag is in flight, or a mutation is in flight (`inFlight`). Resumes after.
- A failed poll keeps the last good board silently (no error toast spam); the existing
  "as of last refresh" label keeps working unchanged.
- Poll starts on mount, cleared on unmount. No config surface in v1 (constant).

### Drawer

- Full checklist as a section above the body (same row styling, no viewport/fade, no animation
  requirements beyond status styles).

### Tests

- `checklistWindow`: centring on in_progress / first-pending / all-completed; lists shorter than
  5; ties (multiple in_progress → first).
- Row status classes per status; unknown status → pending styling.
- Appear/recentre class hooks present; reduced-motion path (class or media-query behaviour) has at
  least a smoke test.
- Poll: advances fake timers → fetch called; dragging or inFlight → poll skipped; unmount clears.
- Backend: checklist serialization happy/absent/malformed.

## Constraints (binding, from the repo's standing rules)

- Gates: frontend `npm run test` + `npx tsc --noEmit` (node via
  `export PATH="$HOME/.nvm/versions/node/v22.22.1/bin:$PATH"`); backend pytest via the worktree
  venv. All green before any push.
- **Committed-dist rule:** every commit touching `frontend/src/**` — *including test files, which
  are srchash inputs* — bundles a fresh `npm run build` `dist/` (incl. `.srchash`) in the same
  commit.
- New npm deps (`react-markdown`, `remark-gfm`) land in `package.json` + lockfile in the commit
  that introduces them.
- No interactive element may contain another (TileShell invariant).
- No new mutation endpoints; overseer ledger files are never written by dashboard code.
- Branch `feat/overseer-dashboard`, push to PR #25. Commit trailers per session convention.

## Sequencing (independently shippable)

1. **Chunk M** — MarkdownView + drawer toggle (frontend only).
2. **Chunk C1** — backend checklist serialization (board + detail payloads, tests/fixtures).
3. **Chunk C2** — tile viewport + drawer checklist + status styles + animations (frontend, depends
   on C1's shape via types only — can use fixtures).
4. **Chunk C3** — polling with drag/mutation pause (frontend).

Out of scope (explicitly): edit mode for card text; the `checklist` CLI verb + sync hook (separate
approved spec); any SSE/websocket push (poll is v1); persisting the toggle; configurable poll
interval.
