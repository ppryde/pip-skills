# Claude Code Task System — Research Notes

**Date:** 2026-07-12
**Method:** official docs (code.claude.com/docs: `agent-sdk/todo-tracking.md`, `agent-teams.md`,
`hooks-guide.md`, `interactive-mode.md`) **plus empirical probes** run on this machine (a live-session
disk inspection and a throwaway headless session with stdin-dumping hooks). Empirical findings are
marked **[verified]**; doc-only claims are marked **[docs]**.

These notes ground the overseer card ↔ task-checklist integration
(`docs/superpowers/specs/2026-07-12-overseer-task-checklist-sync-design.md`).

## 1. What tasks are

`TaskCreate` / `TaskUpdate` / `TaskList` / `TaskGet` (successor to `TodoWrite`, since v2.1.142
**[docs]**). Flat items — no native hierarchy — with:

| Field | Notes |
|---|---|
| `subject`, `description` | free text |
| `activeForm` | spinner text shown while `in_progress` |
| `status` | `pending` / `in_progress` / `completed` / `deleted` (deleted = removal) |
| `owner` | names an agent/teammate; teammates self-claim unowned unblocked tasks **[docs]** |
| `addBlocks` / `addBlockedBy` | flat dependency edges; completing a blocker auto-unblocks **[docs]** |
| `metadata` | **arbitrary JSON, verified round-trip to disk** — the documented pattern for custom hierarchy is a parent id in metadata **[verified + docs]** |

Task ids are small numeric strings assigned by `TaskCreate` (returned in `tool_response.task.id`)
**[verified]**.

## 2. Storage & persistence — the load-bearing facts

Tasks live under `~/.claude*/tasks/<list>/` as one JSON file per task plus `.lock` and
`.highwatermark` (the id counter) **[verified]**. Two list kinds with **different retention**:

- **Session-scoped list** (default): dir `session-<first-8-of-session-id>`. A pending/in_progress
  task is a full JSON file on disk; **the file is deleted the moment the task completes**
  **[verified]** (observed: `73.json` present while pending, gone seconds later on completion).
  Completed state survives only in the session transcript. The disk list is a *work-remaining
  queue*, not a history.
- **Named list** (`CLAUDE_CODE_TASK_LIST_ID=<name>` at process launch): dir `<name>`, shared by every
  session launched with that id **[docs + verified]**. **Completed tasks REMAIN on disk** with
  `status: "completed"` and full metadata **[verified]** (observed: probe task `1.json` intact after
  completion). Mechanically necessary: cross-session dependency resolution needs completed state.
- Retention for both is governed by `cleanupPeriodDays` **[docs]** — so even named lists are not a
  permanent archive.

**Env var timing:** the list id is process-level. `/clear` resets the conversation inside the same
process, so it neither loses nor adopts an env change; a **newly-set** `CLAUDE_CODE_TASK_LIST_ID`
requires one fresh `claude` launch. Set it durably via the project `.claude/settings.json` `env`
block; thereafter every launch inherits it and `/clear`-based handovers carry the list untouched.

## 3. Hook surfaces — empirically dumped payloads

### `TaskCreated` / `TaskCompleted` events **[verified]**

Fire when a task is created / marked completed; **can veto** (exit 2 or `decision:"block"` rolls back
the creation / prevents the completion) **[docs]**. No matcher support. Payload is the common fields
plus ONLY:

```json
{
  "hook_event_name": "TaskCompleted",
  "task_id": "1",
  "task_subject": "hook payload probe",
  "task_description": "Probe hook payload"
}
```

**No `metadata`, no `status`, no `owner`.** A gate hook that needs the task's metadata (e.g. a card
id) must recover it from disk: `~/.claude*/tasks/$CLAUDE_CODE_TASK_LIST_ID/<task_id>.json` — viable
on a named list, where the file exists at completion time **[verified]**.

### `PostToolUse` matched to `TaskCreate|TaskUpdate` **[verified]**

The full-fidelity channel. Payload carries `tool_name`, complete `tool_input`, and a rich
`tool_response`:

- `TaskCreate`: `tool_input` includes **`metadata` verbatim** (card ids flow through);
  `tool_response.task.id` is the assigned id.
- `TaskUpdate`: `tool_response` includes `updatedFields` and an explicit
  `statusChange: {"from": "in_progress", "to": "completed"}`.

This is the correct sync channel for projecting task activity elsewhere; the lifecycle events alone
cannot identify which card a task belongs to.

## 4. Teams & UI **[docs]**

- Each session forms one implicit team; the shared task list is the coordination primitive —
  file-locked claiming, `owner` assignment, auto-unblock on completion. A named list extends this
  across sessions.
- UI: `Ctrl+T` toggles a checklist (up to 5 tasks) in the status area; `activeForm` replaces the
  subject while in_progress; tasks persist across context compaction.

## 5. Implications for overseer/vigil integration

1. **Cards must remain the durable record.** Both list kinds are prunable (`cleanupPeriodDays`), and
   session lists drop completion state instantly — so any card-level checklist must be written by a
   sync at transition time; it is the *only* durable completion record, not a convenience.
2. **A named list is mandatory** for orchestrated work: it survives vigil's `/clear` handovers
   (same process → same env) and full restarts (settings env block), and keeps completed state for
   dependency resolution.
3. **`PostToolUse (TaskCreate|TaskUpdate)`** is the sync channel (metadata + statusChange);
   **`TaskCompleted` exit-2** is the enforcement channel (veto completion), recovering metadata from
   the named list's task file.
4. vigil's threshold nudge already matches `TaskCreate|TaskUpdate` — orchestrate driving tasks means
   the nudge fires at exactly the work boundaries it targets.
