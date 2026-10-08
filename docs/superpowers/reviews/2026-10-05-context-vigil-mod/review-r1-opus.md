# context-vigil-mod: adversarial review, round 1 (opus)

Target: `plugins/context-vigil-mod` on `feat/context-vigil-mod` (HEAD 6393e6e). Read-only.
Gates run: `claude plugin validate` passed (warnings are only the env/state read-write listing), `claude plugin test` 244 pass / 0 fail, `typecheck.sh` clean, pytest `tests/context_vigil_mod` 6 passed.
Checked against: the spec, README, PROBES, SMOKES, the Mods Field Notes doc, and the engine typings in `.claude-plugin/types/claude-code/index.d.ts`.
Paths are relative to `plugins/context-vigil-mod/` unless stated.

---

## Critical

### 1. A `vigil_handover` call with no `awaiting` becomes a "request", and its clear skips both the attended check and the RC check
- **Severity:** Critical. **Confidence:** medium. It is certain in the code. How often it happens live depends on the model and on queued-submit behaviour.
- **Where:** `hooks/register.tsx:739-741` (`reason = awaiting?.reason ?? 'request'`, `resume = awaiting?.resume ?? true`) and `:762` (`scheduleClear($, reason === 'threshold')`, so a request runs with `unattended=false`). In `core/surfaces.ts:26`, the countdown and holdback apply only when `unattended` is true.
- **Failure:** whenever the tool runs while `awaitingA` is null, the code treats it as a clear the person asked for. It then runs at once with no attended re-check, no RC decline, no countdown and no holdback. Real ways to reach this:
  - (a) A second instruction prompt is queued (see #5, the subagent `turn.complete` retry, or #4, an Esc). The first tool call nulls `awaiting`. The queued instruction's turn then calls the tool again with `awaiting=null`, so reason is `request`. An auto handover that was **parked** (`clear.skipped attended`, or `rc-declined` / `rc-unanswered`) becomes an immediate clear on a person who is present, or on a phone where the person declined auto-clear.
  - (b) A manual `/clear` lands while the instruction prompt is still queued. The `awaiting` wipe is covered by the test at `shell-handover:337`, but the prompt itself is not. In the new session the queued "[context-vigil-mod] … Call the tool now" runs, writes a handover of an empty session, then clears **again** and submits a resume.
  - (c) After "couldn't write a handover" (`attempts` exhausted, `:645`), the model calls the tool late in a later turn while the person is working. The session clears under them.
- **Test:** set `auto` on, arm on the phone, set `rcAutoClear: 'no'`, reach the threshold handover, call the tool, and confirm `rc-declined` (parked). Then call `$.tool.call(TOOL …)` a second time with no new `startHandover`. Expect `w.commands` to not contain `clear`. Today it does. Better: make a call with no `awaiting` save the handover only (no clear), or carry the reason that last parked.

### 2. Answering the RC question "Yes" schedules an unattended phone clear 30 s after the person answered, and they cannot see the countdown
- **Severity:** Critical. **Confidence:** medium-high.
- **Where:** `hooks/register.tsx:724` (`if (settings.rcAutoClear === 'yes' && clearParked && pending) scheduleClear($, true)`). The `AskUserQuestion` answer is never recorded as human activity, so there is no `observe`. Related: `core/surfaces.ts:29-33` and PROBES §1 (toasts and logs never reach the phone).
- **Failure:** the phone session arms (no bridge prompt for ≥ idle window), and `maybeAskRc` queues the RC card. The threshold handover runs first and parks with `rc-unanswered`. The model then asks the card and the person answers **Yes** on the phone. That person is present right now, but `lastBridgeAt` is old, so the holdback passes. `mode()` still says `auto`, so the attended skip does not fire. The 30 s countdown starts, but its notice is terminal-only. The clear lands while the person is very likely typing their next message. The same path fires when a clear was parked because the person **cancelled the countdown** or because of an attended skip, if they later answer the card.
- **Test:** call `armOnPhone`, cross the threshold, call the tool, and assert `guard.wait rc-unanswered`. Answer the card "Yes" through `$.tool.call(ask(...))`, advance 31 s, and expect no `clear`. Today `clear` runs. Fix: count an answered card as presence (`observe` a human signal with the session's last origin), and do not auto-resume a parked clear from the answer hook.

---

## Important

### 3. A stale last-light handover is offered hours later as "resume (cheap)", and choosing it clears away all the work since
- **Severity:** Important. **Confidence:** high.
- **Where:** `hooks/register.tsx:590-600` (`holdOnReturn` only asks "is the pending handover last_light, and is now ≥ lastApi + 1 h"), with `core/last-light.ts:37-39`. Nothing drops a `last_light` pending when the person comes back before expiry. `shouldFire` (`core/last-light.ts:27`) then blocks every later last light, because `pending` is set.
- **Failure:** last light fires at 23:00 and writes handover A. The person returns at 23:30 while the cache is still warm, so the prompt passes. They work for 3 hours, then leave. They return the next morning: the prompt is held and they are asked "A handover is ready — resume from it (cheap)…". Picking Resume clears the conversation and injects A, which is 3 hours stale. Last light also never fired that night (it was blocked by the stale pending), so the "cheap" option is both wrong and stale.
- **Test:** fire last light and write the handover. Send `human('back')` at +10 min, then run `turn.complete` and several turns. Advance 2 h and send `human('morning')`. Expect no `drop` and no ask (or a fresh last light fired). Today: `drop` plus an ask. Fix: drop a `last_light` pending (store and state) on the first human prompt that passes, or apply `reusable`-style staleness (any `turn.complete` after `createdAt`).

### 4. An interrupted (Esc) handover turn counts as a missed attempt: the instruction is resubmitted and the unattended clear still runs
- **Severity:** Important. **Confidence:** medium-high.
- **Where:** `hooks/register.tsx:639-649` ignores `e.isAborted` (typings: `TurnCompleteFields.isAborted`). Pressing Esc is not an `observe` signal.
- **Failure:** auto mode starts a threshold handover. The person is at the terminal, sees it and presses Esc to stop it. `turn.complete{isAborted:true}` with `started` set leads to `attempts 2` and a resubmitted instruction. The model writes the handover, and `tryClear` sees `mode` still as `auto` (Esc left no trace), so it clears on the person who just tried to stop it.
- **Test:** arm auto mode, cross the threshold, and let the instruction start. Send `$.turn.complete({ ...turn(), isAborted: true, reason: 'aborted' })`. Expect no second instruction submit, and expect the person to be treated as present. Today the instruction is resubmitted.

### 5. A subagent's `turn.complete` is counted as the instruction turn's missed attempt
- **Severity:** Important. **Confidence:** high on the mechanism, medium on frequency.
- **Where:** `hooks/register.tsx:639` checks `awaitingNow?.started` with no `e.agentId === undefined` guard. Line 635 guards the TTL read but not this. The typings say every hook sees a subagent's turn with `agentId` set.
- **Failure:** a background subagent (common in this owner's workflow) finishes while the instruction turn runs. That bumps `attempts` and queues a **second** instruction. If two complete, the second one hits `attempts ≥ 2`: "📜 Couldn't write a handover — nothing was cleared" appears while the main turn is still writing it. Either way the extra instruction leads into #1(a). `lastApiA` and the last-light timer are also moved by subagent turns (`:633-634`), which pushes the hold-on-return expiry around.
- **Test:** `startHandover` via `/vho`, settle (`started=true`), then `$.turn.complete({ ...turn('sub'), agentId: 'a1' })`. Expect `submits` to hold exactly one instruction and expect no `handoverFailed` notice. Today there are two.

### 6. Settings are read once per process, and `/vsetup` in one session writes its stale copy over the account
- **Severity:** Important. **Confidence:** high.
- **Where:** `hooks/register.tsx:213` (`loadSettings` only in `bindSession`), `:710-712` (`applyAnswers(settings, …)` then `$.store.set(STORE_KEY, settings)`, which writes the whole object).
- **Failure:**
  - (a) In session A, `/vsetup auto` sets Off. Session B is already running and keeps `auto: true` in memory, so it keeps auto-handing-over and clearing. The same happens with `rcAutoClear: 'no'`: B still clears on the phone.
  - (b) B then runs `/vsetup bar`. It writes B's stale whole object, which silently reverts A's `auto: false` in the store for every future session.
  - The README says "Settings are per account".
- **Test:** two `world`s share one `store` Map. A answers the auto card "Off". B, already started, reaches the threshold armed and should not hand over. Then B answers the bar card, and `store.settings.auto` should stay false. Both fail today.

### 7. An in-process `/resume` (or fork) never rebinds the session, so handovers, pending keys and logs cross sessions
- **Severity:** Important. **Confidence:** medium. The typings list `classic.SessionStart` `source: 'startup'|'resume'|'clear'|'compact'|'fork'` and `session.end` `reason: 'resume'`, so a session swap inside one process exists.
- **Where:** `hooks/register.tsx:545` (`if (e.source !== 'clear') return out`). `session`, `edited`, `git`, `activity`, `handoverCount` and the timers are all kept.
- **Failure:** session A parks a handover (`rc-declined`, or an attended skip), which leaves `pending:A` in the store. The person runs `/resume` into B, but `session` is still A. Later they `/clear` in B. The clear branch reads `pendingKey(session=A)`, injects A's handover into B's fresh session and submits "Resume from the handover…", so B starts doing A's work. Before that, any handover written in B is named `A-<n>.md` and carries A's `edited` list, and B's events go into A's log. B's own stored pending is never offered.
- **Test:** start as s1, park a handover, then `w.sessionId.value='s2'` and `$.classic.SessionStart({ source: 'resume' })`. Then set `w.sessionId.value='s3'` and send a clear SessionStart. Expect no `additionalContext` from s1's handover. Today it is injected.

### 8. Unknown or unattested prompt origins count as the agent working, so a human there arms auto mode instead of disarming it
- **Severity:** Important. **Confidence:** medium.
- **Where:** `core/arming.ts:5-9`. Everything outside `composer|bridge|slack-ping|sdk` becomes `agent`. The typings say a channel the engine cannot attest (a same-user socket) "arrives as `unclassified`". `headless` is sticky for the whole process (`core/arming.ts:28`, never reset).
- **Failure:**
  - A person whose prompts come from an unattested channel (an IDE or desktop surface, or a socket) is treated as "agent working". Each prompt they send keeps the session in `auto`, so after the idle window, auto handover and clear run on someone actively prompting.
  - If any `sdk`-origin prompt ever reaches an interactive process, `headless=true` holds for good: later `composer` prompts never count as engaged, and auto clears fire on a present human.
  - This fails unsafe: an unknown origin should count as possibly human.
- **Test:** `observe` a prompt with `origin.kind: 'unclassified'` every minute for 40 min with the agent working. Expect `mode` to be `attended` (or at least not `auto`). Today it is `auto`. Then send an `sdk` prompt followed by a `composer` prompt and expect `attended`. Today it is `auto` or `idle`.

### 9. With an idle window of 60 min, last light never fires
- **Severity:** Important. **Confidence:** high.
- **Where:** `core/last-light.ts:25` (`mode !== 'idle'`), `core/arming.ts:41`. The fire is at `lastApi + 55 min` (`core/last-light.ts:9`).
- **Failure:** the person's last prompt comes at T. The turn ends at T+d, and the fire is at T+d+55 min. `mode` is `attended` until T+60 min, so with `idleMin: 60` (a setup option) it only fires if the turn took ≥ 5 min. There is no retry (`:484`), so it fails silently. Any `idleMin > 55` (store allows up to 1440) disables last light. After a hot reload `bindSession` sets `lastHumanAt = now`, so a reload more than about 25 min into the idle gap kills that fire with the default 30 min too.
- **Test:** settings `{ lastLight: true, idleMin: 60 }`. Send `human('hi')`, `measure(30)`, `turn.complete`, advance 55 min. Expect `last_light.fired`. Today: not fired. Fix: test "agent idle and no human within the fire lead", not the full idle window.

### 10. Phone notices and countdown never reach the phone, though the README and spec promise both (known, still open)
- **Severity:** Important. **Confidence:** high (PROBES §1 phone result, SMOKES #4 FAIL).
- **Where:** `hooks/register.tsx:93-95` (`notify` = toast + log only). `showNudge` `:394` sends phone sessions the notice "instead of the bar". The countdown starts at `:321`.
- **Failure:**
  - In an RC session the attended nudge goes nowhere, so the phone user gets **no** nudge at all.
  - The 30 s countdown that the README and the setup card offer as the safety net ("send anything to cancel") is invisible on the phone. So "Yes" to RC auto-clear means a silent clear 30 s after the holdback.
  - The README table ("notice on the phone") and the Remote Control section are false as shipped.
- **Test:** a shell test asserting that, when `onPhone`, nudge and `countdown-start` produce a plugin `$.prompt.submit` (the proven phone channel). The countdown should start only after that submit resolves.

### 11. A `/vho` deferred by the limit latch clears hours later with no presence or RC re-check
- **Severity:** Important. **Confidence:** medium.
- **Where:** `hooks/register.tsx:241-246` (defers `{reason:'request'}`), `:345-349` (drains on any later `checkLatch`), `:762` (`request` gives `unattended=false`, skipping the countdown and holdback).
- **Failure:** the person hits `/vho` while latched, then walks off or moves to the phone. Hours later the latch lifts on a `session.measure`. The instruction runs, and the clear goes straight through `clearGate` with `unattended:false`. On the phone that is no countdown and no holdback, and the draft is invisible, so the clear lands mid-message. The request was consent for a clear *then*, not hours later. A deferred `threshold` handover similarly pushes an instruction turn into whatever conversation the person has resumed.
- **Test:** set the latch, run `/vho` (deferred), then `human('x','bridge')`. Lift the latch (`store.delete('latch')`, then measure), call the tool, and `settle`. Expect the countdown or a re-ask, not a `clear`. Today: `clear`.

### 12. `$.ui.ask` on return has no timeout and no token, so two held prompts can lose a message
- **Severity:** Important. **Confidence:** medium-low. The Field Notes say "Never trust an open $.ui.ask to end … expect the dialog to outlive a /clear".
- **Where:** `hooks/register.tsx:491-503`, `:595-600`.
- **Failure:** while the first ask is open (or before it opens, since it is scheduled on `after(0)`), a second human prompt arrives, for example from the phone. `holdOnReturn` is still true, so it is dropped too and a second ask opens. Answer 1 "Resume" stores `followUp: held1` and schedules the clear. Answer 2 "Carry on" runs `savePending(null)`, which deletes `held1` with the pending, and `tryClear` then sees no pending and returns. `held1` is lost, which breaks the spec's "the held message is never lost". A late answer after a manual `/clear` resubmits the held text into the wrong session.
- **Test:** hold `human('one')`, and before settling hold `human('two')`. Answer the first ask Resume and the second Carry on. Expect both texts submitted (or the second not held). Today 'one' is lost.

### 13. Early stop fires again after every hot reload and in every new session, and its resume timer dies on reload
- **Severity:** Important. **Confidence:** high.
- **Where:** `hooks/register.tsx:56` (`firedEarlyStops` is a module variable), `:358-374` (`scheduleResume` uses clock timers, which the Field Notes say die on hot reload). `types/index.d.ts:88-89` claims "The latch and fired early stops live in $.store", which the code does not do.
- **Failure:**
  - The Field Notes say "A hot reload happens whenever the mod's source changes — including a git pull or checkout in the repo that holds it". This mod lives in the owner's working repo. At ≥ 95% weekly, every branch checkout means a reload. The next `session.measure` then submits another handover instruction turn into the live conversation (even if attended) and schedules another resume.
  - Each new session on the account also does this at its first measure.
  - Separately, a reload while waiting days for the reset silently drops the scheduled resume, unless the re-fire happens to re-create it. If it is latched by then, the re-fire defers a second limit handover that drains as an extra instruction prompt next to the resume.
  - The resume prompt itself (`:366`) is sent with no presence check, into whatever the person is doing at reset + 5 min.
- **Test:** seven_day at 96%, `measure`, call the tool. Then simulate a reload (`session.start` again, as other tests do) and `measure` again. Expect one `limit.early_stop`. Today: two. Fix: key the marks in `$.store` (`earlyStop:<kind>:<resetsAt>`) as the types comment says.

---

## Minor

### 14. The "Last light is off" line is an always-on band with a plain `0` hotkey
- **Severity:** Minor. **Confidence:** medium.
- **Where:** `hooks/register.tsx:783-789`.
- **Failure:** the spec makes the bar threshold-only because a bare digit typed into an empty box presses a `plain` button. This info line is shown for every 5-minute-cache session with last light on (that is, every API-key or credits session), from the first response until dismissed, and again after every `/clear` (`ttlInfoDismissed` reset at `:564`). A prompt that starts with `0` (such as "0.5 is wrong…" or "0) first…") loses its first key to Dismiss.
- **Test:** render with `cacheTtl='5m'` and assert that no `plain` hotkey Button is mounted, or that the line draws only between turns.

### 15. Stand-down and latch do not cover the setup prompts
- **Severity:** Minor. **Confidence:** high.
- **Where:** `hooks/register.tsx:138`, `:156-163`, `:146-153`.
- **Failure:** while classic is active (`standDown`), auto mode can still "arm" on the phone, and `maybeAskRc` submits a plugin prompt that makes the model ask the RC card. That breaks "no arming … one notice". While latched, the same `startSetup` submit goes through, which breaks spec §5 "never submits". A manual `/clear` while latched also submits the resume prompt (`:573`) without checking the latch.
- **Test:** with classic hooks in `/cfg/settings.json`, run `armOnPhone` and expect zero submits.

### 16. Cancelling the countdown with the `0` button is not recorded as presence, and any agent-origin prompt cancels the countdown
- **Severity:** Minor. **Confidence:** medium.
- **Where:** `hooks/register.tsx:777` (`onPress={() => cancelCountdown($)}`, no `observe`), `:602` (`origin.kind !== 'plugin'` cancels on `task-notification`, `scheduled-trigger`, `peer` and so on).
- **Failure:**
  - A person at the terminal presses 0 but stays "unattended". The agent keeps working, and at the next step a fresh auto handover and countdown start again.
  - Conversely, a background task notification during an RC countdown cancels it for good (`clearParked`) with a "cancelled" notice nobody gave.
- **Test:** press cancel and expect `mode` to be `attended`. Then `prompt.submit` with `origin.kind:'task-notification'` during the countdown and expect the countdown to keep running.

### 17. Two concurrent first `log()` calls lose a line, and a day log over 4 MiB is wiped
- **Severity:** Minor. **Confidence:** medium.
- **Where:** `hooks/register.tsx:87` (`dayText[path] = await $.fs.read(...)` runs after each caller's own await). `$.fs.read` refuses files over 4 MiB, which then becomes `''` and overwrites the file.
- **Failure:** two hooks log for the first time in a day or after a reload (for example `arm` from `tool.call` and `threshold` from `session.measure`). The second read's assignment overwrites the first record before it is written. The dashboard and the side-by-side comparison then miss events.
- **Test:** make `fs.read` resolve after a tick, then fire two `log`-producing events concurrently and expect both lines in the file.

### 18. `install.sh` replaces a symlinked settings.json, changes its mode, and `status` writes to disk
- **Severity:** Minor. **Confidence:** high.
- **Where:** `scripts/install.sh:10-11` (`mkdir` and `echo '{}' >` run for `status` too, before the `jq` check), `:20-22` (`mktemp` gives 0600, then `mv` over `$file`).
- **Failure:**
  - A dotfiles-managed `settings.json` symlink becomes a regular file, so the dotfiles copy silently diverges.
  - Permissions drop to 0600.
  - If `jq` fails on invalid JSON, `set -e` leaves `.settings.XXXXXX` behind.
  - `install.sh status` creates a config dir and settings file in an account that has none.
- **Test:** a pytest that symlinks `$CLAUDE_CONFIG_DIR/settings.json`, runs `install`, and asserts it is still a link. A second one runs `status` in an empty dir and asserts nothing was created.

### 19. `pending:<session>` keys leak in `$.store` forever
- **Severity:** Minor. **Confidence:** high.
- **Where:** `hooks/register.tsx:232-237`, `:515-520`.
- **Failure:** every session that exits with a parked or offered handover (rc-declined, attended skip, last light, limit) leaves a full-markdown entry in the account store file, which every session reads and writes. Nothing ever cleans them.
- **Test:** park a handover, end the session (`session.end`), and expect `pending:s1` to be gone (or pruned past an age).

### 20. `/compact` (SessionStart `source:'compact'`) keeps `lastNudged`, `baseline` and the bar from before the compaction
- **Severity:** Minor. **Confidence:** medium.
- **Where:** `hooks/register.tsx:545`, `core/handover.ts:7`.
- **Failure:** nudged at 45%, then auto-compact drops context to 15%. Steps 35/40/45 are suppressed until context passes 50 again. The auto-mode baseline is the pre-compact reading, and `barShown` keeps showing the old figure.
- **Test:** nudge at 45, send `SessionStart{source:'compact'}`, measure 36, and expect a nudge.

### 21. The handover counter restarts at 0 for a reused session id, so an existing `<session>-1.md` is overwritten
- **Severity:** Minor. **Confidence:** low. It depends on whether `--resume` keeps the id.
- **Where:** `hooks/register.tsx:743-745` (`handoverCountA` is in `$.state` and lost on a process restart).
- **Failure:** a restarted `--resume` session writes `s-1.md` over the handover that a stored pending still points at.
- **Test:** pre-seed the file `/cfg/context-vigil-mod/handovers/s1-1.md`, start, call the tool, and expect a new path.
