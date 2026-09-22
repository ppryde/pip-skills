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

New `hooks/pretool.sh` → `cli.py pretool-hook` (one process runs the guard and
the Read limit, §5.7). Never blocks on its own failure (errors → allow).

- **Orchestrator identity:** new `orchestrators(card_id, session_id, stamped)`
  table in `board.db` (a side table, so the `Card` model and dashboard are
  untouched), stamped from `CLAUDE_CODE_SESSION_ID` by the work verbs
  (`set-stage`, `log-progress`, `log-review`, `dispatch-prep`, `bootstrap`);
  cleared on `done`/`park`/`abandon`/`unclaim` and by a new `release <card>` verb
  (the per-card escape hatch).
- **Applies when** a live card has `orchestrator_session == payload.session_id`.
- **No fork (any session with a live card, orchestrator or agent):** deny `Agent`
  with `subagent_type == "fork"` → reason `"WF-12 in flight: forks inherit full
  context — dispatch a fresh overseer-* agent with a bundle path"`.
- **No work (orchestrator only, `agent_id` absent):** deny `Edit`, `Write`,
  `NotebookEdit`, `mcp__*`, `Read`/`Grep`/`Glob` outside the state root, the plugins directory and the Claude config dir, and
  `Bash` unless the command is the overseer or vigil CLI, `git`
  (status/log/diff --stat/worktree/branch/fetch/pull/push/commit on the card
  branch), or `gh pr`. Reason names the card and says "dispatch instead".
- **Foreman (Phase 2):** a call with `agent_type == "overseer-foreman"` gets the
  same no-work rule as the orchestrator.
- **Tripwire:** an orchestrator `Agent` dispatch on a card whose spend is ≥ 2×
  its estimate is denied with the overrun story (replaces the `log-progress`
  exit-2 path, which the orchestrator no longer calls).
- **Escape hatch:** `release <card>`, config `"guard": false` in
  `.overseer/config.json`, or `OVERSEER_GUARD=off` in the session env. The deny
  reason names them.
- **Not a security boundary.** Command parsing is best-effort and fails open;
  its job is to stop accidental token spend, not a determined user.

### 5.2 Agent definitions

New `agents/overseer-{planner,implementer,reviewer,fixer,verifier}.md`: a
`tools:` allowlist, default `model: sonnet` (the orchestrator passes `model` per
`policy.md` tier on the `Agent` call), and a body that is the static role charter
+ the role's reply line. Reviewers, planners and verifiers get no `Edit`. Plugin
agents are addressed as `overseer:overseer-<role>` (probe: `agent_type` carries the
plugin prefix). The orchestrator dispatches only these types; a chunk that needs
MCP tools is dispatched as `general-purpose` with the same bundle path.
Probe: a `tools: Read, Write` plugin agent opened at 2.6k context vs 18.8k for
`general-purpose` (no CLAUDE.md in the probe dir).

### 5.3 `dispatch-prep` verb

`cli.py dispatch-prep <card> --stage <s> [--round n] [--chunk n] [--role r]`
does in one call what the orchestrator does in ~5 turns today: `calibration`,
fact selection for the card, diff to `diff.patch` (review stages), prior
findings from earlier rounds' verdict files, template fill. Writes `bundle.md`,
prints its absolute path only. The orchestrator's dispatch prompt is
the bundle path alone. Small free-text inputs (gate commands, a lens) pass as
`--var key=value`, **each capped at 300 characters** — anything longer must be a
file, which makes F2's pasted walls impossible through this verb.

### 5.4 Report hook (`SubagentStop`)

New `hooks/report.sh` → `cli.py report-hook`. Acts only for `agent_type`
starting `overseer-`.

Superseded from the original Phase 1 text: replies are no longer a fixed
one-line grammar (former §4.2). Each role's reply is a single fenced
` ```overseer-report ` JSON block, one frozen dataclass per role
(`scripts/schemas.py`), parsed with every problem collected at once (unknown/
missing field, wrong type, bad enum, `detail` path outside the card's
dispatch directory) rather than failing on the first. A JSON Schema per role
is committed under `schemas/` and checked for drift against the generator.

1. Extract the LAST ` ```overseer-report ` block from `last_assistant_message`
   and parse it against the role's schema; card/stage/round/slot/chunk are
   typed fields on the parsed report, not derived from a path pattern.
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

4. **Bounded retry, not silent record-only** (revised from the original
   Phase 1 text — see §9's updated "Rejecting long replies in the stop hook"
   entry). A missing block, invalid JSON, or a block that fails its role's
   schema:
   - `stop_hook_active` is not set → print exactly one
     `{"decision": "block", "reason": "<every problem found>; expected
     <shape>"}` on stdout and record nothing yet.
   - `stop_hook_active` is set (this is the bounce's own retry) → record it
     as `unparsed` with the full error list, print nothing. Never a second
     block.
   A report that parses never blocks, regardless of `stop_hook_active`.

`usage.jsonl` entries gain `input`, `cache_read`, `cache_creation`, `output`,
`budget_tokens`, `agent_id`, `source: "hook"`. `tokens` stays = raw total so
existing readers keep working.

**Budget semantics:** as today, only implementer and fixer spend feeds the card's
`budget_actual` (and so the tripwire); planner, reviewer and verifier spend lands
in `usage.jsonl` only (`references/telemetry.md`). The amount added is
`input + cache_creation + output` — tokens newly placed in context — not the raw
total. Cache reads are the ~750× re-read amplification; counting them would trip
every card against today's S/M/L bands. The raw figure lives in `usage.jsonl`.

**Concurrency:** parallel reviewers finish together, so the hook mutates the card
inside one `BEGIN IMMEDIATE` transaction (load → change → save), never the
whole-row last-write-wins `_sync` path. Orchestrator `log-progress --tokens` /
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

`PreToolUse` on `Read` where `agent_id` is present, `agent_type` is an
`overseer-*` role, and no `limit`/`offset` is given → `updatedInput` with
`limit: 400` (config `read_limit`, `0` disables; images/PDFs/notebooks exempt).
Agents can still pass an explicit `offset`/`limit`. **Verified:** `updatedInput`
works with no `permissionDecision`, so permission rules still apply. The guard
and this rule share one `PreToolUse` hook process. Measure turns per agent before and after; revert if
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

One shared text, written into every bundle by `dispatch-prep` (so config can
switch it) and into the orchestrator's user-communication section: *terse and factual; state results, not process;
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

- Every hook wraps its CLI call in `trap 'exit 0' EXIT`; any exception inside
  the CLI itself → allow (guard) or silent (report — nothing is printed, so
  `report.sh`'s trap has nothing to pass through). A broken hook must never
  stall a session.
- The guard hook fails open, not closed: a false deny costs a session; a false
  allow costs tokens.
- The report hook is the one exception to "never retries": a missing or
  invalid `overseer-report` block gets exactly ONE bounce (§5.4), bounded by
  `stop_hook_active` so it can never loop. `report.sh` passes the CLI's
  stdout through (unlike the fully-silent hooks) for exactly this reason —
  stderr stays suppressed. Everything downstream of a report that still
  doesn't parse on the retry — recorded as `unparsed` with its error list —
  and missing detail files or paths outside the dispatch directory once a
  report DOES parse, are ledger records, visible on the dashboard, never
  retried again.
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
- **Rejecting long replies in the stop hook — reversed.** Originally rejected
  here: "a bounce costs an extra agent turn and risks a continuation loop; the
  cap is stated in the dispatch instead, the hook only records overruns." That
  held for a soft word-count cap, where a bounce would only ever be advisory.
  It stopped holding once replies became a typed, machine-checked JSON block:
  a malformed block is a real parse failure the orchestrator would otherwise
  have to notice from a garbled downstream read, diagnose, and re-dispatch —
  strictly more expensive than one bounded retry. `stop_hook_active` is
  Claude Code's own guarantee that Stop/SubagentStop fires at most once more
  after a block, which is exactly the bound a naive "block on invalid" lacks:
  the risk this bullet originally warned about (an unbounded continuation
  loop) doesn't apply to a retry that can only ever happen once. §5.4 and §7
  now bounce a missing/invalid report exactly once, guarded by
  `stop_hook_active`, and record — never re-bounce — anything still invalid
  after that.
- **Hard turn caps / round caps.** Turn caps create BLOCKED re-dispatches that
  cost more hub turns than they save; round caps trade review quality for ~0.2
  Mtok/card.

## 10. Open items

Resolved during planning: `updatedInput` works without a permission decision;
plugin agent definitions cut turn-1 context (2.6k vs 18.8k); plugin agent types
carry the `overseer:` prefix; transcript usage repeats identically per content
block, so de-duplication by message id is exact.

Measured live in Task 12 (headless `claude -p` sessions against this
worktree's plugin, not unit tests):

- **Guard denials.** With WF-001 in flight, the orchestrator's own attempt to
  read/edit a tracked file was denied verbatim: `WF-001 in flight: the
  orchestrator dispatches, it does not do the work — dispatch an overseer-*
  agent with a dispatch-prep bundle instead. (Escape hatch: release <card>,
  "guard": false in .overseer/config.json, or OVERSEER_GUARD=off.)`. A `fork`
  Agent call was denied with `WF-001 in flight: forks inherit the full parent
  context — dispatch a fresh overseer-* agent with a bundle path instead.`. A
  dispatched `overseer:overseer-implementer` Agent call in the same session
  was allowed through and edited the target file (confirmed on disk), then
  reported `DONE tests 0/0 - → .../c1.md`.
- **Report hook.** The same implementer's `SubagentStop` fired the report
  hook, which wrote a `## Progress log` entry (`chunk 1 — DONE tests 0/0 -
  → .../c1.md (~15.804k tokens)`) and a `usage.jsonl` line with `source:
  "hook"`, non-zero `cache_read` (43,155) and `output` (715), total 58,959
  raw tokens / 15,804 budget tokens. The detail file already existed when the
  hook read it — the implementer's own charter has it write that file before
  replying — so this run exercised the happy path rather than the
  `error: detail file missing` branch; that branch is covered by
  `test_report_hook.py` at the unit level, not live here.
- **Read limit.** An `overseer:overseer-reviewer` agent asked to Read a
  2000-line file with no limit/offset received exactly 400 lines back
  (through line `400\tline 400`), and reported "400" as its last line seen —
  confirming the Read limit hook caps at 400 regardless of the caller's
  arguments.
- **Turn-1 context, real repo with CLAUDE.md.** Spawning one
  `overseer:overseer-reviewer` and one `general-purpose` agent in this
  worktree (real CLAUDE.md in scope) and reading each transcript's first
  usage snapshot gave turn-1 context of **12,325 tokens** for the overseer
  agent vs **27,447 tokens** for general-purpose — a ~55% reduction,
  consistent with the plugin-agent-definition saving noted above (2.6k vs
  18.8k) plus this repo's own CLAUDE.md/system overhead common to both.

Full gates after verification: `pytest -c pyproject.toml` 762 passed;
`ruff check scripts ../../tests/overseer` and `mypy scripts` show only
pre-existing debt (no files touched by Task 12); `tests/run.sh` green across
all five plugin suites (overseer 762, census 114, vigil 154, review-clone 14,
chronicle 223).
