# Overseer P2 bundle — links, pull-children, colour registry (+ ledger scale, pending) (PR5)

**Date:** 2026-08-10
**Epic:** WF-055 (overseer parity for ledger-poc 377-card migration)
**Cards:** F8 links (WF-065) · F9 pull-children (WF-066) · F10 colour registry (WF-067) · S1 ledger scale (WF-068, HELD) · S2 archived-parent epics (WF-069, HELD)
**Branch:** `feat/overseer-p2-bundle` (base `caff728`). Version → `0.15.0` at close.

## Purpose

The final parity bundle. Three ledger-independent features (F8, F9, F10) plus two
ledger-view fixes (S1, S2) that are **HELD** pending a decision on the ledger's
future (see below).

## The ledger decision (blocks S1/S2 only)

`ledger.md` is a gitignored, write-only generated view — regenerated on every
mutation, read by no code (the CLI/dashboard/resume all read `board.db`; the
README calls it "a generated view"; `store.py` skips it). Its only value is
human/agent glance-ability. S1 (scale the `## Planned` section) and S2
(archived-parent epic grouping) exist solely to maintain this view. Three paths,
user to choose:
1. **Keep + lightweight S1/S2** (original plan): top-N + "…and X more" for
   Planned; include archived parents with live children in epic grouping.
2. **Slim it**: regenerate a compact summary (section counts + top items),
   subsuming S1 and sidestepping S2. (RECOMMENDED.)
3. **Retire it**: stop generating `ledger.md`; drop S1/S2 entirely.

Until chosen, S1/S2 are blocked (WF-068/069) and out of the plan below. F8/F9/F10
proceed now.

---

## F8 — `links[]` (model + importer + read-only drawer display)

11 source cards carry `{label, path}` PR URLs; overseer has no `links` field, so
the importer silently drops them. This preserves + surfaces them.

- **Model** (`scripts/models.py`): add `links: list[dict] = field(default_factory=list)`,
  each entry `{"label": str, "path": str}`. Serialize into the card frontmatter
  and parse back (same round-trip contract as `labels`), tolerant of absence
  (older cards → `[]`).
- **Importer** (`scripts/importer` / migrate path): carry the source `links`
  onto the Card. Malformed entries (missing label/path, or a non-http(s)
  scheme) are silently dropped (no warning), consistent with the model's
  other list-field parsing (`labels`, `checklist`, etc.).
- **Payload**: add `"links": card.links` to the board card dict (`board.py`) and
  it flows to `CardDetail`; frontend `BoardCard` gains `links: {label:string;
  path:string}[]`.
- **Frontend**: `CardDetailDrawer` renders a read-only **Links** section — each a
  clickable `<a href={path} target="_blank" rel="noopener noreferrer">{label}</a>`.
  Omitted entirely when `links` is empty. No editor (YAGNI — brief says preserve,
  not edit).
- **Tests**: model round-trip (incl. empty); importer preserves + skips
  malformed; board payload includes links; drawer renders links / renders nothing
  when empty.

## F9 — pull-children (CLI verb + endpoint + UI)

Bulk action: move every live child of an epic into the parent's board column.

- **CLI** (`scripts/cli.py`): new verb `pull-children <card_id>`. Loads the epic
  and its **live** (non-archived) children; for each child, sets its stage to the
  parent epic's stage (via the same `card.set_stage` path `set-stage` uses); if
  the parent has **no** stage, falls back to the parent's status semantics
  (unblock → in-flight/planned as `move` does). Skips archived/done/abandoned
  children. No-op (exit 0, message) if the card has no live children or isn't a
  parent. Single-writer: one `_sync` per child, then one `rebuild_index`.
- **Backend** (`dashboard/backend/app/main.py`): `POST /api/card/{id}/pull-children`
  (token-gated, `dependencies=[Depends(require_token)]`) → `check_id` →
  `run_overseer(root, "pull-children", id)` → returns `_board_response`. Errors via
  `_mutation_error`.
- **Frontend**: a "Pull children" affordance on the epic (drawer, shown only when
  `is_epic`), behind a `window.confirm` ("Pull all live children into this
  epic's column?") → `client.pullChildren(id)` routed through `useBoard().mutate`
  (single-mutation-entrypoint) → board refresh.
- **Tests**: CLI (children moved to parent stage; archived children skipped;
  non-parent no-op; parent-without-stage path); endpoint (token-gated, moves
  children, 400s on bad id); UI (confirm gates the call; only shown for epics).

## F10 — label colour registry (board.db table + endpoint + settings panel)

Make label colours editable instead of hash-derived, without re-modeling labels.

- **Storage** (`scripts/db.py`): new table `label_colors(name TEXT PRIMARY KEY,
  color_key TEXT NOT NULL)`, created idempotently (`CREATE TABLE IF NOT EXISTS`)
  in the connect/migrate path — same PRAGMA-guarded, no-SCHEMA_VERSION-bump
  spirit as F1's labels column. `color_key` is one of the existing **9 palette
  keys** (slate/sage/plum/clay/sky/violet/olive/terracotta/teal) — NOT arbitrary
  hex, so the existing `.label-chip--<key>` CSS applies unchanged.
- **CLI** (`scripts/cli.py`): `label-color set <name> <color_key>` (validates the
  key ∈ palette, else exit 1) and `label-color clear <name>` (removes the row →
  reverts to hash default). A `label-color list --json` for completeness.
- **Payload**: `board_data` gains a top-level `"label_colors": {name: color_key}`
  map (≈38 entries, cheap) so the frontend always has current colours on the
  normal board poll — no separate fetch/refetch dance.
- **Endpoint**: `POST /api/labels/colors {name, color}` (token-gated) → shells
  `label-color set/clear` → returns `_board_response`. (No GET needed; colours
  ride the board payload.)
- **Frontend**:
  - `board/labelColor.ts` gains an overload/registry param: `labelColor(name,
    registry?)` → `registry?.[name] ?? <existing hash-palette>`. All call sites
    (LabelChips, LabelEditor, LabelFilterPopover) thread the board's
    `label_colors` map through.
  - A **dedicated Labels settings panel** (`LabelSettingsDialog.tsx`, opened from
    a TopBar control, ClearDialog-style overlay): lists every distinct label with
    its current swatch + a 9-swatch picker; choosing a swatch → `client.setLabelColor(name, key)`
    via `useBoard().mutate`; a "reset" reverts to hash default (clear). 
- **Tests**: db table create/roundtrip + CLI (set/clear/list, invalid key
  rejected); endpoint (token-gated, sets/clears, returns updated `label_colors`);
  `labelColor` with registry (registry hit, hash fallback on miss); the settings
  panel (renders labels, picking a swatch calls the client, reset clears).

## S1 / S2 — HELD (see the ledger decision above). Not in the plan until chosen.

## Cross-cutting

- Backend stays a pure CLI client; all new mutations token-gated; reads open.
- The route-gating meta-test (from PR3) will now also cover `pull-children` and
  `labels/colors` — confirm it still passes (it walks `app.routes`).
- Frontend `dist` rebuilt via the nvm node path + `test_dist_freshness`.
- Version bump `0.14.0 → 0.15.0` (plugin.json) + `1.19.0 → 1.20.0` (marketplace)
  at close.

## Testing / review protocol

TDD; subagent-driven; per-task review; DUAL blind final (Opus + Sonnet) for the
user to adjudicate; scoped re-review of fixes; dist rebuild. Update WF-065/066/067
as each lands.
