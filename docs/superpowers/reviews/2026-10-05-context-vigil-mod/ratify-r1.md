# Ratification of round-1 architectural / behaviour findings — context-vigil-mod

Ruling on behalf of the absent owner. Read-only on code. Target `feat/context-vigil-mod` HEAD 6393e6e,
`plugins/context-vigil-mod/` (`register` = `hooks/register.tsx`). Every cited line was read.

Standing intent applied throughout:
1. An unattended `/clear` never lands on a present human or a half-typed message (commit 247b45f).
2. When in doubt, don't clear; prefer a visible notice.
3. Defaults stand: nudge 35 %, idle 30 min (15/30/60), phone countdown 30 s.
4. Merge tonight: minimal, safe fixes; anything bigger goes to a follow-up card.

One line per id, then the detail.

| id | ruling |
|---|---|
| R1-03 | APPROVE WITH CHANGE — any answered AskUserQuestion is presence; drop the re-arm at :724, offer the parked handover instead |
| R1-07 | APPROVE WITH CHANGE — last light's "you idle" = no human signal since the last API activity (not the idle window); the hot-reload half is DEFERRED |
| R1-09 | APPROVE WITH CHANGE — a deferral drops on any human prompt/command; at drain, `threshold`/`request` run only when auto is on and the person is not attended, and then clear as *unattended*; otherwise dropped with a notice |
| R1-10 | APPROVE WITH CHANGE — manual `/clear` still injects an offered handover, but the mod's auto-resume is sent only when the handover is fresh and the latch is not set; the person's held text is always sent |
| R1-12 | APPROVE WITH CHANGE — one resume chain per process; no resume submit after a human signal since the early stop or over a non-empty draft (notice instead); a null path gets its own text |
| R1-20 | APPROVE WITH CHANGE — the 5 m-cache line becomes `Text` only, hidden by the next human prompt; no Button, no hotkey |
| R1-24 | APPROVE WITH CHANGE — `unclassified` prompts move `lastHumanAt` only (disarm auto mode); nothing else treats them as human |
| R1-25 | DEFER — the stall fails safe, is once per account, and only with auto On; follow-up card: `$.ui.ask` or a timeout for the RC question |

---

## R1-03 — RC "Yes" re-arms a parked unattended clear; the answer is not presence

**Ruling: APPROVE WITH CHANGE.**

A person who just answered a card is present by any reading of intent #1. The adjudicator's direction
is right; two precisions:

1. **Scope of the presence signal.** Observe `human-command` for *every* AskUserQuestion that returns an
   answer, not only setup cards. In the `tool.call AskUserQuestion` handler (register:701), after
   `await next(e)`: if `extractAnswers(e, r)` is non-empty, `await observe($, { kind: 'human-command', at: now })`
   — placed **before** the `if (!run) return` line so it runs whether or not the mod asked the question.
   An answered question is a human act whoever asked it. An empty answer set (dismissed/aborted card)
   observes nothing.
2. **Replace, don't just delete, line :724.** `if (settings.rcAutoClear === 'yes' && clearParked && (await read($, pendingA))) scheduleClear($, true)`
   becomes: if `clearParked` and a pending exists, `await notify($, V.pendingOffer(pending.path))`. The
   parked handover stays offered; nothing is re-armed. The new setting governs the *next* unattended
   threshold (via `clearGate` on the next `tryClear`), which is what "Yes" means.

Consequence to accept: a prompt answer on the phone makes the session attended for the idle window
(30 min by default). Auto mode re-arms only after another full idle window. That is the correct
reading of "they touched the phone".

**Tests.** `shell-setup.test.tsx:95` ("RC answered Yes …") currently relies on an immediate threshold
handover after the answer; it must now advance the clock past `idleMin` and complete a turn (so the
agent is "working") before the 36 % measure, or it will see a nudge. Add the adjudicator's test: arm on
phone, cross threshold, tool call → `guard.wait rc-unanswered`; answer Yes; advance 31 s; expect no
`clear`, mode `attended`, and the `pendingOffer` notice.

**Spec §2, Remote Control bullet "First RC session"** — add: "Answering the question (or any card)
counts as you being here: it never runs a clear that was parked while you were away; the saved handover
stays offered (`/clear` to resume from it) and the answer governs the next unattended threshold."

**README "Remote Control"** — after "`/vsetup rc` re-asks": "Answering counts as you being here — a
handover parked while the question waited is offered, never run."

---

## R1-07 — Last light never fires with `idleMin ≥ 55`; a reload suppresses it

**Ruling: APPROVE WITH CHANGE** for the idle-window half; **DEFER** the hot-reload half.

The defect is real and hits a shipped setup option (60 min). Of the two directions offered, take the
*definition* fix, not the rescheduling fix: `max(fireAt, lastHumanAt + idleMin)` leaves a lead equal to
the turn's own duration when `idleMin = 60` (seconds, for a short turn) and is knife-edge against the
`now >= lastApiAt + TTL_1H` cold check. The definition fix is robust and reads as what last light
actually means: *the agent's last turn is the most recent thing that happened, and nothing has come
from you since*.

**Behaviour to implement.**

- `core/last-light.ts`: `FireFacts.mode: Mode` becomes two booleans, `youIdle` and `agentIdle`.
  `shouldFire`: `if (!f.youIdle || !f.agentIdle) return { fire: false, reason: 'not-idle' }`.
- `register maybeFireLastLight` (after the existing draft-pickup `observe`):
  - `lastApiAt = await read($, lastApiA)`; if null → `youIdle = false` (no fire — the timer cannot
    legitimately exist without a `turn.complete`).
  - `youIdle = activity.lastHumanAt === null || activity.lastHumanAt <= lastApiAt`
    (`lastHumanAt` moves on prompt, human command, edit and the draft pickup, so a draft in the box
    still blocks the fire).
  - `agentIdle = activity.lastAgentAt === null || now - activity.lastAgentAt >= WORKING_MS`
    (export `WORKING_MS` from `core/arming.ts`; it already exists).
- `settings.idleMin` is no longer consulted by last light at all.

Headless (`sdk`) sessions: `lastHumanAt` stays null → `youIdle` true, same as today's `idle` mode.

**Deferred: the hot-reload half.** `bindSession` sets `lastHumanAt = now` (a reload counts as you being
here). That is load-bearing for *arming* safety — a fresh process with auto On must not arm before a
human has been seen — so it stays. Under the new definition it means any hot reload after the last
turn skips that idle period's last light (`not-idle`). This **fails closed** (no handover written; the
morning pays the cold cache exactly as it does today without the mod), is rare in use (a reload is a
plugin update or a developer action), and the next `turn.complete` reschedules normally. Follow-up
card: keep a `reloadedAt` distinct from `lastHumanAt`, or persist the last *attested* human time in
`$.state` beside the phone facts, so a reload counts as presence for arming but not for last light.

**Tests.** Replace the `mode` cases in `last-light.test.ts` with `youIdle`/`agentIdle`. Shell:
settings `{ lastLight: true, idleMin: 60 }`; `human('hi')`, measure 30, `turn.complete`, advance 55 min →
`last_light.fired`. Variant: `prompt.edit` at +40 min → no fire (`not-idle`). The reload test the
adjudicator asked for is **not** written tonight (deferred half).

**Spec §4 "Fire conditions"** — replace "the session is in last-light territory (you idle, agent idle
— §2)" with: "the session is in last-light territory: **you idle** — no human signal (prompt, slash
command, prompt-box edit or draft) since the last API activity — and **agent idle** (no step in the
last 2 min). The idle window (§2) governs auto mode only; last light runs on the cache's clock, so it
works with any idle window, 60 min included."

**Spec §2 table**, last-light row — footnote: "'idle' here means nothing from you since the agent's last
turn (§4), not the idle window."

**README "Last light"** — "When you and the agent are both idle" → "When nothing has come from you since
the agent's last turn and the agent is idle".

---

## R1-09 — A latched (deferred) handover drains hours later unvalidated

**Ruling: APPROVE WITH CHANGE.**

A drained `request` clearing with `unattended=false` is a direct breach of intent #1: it skips the
attended re-check and every RC guard, hours after the person asked. Two further facts shape the fix:

- `last_light` cannot normally be deferred: `shouldFire` already refuses while latched, so
  `startHandover('last_light')` is never reached under a latch (only a sub-millisecond race).
- `armed()` is **useless at drain time**: `mode === 'auto'` needs agent activity within 2 min, and a
  rate-limited session has had none for hours. Using it as the gate would make every deferral a dead
  letter. The right question at drain is "is auto mode on, and is the person *not* attended?"

**Behaviour to implement.**

1. **Drop on human return.** In `observe`, when the signal is a human `prompt` or a `human-command`
   and `deferredA` is set: `update(deferredA, () => null)`, `notify($, V.deferredDropped)`,
   `log('guard.wait', { reason: 'deferred-dropped', deferred: reason })`. Edits/drafts do not drop it
   (an explicit act does). Suggested voice: `⏳ The handover that waited on the usage limit was not run —
   you are back; /vho when you want one`.
2. **Re-validate at drain** (`checkLatch`, register:345-349):
   - `limit` → as today (write only, `resume: false`).
   - `threshold` or `request` → if `settings.auto && mode(activity, now, settings) !== 'attended'`,
     start it with **unattended clear semantics** (below); otherwise drop with the same notice and log.
   - `last_light` → drop silently (log only); it should not occur.
3. **Unattended semantics for a drained handover.** Add `unattended: boolean` to the `Awaiting` type.
   `startHandover($, reason, resume, unattended = reason === 'threshold')` stores it; the
   `TOOL_FULL` handler uses `awaiting.unattended` instead of `reason === 'threshold'` for
   `scheduleClear`, and so does the `reusable` early-exit in `startHandover`. The drain passes
   `unattended: true` for both `threshold` and `request`. Result: the clear goes through the attended
   re-check, the draft guard and the full RC gate (countdown/holdback/decline), as any auto clear does.

A `/vho` from a person with auto **Off** who then walks away is therefore dropped at drain with a notice
and nothing is lost: no handover was written, the conversation is intact, `/vho` again takes seconds.
That is the auto-Off contract and matches intent #2.

**Tests.** (a) latch, `/vho` (deferred), `human('x','bridge')`, lift latch, measure → no instruction
submitted, `deferredDropped` notice. (b) no human in between, auto On, phone → instruction runs, tool
call, then `guard.wait rc-unanswered` (or countdown with Yes) — never a bare `clear`. (c) auto Off, no
human in between → dropped with notice. (d) `Awaiting.unattended` is honoured by the tool handler.

**Spec §5 "Latch"** — after "never submits": "A handover that was asked for or due while latched waits
for the latch. Any message or command from you while it waits cancels it (a notice says so). When the
latch lifts it runs only if auto mode is on and you are still away, and then as an unattended
handover — the clear takes the attended re-check and the Remote Control rules like any auto clear.
Otherwise it is dropped with a notice; `/vho` again when you want one."

**README "Limits"** — replace "A handover asked for while the limit latch is set is deferred and
starts when the latch lifts" with: "A handover asked for or due while the latch is set waits for it;
your next message cancels it. When the latch lifts it runs only if auto mode is on and you are still
away, as an unattended handover (attended re-check and RC rules apply); otherwise a notice tells you it
was not run."

---

## R1-10 — Manual `/clear` consumes any parked handover and auto-resumes; ignores the latch

**Ruling: APPROVE WITH CHANGE.**

Consumption on manual `/clear` is designed and stays: every parking notice (`pendingOffer`,
`clearSkippedAttended`) tells the person "/clear to resume from it". What is not designed is
(a) auto-submitting a resume from a handover that later turns made stale, and (b) submitting the mod's
own prompt while latched. Fix both minimally; do not stop injecting.

**Behaviour to implement.**

1. **Freshness.** Mirror `lastApiAt` into a module variable at every `turn.complete` (the clear branch
   runs after the `$.state` wipe; module variables survive a `/clear`, as `session` already does). Extract
   the timing half of `reusable` into `fresh(p, lastApiAt, now)` with no reason filter (R1-04's
   `now`-aware rule applies here too) and have `reusable` call it. In `classic.SessionStart` for
   `source === 'clear'`:
   - **always** inject `pending.markdown` as today (the offer was made; the file is the continuity);
   - submit `resumeText(pending.path)` only if `pending.resume && fresh(pending, lastApiMirror, now)`;
   - when stale, notify instead — suggested voice:
     `📜 Handover injected (<path>) — it was written before later turns, so no automatic resume; say where to pick up`
     — and log `resume` with `{ stale: true }`.
2. **Latch.** Before the mod's resume submit at :573: if `await readLatch($)`, do not submit; notify
   `⏳ Handover injected (<path>) — the usage limit is in force, so the resume prompt was not sent; ask to resume when it lifts`;
   log `guard.wait { reason: 'latched', deferred: 'resume' }`. No deferral machinery tonight.
3. **The person's held text is sacrosanct.** The `followUp` submit at :572 (a last-light "Resume"
   carrying the person's own message) is **sent regardless of freshness or latch**: it is the human's
   message, not the mod's; spec §4 "the held message is never lost" outranks §5's "never submits",
   which is about the mod's prompts.

`limit` pendings (`resume: false`) are unaffected; `scheduleResume` owns their resume.

**Tests.** park a pending, run two turns (`turn.complete` ×2, > 60 s after `createdAt`), manual
`SessionStart({ source: 'clear' })` → `additionalContext` carries the inject, no `Resume from the handover`
submit, the stale notice. Fresh pending → inject + resume (existing behaviour). Latch set, fresh
pending → inject, no resume, latched notice. Latch set, `followUp` present → the held text **is**
submitted.

**README "The handover"** paragraph (line 38) — append: "A `/clear` you run yourself picks up a saved
handover the same way; the automatic resume is sent only when no turn has run since the handover was
written and no usage limit is in force — otherwise the handover is injected and a notice asks you where
to pick up."

**Spec §3 step 5** — append the same sentence in short form.

---

## R1-12 — Limit resume: duplicate chains, no presence check, "(no file)"

**Ruling: APPROVE WITH CHANGE.**

The spec's "if the session is still open" was written when nobody had thought about the person having
come back. Submitting a mod prompt into a conversation the person has already resumed is disruptive
(duplicated work), and intent #2 says notice over action. No clear is involved, so the fix is small.

**Behaviour to implement.**

1. **One chain per process.** Keep the active timer handle (`limitResumeTimer`); `scheduleResume`
   cancels it before arming a new one. The job record gains `stoppedAt: number` (the early-stop time).
2. **Presence at resume time.** When the hop reaches `at`, before submitting:
   - if `activity.lastHumanAt !== null && activity.lastHumanAt > job.stoppedAt` (any human prompt,
     command or edit since the stop), **or** `(await $.prompt.read()).text.trim()` is non-empty: do not
     submit; notify `⏳ The limit has reset — you are back, so no resume was sent; the handover is at <path>`
     (or "no handover was written" when null); log `guard.wait { reason: 'resume-skipped', human: true }`;
     end the chain. No re-ask.
   - Latched → the existing 60 s re-hop stays.
3. **Null path.** `limitResumeText(null)` gets its own sentence instead of "(no file)":
   "The usage limit has reset. No handover was written before the stop (it was deferred or classic was
   active); pick up from the conversation as it stands." Keep the existing text for a real path.

**Tests.** Two windows ≥ 95 in one measure (or two measures) → exactly one `limitResumeText` submit after
reset + 5 min. Variant: `human('hi')` after the early stop → no submit, the skipped notice. Variant:
draft in the box at resume time → no submit. Variant: deferred handover (latched at stop) → null-path
text, not "(no file)".

**Spec §5** — "which submits the resume prompt if the session is still open" → "which submits the
resume prompt if the session is still open **and nothing has come from you since the stop** (otherwise a
notice names the handover and leaves the conversation to you)".

**README "Limits"** — "arranges a resume 5 min after the reset if the session is still open" → "… if the
session is still open and you have not come back in the meantime (then a notice names the handover
instead)".

---

## R1-20 — The "last light is off" line is an always-on band with hotkey `0`

**Ruling: APPROVE WITH CHANGE.**

The owner's own spec §3 rules out always-on bands for exactly this reason, and 9d4befc contradicts it.
Keep the feature (the information is useful once per session); remove the hotkey.

**Behaviour to implement.**

- The 5 m-cache line (register:781-789) renders as `<Box><Text>{V.lastLightOff}</Text></Box>` — no
  `Button`, no hotkey. `V.lastLightOff` may gain a hint: `… — /vsetup last-light`.
- It is hidden by **the next human prompt** after it appears: in `prompt.submit`, when
  `classifyOrigin(e.origin.kind) === 'human'` and `(await read($, cacheTtlA)) === '5m'`, set
  `ttlInfoDismissedA = true`. Plugin-origin prompts (the mod's own resume) do not hide it.
- `setCacheTtl` resets `ttlInfoDismissedA = false` when `to === '5m'`, so a later 1h→5m switch shows the
  line again until the next human prompt. The 5m→1h `lastLightBackOn` notice is unchanged.
- `/clear` behaviour is unchanged (the state wipe re-learns the TTL; the line shows once more until the
  person's next message).

**Tests.** `shell-bar` / `shell-last-light`: render with `cacheTtl = '5m'` → no `Button` with a `hotkey`
mounted; a `composer` prompt hides it; a `plugin` prompt does not; after `PostModelSwitch 1h` then `5m`
the line is back until the next human prompt. The current `ui.press({ key: 'dismiss-ttl' })` tests
(shell-last-light.test.tsx ~367-375) are rewritten to the new hide rule — the "stays dismissed across
switches" expectation at :372-374 is intentionally inverted.

**Spec §4** — "a dismissible line above the prompt says it is off (the threshold bar wins)" → "a line
above the prompt says it is off until your next message (the threshold bar wins; no hotkey, per §3)".

**README "Last light"** — "it shows a dismissible 'Last light is off for this session' line above the
prompt" → "it shows a 'Last light is off for this session' line above the prompt until your next
message".

---

## R1-24 — `unclassified` prompt origins count as the agent working

**Ruling: APPROVE WITH CHANGE** (the fail-safe option, narrowly).

The engine typings say a same-user channel the engine cannot attest "arrives as `unclassified`". If that
is a person, today's mapping keeps auto mode armed on a present human — intent #1 fails. The cost of the
fail-safe mapping is that an engine-originated `unclassified` prompt merely disarms auto mode for one idle
window (a nudge instead of a handover). That is the right side to fail on. But treat it as human for
**disarming only**, nowhere else — an engine notice must never be held as "your message" (§4 return
hold) or counted as a phone fact.

**Behaviour to implement.**

- `core/arming.ts record()`, case `'prompt'`: when `s.origin === 'unclassified'`, return
  `{ ...a, lastHumanAt: s.at }` — `lastHumanOrigin`, `lastBridgeAt` and `headless` unchanged.
  `classifyOrigin('unclassified')` still returns `'agent'`, so:
  - `rearm` (last light) ignores it;
  - `holdOnReturn` ignores it (never held, never asked);
  - `savePhoneFacts` is not called for it; `onPhone` is unaffected;
  - `command.run` with an `unclassified` origin is unchanged (not a human command).
- Under R1-07's new rule an `unclassified` prompt after the last turn also blocks that period's last
  light (`youIdle` false) — fails closed; a later `turn.complete` moves `lastApiAt` past it. Accepted.
- Logging: the `arm`/`disarm` log's `origin` field still names the last **attested** human origin; add
  nothing tonight.

**Tests.** `arming.test`: `record` with an `unclassified` prompt moves `lastHumanAt`, leaves
`lastHumanOrigin`/`lastBridgeAt`; `mode` after it is `attended`; `rearm(false, 'unclassified')` is false;
`holdOnReturn` with origin `unclassified` is false.

**Spec §2 "Engaged" list** — add a bullet: "a prompt whose origin is `unclassified` (a same-user channel
the engine cannot attest) disarms auto mode and restarts the idle clock, but counts for nothing else: it
is not a phone fact, does not re-arm last light and is never held on return." **README line 34** —
append: "An `unclassified` prompt disarms auto mode but counts for nothing else."

---

## R1-25 — The first-RC question is asked on `arm`, when the person is away, and blocks the run

**Ruling: DEFER to a follow-up card.**

The stall is real and was not costed in ruling F24, but it is safe to ship:

- It fails safe: nothing is cleared while the card waits; the only loss is autonomous progress until
  the person answers.
- It is bounded: `needsRcQuestion` needs `settings.auto` On (default Off) and `rcAutoClear === 'unanswered'`;
  the answer is stored per account, so this is a **one-time** interruption per account, and `rcAsked`
  prevents a loop within a process.
- The phone does see it: the Field Notes record that an open ask raises Remote Control's "action
  required" push and can be answered there.
- Moving it to "the first parked `rc-unanswered` clear" does not remove the stall, only delays it to the
  point where (under R1-03) the answer can no longer help the current session. Asking early is the
  better placement for the feature; the defect is the *surface*, not the timing.

Follow-up card: ask the RC question with `$.ui.ask` (no model turn, no blocking tool call; verified to
resolve on the phone) or give the AskUserQuestion a timeout that resolves to "unanswered" (treated as
No: handover parked, notice). Either is a redesign of the setup surface and not for tonight.

**Doc change tonight (one sentence).** README "Remote Control", after "a one-off question asks whether
to allow auto-clear in RC sessions": "The question is a card in the conversation; the agent waits for
your answer — until then nothing is cleared, and the question is asked once per account." Also honour the
adjudicator's note: PROBES §6 should record the Field Notes' phone `ui.ask` result.

---

## Notes for the fixer

- Order: R1-03 and R1-09 touch the same `Awaiting`/clear-gate seam as R1-01; land R1-01 first, then
  R1-09's `Awaiting.unattended`, then R1-03.
- R1-07 and R1-24 interact only through `lastHumanAt`; both are small and independent of each other.
- R1-10 shares the freshness helper with R1-04 — one `fresh(p, lastApiAt, now)` for both.
- No default changes anywhere: nudge 35 %, idle 30 (15/30/60), countdown 30 s all stand.
- Every "notice" above is a `notify` + `log`; wording is suggested, not binding, but each new string
  belongs in `core/voice.ts`.
