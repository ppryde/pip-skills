# Handoff: Quest Board — RPG re-skin of the orchestration dashboard

## Overview
This is a cosmetic **re-theme** of the existing `overseer-orchestration` swim-lane dashboard
(the kanban board of workflow items `WF-xxx`, the Sessions panel, and the card-detail view).
The re-theme reframes the tool as a cozy **adventurers' guild quest board**: warm autumn
parchment palette, rounded hand-drawn cards, quest-banner column headers, cards as
"quests with sub-quests", and the live agent **Sessions** panel reframed as your **Party** of
heroes (their context % shown as a mana bar). All of the original data and functionality is
preserved — only the presentation changes.

## About the Design Files
The file in this bundle (`Quest Board Full.dc.html`) is a **design reference created in HTML** —
a working prototype that shows the intended look and behavior. It is **not** production code to
paste in. The task is to **recreate this look inside the existing `overseer-orchestration`
codebase**, using its current framework, component structure, data layer, and state — swapping
styling/markup, not rewriting the app. Keep every existing feature (drag-reorder, Refresh,
Archive toggle, Threshold set, Sessions, dependency links, token counts, PR status, markdown tab).

> The prototype uses invented sample data (WF-2477 "Patch the merge cavern", heroes Aria/Bram/Pip,
> etc.). Ignore the sample content — wire the theme to the app's real data.

## Fidelity
**High-fidelity.** Final colors, typography, spacing, radii, and interactions are all specified
below and are intended to be matched closely. Recreate pixel-for-pixel using the codebase's
existing patterns; only substitute equivalents where a raw HTML approach doesn't map cleanly to
the app's component library.

## Terminology mapping (theme layer only — keep original data keys/routes)
| Original | Themed label | Notes |
|---|---|---|
| Column names (Backlog, Bootstrap, Planning, Plan Review, Implementation, Impl Review, Verification, Awaiting Merge, Done, Parked) | **kept verbatim**, styled as pennant banners | Do NOT rename in data — only restyle the header |
| Work item card (`WF-xxx`) | a **Quest** | |
| Checklist / subtasks on a card | **Sub-quests** | |
| Token count (e.g. `20k`) | **Gold** (coin icon) | same number, coin glyph prefix |
| Dependency ("waiting on WF-021") | **Locked behind** pill (padlock icon) | |
| Sessions panel (live agents) | **Party** of heroes | one row per active agent |
| Agent model (Opus/Sonnet/Haiku, "1M context") | hero **class** | |
| Agent context % | **mana** bar | 100% = full mana |
| Card status (in progress / review / done / on hold) | status chip, tinted per column | |
| Card description + Markdown view | **Description** block + **Scroll (MD)** tab | |

## Screens / Views

### 1. Board (main view)
- **Purpose:** overview of all quests across workflow columns; scan status, open a quest, see the party.
- **Layout:**
  - Full-height flex column. Sticky top bar, then a horizontally-scrolling board region (`overflow-x:auto`), then columns laid out as a horizontal flex row (`gap: 18px`), each column `flex: 0 0 268px`.
  - Each column: a banner header (fixed) + a vertically-scrolling card list below it.
  - Rightmost item in the scroll row is the **Party** panel (`flex: 0 0 288px`, dark).
- **Top bar** (`background:#FBF4E1`, `border-bottom: 2px dashed #D8C39A`, `box-shadow: 0 6px 16px rgba(90,62,40,.08)`, sticky, `padding: 18px 26px`):
  - Left: a `50px` circular crest (irregular radius `50% 48% 52% 50%`, `2px solid #5B4632`, fill `#F3E1B8`) + title **"Adventurers' Guild Board"** (Baloo 2, 800, 26px, `#4A3826`) with a subtitle line (Patrick Hand, 17px, `#9A8464`) — map subtitle to the app's project name / refresh timestamp.
  - Right: three pills → **Gold total** (`#F3E1B8` fill, `2px solid #D9A441`, coin icon, `#7A5A1A` text), **"12 / 40 vanquished"** progress (`#EAF0DE`/`#A9BE7E`, check icon, `#5A6E38`) mapped to Done-count / total, and **"N questing"** button (`#F3E1E7`/`#D9A0B4`, `#A8506B`) → opens the Party page. Map original controls (Refresh, Archive checkbox, Threshold input + Set, Sessions button, CTX %) into this bar in the same style.
- **Column header banner** (per column): pennant shape via asymmetric radius
  `border-radius: 255px 10px 225px 10px / 10px 225px 10px 255px`, `padding: 7px 14px`,
  white text, `box-shadow: 0 4px 0 <darker>`. A right-aligned count chip
  (`background: rgba(255,255,255,.25)`, `border-radius: 9px`). Banner fill is per-column (see tokens).
- **Quest card** (`background:#fff`, `border: 2px solid <column-tint>`, alternating asymmetric radius
  `14px 20px 14px 20px` / `20px 14px 20px 14px`, `padding: 14px`, `box-shadow: 0 3px 0 <soft tint>`;
  hover lifts `translateY(-3px)` with `transition: transform .12s, box-shadow .12s`; whole card is clickable → opens detail):
  - Header row: `WF-id` (Silkscreen, 10px, `#9A8464`) + rarity stars (1–3 filled `#D9A441`, empty `#E0D3B4`) or a status chip.
  - Title (Baloo 2, 600, 18px, `#4A3826`, line-height 1.15).
  - Sub-quest lines: a `15px` rounded checkbox (`border-radius:5px`; done = filled column-color w/ white check, todo = `2px solid #D8C39A`) + label (done `#7A6A54`, todo `#B0A088`, 16px).
  - Optional progress bar (`height:8px`, track `#F0E3C4`, fill column-color) for in-progress quests.
  - Footer: gold (coin + number, `#7A5A1A`), optional **Locked behind** pill (`#F3E1E7`/`#A8506B`, padlock icon), optional assigned-hero avatar chip. Footer separated by `1px dashed #E0CEA5`.
  - **Done** cards: muted (`background:#F3EAD6`, `opacity:.94`), title strikethrough `#6E6250`, green check-in-circle, "+N gold earned".
  - **Parked** cards: `background:#F1E9DA`, `2px dashed #C4B292`, "on hold" chip, muted text, no gold.

### 2. Card detail (modal overlay)
Opens when a card is clicked. Backdrop `rgba(52,36,22,.5)` + `backdrop-filter: blur(3px)`, centered.
Sheet: `width:640px`, `max-height:90vh` scroll, `background:#FBF4E1`, `2px solid #C9A86A`,
`border-radius:26px`, `box-shadow:0 24px 60px rgba(50,30,15,.4)`, `padding:26px 28px`.
- **Header row:** column banner pill + `WF-id` + rarity stars + a round close button (`✕`, `38px`, `#F3EAD6`/`2px solid #D8C39A`).
- **Title:** Baloo 2, 800, 30px, `#4A3826`.
- **Meta chips:** status chip (tinted per column), gold chip, assigned-hero chip (avatar + name + class).
- **Tab bar** (segmented, in a `#EDE0C2` track, `border-radius:14px`, `padding:5px`): **Quest** | **Scroll `MD`**. Active tab = white pill (`#fff`, text `#4A3826`); inactive text `#9A8464`. The "MD" badge is a tiny Silkscreen tag (`#7A8B45` bg, white).
  - **Quest tab:** Description paragraph (18px, `#5B4632`, line-height 1.5) → optional Journey-progress bar → **Sub-quests** panel (white card, `2px solid #E0CEA5`, `border-radius:16px`; header "Sub-quests" + "done / total" count; `22px` rounded checkboxes) → **Locked behind** dependency pills → **Quest log** (vertical timeline, `2px dashed #D8C39A` left rule, colored dots, entry text + Silkscreen day stamp).
  - **Scroll (MD) tab:** the quest rendered as **Markdown** inside a white card. Sections: description prose, `## Acceptance` (checklist), `## Locked behind` (deps), `## Reward` (gold). In the app, render the item's **real markdown field** here with the existing markdown renderer.

### 3. Party page (modal overlay)
Opens from the top-bar "N questing" button. Backdrop as above. Sheet `width:800px`,
dark `#3E2F22`, `border-radius:26px`, `padding:26px 28px`.
- Title **"⚔ The Party"** (Baloo 2, 800, 30px, `#F6EAD2`) + "3 OF 5 HEROES" (Silkscreen, `#C9AE84`) + close button. One-line helper: "…their mana is the context they have left."
- Responsive grid of hero cards (`repeat(auto-fill, minmax(340px, 1fr))`, `gap:16px`). Each hero card (`#F3E7CE`, `border-radius:20px`, `padding:18px`, `box-shadow:0 5px 0 rgba(0,0,0,.18)`):
  - `52px` avatar circle (accent fill, initial, live green dot bottom-right that pulses).
  - Name (Baloo 2, 700, 22px, `#4A2E1C`) + "class · LV n" (Silkscreen, `#A06A3C`).
  - **Mana** bar (`height:11px`, track `#E4D2AB`, gradient fill; blue gradient for high, warm gradient for low).
  - "ON QUEST · WF-id" card with the current quest title.
  - Two stat tiles: **cleared** (green `#EAF0DE`/`#5A6E38`) and **earned** gold (`#F3E1B8`/`#7A5A1A`).
- One dashed **"Summon a hero"** empty slot at the end (open session slots).

Map hero fields to real agent-session data: name = agent id/label, class = model, mana = context %, quest = current WF, live dot = session LIVE, cleared/earned = optional metrics (hide if unavailable).

## Interactions & Behavior
- **Open detail:** click anywhere on a quest card → detail modal for that card; resets to the Quest tab.
- **Tabs:** clicking Quest / Scroll swaps the panel; active tab is a white pill.
- **Open party:** top-bar "N questing" button → Party overlay.
- **Close overlays:** click the `✕` or click the backdrop (clicks inside the sheet must `stopPropagation`).
- **Card hover:** `translateY(-3px)`, 120ms ease.
- **Live pulse:** green session/hero dots animate `qb-pulse` (scale 1→0.8, opacity 1→0.4) at 1.6s infinite.
- **Scrollbars:** custom, `#C9A86A` thumb on `#E7D6B4` track, rounded (`::-webkit-scrollbar`, 12px).
- **Responsive:** board scrolls horizontally; overlays are `max-width:100%` with 24px page padding and cap at `90vh` with internal scroll. On narrow screens the party grid collapses to one column via `auto-fill/minmax`.
- Preserve all existing behaviors from the current app (drag-and-drop reorder, Refresh, Archive filter, Threshold set, dependency navigation).

## State Management
Theme adds only presentational UI state; keep the app's existing data/state.
- `detailCode` (string | null) — which WF card's detail modal is open.
- `detailTab` ("quest" | "scroll") — active tab in the detail modal; reset to "quest" on open.
- `partyOpen` (boolean) — Party overlay visibility.
Everything else (columns, cards, sessions, threshold, archive, refresh) comes from existing state/data.

## Design Tokens

**Base**
- Page bg: `#EFE3CC` with two soft radial highlights (`#F7EED8` top-left, `#EADCBD` bottom-right).
- Panel/parchment: `#FBF4E1`; muted parchment `#F3EAD6` / `#F1E9DA`.
- Ink text: `#4A3826` (headings), `#5B4632` (body), `#7A6A54` / `#9A8464` (muted), `#B0A088` (todo/disabled).
- Dashed dividers/borders: `#D8C39A` / `#E0CEA5`; card border `#C9A86A`.

**Column accents** (banner fill / card border / softer card shadow)
- Backlog — `#7A8B45` (shadow `#63722F`), card border `#C9A86A`
- Bootstrap — `#B08948` (shadow `#977236`), card border `#DDBB7C`, shadow `#EDD9AE`
- Planning / Plan Review — `#5C86B0` (shadow `#47709A`), card border `#A9C0DA`, shadow `#D3E0EE`
- Implementation / Impl Review — `#D98A3D` (shadow `#BC722C`), card border `#E0A24C`, shadow `#F0DBAE`
- Verification — reuse Planning blue or a teal from the ramp
- Awaiting Merge — `#A8506B` (shadow `#8C3E56`), card border `#D49AAD`, shadow `#EBD1D9`
- Done — `#5B4632` (shadow `#43331F`), muted card `#F3EAD6`/`#C9B48C`
- Parked — `#9A8464` (shadow `#7F6B4E`), dashed card

**Accent utilities**
- Gold: coin fill `#E7B93D`, stroke `#B5851F`; gold chip bg `#F3E1B8`, border `#D9A441`, text `#7A5A1A`.
- Success/done: `#7A8B45` / chip `#EAF0DE` text `#5A6E38`.
- Locked/dep: chip `#F3E1E7`, text/icon `#A8506B`.
- Mana bars: high = `linear-gradient(90deg,#5E86C7,#8FB6E0)`; low = `linear-gradient(90deg,#C25A3B,#E08A3C)`.
- Dark party surfaces: `#3E2F22` (panel), `#4A3524` (row), border `#6E4A32`, text `#F6EAD2`/`#C9AE84`.

**Typography** (all Google Fonts)
- Display/headings: **Baloo 2** (600/700/800).
- Body / hand-drawn UI: **Patrick Hand**.
- Column banners: **Gaegu** (700).
- Mono / game numerals & labels (WF-ids, LV, day stamps, "MD" badge): **Silkscreen** (9–13px, letter-spacing ~1px).
- Markdown / prose fallback: **Nunito**.
- Sizes: page title 26px, modal title 30px, card title 18px, body 16–18px, meta/Silkscreen 9–13px. Keep the game/hand-drawn faces — if the codebase can't add fonts, closest rounded substitutes: Baloo 2→Quicksand/Fredoka, Patrick Hand→Gaegu/Comic Neue, Silkscreen→any pixel/monospace.

**Radii**
- Cards `14–20px` (alternating asymmetric), modals `26px`, chips/pills `10–14px`, checkboxes `5–7px`, banner pennant `255px 10px 225px 10px / 10px 225px 10px 255px`, buttons/avatars `999px`/`50%`.

**Shadows**
- Cards: hard offset `0 3px 0 <soft tint>` (sticker feel), not blurred.
- Banners/hero cards: `0 4–5px 0 <darker>`.
- Modals: `0 24px 60px rgba(50,30,15,.4)`.

**Animation**
- `qb-pulse`: `0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.4;transform:scale(.8)}`, 1.6s infinite (live dots).
- Card hover: `transform .12s ease, box-shadow .12s ease`.

## Assets
- **Icons:** all inline SVG in the prototype (coin, star, check, padlock, check-in-circle, pause, chevron). Replace with the codebase's existing icon set — the guide notes Lucide at stroke-width ~2.75 for a rounded look; a coin/star/heart may need a filled custom glyph.
- **Fonts:** Baloo 2, Patrick Hand, Gaegu, Silkscreen, Nunito via Google Fonts.
- **Images:** none — the design is fully CSS/SVG. No raster assets to migrate.
- Emoji used sparingly (⚑ crest, ⚔ party, 🎉) — swap for icons if the app avoids emoji.

## Files
- `Quest Board Full.dc.html` — the full board prototype: top bar, all columns, quest cards, Party panel, card-detail modal (Description + Quest/Scroll-MD tabs), Party page overlay. Open it in a browser to see every interaction. Styling is inline; the logic (state, sample data, the tiny markdown renderer, click wiring) is in the component script near the top.
