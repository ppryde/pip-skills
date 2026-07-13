# Overseer Dashboard — Quest Board Theme — Design Spec

**Date:** 2026-07-13
**Status:** Approved design (user approved direction and all structural decisions in session)
**Fidelity reference:** `docs/design/quest-board/HANDOFF.md` (the design-guild handoff — palette,
type, radii, shadows, per-column accents, and interaction specs are authoritative there and are
NOT restated here) and `docs/design/quest-board/prototype.html` (open in a browser).

## Context

A full cosmetic re-theme of the overseer dashboard as a cozy adventurers' guild quest board:
parchment palette, hand-drawn type, pennant column banners, cards as quests with sub-quests,
sessions as a Party of heroes with mana bars. **Presentation only** — no data keys, routes, or
state semantics change. The old theme is banked on `main`; this is a full commitment, not a
toggle (decided in session: maintaining both doubles every future component's styling burden).

The design maps onto real data with no invention:

| Theme element | Real data |
|---|---|
| Rarity stars (1–3) | card `complexity` S/M/L |
| Gold (coin + number) | budget tokens, humanised (WF-014) — tripwire keeps its red flag |
| "N / M vanquished" | done count / total |
| Assigned-hero avatar chip | `claimed_by` (WF-021/023) |
| Party / heroes / class | census sessions / `session_name` / model |
| Mana bar | 100 − ctx% |
| "ON QUEST · WF-xxx" | the hero's claimed card |
| Locked-behind pill | unready `depends_on` |
| Sub-quests | card `checklist:` frontmatter (WF-009 sync) |

## Decisions (all made with the user)

| Question | Decision | Rationale |
|---|---|---|
| Commit level | **Full re-theme**, no toggle | Old look banked on main; a toggle doubles styling maintenance forever |
| Card detail | **Restyle the existing drawer** as the parchment sheet — NOT the mockup's centered modal | The handoff blesses equivalents; the drawer's focus management, controls, and tests survive untouched |
| Party | **Full mockup**: dark Party column at the scroll-row's end AND the Party overlay from the "N questing" pill; the TopBar sessions dropdown retires, its census fetch/poll transplants | Ambient at-a-glance mana on the board + the rich overlay; the pill gives instant access from anywhere |
| Foundations first | Tokenise `styles.css` into CSS custom properties before any theming | Makes the theme mechanical and revert-safe; the hard-coded hexes were the standing debt |
| Fonts | Bundled **locally** as woff2 `@font-face` (Baloo 2, Patrick Hand, Gaegu, Silkscreen, Nunito) — no Google Fonts CDN at runtime | Local single-user tool; committed-dist policy; offline |
| Checklist wheel | Keep WF-015's 3-row wheel mechanics (window, fade, slide); restyle its rows as the mockup's rounded sub-quest checkboxes | The wheel was user-requested; the mockup's checkbox look is a row-skin, not a mechanics change |
| Icons | Inline SVG (coin, star, check, padlock, chevron) — no icon library dependency | Matches the prototype; repo has no icon set |
| Data gaps | "LV n" omitted (no level concept); per-hero cleared/earned hidden in v1; top-bar gold total = sum of card budget actuals; subtitle = project name · last-refresh time | HANDOFF.md's own instruction: hide what real data cannot honestly supply |

## Components touched

- `styles.css` — tokenisation (`:root` custom properties for every colour/radius/shadow/font),
  then the guild token sheet + component rules. Per-stage accent map per HANDOFF.md tokens.
- `TopBar.tsx` — crest + title/subtitle; gold-total, vanquished, questing pills; Refresh /
  Archive / Threshold / ctx% restyled in the same pill language. Sessions dropdown removed.
- `Lane.tsx` — pennant banner header + count chip.
- `TileShell.tsx` / `CardTile.tsx` / `EpicCard.tsx` — quest card chrome (alternating asymmetric
  radii, tint borders, sticker shadows, hover lift), stars, gold footer, locked-behind pill,
  hero chip; Done/Parked treatments.
- `ChecklistRows.tsx` — checkbox row skin (mechanics untouched).
- New: `PartyColumn.tsx` (board scroll-row tail) and `PartyOverlay.tsx` (hero-card grid, summon
  slot) — both fed by the transplanted `getSessions()` poll; `SessionsPanel.tsx` retires.
- `CardDetailDrawer.tsx` — parchment sheet skin; Quest | Scroll (MD) segmented tabs over the
  existing Rendered/Source toggle; sub-quests panel; locked-behind pills; **stretch:** Quest-log
  timeline parsed from the card's Progress log section (fall back to plain section rendering if
  parsing is fragile).
- Fonts: `frontend/src/assets/fonts/*.woff2` + `@font-face` block.

## Quality floor

Ink-on-parchment contrast (≥ 4.5:1 body); visible keyboard focus on parchment; every pulse,
hover-lift and wheel slide inside the existing `prefers-reduced-motion: no-preference` block;
inert-`<li>` and no-nested-interactive invariants untouched; text-based test assertions survive
(data text unchanged) — class/snapshot-level tests updated where skins changed. Committed-dist
policy applies: every card rebuilds `dist/`.

## Delivery

Epic + four cards, in order (2–4 depend on 1; branch cuts from the claims bundle — merge PR #31
first, then `feat/quest-board-theme`, new rolling PR):

1. **Foundations** — tokenise styles.css; bundle fonts; parchment page chrome (S/M).
2. **Board** — banners, quest cards, sub-quest skin, stars/gold/locked/hero chips, Done/Parked (M).
3. **Top bar + Party** — bar restyle + pills; PartyColumn + PartyOverlay; dropdown retires (M).
4. **Drawer** — parchment sheet, tabs, sub-quests panel, quest-log stretch (M).

Verification per card: vitest + tsc + backend dist-freshness + real-DOM headless-Chrome
screenshots compared against `prototype.html` at 1600px and a narrow width.

## Out of scope

- Sounds/music. Editing tasks from the dashboard. Theming the CLI output. Renaming any data
  concept (columns keep verbatim names, styled as banners — HANDOFF.md terminology table).
