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
| Delivery — primary | Push: backend shells `overseer claim … --kick`, which resolves the session's tmux pane from census and reuses the vigil-style detached send-keys dispatch with prompt `Claimed for you from the dashboard: pick up <id>` | The only proven inbound channel; pane id comes from census once ingest records it |
| Delivery — fallback | Pull at natural boundaries: `resume` output (already read at every orchestrated session start) lists cards claimed by *this* session first; a UserPromptSubmit hook injects a one-line notice when an unacknowledged claim addressed to this session exists | Sessions outside tmux (or with a dead pane) still learn of the claim at the next boundary; no invented poll loop |
| Pane discovery | census `ingest` additionally records `tmux_pane` (from `TMUX_PANE` env) per session entry | Ingest is a child of the session process — the env is authoritative and already flowing; one field, no new writer |
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
overseer claim WF-XXX --session abc… [--kick]
        │  writes claimed_by: abc… (+ claimed_at) to card frontmatter
        │  --kick: census for_session(abc…) → payload.tmux_pane
        ▼
detached: sleep 2; tmux send-keys -t %N -l "Claimed for you from the dashboard: pick up WF-XXX"; tmux send-keys -t %N Enter
        │  (pane dead / no pane / not tmux → claim still recorded; kick silently skipped)
        ▼
session picks up WF-XXX  ── or learns via resume/UserPromptSubmit at the next boundary
```

## 2. Census: record the pane (prerequisite, tiny)

`ingest()` gains one line of capture: `tmux_pane: os.environ.get("TMUX_PANE") or None` stored on
the session entry beside `worktree_cwd`. Readers pass it through like every other field. Absent
env → field absent → kick degrades to fallback delivery. No migration: old entries simply lack
the key.

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
- `overseer claim <id> --session <sid> [--kick] [--force]`:
  - unknown card → exit 1; already claimed by a live session and no `--force` → exit 1 with the
    holder's id/name in the message; claimed by a stale/absent session → claim succeeds, prints a
    note that the stale claim was displaced.
  - liveness = census `for_session(sid)` fresh within the 90s horizon (via the census CLI, matching
    the dashboard backend's client pattern — overseer must not import census internals).
  - `--kick`: resolve pane, dispatch the detached send-keys. **Implementation trap (from review):
    reuse ONLY the low-level `_dispatch_resume_kick(pane, tmux_bin, delay)` — it takes the pane as
    an argument and works from any process. Do NOT copy `_maybe_kick_resume`'s gate, which checks
    the CALLING process's own `$TMUX`/`$TMUX_PANE` and would silently break every kick sent from
    the non-tmux dashboard backend.** Before dispatch, probe the pane still exists
    (`tmux list-panes -t <pane>`); delay env-tunable, everything swallowed. The kick is
    best-effort by definition; the claim write is the source of truth.
- `overseer unclaim <id>`: clears all claim fields, exit 0 even if already unclaimed (idempotent).
- `resume` gains: when invoked with the existing global `--session-id` flag, cards claimed by that
  session sort first and are marked `← claimed for this session`; without it, claimed cards are
  simply labelled `claimed by <holder>`. (No env-var self-discovery exists for bare CLI calls —
  the notice hook below is the channel that knows the session's own id.)

## 4. Delivery fallback: UserPromptSubmit notice

A new overseer hook (same quarantine-safe shape as checklist-sync): on UserPromptSubmit, read
`session_id` from the hook's stdin payload (every hook payload carries it — the codebase's
established identity channel), then scan cards for `claimed_by == session_id && !claim_acked`;
if any, inject one line of additionalContext:
`Cards claimed for this session from the dashboard: WF-XXX — run resume / pick it up.`
Absent claims → empty output, zero cost. The hook never blocks the prompt. The notice repeats at
every prompt until a work verb acks the claim — deliberate: it is the guaranteed-delivery channel;
the kick is only the fast path.

## 5. Dashboard

- Backend: `POST /api/card/{id}/claim {session_id}` and `POST /api/card/{id}/unclaim` following
  `_mutate` verbatim (validate id, shell `overseer claim … --kick` / `unclaim`, return fresh
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
| Kick fails (pane gone, tmux dead, not tmux) | Claim recorded; kick silently skipped; fallback delivery at next boundary |
| Two users claim simultaneously | Single-writer CLI serialises; second claim hits the live-holder refusal |
| Claimed session ignores the kick | Nothing breaks — claim is routing metadata; UserPromptSubmit notice repeats at each prompt until acknowledged |
| Session outside tmux | Fallback-only delivery; claim still fully functional |
| Kick lands mid-turn (target busy, not at an idle prompt) | New territory vigil never exercises: `send-keys` text enters the input buffer and is queued as the next user message. Acceptable — the prompt arrives at the turn boundary; the notice hook independently repeats until acked |
| Pane id recycled (target died <90s ago, still offered as live; tmux reused `%N`) | Rare but real: the pre-dispatch `list-panes` probe passes and the kick lands in an unrelated pane as a stray typed line. Accepted residual risk — bounded by the 90s horizon, and the payload is a harmless English sentence. The claim record itself is unaffected |
| `resume` invoked without `--session-id` | Claim-first ordering unavailable; claimed cards still labelled with their holder. The notice hook (which always knows its session id from stdin) remains the authoritative "this claim is yours" channel |

## 7. Testing

- overseer: claim/unclaim/force/stale-displacement/idempotency, frontmatter round-trip +
  byte-stability of unclaimed cards, resume ordering with/without `--session-id`, ack
  transitions (work verbs ack, routing verbs don't, reorder-after-claim does NOT ack — the
  review's counterexample becomes a regression test) (store test patterns).
- census: ingest records/omits `tmux_pane` (env present/absent).
- kick dispatch: subprocess-spy test mirroring vigil's `test_resume_kick.py`.
- hook: fixture payloads → notice/no-notice/never-blocks (checklist-sync test pattern).
- backend: claim/unclaim endpoints (existing endpoint test pattern); frontend: badge + assign
  select (RTL).
- Manual E2E: two tmux sessions + dashboard; assign from drawer → kick arrives; kill a claimant →
  badge dims → re-claim displaces.

## 8. Follow-up implementation cards

1. **census: record tmux_pane at ingest** (S, fully specified — rubric: task brief only). Must
   include the manual TMUX_PANE-reaches-ingest verification (§2).
2. **overseer: claim fields (claimed_by/claimed_at/claim_acked) + claim/unclaim verbs + work-verb
   ack + resume ordering + kick dispatch** (M).
3. **overseer: UserPromptSubmit claim-notice hook + orchestrate doctrine** ("respond to a claim",
   claim-awareness in pickup; S/M).
4. **dashboard: claim endpoints + assign UX + claim badges** (M).

Order matters: 1 → 2 → {3, 4} (3 and 4 are independent once 2 lands).

## 9. Out of scope

- Riding CC's native task `owner` field (doc-only, unverified — revisit if it's ever proven).
- Dashboard-initiated *unassignment kick* (telling a session it lost a card mid-flight).
- Multi-card queues per session (claim one card at a time; a queue is a sprint concern).
- Auto-claim (a session grabbing unclaimed P0s without a human click) — separate doctrine debate.
