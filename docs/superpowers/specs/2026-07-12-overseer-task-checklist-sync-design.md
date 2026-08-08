# Overseer — Card ↔ Task-Checklist Sync — Design Spec

**Date:** 2026-07-12
**Status:** Approved design (user approved direction; pre-implementation)
**Grounding:** `docs/research/2026-07-12-claude-code-task-system.md` (all task-system claims there
are empirically verified or doc-cited; this spec does not restate evidence).

## Context

Orchestrated work currently runs **two parallel bookkeeping systems by hand**: overseer cards (the
durable ledger — stages, budgets, review logs, PR links) and Claude Code tasks (the live surface the
harness natively understands — UI checklist, teammate claiming, dependency unblocking, and vigil's
threshold nudge, which matches `TaskCreate|TaskUpdate`). Every orchestrated session mirrors state
between them manually. That is duplicated process — not DRY — and the duplication is invisible when
it drifts.

The integration model (user-chosen): **tasks are smaller than cards.** A card is the durable unit of
work; its tasks are the live checklist under it. The agent only ever manages tasks; the card's
checklist is a machine-written projection. Hooks do the projection, so there is exactly one
bookkeeping surface for the agent and one durable record for the system.

Two empirical facts make the sync load-bearing rather than cosmetic:
- Session-scoped task lists **delete a task's file the instant it completes**; named lists retain
  completed state but are still subject to `cleanupPeriodDays`. The card checklist is therefore the
  **only durable record** of the breakdown and its completion.
- The `TaskCreated`/`TaskCompleted` hook payloads carry **no metadata**, so they cannot identify a
  task's card; `PostToolUse (TaskCreate|TaskUpdate)` carries full `tool_input` metadata and
  `tool_response.statusChange` — it is the only viable sync channel.

### Decisions already made

| Decision | Choice | Rationale |
|---|---|---|
| Hierarchy | Card 1—N tasks; join = `metadata: {card: "<id>"}` on each task | The docs' own recommended pattern for hierarchy; verified to round-trip to disk and through PostToolUse |
| Authority | **Cards are authoritative and durable; tasks are a session-lived projection surface** | Task lists are prunable and (session-scoped) drop completion state instantly |
| Sync direction | One-way, task events → card checklist | Two-way sync invites drift and conflicts; the agent's single surface is tasks |
| Sync channel | `PostToolUse` matched to `TaskCreate\|TaskUpdate` → shells a new overseer CLI verb | Full fidelity (metadata in, assigned id + statusChange out); lifecycle events lack metadata |
| Card writes | ONLY via the overseer CLI (new `checklist` verb), never raw file edits from a hook | Preserves overseer's single-writer invariant |
| Task list | **Named list required** for orchestrated work: `CLAUDE_CODE_TASK_LIST_ID` in the project `.claude/settings.json` `env` block, written by orchestrate's bootstrap | Survives vigil `/clear` handovers (same process env) and restarts (settings block); retains completed state for dependency resolution |
| Env adoption | One fresh `claude` launch after the env block is first written; orchestrate announces it loudly | `/clear` cannot adopt a new env var (process-level); after adoption, handovers need nothing |
| Checklist retention | Checklist stays in the card permanently (including after card done) | It is the durable record of the work breakdown; cards are the archive |
| Orphan tasks | Tasks without `metadata.card` are ignored by the sync | Not everything is card work; no noise |
| Enforcement (later, optional) | `TaskCompleted` exit-2 gate: veto completion when the card fails its stage gates, recovering the card id from the named list's `<task_id>.json` | Documented veto power + verified disk lookup; separate card, not this build |

## 1. The shape

```
overseer card (durable .workflow/cards/WF-XXX.md)
  frontmatter: checklist:
    - {task: "7", subject: "write failing tests", status: in_progress}
    - {task: "8", subject: "implement verb",      status: pending}
        ▲ machine-written projection (overseer CLI `checklist` verb)
        │
  PostToolUse (TaskCreate|TaskUpdate) hook ── reads tool_input.metadata.card + tool_response
        │
CC task list (named, ~/.claude*/tasks/<CLAUDE_CODE_TASK_LIST_ID>/)
  tasks carry metadata: {card: "WF-XXX"}   ← the ONLY thing the agent maintains
```

Dashboard renders `checklist:` under each card tile — a live checklist with zero new data plumbing
(the board already serves card frontmatter).

## 2. Overseer: the `checklist` verb

`overseer checklist <card-id> --task <task-id> --subject <text> --status <pending|in_progress|completed|deleted>`

- Upserts the entry (keyed by task id) in the card's `checklist:` frontmatter list; `deleted`
  removes the entry.
- Validates the card exists; unknown card → exit 1 with a clear message (the hook swallows it).
- Ordinary single-writer card update through the existing store (index rebuild etc. as any verb).
- Idempotent: replaying the same update is a no-op.

## 3. The sync hook

`hooks/checklist-sync.sh` registered on `PostToolUse` with `"matcher": "TaskCreate|TaskUpdate"`
(in the **overseer** plugin's hooks.json — this is overseer machinery, not vigil's):

1. Read the payload once. `tool_name` distinguishes create vs update.
2. `TaskCreate`: card id from `tool_input.metadata.card` (absent → exit 0, orphan task); task id
   from `tool_response.task.id`; subject from `tool_input.subject` → `checklist` upsert as `pending`.
3. `TaskUpdate`: task id from `tool_input.taskId`; status from `tool_response.statusChange.to`
   (absent → non-status update; upsert subject if changed, else exit 0). The card id is recovered
   from the named list's task file (`$CLAUDE_CODE_TASK_LIST_ID/<id>.json` → `metadata.card`);
   if the file is already gone (session-scoped list or racing prune) fall back to scanning cards'
   existing checklists for the task id.
4. Shell `overseer checklist ...`. Quarantine-safe: any failure → exit 0, never blocks the tool.
5. Never fires vigil logic — vigil's own nudge registration on the same matcher is independent and
   both hooks run.

## 4. Orchestrate awareness (doctrine + bootstrap)

The orchestrate skill gains a **Tasks** section:

- **Bootstrap (once per project):** ensure `.claude/settings.json` (or `.local`) has
  `env.CLAUDE_CODE_TASK_LIST_ID` (default: a slug of the project root). If newly written, announce:
  "restart this CLI once to adopt the shared task list — /clear is not sufficient."
- **Adoption spawn (reinstated relaunch, install-only nicety):** rather than leaving the restart to
  the user, orchestrate MAY programmatically spawn the replacement CLI and invite the user to move:
  `tmux new-session -d -s <name> -c <worktree> -e CLAUDE_CODE_TASK_LIST_ID=... claude` — then print
  "attach with `tmux attach -t <name>` and close this session." This resurrects the old
  new-CLI-relaunch mechanism for exactly one purpose (env adoption at install); it is NOT a handover
  path — vigil's in-place `/clear` owns handovers. Spawning under tmux also enables vigil's
  hands-free clear dispatch in the new session by construction. During development, add
  `--plugin-dir <repo>/plugins` so the spawned session loads the working-tree plugins (live hooks)
  rather than the installed marketplace copies.
- **Working rule (DRY):** when picking up a card, break it into tasks via `TaskCreate` with
  `metadata: {card: <id>}`; work the tasks (`in_progress` → `completed`); **never hand-edit the
  card's checklist** — the sync owns it. Card-level transitions (stages, done, block) remain CLI
  verbs as today.
- **Boundary check:** marking tasks complete is what fires vigil's threshold nudge at work
  boundaries; card transitions that bypass the task list (pure CLI) should be preceded by an
  explicit `vigil context` check per the vigil trigger spec.
- Sprint teardown: tasks for done cards may be `deleted` (list hygiene); the card checklist remains.

## 5. Dashboard

`CardDetailDrawer` (and optionally the tile) renders `checklist:` from the card it already fetches:
subject + status glyph per entry, live via the existing refresh-on-mutation model. No new endpoints.

## 6. Failure honesty

| Scenario | Behaviour |
|---|---|
| Task without `metadata.card` | Ignored by sync (orphan; deliberate) |
| `overseer` CLI missing/erroring | Hook exits 0 silently; checklist simply lags (agent's tasks unaffected) |
| Task file pruned before update sync | Card-scan fallback; if still unresolved, exit 0 (lag, not breakage) |
| Two sessions, same named list, same card | `checklist` upserts are per-task-id and idempotent; last write per task wins — acceptable |
| Env var absent (bootstrap not run) | Sync still works within the session (session list); durability caveats apply until bootstrap |
| Checklist vs reality drift (e.g. manual task deletion) | Cards are authoritative for history, tasks for "now"; a `resume`/board read shows both; no reconciliation pass (YAGNI) |

## 7. Testing

- `checklist` verb: upsert/update/delete, unknown card, idempotency, frontmatter round-trip
  (overseer's existing store test patterns).
- Sync hook: fixture payloads (verified shapes from the research doc) for create/update/orphan/
  non-status-update/missing-task-file → correct CLI invocations (subprocess spy) and exit 0 on all
  failure paths.
- Dashboard: checklist renders from a card fixture (existing RTL pattern).
- Manual E2E: bootstrap env block → restart → create tasks under a card → watch the card checklist
  and dashboard update live; complete through a vigil handover and confirm the checklist survives.

## 8. Out of scope

- The `TaskCompleted` exit-2 **gate** (veto completion on failed card gates) — follow-up card.
- Two-way sync / editing tasks from the dashboard.
- Migrating historical cards to checklists.
- Teammate/owner-aware rendering (owner column on the dashboard) — future nicety.
