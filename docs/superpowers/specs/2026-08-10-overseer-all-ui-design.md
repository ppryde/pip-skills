# Overseer dashboard — all-UI PR (mobile board + polish)

**Date:** 2026-08-10
**Epic:** WF-055
**Cards:** WF-085 mobile lane-nav (subsumes WF-074 mobile cleanup + WF-075 lane scroll) · WF-077 party-dot overlap · WF-078 control sizing · WF-079 hand-drawn label chips · WF-080 label-× circle · WF-081 depends-on titles · WF-082 all-caps edit · WF-084 party session-id
**Branch:** `feat/overseer-all-ui` (base `256c1d5`). Version → `0.17.0` at close.

## Purpose

An all-frontend polish pass, headlined by a mobile board redesign (locked via the
prototype at artifact `803e699d`). Desktop keeps its Kanban columns; all changes
are additive/responsive. Every item below is independent — order doesn't matter
except the shared version/dist finalize.

## WF-085 — Mobile board: swipe lanes + transparent RPG icon-nav (the headline)

At `≤720px` (existing breakpoint) only; desktop unchanged.
- **Layout:** one lane full-width at a time. The board is a horizontal
  **scroll-snap** carousel (`scroll-snap-type:x mandatory`, each lane a
  `scroll-snap-align:center` child ~88vw). No per-lane `overflow-y` trap on
  mobile — this fixes WF-075's "one card at a time" pain.
- **Icon-nav bar** (replaces the desktop nothing / mobile need): a strip above
  the track with one **transparent RPG icon per non-empty lane + its count**.
  Active lane = accent-coloured pill + slight lift/scale; tap an icon to jump
  (scroll-snap to that lane); the active updates as you swipe. Icons full-strength
  (no fade). **The count lives only here** — removed from the lane row header on
  all viewports (no duplication).
- **Icons:** committed at `frontend/src/assets/lane-icons/<lanekey>.png` (11,
  transparent, one per lane kind — mapping in WF-085's card). Imported so Vite
  fingerprints/bundles them. **Compressed** (≤~64px, a few KB each) as part of
  this work — the raw 1.6 MB must not ship.
- **Controls (WF-074 subsumed):** at `≤720px`, keep visible: repo · branch ·
  ＋New and a compact status glance (short/long rest · questing · vanquished ·
  cost). Collapse search + priority/complexity/label filters + threshold + Clear
  behind a **"Controls ▾"** toggle (collapsed by default).
- **Dropdowns:** repo/branch selects **truncate with ellipsis**
  (`overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0`) — no
  two-line wrap.
- **Tests:** the pure lane-bucketing logic is unchanged (no logic change — this is
  presentation/CSS + a small nav component); component test for the icon-nav
  (renders an icon+count per lane, active reflects the shown lane, tap jumps,
  count absent from the lane header); a jsdom check that the mobile layout classes
  apply. Desktop rendering unaffected (existing Board/Lane tests stay green).

## WF-082 — edit-drawer text renders ALL-CAPS (P2)

The card body edit/source view shows all-caps — an inherited `text-transform:
uppercase` on the body/source/`<textarea>`. Remove the transform for the body
read/source/edit views so real casing shows. Test: the body textarea/source has
no uppercasing (assert the rendered/computed text matches input casing, or that
the offending class/rule is gone).

## WF-077 — party dot overlaps lane top on scroll (P2)

The Party-lane avatar dot renders above the lane container's top edge on scroll
while other content clips under it — a z-index/stacking-context issue. Make the
dot clip under the lane top like everything else (fix the z-index / overflow /
sticky context in the party column CSS). Test/verify: no `z-index` on the dot
exceeding the lane header's; visual note in the report.

## WF-078 — control sizing (P3)

Dropdown selects (repo/branch/priority/complexity) render larger than the Role A
action buttons; the **Refresh** button is a different size. Normalize
padding/font/height so dropdowns + Refresh match the standard Role A button
metrics. Test: n/a beyond visual; keep existing TopBar tests green.

## WF-079 — hand-drawn label chips (P3)

Label chips are flat; buttons use the Role A hand-inked wobble
(`--qb-btn-wobble*`). Apply a matching hand-drawn border-radius wobble (and subtle
ink treatment) to `.label-chip` so chips read as part of the illustrated system —
without breaking the 9-colour palette classes. Keep chip legibility.

## WF-080 — remove the × circle on label-remove (P3)

`LabelEditor`'s per-chip remove renders the × inside a large circle. Drop the
circle → a tidy × (minimal affordance) consistent with the chip. `aria-label`
("remove <label>") preserved. Test: remove still works + accessible name intact.

## WF-081 — depends-on dropdown shows card titles (P3)

`LinkEditor`'s depends-on picker lists only ids. Add the card **title in small
text** next to each id so the user knows what they're linking. The title comes
from the board's cards (already available). Test: options render `id — title`.

## WF-084 — party session-id small text (P3)

Surface each party member's session id in small text (alongside name/avatar) in
the Party column/overlay. Test: the session id renders for a party member.

## Cross-cutting
- All frontend; backend untouched (no CLI/endpoint/model change). No new mutation.
- `dist` rebuilt via the nvm node path + `test_dist_freshness`.
- Version bump `0.16.0 → 0.17.0` (plugin.json) + `1.21.0 → 1.22.0` (marketplace).

## Testing / review
Per-task review; DUAL blind final (Opus + Sonnet) for the user; scoped re-review
of fixes; dist rebuild. Update WF-077/078/079/080/081/082/084/085 as each lands.
