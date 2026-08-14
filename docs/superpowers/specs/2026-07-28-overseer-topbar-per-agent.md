# Overseer dashboard: per-agent context + fleet-health top bar (WF-042) — design

**Date:** 2026-07-28
**Status:** Approved (brainstorm), pending implementation plan
**Depends on:** Task 13 (PR #35 — scoped Party, per-agent branch, `/api/sessions` with model/pct/pr/branch).

## Problem

The top bar shows **ctx% / model / PR of the *launching* session** (from a single `context` blob via vigil/census). In a multi-agent dashboard that's arbitrary — those are per-session facts sitting in a global bar. They belong per-agent; the top bar should describe the board/account and the fleet.

## Goals

- Move per-session **ctx% / model / PR** out of the global top bar; surface them **per-agent** in the Party.
- Give the top bar a **fleet-health summary** instead of one session's numbers.
- Keep **threshold** as a single **global default** (reframed); per-agent override deferred.
- **Handover-enabled indicator: PARKED** (see below) — revisit as a follow-up.

## Decisions (from brainstorm)

| Decision | Choice |
|---|---|
| Top bar after removal | Board/account controls **+ a fleet health line** |
| Per-agent facts | ctx% + near-threshold cue + PR added to Party cards (model/branch/mana already there) |
| Threshold | Global default now; per-agent override deferred |
| Handover indicator | **Parked** — census carries no vigil state; surfacing it needs a new `vigil status` command or backend coupling to vigil's internal `.vigil/` markers (changes shape / adds deps) — against the user's guardrail |

## Why handover is parked (evidence)

Census payload has no vigil/handover field. Vigil's "handover enabled" state is filesystem markers **per worktree** (`.vigil/active`, `.vigil/paused`, `context.mode`) and vigil has **no status command** that reports them. Surfacing per-agent handover state would require either (a) a new `vigil status --json` command (changes vigil's reporting) + per-session shell-outs, or (b) the overseer backend reading vigil's internal marker files (couples overseer to vigil internals). Both trip "if vigil reporting changes shape / adds dependencies / gets complex, park it." → **Follow-up card**; likely first step is a clean `vigil status --json` command, then wire it.

## Architecture

Almost entirely **frontend** — the data is already in `/api/sessions` (each session: `model`, `pct`, `pr`, `branch`, `session_name`, `stale`) and `/api/board`'s `context.threshold`.

**1. Top bar (`TopBar.tsx`)**
- **Remove** the launching-session pills: `context.model`, `context.pr`, and the single `ctx NN%` value.
- **Keep**: repo selector, Refresh, Archive, questing count, account rate-limits (`limits`), and the **threshold control** — reframed/labeled as the **global default**.
- **Add a fleet-health line** computed from the live (non-stale) sessions + the global threshold, e.g.:
  `⚔ 5 questing · top ctx 86% · 2 near threshold`
  - *questing* = live session count (existing).
  - *top ctx* = max `session.pct` across live sessions (omit if no pct data).
  - *near threshold* = count of live sessions with `pct >= threshold` (omit/zero-state gracefully).
- Backend `context.model`/`context.pr`/`context.pct` may remain in the payload (harmless); the top bar simply stops rendering them. (Optional tidy: stop computing them in `_census_extras`/`_board_response` — out of scope unless trivial.)

**2. Party cards (`PartyOverlay.tsx` hero cards, `PartyColumn.tsx`/`PartyAvatar.tsx`)**
- Already render: `model`, `branch`, mana (`100 - pct`).
- **Add** per agent: explicit **ctx%** (the raw `session.pct`), a **near-threshold cue** (a warning tint/ring when `pct >= threshold` — threshold passed down from board context), and the agent's **PR** (`pr.number` · `pr.review_state`, linking `pr.url` if present).
- Keep it on-theme (parchment/guild). Absent fields (no pct/pr) → omitted, mirroring current "forward what's there" style.

**3. Fleet-summary util (`src/board/fleet.ts`, new)**
- `fleetSummary(sessions, threshold) -> { questing, topCtx, nearThreshold }` — pure, testable; drops stale sessions; handles missing pct.

## Data flow

`/api/sessions` (model/pct/pr/branch per agent) + `/api/board` `context.threshold` → `fleetSummary()` feeds the top-bar line; per-session fields feed the Party cards; the top bar stops reading `context.model/pr/pct`.

## Error handling

- All per-agent fields optional (absent → omitted).
- No live sessions / no pct → fleet line shows a graceful zero-state ("no adventurers questing" or just the questing count), never NaN/undefined.
- Threshold absent → near-threshold cue simply doesn't fire.

## Testing

- `fleetSummary`: questing counts live-only; topCtx = max pct; nearThreshold counts `pct>=threshold`; zero-state (no sessions / no pct) safe.
- TopBar: no longer renders `context.model`/`context.pr`/single ctx value; renders the fleet line; threshold control still works and reads as the default.
- Party cards: render ctx% + PR; near-threshold cue fires when `pct>=threshold`, not otherwise; absent fields omitted.

## Non-goals / deferred (follow-up cards)

- **Per-agent threshold override** (needs per-session threshold storage).
- **Handover-enabled indicator** (needs a `vigil status --json` command; parked per guardrail).
- Backend cleanup of now-unused `context.model/pr` (leave unless trivial).

## Scope / sequencing

Own branch + PR, after PR #35 (Task 13) merges. No cross-plugin change (vigil untouched — that's the parked part). Backend unchanged unless the optional tidy is trivial.
