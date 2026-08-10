# Overseer All-UI PR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]`.

**Goal:** A frontend-only polish PR: a mobile board redesign (swipe + transparent RPG icon-nav) plus seven independent UI tweaks.

**Architecture:** All in `plugins/overseer/dashboard/frontend`. No backend/CLI/model change. Desktop unchanged; mobile changes gated at `@media (max-width:720px)`.

**Tech Stack:** React + TypeScript + Vite; vitest.

## Global Constraints
- Frontend only. No new backend mutation/endpoint. Existing Board/Lane/TopBar tests must stay green (update additively only where a prop/text genuinely changed).
- Run: `cd plugins/overseer/dashboard/frontend && PATH=$HOME/.nvm/versions/node/v22.22.1/bin:$PATH npm test [-- <file>]` + `…npx tsc --noEmit`. Dist: `…npm run build`. Backend freshness: `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest -q`.
- Do NOT rebuild dist per-task (Task 10 does it once).
- Commit trailers on every commit: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` / `Claude-Session: https://claude.ai/code/session_019MauNUBEVQLRKSrDqDnFV3`.
- Spec: docs/superpowers/specs/2026-08-10-overseer-all-ui-design.md — the authority for each item.

---

## Task 1: WF-082 — edit-drawer text no longer ALL-CAPS
**Files:** `components/CardDetailDrawer.tsx` + `styles.css` (find the `text-transform:uppercase` on the body/source/textarea); test in `CardDetailDrawer.test.tsx`.
- [ ] Failing test: the body edit textarea / source view preserves mixed-case text (assert no uppercasing — e.g. the rendered source text equals the input casing, or the specific rule/class is absent).
- [ ] Run → fail.
- [ ] Remove the `text-transform:uppercase` from the body read/source/edit path (keep it on genuine labels/eyebrows if those legitimately use it — only the body content must not uppercase).
- [ ] Run → pass; full `npm test` + `tsc`.
- [ ] Commit `fix(overseer-dashboard): stop uppercasing card body in the drawer (WF-082)`.

## Task 2: WF-080 — remove the × circle on label-remove
**Files:** `components/LabelEditor.tsx` (+ its CSS in styles.css) + `LabelEditor.test.tsx`.
- [ ] Failing/kept test: remove-button still fires `onSave` without the label and keeps `aria-label="remove <label>"`.
- [ ] Drop the circular background/border on the remove `×` (a tidy inline × instead); keep it keyboard-focusable + aria-labelled.
- [ ] Run → pass; `tsc`.
- [ ] Commit `fix(overseer-dashboard): tidy label-remove × (drop the circle) (WF-080)`.

## Task 3: WF-078 — normalize dropdown + Refresh sizing
**Files:** `styles.css` (the `.topbar__*-select`, priority/complexity/claim selects, `.topbar__refresh`); confirm against the Role A button metrics (`.card-drawer__edit-actions button` / `--qb-btn-*`).
- [ ] Adjust padding/font-size/height so the selects + Refresh match the Role A action buttons (no oversized controls).
- [ ] Run full `npm test` (TopBar tests stay green) + `tsc`.
- [ ] Commit `fix(overseer-dashboard): normalize dropdown + Refresh sizing to Role A (WF-078)`.

## Task 4: WF-079 — hand-drawn label chips
**Files:** `styles.css` (`.label-chip`), keep the `.label-chip--<key>` palette intact.
- [ ] Give `.label-chip` a hand-inked wobble border-radius (reuse a `--qb-btn-wobble*` value) + subtle ink border so chips match the illustrated buttons; verify all 9 palette classes still render legibly.
- [ ] Run `npm test` + `tsc` (LabelChips tests green).
- [ ] Commit `feat(overseer-dashboard): hand-drawn wobble on label chips (WF-079)`.

## Task 5: WF-077 — party dot no longer overlaps lane top on scroll
**Files:** `styles.css` (party column/avatar z-index / stacking) + `components/PartyColumn.tsx` if needed.
- [ ] Read how the party lane/dot stacks (z-index, sticky, overflow). Make the avatar dot clip UNDER the lane header/top on scroll like other content (lower its z-index below the lane header, or fix the overflow/stacking context). Do not break the avatar's normal appearance.
- [ ] Run `npm test` + `tsc`; note the fix (which z-index/context) in the report.
- [ ] Commit `fix(overseer-dashboard): party avatar dot clips under lane top on scroll (WF-077)`.

## Task 6: WF-081 — depends-on dropdown shows card titles
**Files:** `components/LinkEditor.tsx` (+ test). The board's cards (id+title) are available to the drawer/LinkEditor — thread them if not already.
- [ ] Failing test: the depends-on option list renders `id — title` (small title text) per candidate card, not just the id.
- [ ] Implement: render each option/candidate with its title in small text alongside the id (use the cards list already in scope; if not present, pass it as a prop from the drawer which has `allCardIds`/board).
- [ ] Run → pass; `tsc`.
- [ ] Commit `feat(overseer-dashboard): show card titles in the depends-on picker (WF-081)`.

## Task 7: WF-084 — party session-id in small text
**Files:** `components/PartyColumn.tsx` / `PartyOverlay.tsx` (+ tests).
- [ ] Failing test: a party member row surfaces its `session.id` (or the census session id) in small text alongside name/avatar.
- [ ] Implement the small-text session id; truncate if long.
- [ ] Run → pass; `tsc`.
- [ ] Commit `feat(overseer-dashboard): show session id (small) for party members (WF-084)`.

## Task 8: WF-085a — lane icons + swipe + icon-nav (mobile)
**Files:** `board/laneIcons.ts` (new — map lane key → imported icon URL), `components/LaneIconNav.tsx` (new + test), `components/Board.tsx`, `styles.css`; compress `src/assets/lane-icons/*.png`.
- [ ] **Compress icons first:** downscale each `src/assets/lane-icons/*.png` to ~64px + optimize (the raw ~150KB each must drop to a few KB). Use the nvm node toolchain or `sips`/`pngquant` if available; commit the compressed PNGs (verify they still render).
- [ ] `laneIcons.ts`: `import backlog from "../assets/lane-icons/backlog.png"` … export `laneIcon(laneKey): string` mapping all 11 lane kinds (backlog/bootstrap/planning/plan-review/implementation/impl-review/verification/awaiting-merge/done/parked/abandoned) → its imported URL.
- [ ] `LaneIconNav.tsx`: props `{ lanes: {key,label,count,accent}[], activeKey, onJump(key) }`. Renders a strip: per lane an icon (`laneIcon(key)`) + count; active = accent pill + lift; `aria-label` = `"<label>, <count> cards"`; click → onJump. Test it (icon+count per lane, active reflects activeKey, click calls onJump).
- [ ] `Board.tsx` (mobile only, ≤720px via CSS + a matchMedia or CSS-driven layout): make the lane track a horizontal scroll-snap carousel; render `<LaneIconNav>` above it; sync active on scroll + on nav jump. Remove the count from the lane header (`Lane`/`lane__count`) on ALL viewports (kept only in the nav). Desktop columns unchanged.
- [ ] CSS: `@media (max-width:720px)` — track `scroll-snap-type:x mandatory`, lanes `flex:0 0 88vw; scroll-snap-align:center`, drop per-lane `overflow-y` trap; the icon-nav strip styling (transparent icons full-strength, active accent pill + lift).
- [ ] Run full `npm test` + `tsc`; existing Board/Lane tests stay green (update the lane-header-count assertion additively — count now in nav).
- [ ] Commit `feat(overseer-dashboard): mobile swipe lanes + RPG icon-nav (WF-085)`.

## Task 9: WF-085b — mobile controls collapse + dropdown truncation
**Files:** `components/TopBar.tsx` (+ test), `styles.css`.
- [ ] Dropdown truncation (all viewports fine): repo/branch selects get `overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0` so long names don't wrap.
- [ ] Mobile (≤720px): keep repo · branch · ＋New + the compact status glance (short/long rest · questing · vanquished · cost) visible; collapse search + priority/complexity/label filters + threshold + Clear behind a "Controls ▾" toggle (collapsed by default). Desktop layout unchanged.
- [ ] Test: the Controls toggle shows/hides the collapsed group (jsdom); truncation class present on the selects.
- [ ] Run → pass; `tsc`.
- [ ] Commit `feat(overseer-dashboard): mobile collapsed controls + truncating dropdowns (WF-085/074)`.

## Task 10: Version bump + dist + full green
- [ ] plugin.json `0.16.0→0.17.0`; marketplace.json `1.21.0→1.22.0`.
- [ ] `npm test` + `tsc` green; `npm run build`; backend `pytest -q` incl. `test_dist_freshness`; CLI pathless `pytest -q`.
- [ ] Commit `chore(overseer-dashboard): all-UI PR — v0.17.0 + dist`.

## Self-review notes
- Coverage: WF-082→T1, WF-080→T2, WF-078→T3, WF-079→T4, WF-077→T5, WF-081→T6, WF-084→T7, WF-085→T8+T9 (subsumes WF-074/075). Version/dist→T10.
- Independent tasks (order-free) except T10 last. Each ends green + committed; dist rebuilt once at T10.
- Icon compression is inside T8 (must not ship raw 1.6 MB).
