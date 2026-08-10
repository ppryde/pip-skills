# Overseer P2 Bundle (F8/F9/F10) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship the three ledger-independent P2 features — F8 `links[]`, F9 pull-children, F10 label colour registry. (S1/S2 are HELD pending the ledger keep/slim/retire decision and are NOT in this plan.)

**Architecture:** F8 = model field + importer + read-only drawer display. F9 = new CLI verb + token-gated endpoint + drawer button. F10 = new board.db table (name→palette-key) + CLI + board-payload map + registry-aware `labelColor` + a dedicated Labels settings dialog. Backend stays a pure CLI client; all new mutations token-gated.

**Tech Stack:** Python (models/db/cli/board/importer); React+TS+Vite; pytest; vitest.

## Global Constraints

- Backend is a pure CLI client; new endpoints shell CLI verbs; all mutating routes carry `dependencies=[Depends(require_token)]`; reads ungated. The PR3 route-gating meta-test (`test_mutations.py`) must still pass with the new routes.
- F10 `color_key` ∈ the 9 existing palette keys only (`slate,sage,plum,clay,sky,violet,olive,terracotta,teal`) — reuse `.label-chip--<key>` CSS; NO arbitrary hex, no new colour CSS.
- Frontend mutations route through `useBoard().mutate` (single-mutation-entrypoint); dialogs needing inline errors may use `mutate(fn,{rethrow:true})` (added in PR3).
- Run commands: CLI tests pathless `cd plugins/overseer && ../../.venv/bin/python -m pytest -q`; backend `cd plugins/overseer/dashboard/backend && ../../../../.venv/bin/python -m pytest -q`; frontend `cd plugins/overseer/dashboard/frontend && PATH=$HOME/.nvm/versions/node/v22.22.1/bin:$PATH npm test [-- <file>]` + `…npx tsc --noEmit`; dist `…npm run build`.
- Commit trailers on every commit: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` / `Claude-Session: https://claude.ai/code/session_019MauNUBEVQLRKSrDqDnFV3`.
- Version bump at close (final task): plugin.json `0.14.0→0.15.0`, marketplace.json `1.19.0→1.20.0`.

## File Structure
- `plugins/overseer/scripts/models.py` — Card gains `links`; `from_text`/`to_text` round-trip it.
- `plugins/overseer/scripts/db.py` — `_migrate_columns` adds `links`; new `label_colors` table in `_SCHEMA`; `migrate_from_workflow` preserves source links; get/set/clear/list helpers for label_colors.
- `plugins/overseer/scripts/cli.py` — `pull-children` verb; `label-color set/clear/list` verbs.
- `plugins/overseer/scripts/board.py` — card dict gains `links`; payload gains top-level `label_colors`.
- `plugins/overseer/dashboard/backend/app/main.py` — `POST /api/card/{id}/pull-children`, `POST /api/labels/colors` (both token-gated).
- Frontend: `api/types.ts` (`links`, `label_colors`), `api/client.ts` (`pullChildren`, `setLabelColor`), `board/labelColor.ts` (registry param), `components/CardDetailDrawer.tsx` (Links section + Pull-children button), `components/LabelSettingsDialog.tsx` (+ TopBar wiring), `styles.css`.
- Tests alongside each.

---

## Task 1: F8 — `links` on the model (round-trip)

**Files:** `scripts/models.py`; `tests/overseer/test_models.py`

**Interfaces:** Produces `Card.links: list[dict]` (`{"label","path"}`), serialised in frontmatter, tolerant of absence. Consumed by Tasks 2, 3.

- [ ] **Step 1: Failing tests** in `tests/overseer/test_models.py`:

```python
def test_links_roundtrip():
    c = Card(id="WF-1", title="T", status="planned", links=[{"label": "PR #9", "path": "https://x/9"}])
    c2 = Card.from_text(c.to_text())
    assert c2.links == [{"label": "PR #9", "path": "https://x/9"}]

def test_links_absent_defaults_empty():
    # a card text with no `links:` key parses to []
    c = Card.from_text(_MINIMAL_CARD_TEXT)  # reuse the file's minimal fixture
    assert c.links == []
```

- [ ] **Step 2: Run → fail.** `cd plugins/overseer && ../../.venv/bin/python -m pytest -q -k links_roundtrip`
- [ ] **Step 3: Implement.** Add to the Card dataclass (near `labels`, models.py:105): `links: list[dict] = field(default_factory=list)`. In `from_text` (after the labels block ~148-154): parse `meta.get("links")` — accept a list of `{label,path}` dicts, coerce each to `{"label": str(e["label"]), "path": str(e["path"])}`, skip malformed entries, default `[]`. In `to_text` (the frontmatter dict ~246): add `"links": self.links or None` (omit when empty, matching the `labels` idiom).
- [ ] **Step 4: Run → pass**, then full `tests/overseer/` pathless.
- [ ] **Step 5: Commit** `feat(overseer): links[] field on Card model, frontmatter round-trip (F8, WF-065)`

---

## Task 2: F8 — importer preserves `links`

**Files:** `scripts/db.py` (`migrate_from_workflow` ~155); `tests/overseer/test_db.py`

**Interfaces:** Consumes Task 1's `Card.links`. Produces: imported cards carry source `links`; malformed skipped with a warning (D1 style).

- [ ] **Step 1: Failing test** — a source card file with a `links:` frontmatter list imports with links preserved; a malformed entry (missing `path`) is dropped, others kept. (Match how `test_db.py` builds source card files for `migrate_from_workflow`.)
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — `migrate_from_workflow` parses cards via `Card.from_text` (which now carries links from Task 1), so links should flow through automatically; verify and, if the importer builds the Card dict field-by-field, add `links`. Confirm malformed-entry skipping happens in `from_text` (Task 1) and surfaces consistently.
- [ ] **Step 4: Run → pass**, full CLI suite pathless.
- [ ] **Step 5: Commit** `feat(overseer): importer preserves card links (F8, WF-065)`

---

## Task 3: F8 — payload + read-only drawer Links section

**Files:** `scripts/board.py` (card dict ~72); `dashboard/frontend/src/api/types.ts`; `components/CardDetailDrawer.tsx` (+ test)

**Interfaces:** Consumes `Card.links`. Produces `BoardCard.links: {label:string;path:string}[]`; drawer renders a read-only Links section.

- [ ] **Step 1:** backend test — `board_data` card dict includes `links` (add to test_board.py, mirroring the `body`/`repo` pass-through tests).
- [ ] **Step 2:** frontend failing test — `CardDetailDrawer` renders a link `<a href>` for each entry and nothing when empty.
- [ ] **Step 3:** implement — `board.py`: add `"links": card.links,` to the card dict. `types.ts`: add `links: { label: string; path: string }[]` to `BoardCard`. `CardDetailDrawer.tsx`: when `detail.links?.length`, render a "Links" section with `<a href={l.path} target="_blank" rel="noopener noreferrer">{l.label}</a>` per entry; render nothing when empty.
- [ ] **Step 4:** run backend + frontend suites → pass; `tsc` clean.
- [ ] **Step 5: Commit** `feat(overseer-dashboard): expose + render card links read-only in drawer (F8, WF-065)`

---

## Task 4: F9 — `pull-children` CLI verb

**Files:** `scripts/cli.py`; `tests/overseer/test_cli.py`

**Interfaces:** Produces `overseer pull-children <card_id>` — moves every LIVE child to the parent's stage (or status). Consumed by Task 5.

- [ ] **Step 1: Failing tests** in `test_cli.py`:

```python
def test_pull_children_moves_live_children_to_parent_stage(self, repo):
    run(repo, "new-card", "--title", "Epic")            # WF-001
    run(repo, "new-card", "--title", "K1"); run(repo, "set-field", "WF-002", "--parent", "WF-001")
    run(repo, "new-card", "--title", "K2"); run(repo, "set-field", "WF-003", "--parent", "WF-001")
    run(repo, "set-stage", "WF-001", "implementation")   # parent in a stage
    assert run(repo, "pull-children", "WF-001") == 0
    assert _card(repo, "WF-002").stage == "implementation"
    assert _card(repo, "WF-003").stage == "implementation"

def test_pull_children_skips_archived_children(self, repo):
    run(repo, "new-card", "--title", "Epic"); run(repo, "new-card", "--title", "K1")
    run(repo, "set-field", "WF-002", "--parent", "WF-001"); run(repo, "done", "WF-002")
    run(repo, "set-stage", "WF-001", "implementation")
    assert run(repo, "pull-children", "WF-001") == 0   # no crash; archived child untouched

def test_pull_children_no_live_children_is_noop(self, repo):
    run(repo, "new-card", "--title", "Solo")
    assert run(repo, "pull-children", "WF-001") == 0
```

- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** `cmd_pull_children` + parser (`pull-children` with a `card_id`). Load the parent via `_load`; load live cards via `db.load_live_cards`; select children where `c.parent == card_id`; for each, `child.set_stage(parent.stage, _now())` if `parent.stage` else apply the parent's status path (mirror `cmd_unblock`/move semantics — set to in-flight/planned); `_sync` each. Then one `rebuild_index`. Print a summary (`"pulled N children into WF-001"`). Archived children aren't in `load_live_cards`, so they're naturally skipped.
- [ ] **Step 4: Run → pass**, full CLI pathless.
- [ ] **Step 5: Commit** `feat(overseer): pull-children CLI verb — move live children to parent's column (F9, WF-066)`

---

## Task 5: F9 — `POST /api/card/{id}/pull-children` endpoint

**Files:** `dashboard/backend/app/main.py`; `tests/test_mutations.py`

**Interfaces:** Consumes Task 4's verb + `require_token`. Produces the endpoint → board response.

- [ ] **Step 1: Failing tests** — endpoint moves children (assert via `_show`), is token-gated (401 without header on a gated app), 400 on bad id. Confirm the existing route-gating meta-test now counts this route.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — mirror `park_card`:

```python
    @app.post("/api/card/{card_id}/pull-children", dependencies=[Depends(require_token)])
    def pull_children(card_id: str, root: str | None = None) -> dict[str, Any]:
        effective = _resolve_root(launch_root, _derived_launch_root, root)
        def do() -> None:
            check_id(card_id)
            run_overseer(effective, "pull-children", card_id)
        return _mutate(do, effective)
```

- [ ] **Step 4: Run → pass** (whole test_mutations.py, incl. the meta-gate test).
- [ ] **Step 5: Commit** `feat(overseer-dashboard): POST /api/card/{id}/pull-children (F9, WF-066)`

---

## Task 6: F9 — drawer button + confirm + client

**Files:** `api/client.ts`, `components/CardDetailDrawer.tsx` (+ test)

**Interfaces:** Consumes the endpoint. Produces `client.pullChildren(id): Promise<BoardResponse>`; a drawer button (epics only) behind a confirm.

- [ ] **Step 1: Failing test** — for an epic (`is_epic`/has children), a "Pull children" button appears; clicking → `window.confirm` true → `mutate(() => pullChildren(id))`; confirm false → no call; button absent for non-epics.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — `client.ts`: `export function pullChildren(id){ return request("POST", withRoot(`/api/card/${id}/pull-children`)); }`. Drawer: when the card is an epic, render a "Pull children" button; onClick → `if (!window.confirm("Pull all live children into this epic's column?")) return; await mutate(() => pullChildren(detail.id)); refetchDetail();`.
- [ ] **Step 4: Run → pass**, full frontend + `tsc`.
- [ ] **Step 5: Commit** `feat(overseer-dashboard): pull-children drawer control w/ confirm (F9, WF-066)`

---

## Task 7: F10 — `label_colors` table + CLI verbs

**Files:** `scripts/db.py`, `scripts/cli.py`; `tests/overseer/test_db.py`, `test_cli.py`

**Interfaces:** Produces the `label_colors(name PK, color_key)` table + helpers `set_label_color/clear_label_color/load_label_colors` and CLI `label-color set/clear/list`. `color_key` validated ∈ the 9 palette keys (define `LABEL_PALETTE_KEYS` in models.py). Consumed by Tasks 8, 9.

- [ ] **Step 1: Failing tests** — db: set→load round-trip, clear removes, overwrite updates; cli: `label-color set foo sky` persists, `set foo notakey` → exit 1, `clear foo` removes, `list --json` returns the map.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — add `LABEL_PALETTE_KEYS = ("slate","sage","plum","clay","sky","violet","olive","terracotta","teal")` to models.py (mirror the frontend palette). db.py: add to `_SCHEMA` `CREATE TABLE IF NOT EXISTS label_colors (name TEXT PRIMARY KEY, color_key TEXT NOT NULL)` (idempotent, safe on existing DBs); helpers `set_label_color(conn,name,key)`, `clear_label_color(conn,name)`, `load_label_colors(conn) -> dict[str,str]`. cli.py: `label-color` subparser with `set <name> <color_key>` (validate key ∈ LABEL_PALETTE_KEYS else exit 1), `clear <name>`, `list --json`.
- [ ] **Step 4: Run → pass**, full CLI pathless.
- [ ] **Step 5: Commit** `feat(overseer): label_colors registry table + label-color CLI (F10, WF-067)`

---

## Task 8: F10 — payload map + registry-aware `labelColor`

**Files:** `scripts/board.py`; `api/types.ts`, `board/labelColor.ts` + all call sites (LabelChips, LabelEditor, LabelFilterPopover); tests

**Interfaces:** Consumes `load_label_colors`. Produces board payload `label_colors: {name: color_key}`; `labelColor(name, registry?)` returns `registry[name] ?? <hash palette>`.

- [ ] **Step 1: Failing tests** — backend: `board_data` includes top-level `label_colors`. frontend: `labelColor("x", {x:"sky"})==="sky"`; `labelColor("x", {})` falls back to the hash palette (unchanged for unset).
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — `board.py`: `data["label_colors"] = load_label_colors(conn)`. `types.ts`: `BoardResponse.board` (or top-level board payload type) gains `label_colors: Record<string,string>`. `labelColor.ts`: add optional 2nd param `registry?: Record<string,string>` → `registry?.[label] ?? <existing djb2 palette>`. Thread the board's `label_colors` into LabelChips/LabelEditor/LabelFilterPopover call sites (pass the map down from where the board is available). Keep the no-registry behaviour byte-identical.
- [ ] **Step 4: Run → pass**, frontend + backend + `tsc`.
- [ ] **Step 5: Commit** `feat(overseer-dashboard): registry-aware labelColor + label_colors in payload (F10, WF-067)`

---

## Task 9: F10 — `POST /api/labels/colors` endpoint

**Files:** `dashboard/backend/app/main.py`; `tests/test_mutations.py`

**Interfaces:** Consumes Task 7's CLI + `require_token`. Produces the endpoint → board response (with updated `label_colors`).

- [ ] **Step 1: Failing tests** — POST `{name,color}` sets (assert board payload `label_colors[name]==color`); `{name, color:null}` or a `clear` flag clears; token-gated (401); invalid color → 400 (CLI exit 1 → `_mutation_error`).
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — `LabelColorBody(BaseModel){ name: str; color: str | None }`; endpoint shells `label-color set name color` when color truthy else `label-color clear name`; token-gated; returns `_board_response`.
- [ ] **Step 4: Run → pass** (whole file incl. meta-gate).
- [ ] **Step 5: Commit** `feat(overseer-dashboard): POST /api/labels/colors (F10, WF-067)`

---

## Task 10: F10 — Labels settings dialog + TopBar wiring

**Files:** `components/LabelSettingsDialog.tsx` (+ test), `components/TopBar.tsx` (+ test), `api/client.ts`, `styles.css`

**Interfaces:** Consumes `label_colors`, `distinctLabels`, `setLabelColor`. Produces a dialog listing labels + 9-swatch picker.

- [ ] **Step 1: Failing tests** — dialog lists each distinct label with its current swatch; picking a swatch calls `client.setLabelColor(name, key)` (via mutate); a reset calls it with clear; TopBar renders a "Labels" settings control opening the dialog.
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — `client.ts`: `setLabelColor(name, color: string | null)` → `POST /api/labels/colors`. `LabelSettingsDialog.tsx`: ClearDialog-style overlay (`.party-overlay`/`.party-sheet`); props `{ open, onClose, labels, colors, mutate }`; per label a row: name chip (current colour) + the 9 swatches (each a button `label-chip--<key>`, aria-label `"<name>: <key>"`) + a reset; picking → `await mutate(() => setLabelColor(name, key))`. TopBar: a control (e.g. next to Clear) opening it, passing `distinctLabels(cards)` + the board `label_colors` + `mutate`. CSS: reuse existing dialog + `.label-chip--*` classes; add only layout for the settings rows/swatch grid.
- [ ] **Step 4: Run → pass**, full frontend + `tsc`.
- [ ] **Step 5: Commit** `feat(overseer-dashboard): Labels settings dialog — editable colour registry (F10, WF-067)`

---

## Task 11: Version bump + dist rebuild + full green

**Files:** `plugin.json`, `marketplace.json`, `dist/**`

- [ ] **Step 1:** bump `plugins/overseer/.claude-plugin/plugin.json` `0.14.0→0.15.0`, `.claude-plugin/marketplace.json` `1.19.0→1.20.0`.
- [ ] **Step 2:** full frontend `npm test` + `tsc --noEmit` → green.
- [ ] **Step 3:** rebuild dist `npm run build`.
- [ ] **Step 4:** backend `pytest -q` (incl. `test_dist_freshness`) + CLI pathless `pytest -q` → green.
- [ ] **Step 5: Commit** `chore(overseer): PR5 P2 bundle — dist rebuild + v0.15.0`

---

## Self-review notes
- **Spec coverage:** F8 → Tasks 1,2,3. F9 → Tasks 4,5,6. F10 → Tasks 7,8,9,10. Version/dist → Task 11. S1/S2 intentionally absent (HELD on ledger decision).
- **Type consistency:** `Card.links` (T1) → `board.py` `links` (T3) → `BoardCard.links` (T3). `label_colors` map: `load_label_colors` (T7) → payload (T8) → `BoardResponse` type (T8) → dialog (T10). `LABEL_PALETTE_KEYS` (T7) is the single source for the 9 keys, mirrored by the frontend palette. `pullChildren`/`setLabelColor` client fns (T6/T10) match their endpoints (T5/T9).
- **Placeholder scan:** correctness-critical code (model round-trip, CLI verbs, endpoints, labelColor) is concrete; component/dialog JSX+CSS defers to in-file idiom (marked), consistent with PR3/PR4.
- **Gate coverage:** T5 and T9 add mutating routes — both carry `require_token`; the PR3 route-gating meta-test must stay green (verified in each).
