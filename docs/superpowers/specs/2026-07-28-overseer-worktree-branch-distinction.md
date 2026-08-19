# Overseer: worktree/branch distinction on the shared board — design

**Date:** 2026-07-28
**Status:** Approved (brainstorm), pending implementation plan
**Branch:** `feat/overseer-worktree-branch`
**Depends on:** the SQLite board migration + repo selector (PR #34, merged) — `board.db` per repo with `meta['repo_root']`, `derive_repo_root`, `/api/repos`.

## Problem

Cards now live in one per-repo `board.db` shared across all worktrees (good). But nothing distinguishes *which worktree/branch* a card or a live agent is working on, and the dashboard's Party/sessions panel is **account-global** — it shows every session under the account (census is rooted at `$CLAUDE_CONFIG_DIR`, not per repo), so agents from unrelated repos (agent-ui, ledger-poc) appear on the pip-skills board. Empirically: 15 "live" sessions across 3 repos where only 5 belong to pip-skills.

## Goals

- **Distinguish branch/worktree** for both cards and live agents on the shared board.
- **Scope the Party** to the repo the board is serving.
- **Surface "unbegun" repos** — repos that have live agents (census cwds) but no `board.db` yet appear in the selector; choosing one shows a quest-themed holding page prompting the user to raise a board there.
- Keep census a soft, fail-safe dependency; every branch value optional end-to-end.

## Decisions (from brainstorm)

| Decision | Choice |
|---|---|
| Card branch source | `card.branch` — already set by the orchestrator (`set-field --branch`) |
| Agent branch source | **Census captures the git branch at write time** (status-line runs in the session's worktree) |
| Party scoping | Filter to sessions whose `derive_repo_root(worktree_cwd) == board repo_root` |
| Ghost sessions | A session whose cwd no longer resolves to a repo (removed worktree) → dropped |
| Filter behaviour | Pick a branch → non-matching cards **dim** (stay visible); matching cards + Party agents on that branch **spotlighted**; "All" resets |
| Unbegun repos | Repos with live census sessions but no `board.db` appear in the selector (distinct styling); selecting one shows a quest-themed holding page — no board fetch, no shelled root |

## Architecture

### 1. Census (leaf) — capture the branch
The census status-line recorder runs in each session's worktree. At record time, derive the git branch (`git -C <worktree_cwd> rev-parse --abbrev-ref HEAD`) and store it as `branch` on the session entry, beside `worktree_cwd`.
- **Fail-safe:** git missing / detached HEAD / not-a-repo → `branch` omitted (None). Never raises; census must never break the status line.
- **Backward-compatible:** old entries simply lack `branch`.
- Location: the census ingest path (`statusline.py` / `store.py` record). Derive from the resolved worktree cwd (the same value `resolve.worktree_cwd` produces).

### 2. Overseer backend — surface branch + scope sessions
`dashboard/backend/app/main.py`:
- `_session_summary` (line ~145) already returns `worktree_cwd`; add `branch` (soft — omit when absent).
- `_sessions_list` / `GET /api/sessions` (line ~175, ~319): **scope to a repo**. Accept the same validated `root` the board endpoints use (default `_derived_launch_root`), and keep only sessions where `derive_repo_root(worktree_cwd)` equals that root's derived repo root. Drop sessions whose cwd doesn't resolve (ghosts).
  - `derive_repo_root` runs a git subprocess per session — N is small (a handful); acceptable. Cache within a single request if trivial.
- Card `branch` is already in the board JSON — no card-side backend change.
- **`GET /api/repos` augmentation (unbegun repos):** the endpoint currently returns only repos with a `board.db` (from the `repos --json` CLI verb). Augment it in the backend by unioning in **repos derived from live census sessions that have no board**: for each live session, `derive_repo_root(worktree_cwd)`; any distinct repo root NOT already in the board set becomes an "unbegun" entry. Each `/api/repos` entry gains `has_board: bool` and `live_sessions: int` (count of live sessions mapping to that repo). Board repos → `has_board: true`; unbegun repos → `has_board: false`, `live_sessions > 0`. Keep the `repos` CLI verb board-only; the census union is dashboard-specific and lives in the backend (which already reads census). Unbegun roots are NOT added to the board-serving allowlist — the dashboard never fetches `/api/board` for them, so no new shelled-root surface.

  `label` for an unbegun repo = its directory basename (via `derive_repo_label` or the path's name); resolve from the derived repo root.

### 3. Overseer frontend — badges, scoped party, filter
`dashboard/frontend/src/`:
- **Card branch badge:** a small branch chip on any card with `card.branch` (`components/` card renderer). On-theme (parchment/guild), distinct from status chips.
- **Party avatars:** show each agent's `branch` (from the scoped `/api/sessions`) alongside its worktree (`PartyAvatar.tsx` / `PartyColumn.tsx` / `PartyOverlay.tsx`, `board/useSessions.ts`). Party is now repo-scoped by the backend, so it shows only the current board's agents.
- **Branch filter:** a control listing the distinct branches present = union of `card.branch` across board cards and `branch` across scoped sessions. Selecting one sets `activeBranch`:
  - cards where `card.branch !== activeBranch` get a `dimmed` class (faded, in place);
  - cards matching + Party agents on `activeBranch` get a `spotlight` class;
  - "All" clears. Session-local state (mirror the repo selector's pattern; localStorage optional).
- **Unbegun-repo selector entries + holding page:** the selector renders unbegun repos (`has_board: false`) with distinct styling (e.g. a faded/dashed entry with a small "not begun" hint and the live-agent count). Selecting an unbegun repo renders a **quest-themed holding page** in the board area instead of fetching `/api/board`. Copy (quest/guild voice — polish to taste, keep the command accurate):
  > 🗺️ **Your quest has not yet begun in _{repo}_.**
  > {N} adventurer{s} already roam these lands, but no Guild Board has been raised here.
  > To open the board and begin chronicling quests, run `overseer init` in `{repo}` (or invoke the overseer skill there).

  Pluralise "adventurer(s)" from `live_sessions`. Once a board is raised there, the repo simply becomes a normal `has_board: true` entry on the next `/api/repos` poll.

## Data flow

census store (`branch` added) → `census read` → backend `_sessions_list` (scoped by `derive_repo_root` to the served board, ghosts dropped, `branch` surfaced) → `/api/sessions` → frontend Party (scoped, branch-tagged). Board JSON's `card.branch` → frontend card badges + branch-filter source.

## Error handling

- Branch optional at every layer: no branch → no chip / no label / not offered in the filter.
- Census branch derivation wrapped fail-safe (returns None, never raises).
- Backend session scoping: `derive_repo_root` failure or non-match → session excluded; endpoint still 200 with the sessions it can place.
- Filter over a branch that later disappears → falls back to "All" (no matches ≠ empty board).

## Testing

- **Census:** branch captured from a real git worktree cwd; `None` on non-repo / detached HEAD / git failure; recorder never raises.
- **Backend:** `_session_summary` carries `branch` when present; `/api/sessions?root=…` returns only sessions whose derived repo root matches; ghost (unresolvable cwd) dropped; unknown root still rejected (existing security test unaffected). `/api/repos` includes unbegun repos (live census sessions, no board) with `has_board:false` + `live_sessions`, while board repos keep `has_board:true`; a repo with a board is never double-listed.
- **Frontend:** card branch chip renders for carded branches; distinct-branch derivation (cards ∪ sessions); filter dims non-matching + spotlights matches & party; "All" reset; Party shows only scoped sessions with branch labels; selecting an unbegun repo renders the holding page (with correct repo name, agent count/plural) and does NOT call `/api/board`.

## Non-goals / deferred

- Migrating sprints/usage/knowledge (still file-based — separate phase).
- Cross-repo aggregate views (the selector already switches repos one at a time).
- Persisting the branch filter across reloads (session-local is enough for v1).

## Scope note

This is the one deliberate cross-plugin change: census stores one extra field (`branch`). It's a data-contract extension, not code coupling — the `census ← overseer` soft read is unchanged.
