# Overseer — Sessions Claim a Card from the Dashboard — Design Spec

**Date:** 2026-07-13
**Status:** Proposed design (WF-017; pre-approval)
**Grounding:** fact sheet gathered from the working tree 2026-07-13 (census store shape, sessions
API, card-model precedent, vigil kick machinery — all claims below cite the source; the one
doc-only claim is flagged).

## Context

The dashboard can see live sessions (census-backed `GET /api/sessions`, WF-010) and can mutate
cards (nine single-writer endpoints shelling the overseer CLI), but the two never meet: there is
no way to point at a card on the board, point at a session, and say "you — take this." Assignment
today is a human typing "pick up WF-XXX" into the right terminal.

Verified constraints that shape the design:

- **Cards have no owner concept.** The `Card` dataclass has no owner/assignee/claimed field;
  adding one follows the `checklist:` precedent exactly (parse → dataclass field → conditional
  serialise so untouched cards stay byte-stable → board/show JSON passthrough).
- **Census is a status-line mirror, not a control channel.** It keys sessions by `session_id`,
  records `worktree_cwd` + the payload verbatim, flags entries stale after 90s, and prunes after
  24h. It records no tmux pane today — but `census ingest` runs inside the status-line pipeline,
  a child of the session process, so `TMUX_PANE` (and `TMUX`) are in its environment and can be
  captured at ingest with no new plumbing.
- **There is exactly one proven way to push into a running session:** vigil's resume-kick —
  detached `sleep <delay>; tmux send-keys -t <pane> -l "<prompt>"; tmux send-keys -t <pane> Enter`,
  targeted purely by pane id, every failure swallowed. It currently fires only from the session's
  own SessionStart hook; the mechanism itself is origin-agnostic.
- **There is no poll point in a running session.** The orchestrate loop reads the ledger once at
  session start; no hook re-reads ledger state mid-session. A claim signal must either push (kick)
  or wait for a natural boundary (SessionStart, UserPromptSubmit).
- **CC's native task `owner` field is doc-only.** The task-system research flags owner/self-claim/
  file-locked-claiming as `[docs]`, never empirically verified. Nothing here builds on it.

## Decisions

| Question | Choice | Rationale |
|---|---|---|
| Claim model | New `claimed_by:` frontmatter field on the card (census `session_id`) + `claim`/`unclaim` CLI verbs | Cards are the durable ledger; single-writer stays intact; checklist precedent makes the field mechanical |
| Who may hold a claim | Exactly one session per card; a card per claim (no fan-out) | A card is one unit of orchestrated work; two claimants is a conflict, not a feature |
| Delivery — primary | **Stop-hook check** (turn boundary): a quarantine-safe Stop hook reads `session_id` from stdin, scans for `claimed_by == me && !claim_acked`, and emits `decision: block` with reason `Claimed for you from the dashboard: pick up <id>` — so a session finishing its current work flows straight into the assigned card | The dashboard already "writes the file" (the claim stamp on the card); the turn boundary is the natural dispatch moment and needs no push infrastructure. Loop-bounded: `stop_hook_active` guards one block per stop cycle, and the pickup's own work verb acks the claim so the next Stop passes clean; an ignored nudge degrades to a user-visible `systemMessage` (vigil's Stop hook documents blocking as the infinite-continuation hazard — this design blocks only under a convergent, acked condition) |
| Delivery — attended | A UserPromptSubmit hook injects a one-line notice when an unacknowledged claim addressed to this session exists; `resume` lists this session's claims first when invoked with `--session-id` | Covers a human mid-conversation without waiting for a turn end; no invented poll loop |
| Delivery — idle sessions (optional, deferred) | Push: `overseer claim … --kick` resolves the session's tmux pane from census and reuses the vigil-style detached send-keys dispatch | The one case hooks cannot reach is a session already sitting idle when the claim lands — no turns, no hooks. Deferred to its own follow-up card; without it, an idle session acts on the claim when next touched |
| Pane discovery | census `ingest` additionally records `tmux_pane` (from `TMUX_PANE` env) per session entry — **already landed (WF-020)**; dormant enabler for the optional kick | Ingest is a child of the session process — the env is authoritative and already flowing; one field, no new writer |
| Dashboard UX | "Assign" control on the card drawer (and sessions panel row → card, later): picks from live (non-stale) sessions; `POST /api/card/{id}/claim {session_id}`; tile badge shows the claim (session_name, stale-dimmed) | Mirrors every existing mutation: validate → shell CLI → re-read board |
| Conflict rule | `claim` refuses if `claimed_by` is set AND that session is live in census; succeeds with a note if the holder is stale/absent (stale claims are self-healing); `--force` overrides; `unclaim` clears unconditionally | Deaths shouldn't wedge cards; live claims shouldn't be silently stolen |
| Claim ≠ stage | Claiming does not change status/stage; it is routing metadata. The claimed session drives stages as normal once it picks the card up | Keeps the ledger state machine untouched; a claim on a `planned` card is simply "you're next" |
| Acknowledgement | Dedicated flag: `claim` writes `claim_acked: false`; the **work verbs** (`set-stage`, `log-progress`, `log-review`, `block`) flip it to `true` on their next write to that card; routing verbs (`set-field --order/--priority`, `park`, `depends`) do NOT ack | Review killed the `claimed_at > updated` heuristic: every mutator stamps `updated`, so a routine board reorder would silently swallow the ack signal. A dedicated flag costs one field and cannot be forged by unrelated dashboard actions |
| Session self-identity | The UserPromptSubmit notice hook reads `session_id` from its stdin payload (the established pattern — every hook payload carries it); `resume` keys claim-first ordering off the CLI's existing global `--session-id` flag when provided, and otherwise just labels claimed cards with their holder | Review found `$CLAUDE_SESSION_ID` exists nowhere in this codebase — no bare CLI call can discover its own session id from the environment, so nothing may depend on that |

## 1. The shape

```
dashboard drawer ── POST /api/card/WF-XXX/claim {session_id: "abc…"}
        │  (validate; single-writer _mutate pattern)
        ▼
overseer claim WF-XXX --session abc…
        │  writes claimed_by: abc… + claimed_at + claim_acked: false to card frontmatter
        ▼
the claimed session, at its next turn boundary:
  Stop hook ── claimed_by == me && !claim_acked?
        │  yes → decision: block, reason "pick up WF-XXX" → session continues into the card
        │  (its set-stage/log-progress acks the claim → next Stop passes clean)
        ▼
session picks up WF-XXX
  ── mid-conversation: UserPromptSubmit notice covers the attended case
  ── already idle: acts when next touched (or the optional --kick follow-up pushes via tmux)
```

## 2. Census: record the pane (prerequisite, tiny)

**Status: landed (WF-020).** `ingest()` captures `tmux_pane: os.environ.get("TMUX_PANE") or None`
on the session entry beside `worktree_cwd`; absent env → key absent; re-ingest without the env
drops a stale pane (wholesale-replace, matching sibling fields). With the kick deferred (see
Decisions), this is a dormant enabler — harmless until the optional kick card builds on it.

**Verification requirement (from review):** env inheritance into the *statusline* subprocess is
analogy from the hook path (`CLAUDE_CONFIG_DIR` is the only variable proven through this exact
channel). The implementation card must include a manual check that `TMUX_PANE` actually appears
in a real ingest under tmux before anything downstream builds on it.

## 3. Overseer: `claimed_by` + verbs

- `models.py`: `claimed_by: str | None`, `claimed_at: str | None` (ISO minute, like `updated`) and
  `claim_acked: bool` (meaningful only while claimed), parsed defensively, serialised
  **conditionally** (unclaimed cards stay byte-stable — checklist precedent). The work verbs
  (`set-stage`, `log-progress`, `log-review`, `block`) set `claim_acked = true` as part of their
  ordinary write when the card is claimed; routing verbs leave it alone.
- `overseer claim <id> --session <sid> [--force]`:
  - unknown card → exit 1; already claimed by a live session and no `--force` → exit 1 with the
    holder's id/name in the message; claimed by a stale/absent session → claim succeeds, prints a
    note that the stale claim was displaced.
  - liveness = census `for_session(sid)` fresh within the 90s horizon (via the census CLI, matching
    the dashboard backend's client pattern — overseer must not import census internals).
  - The verb is a pure stamp — no delivery side effects. (The deferred `--kick` option, if its
    follow-up card is ever built: resolve the pane from census, dispatch the detached send-keys.
    **Implementation trap from review: reuse ONLY the low-level
    `_dispatch_resume_kick(pane, tmux_bin, delay)` — never `_maybe_kick_resume`'s gate, which
    checks the CALLING process's own `$TMUX`/`$TMUX_PANE` and would silently break every kick sent
    from the non-tmux dashboard backend. Probe the pane with `tmux list-panes -t <pane>` first.**)
- `overseer unclaim <id>`: clears all claim fields, exit 0 even if already unclaimed (idempotent).
- `resume` gains: when invoked with the existing global `--session-id` flag, cards claimed by that
  session sort first and are marked `← claimed for this session`; without it, claimed cards are
  simply labelled `claimed by <holder>`. (No env-var self-discovery exists for bare CLI calls —
  the notice hook below is the channel that knows the session's own id.)

## 4. Delivery: turn-boundary hooks

Both hooks are quarantine-safe (checklist-sync shape), read `session_id` from their stdin payload
(every hook payload carries it — the codebase's established identity channel), and scan cards for
`claimed_by == session_id && !claim_acked`. Absent claims → empty output, zero cost.

**Stop hook (primary — the autonomous dispatch channel).** At turn end, an unacked claim means
this session has been handed work while it was busy. Emit `decision: block` with reason
`Claimed for you from the dashboard: pick up WF-XXX` — the session continues straight into the
assigned card instead of going idle. Loop discipline (vigil's own Stop hook documents blocking as
"the one cause of the costly infinite-continuation loop", so the bound is explicit):

- Block ONLY when `!claim_acked && !stop_hook_active`. The payload's `stop_hook_active` flag is
  true when a Stop hook already blocked this cycle — never block twice in one cycle.
- Convergence: the pickup's own first work verb (`set-stage`/`log-progress`) acks the claim, so
  the next Stop finds `claim_acked` and passes clean.
- Defiance: if the model continued but never acked (ignored the nudge), the next Stop does NOT
  block again for the same claim — it emits a user-visible `systemMessage`
  (`overseer: WF-XXX is claimed for this session and unacknowledged`) and lets the stop stand.
  Requires remembering "already nudged": a `claim_nudged: bool` on the card, set via the CLI by
  the hook itself (single-writer preserved — the hook shells a verb, exactly like checklist-sync).
- Registration note: vigil also registers a Stop hook; both run independently (same dual-
  registration precedent as the two PostToolUse hooks on TaskCreate|TaskUpdate).

**UserPromptSubmit notice (attended sessions).** Injects one line of additionalContext:
`Cards claimed for this session from the dashboard: WF-XXX — run resume / pick it up.`
Never blocks the prompt; repeats at every prompt until a work verb acks the claim. Covers the
human-in-conversation case without waiting for a turn end.

Together the two hooks make delivery guaranteed-at-next-activity. The one unreachable case — a
session already idle when the claim lands, with nobody touching it — is the deferred kick card's
territory; until then such a session acts on its claim when next touched.

## 5. Dashboard

- Backend: `POST /api/card/{id}/claim {session_id}` and `POST /api/card/{id}/unclaim` following
  `_mutate` verbatim (validate id, shell `overseer claim …` / `unclaim`, return fresh
  board). `GET /api/sessions` and the board response pass `claimed_by`/`claimed_at` through (JSON
  passthrough — no backend model work, matching checklist).
- Frontend: drawer gains an "Assign to session" select fed from the sessions panel data (live
  sessions only, labelled by session_name/model/worktree); tiles show a small claim badge
  (session_name, dimmed when that session has gone stale — census staleness is already in the
  sessions payload). Unassign from the drawer.

## 6. Failure honesty

| Scenario | Behaviour |
|---|---|
| Claimed session dies | Claim goes stale with the session (census horizon); any new claim displaces it with a note; badge dims on the board |
| Two users claim simultaneously | Single-writer CLI serialises; second claim hits the live-holder refusal |
| Claimed session already idle when the claim lands | No turns → no hooks → nothing delivered until the session is next touched (the notice/Stop hooks then fire). The deferred kick card is the only cure for this case; until then the badge on the board is the visibility |
| Session blocks-and-ignores the Stop nudge | One block per claim (`claim_nudged`), then a user-visible systemMessage each stop; never an infinite continuation loop |
| A second claim arrives after the first was nudged | `claim_nudged` is per-claim state, cleared by `claim`/`unclaim` — the new claim gets its own single nudge |
| Session outside tmux | Irrelevant to hook delivery (hooks are transport-free); only the deferred kick cares about tmux |
| `resume` invoked without `--session-id` | Claim-first ordering unavailable; claimed cards still labelled with their holder. The hooks (which always know their session id from stdin) remain the authoritative "this claim is yours" channel |
| (Deferred kick, if built) pane gone / recycled / lands mid-turn | Failure rows preserved in the kick follow-up card: silently skipped when the pane is gone; recycled-pane residual bounded by the 90s horizon; mid-turn text queues as the next user message |

## 7. Testing

- overseer: claim/unclaim/force/stale-displacement/idempotency, frontmatter round-trip +
  byte-stability of unclaimed cards, resume ordering with/without `--session-id`, ack
  transitions (work verbs ack, routing verbs don't, reorder-after-claim does NOT ack — the
  review's counterexample becomes a regression test) (store test patterns).
- census: ingest records/omits `tmux_pane` — landed with WF-020.
- Stop hook: fixture payloads → blocks exactly once per unacked claim; respects
  `stop_hook_active`; systemMessage after nudge; acked claim → clean pass; no claim → empty
  output; every failure path exits 0 (checklist-sync test pattern).
- UserPromptSubmit hook: notice/no-notice/never-blocks.
- backend: claim/unclaim endpoints (existing endpoint test pattern); frontend: badge + assign
  select (RTL).
- Manual E2E: two sessions + dashboard; assign from drawer to a busy session → it picks the card
  up at its next turn end; assign to an attended session → notice at next prompt; kill a
  claimant → badge dims → re-claim displaces.

## 8. Follow-up implementation cards

1. **census: record tmux_pane at ingest** — LANDED (WF-020); dormant enabler for card 5.
2. **overseer: claim fields (claimed_by/claimed_at/claim_acked/claim_nudged) + claim/unclaim
   verbs + work-verb ack + resume ordering** (M). Pure stamp — no delivery.
3. **overseer: Stop + UserPromptSubmit claim hooks + orchestrate doctrine** ("respond to a
   claim", claim-awareness in pickup, loop-bound discipline; M).
4. **dashboard: claim endpoints + assign UX + claim badges** (M).
5. **optional/deferred — tmux claim kick for already-idle sessions** (S): `claim --kick` per the
   implementation-trap notes in §3; only worth building if idle-session dispatch proves to be a
   real gap in practice.

Order: 2 → {3, 4}; 5 anytime after 2 (1 already landed).

## 9. Out of scope

- Riding CC's native task `owner` field (doc-only, unverified — revisit if it's ever proven).
- Dashboard-initiated *unassignment kick* (telling a session it lost a card mid-flight).
- Multi-card queues per session (claim one card at a time; a queue is a sprint concern).
- Auto-claim (a session grabbing unclaimed P0s without a human click) — separate doctrine debate.
