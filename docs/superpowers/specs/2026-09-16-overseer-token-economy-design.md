# Overseer token economy — design

**Card:** WF-113 · **Date:** 2026-09-16 · **Status:** design, awaiting review
**Evidence:** `docs/superpowers/research/2026-09-16-overseer-token-audit.md`
(the audit handover; every baseline below comes from it or from probes run on
Claude Code 2.1.273 in this session).

## 1. Problem

A with-subagent overseer card costs **~19.4 Mtok weighted** (6.2 orchestrator +
13.2 subagents); a no-subagent card ~5.1. Content is not the problem — 15
sessions placed ~1.6 Mtok of unique content in context but paid 1,204 Mtok of
cache reads. Cost is **turn count × context size**. The orchestrator is the
expensive party: ~240k context, ~19.5 turns per dispatch, re-reading its own
history on every turn — including turns that only receive a 72-token report.

Three structural causes: the orchestrator does implementation work itself (F1,
19% of spend); forks and pasted-in prompts start agents at 140k–374k (F2); the
orchestrator hand-drives every step of every dispatch and review round (F3).

## 2. Goals and non-goals

**Goals**
- Fewer orchestrator turns per dispatch, and a smaller orchestrator context.
- Agents record their own results; the ledger is written without orchestrator turns.
- Enforce the rules mechanically (hooks), not only in prose.
- Keep live visibility: every agent stays an in-conversation agent visible in
  the Claude Code UI, chronicle, census and plugin hooks.
- Make `usage.jsonl` accurate (today it undercounts ~100×).

**Non-goals**
- Headless `claude -p` workers (see §9, deferred).
- Shrinking SKILL.md, references, templates or CLI output (measured lean).
- Capping review rounds for cost.
- MCP/settings trimming (a user settings change, not a plugin change).

## 3. Verified platform facts (Claude Code 2.1.273)

| Fact | Consequence |
|---|---|
| `PreToolUse`/`SubagentStop` payloads from a subagent carry the parent's `session_id` **plus** `agent_id` and `agent_type`; orchestrator calls have no `agent_id` | "Is this the orchestrator?" = `session_id` matches **and** `agent_id` absent |
| `SubagentStop` carries `last_assistant_message` (verbatim final reply) and `agent_transcript_path` | A hook can parse the reply and total real usage with no agent turn |
| A subagent has the `Agent` tool; nested spawning works | A per-stage foreman can start reviewers and a fixer |
| `CLAUDE_CODE_SESSION_ID` is set in every Bash call | CLI verbs can record the orchestrator session without arguments |
| A Stop/`SubagentStop` hook that blocks makes the agent continue | Every hook here is record-only, `trap 'exit 0' EXIT`, prints nothing |
| Fork = `Agent` call with `tool_input.subagent_type == "fork"` | Forks are detectable and deniable in `PreToolUse` |

## 4. Core rule: results travel as files, replies are one fixed line

Every dispatched agent writes its detail to a file under the card's dispatch
directory and ends with **one line in a fixed grammar, max 25 words**. The
parent reads the line to decide what's next; the `SubagentStop` hook parses the
same line into the ledger. Nobody passes findings, diffs or plans through a reply.

### 4.1 Dispatch directory

`<state_root>/dispatch/<card>/<stage>/` (state root as resolved by the CLI;
already git-ignored). All paths handed to agents are absolute. File names encode
round and slot so the hook needs nothing else:

| File | Written by |
|---|---|
| `bundle.md`, `diff.patch` | `dispatch-prep` |
| `r<round>-<slot>.md` (e.g. `r1-A.md`) | reviewer verdict |
| `r<round>-fix.md` | fixer report |
| `c<chunk>.md` | implementer report |
| `plan.md` / `verification.md` | planner / verifier |
| `summary.md` | foreman (Phase 2) |

### 4.2 Reply grammar

`→` and `->` are both accepted. `<path>` must resolve inside the dispatch directory.

| Role (`agent_type`) | Line |
|---|---|
| `overseer-reviewer` | `(approved\|found wanting) <n>C <n>I <n>M → <path>` |
| `overseer-fixer` | `(DONE\|DISPUTED\|BLOCKED) fixed <n> disputed <n> <sha\|-> → <path>` |
| `overseer-implementer` | `(DONE\|DONE_WITH_CONCERNS\|BLOCKED\|NEEDS_CONTEXT) tests <pass>/<total> <sha\|-> → <path>` |
| `overseer-planner` | `(DONE\|NEEDS_CONTEXT) → <path>` |
| `overseer-verifier` | `(PASS\|FAIL) → <path>` |
| `overseer-foreman` | `<stage> <card>: (approved\|deadlock\|dispute\|failed) r<n> learned <k> → <path>` |

Detail files open with the same fields as a front-matter header, followed by the
body (findings with file:line, dispute reasons, test evidence, `Learned:` lines).

## 5. Phase 1 — no foreman

Each item stands alone and ships in this order within one rolling PR.

### 5.1 Orchestrator guard hook (`PreToolUse`)

New `hooks/guard.sh` → `cli.py guard-hook`. Record-and-decide; never blocks on
its own failure (errors → allow).

- **Orchestrator identity:** new `cards.orchestrator_session` column, stamped
  from `CLAUDE_CODE_SESSION_ID` by the work verbs (`set-stage`, `log-progress`,
  `dispatch-prep`, `bootstrap`); cleared on `done`/`park`/`abandon`/`unclaim`.
- **Applies when** a live card has `orchestrator_session == payload.session_id`.
- **No fork (any session with a live card, orchestrator or agent):** deny `Agent`
  with `subagent_type == "fork"` → reason `"WF-12 in flight: forks inherit full
  context — dispatch a fresh overseer-* agent with a bundle path"`.
- **No work (orchestrator only, `agent_id` absent):** deny `Edit`, `Write`,
  `NotebookEdit`, `mcp__*`, `Read`/`Grep`/`Glob` outside the state root, and
  `Bash` unless the command is the overseer or vigil CLI, `git`
  (status/log/diff --stat/worktree/branch/fetch/pull/push/commit on the card
  branch), or `gh pr`. Reason names the card and says "dispatch instead".
- **Foreman (Phase 2):** a call with `agent_type == "overseer-foreman"` gets the
  same no-work rule as the orchestrator.
- **Escape hatch:** config `guard: off` per repo, or `OVERSEER_GUARD=off` in env.
  The deny reason mentions both.

### 5.2 Agent definitions

New `agents/overseer-{planner,implementer,reviewer,fixer,verifier}.md`: a
`tools:` allowlist, `model:` per `policy.md` tier, and a body that is the role
charter + the terse charter (§5.9) + the role's reply line. Reviewers and
verifiers get no `Edit`. The orchestrator dispatches only these types.

### 5.3 `dispatch-prep` verb

`cli.py dispatch-prep <card> --stage <s> [--round n] [--chunk n] [--role r]`
does in one call what the orchestrator does in ~5 turns today: `calibration`,
fact selection for the card, diff to `diff.patch` (review stages), prior
findings from earlier rounds' verdict files, template fill. Writes `bundle.md`,
prints its absolute path only. Templates collapse to `{{bundle_path}}` +
`{{reply_path}}`; everything else they took inline moves into the bundle.

### 5.4 Report hook (`SubagentStop`)

New `hooks/report.sh` → `cli.py report-hook`. Acts only for `agent_type`
starting `overseer-`. Always exits 0, prints nothing.

1. Parse `last_assistant_message` against §4.2; derive card/stage/round/slot
   from the path.
2. Total real usage from `agent_transcript_path`: sum `input`, `cache_read`,
   `cache_creation`, `output` per assistant message, **de-duplicated by message
   id** (a message's usage repeats across its content blocks).
3. Write the ledger by role:

| Role | Ledger writes |
|---|---|
| reviewer | review entry (stage, round, slot, verdict, counts, file), pending Learned, usage |
| fixer | progress note, commit, dispute flag, usage |
| implementer | progress note, commits, test count, usage |
| planner | `set-section Plan` from `plan.md`, pending Learned, usage |
| verifier | `set-section Verification` from `verification.md`, usage |
| foreman | stage result, usage |

4. Always record `reply_tokens`. A reply over the cap is logged as `overrun`;
   one that doesn't parse is logged as `unparsed` with the raw line. **No
   retry, no block.** The dashboard shows both.

`usage.jsonl` entries gain `input`, `cache_read`, `cache_creation`, `output`,
`reply_tokens`, `agent_id`, `source: "hook"`. `tokens` stays = raw total so
existing readers keep working. Orchestrator `log-progress --tokens` /
`log-usage` after dispatches are removed from SKILL.md.

### 5.5 `set-section` and pending facts

- `cli.py set-section <card> --section Plan|Verification|Decisions --file <path>`
  (used by the report hook; callable by hand).
- Pending Learned queue: `facts --pending [--card]`, `accept-fact <id>`,
  `reject-fact <id> --reason`. The orchestrator adjudicates at stage boundaries,
  in one call per decision.

### 5.6 Disputes via files

Replaces orchestrator adjudication of routine disputes, and takes the one useful
idea from a chatting review team (§9). A fixer that disagrees writes the dispute
and its evidence into `r<n>-fix.md` and replies `DISPUTED`. The next round's
reviewers get those disputes in their bundle as prior findings and must, per
dispute, **withdraw** or **maintain with new evidence** in their verdict. Only a
maintained dispute reaches the orchestrator. Reviewers stay independent: they
still never see each other's verdicts before submitting.

### 5.7 Read limit hook

`PreToolUse` on `Read` where `agent_id` is present, `agent_type` starts
`overseer-`, and no `limit` is given → `updatedInput` with `limit: 400`. Agents
can still pass an explicit `offset`/`limit`. **Verify `updatedInput` on this
build during planning.** Measure turns per agent before and after; revert if
agents take more turns re-reading in pieces.

### 5.8 Fewer orchestrator turns elsewhere

- **`bootstrap` verb:** `new-card` + base-branch detection + worktree + branch +
  `set-field` + `set-stage planning` in one call.
- **No polling:** delete the cadence rule from `implementer.md` and the peer-CC
  rule from SKILL.md Comms. Dispatch in the background; never check on a running
  agent; the completion notice is the report. The unresponsive watchdog reads the
  agent transcript mtime, not pings.
- **Batch independent calls:** SKILL.md rule to issue independent tool calls in
  one turn (measured 1.04 calls/turn today).
- **Handover at every stage boundary:** once a stage is recorded in the ledger,
  the orchestrator runs `handoff | vigil handover` and resumes fresh. Keep the
  existing threshold as a backstop.

### 5.9 Terse charter

One shared text, included in every agent definition and the orchestrator's
user-communication section: *terse and factual; state results, not process;
no preamble or recap; expand only when asked.* Config `verbosity: terse|normal`
(default `terse`) switches the charter paragraph off per repo.

## 6. Phase 2 — review foreman

Built after Phase 1 ships and is measured on real cards (§8).

### 6.1 Role

`agents/overseer-foreman.md`: tools `Agent`, `Read`, `Bash` (overseer CLI
only, enforced by the guard hook treating a foreman like the orchestrator);
tier mid; fresh per stage, discarded at stage end. Runs **plan-review and
impl-review only**. The orchestrator keeps planning, implementation, verification,
all gates, and every judgement call.

### 6.2 Rulebook (mechanical; no judgement)

```
round = 1
loop:
  start reviewers per policy.md panel, in parallel, each with
    bundle path + lens + reply path r<round>-<slot>.md
  read their lines
  all "approved"                       → reply approved r<round>; stop
  any C or I > 0:
    round == cap                       → reply deadlock r<round>; stop
    start fixer with verdict paths
    fixer DONE                         → dispatch-prep --round <round+1>; round += 1
    fixer DISPUTED                     → dispatch-prep --round <round+1>; round += 1
                                         (reviewers withdraw or maintain, §5.6)
    fixer BLOCKED                      → reply failed r<round>; stop
  a dispute maintained after one re-review → reply dispute r<round>; stop
  any unparsed line or failed agent    → reply failed r<round>; stop
```

The foreman writes `summary.md` (one row per round) and makes **no ledger calls**:
the report hook records every agent, the foreman included.

### 6.3 Orchestrator side of a review stage

`set-stage` → `dispatch-prep` → `Agent(overseer-foreman, bundle path)` in the
background → one line back → `facts --pending` adjudication → `set-stage` next
→ handover. On `dispute`/`deadlock`/`failed`, the orchestrator reads only the
named file, decides, and starts a new foreman or blocks the card.

`references/review-loop.md` is rewritten around this; its round cap and
independence rules are unchanged.

## 7. Error handling

- Every hook wraps its CLI call in `trap 'exit 0' EXIT`; any exception → allow
  (guard) or log `hook_error` (report). A broken hook must never stall a session.
- The guard hook fails open, not closed: a false deny costs a session; a false
  allow costs tokens.
- Unparsed replies, overruns, missing detail files, and paths outside the dispatch
  directory are ledger records, visible on the dashboard, never retries.
- Concurrent report hooks (parallel reviewers) write through the existing SQLite
  single-writer path.

## 8. Testing and success criteria

**Tests** (`tests/overseer/`, isolated per CLAUDE.md — `CLAUDE_CONFIG_DIR`,
`OVERSEER_CENTRAL`, `OVERSEER_DB` pinned to `tmp_path`):
- Hook payload fixtures captured from real 2.1.273 payloads (orchestrator call,
  subagent call, nested call, fork call, `SubagentStop`).
- Guard: allow/deny matrix per tool × orchestrator/agent × card live/not × escape hatch.
- Report: every grammar line, overrun, unparsed, bad path, usage de-dup against
  a transcript fixture.
- `dispatch-prep`, `bootstrap`, `set-section`, pending facts: CLI tests in the
  existing style.
- Foreman rulebook: a scripted run with stub agents covering approved r1, fix →
  approved r2, dispute withdrawn, dispute maintained, deadlock, failure.

**Success criteria**, measured with the audit's chronicle queries on the next
real cards (estimates, to be confirmed):

| Metric | Today | After Phase 1 | After Phase 2 |
|---|---|---|---|
| Orchestrator turns per dispatch | 19.5 | ≤ 6 | ≤ 2 per review stage |
| Forks / 140k+ turn-1 prompts | 3 / 6 in 15 sessions | 0 | 0 |
| Orchestrator Edit/Read of source on live cards | 205 | 0 | 0 |
| `usage.jsonl` vs chronicle | ~1% | within 10% | within 10% |
| With-subagent card | 19.4 Mtok | ≤ 11 | ≤ 9 |

## 9. Alternatives considered

- **Headless Python stage driver (`claude -p` workers).** ~3 Mtok/card more than
  this design (workers at 17k preamble; zero-token loop). Rejected for now:
  workers leave the UI, census and plugin hooks; can't be steered mid-run;
  `--bare` refuses OAuth; ~700–1,000 lines. Revisit only if Phase 2 measurements
  show worker preamble dominating.
- **Agent-team review (reviewers and fixer chat directly).** Rejected: every
  message wakes a persistent teammate for a full turn at a context that grows
  across rounds, so a debate multiplies turns rather than removing them; open
  discussion breaks reviewer independence ("approval earned against
  resistance"); ending a conversation needs a rule anyway. Its real benefit,
  settling disputes without the orchestrator, is taken via files in §5.6.
- **Rewinding the orchestrator after admin.** `/rewind` is interactive only;
  admin output is ~0.9 kB/call, so removing it saves little. Stage-boundary
  handover (§5.8) is the reliable form.
- **Rejecting long replies in the stop hook.** A bounce costs an extra agent
  turn and risks a continuation loop. The cap is stated in the dispatch instead;
  the hook only records overruns.
- **Hard turn caps / round caps.** Turn caps create BLOCKED re-dispatches that
  cost more hub turns than they save; round caps trade review quality for ~0.2
  Mtok/card.

## 10. Open items for planning

- Verify `updatedInput` on `PreToolUse` (§5.7).
- Confirm a plugin `agents/` definition's `tools:` allowlist reduces turn-1
  context on this build, and by how much (evidence so far: an `Explore` agent
  opened at 17k vs 53k+).
- Decide the exact git allowlist for the guard (§5.1) against the stacking and
  merge flows in `references/stacking.md` and `references/superpowers.md`.
