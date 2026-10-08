# context-vigil-mod: adversarial review, round 3 (Opus)

Branch `feat/context-vigil-mod` @ 6af4c16. Gates, all run from the worktree root: `claude plugin validate` passed (with warnings), `claude plugin test` 314 passed and 0 failed, `typecheck.sh` clean, `pytest tests/context_vigil_mod` 10 passed. Every finding below gets past all four gates.
Line numbers refer to `plugins/context-vigil-mod/hooks/register.tsx` unless another file is named.

---

1. **The unattended clear checks for the person and for a draft when it queues the clear, not when the clear runs**
   - Severity: **Critical**
   - Where: register.tsx:428-448 (`tryClearInner`), register.tsx:1077 (`scheduleClear` called from inside the tool call). The typings (claude-code/index.d.ts:2965) say `$.command.run` is "queued and run once the session is idle". Spec §2 (line 169) and the README say "Mode is re-checked at the moment of clearing".
   - Scenario: an auto threshold handover reaches the point where the model calls `vigil_handover`. That happens mid-turn, because the instruction turn is still running. `scheduleClear` → `after(0)` → `tryClearInner` passes the attended check and the draft check while the agent is still working, then hands `/clear` to the engine. The engine holds it until the turn ends. If the person comes back in that window, the clear still runs. A typed prompt reaches `prompt.submit` with origin `composer` and makes the mode attended, and a half-typed draft makes `prompt.read` non-empty, but nothing re-checks either before the queued clear runs. The `clearInFlight` flag only stops a second clear; it does not withdraw this one. PROBES §13 and §14 (a prompt or draft during a queued clear) are still unprobed, so whatever the person typed may be lost or land in the fresh session.
   - Fix direction: issue the clear only once the instruction turn has completed and the agent is idle. For example, run `tryClear` from `turn.complete` of the awaited turn, then re-check right before `command.run`, so that queue time and run time are the same moment.
   - Exposing test: in `world.tsx`, model `command.run('clear')` as held until a `turn.complete` (a `clearHold` that releases on turn end). Arm auto mode, take a threshold handover through the tool call, then `$.prompt.submit(human('back'))` before the turn completes. Expect no `clear` to run. Today it runs.
   - Confidence: high on the code path; medium on how much harm it does (it depends on PROBES §13 and §14).

2. **In Remote Control the countdown and every notice stay in the terminal, so the safety net behind the phone "Yes" answer never reaches the phone, and the 2-minute holdback can never trigger**
   - Severity: **Critical**
   - Where: `notify` at register.tsx:132-134 (only `ui.toast` and `ui.log`, both terminal-only per the Field Notes and PROBES §1); `showNudge` at register.tsx:573-581; core/surfaces.ts:29-31 (holdback); register.tsx:428-429 (attended check). README "notice on the phone" and "30 s countdown with Cancel"; spec §2 and §3 ("the phone gets an end-of-turn notice").
   - Scenario 1: someone on the phone answers "Yes" to auto-clear on the promise of a 30 s countdown they can cancel. Neither the countdown notice nor the AbovePrompt band reaches the phone (SMOKES #4 FAIL, two runs). The phone also never gets the threshold nudge or the "handover saved, nothing cleared" notices (`rc-declined` and `rc-unanswered`).
   - Scenario 2: the holdback is dead code. An unattended clear gets past `mode(...) === 'attended'` only when `now - lastHumanAt >= idleMin` (15 minutes or more through setup), and `lastBridgeAt <= lastHumanAt` always holds. So `now - lastBridgeAt < 120 s` can never be true when the gate is reached. The result is that a person who starts typing a reply on the phone after the idle window has no visible warning and no guard against a clear landing mid-message.
   - SMOKES records this as "Fix pending", but this branch has no phone-prompt path and the README and spec still promise it.
   - Exposing test: with `human('x','bridge')`, auto on, `rcAutoClear: 'yes'`, advance past the idle window and reach the threshold, then assert that something reaches the phone (`w.submits` gets a plugin prompt) before the clear. Today only `w.notices` and `w.logs` get anything. A second test: `clearGate` with `rc-holdback` cannot be reached through `tryClearInner` at any `idleMin >= 2`.
   - Confidence: high.

3. **A second `vigil_handover` call in the same turn overwrites the pending handover before the queued clear runs, so an unattended session clears into a handover with no resume and then sits idle**
   - Severity: **Important**
   - Where: register.tsx:1037-1043 (the first call sets `awaiting` to null), register.tsx:1062 (`savePending` overwrites `pending:<session>`), register.tsx:1071-1075 (the "unrequested" branch saves `reason:'request', resume:false`), register.tsx:790-823 (the clear branch reads the store at clear time).
   - Scenario: the model repeats the tool call, or makes two calls in one turn. This is the R1-01 case the code itself anticipates. Call 1 schedules the clear, which is queued until idle (see #1). Call 2 counts as unrequested and replaces the stored pending with `resume:false`. When the clear runs, `SessionStart(clear)` injects call 2's handover and takes the `injectedNoResume` branch. No resume prompt is sent. An auto handover leaves the new session idle with the person away.
   - Two parallel calls also both read `handoverCountA` and both pass `fs.exists` before either writes. They get the same `n` and the second overwrites the first file.
   - Test gap: test "R1-01: a duplicate tool call after a requested handover…" (tests/shell-handover.test.tsx:515) settles the clear between the two calls. The world's clear also runs synchronously, so the store is consumed before call 2 and the bug is hidden.
   - Exposing test: set `clearHold.held = true`, make two tool calls, then release. Expect a resume submit after the clear. Today none arrives.
   - Confidence: medium-high.

4. **A hot reload drops the latch-lift timer and the limit-resume chain, and nothing re-arms them**
   - Severity: **Important**
   - Where: module variables `latchTimer`, `limitResume` and `resumeChain` (register.tsx:59-65). `session.start` (register.tsx:715-750) only calls `checkLatch($, [])`, which lifts a latch that has already expired and never schedules a timer for a live one. `firedEarlyStops` is reset too.
   - Scenario: an early stop schedules a resume for reset + 5 min, and the person walks away. A `git pull` or `checkout` in the repo that `CLAUDE_CODE_PLUGIN_DIRS` points at (install.sh pins the checkout's path) hot-reloads the mod. The resume is silently gone. The README promises "arranges a resume 5 min after the reset if the session is still open".
   - Scenario: if the session is idle and latched, no timer will lift the latch. A deferred handover (in `$.state`, which survives the reload) or a parked clear then waits until some later `session.measure`. An idle session may never get one.
   - Field Notes rule: "Re-arm timers it cancelled".
   - Exposing test: latch set, early stop scheduled; simulate a reload (a new `register` over the same world store and state); advance past the reset. Expect `limit.cleared` plus a resume submit. Today you get neither.
   - Confidence: high on the code; the engine fact ("timers die on hot reload") is in the Field Notes.

5. **An expired latch still counts as in force everywhere it is read**
   - Severity: **Important**
   - Where: `readLatch` at register.tsx:296-298 has no `resetsAtMs` check. It is used at register.tsx:219, 348, 439, 677, 814 and 921.
   - Scenario: session A latches until 14:00 and exits before then. Session B has been idle since before the latch and has had no measure or timer since. At 15:00, `/vho` in B replies "⏳ the usage limit is in force", defers, and the person's next prompt cancels it. B's last light at 14:30 is refused as `latched`, which is the exact idle case last light exists for. B's clears park on `latched` with no re-check (`recheckMs: null`).
   - The "stale latch lifted at session start" fix (R2-04) only covers process start.
   - Exposing test: start a session; put `{latch:{kind:'seven_day',resetsAtMs:now+60_000}}` in the store directly, with no measure; advance 2 minutes; run `/vho`. Expect an instruction submit, not `waiting('latched')`.
   - Confidence: medium. A cross-session `rateLimits` measure might reach idle sessions, but nothing documents that.

6. **An attended `/vho` clear waiting on a draft runs after the person submits that draft, wiping the new exchange**
   - Severity: **Important**
   - Where: register.tsx:428 (the presence re-check covers unattended clears only), the draft retry at register.tsx:465, and `prompt.submit` at register.tsx:840-865, which cancels only a countdown.
   - Scenario: the person runs `/vho` while a draft is in the box, and the clear waits with the ✍️ notice. Instead of deleting the draft they send it. 2 s later the box is empty, the gate opens and the clear is queued. It runs right after the turn their message started, so that whole exchange is gone. The handover predates it, so `fresh()` usually fails and there is no automatic resume either.
   - The draft guard exists to protect the person's words. Here it delays the loss by one turn instead of preventing it. Test "a requested handover is attended by definition" covers a prompt sent before the tool call, not a draft-parked clear.
   - Exposing test: `/vho`, draft set, tool call (the clear waits), then `w.draft.value=''`, `$.prompt.submit(human('the draft'))`, `turn.start`, `advance(2000)`. Expect no clear, or an offer.
   - Confidence: medium. Design could be argued either way, but the outcome is data loss.

7. **Early stop and its "Continue the work" resume fire in any session that gets a measure, including idle or finished ones**
   - Severity: **Important**
   - Where: `session.measure` at register.tsx:955-962; `hopResume` at register.tsx:543.
   - Scenario: rate-limit windows are account-wide. Per the typings, a measure fires when "a window moved a whole point… or the account's limit status changed". In any open session that gets a ≥95% reading, including one whose work finished hours ago, the mod submits a handover turn (spending quota at 95%). Five minutes after the reset it then submits "The usage limit has reset. Continue the work" with nobody watching. The only guard is `lastHumanAt > stoppedAt`. Nothing asks whether the session was doing anything at the stop.
   - The same applies to `claude -p` and SDK runs on the account (see #8).
   - Exposing test: a session with its last turn 3 hours ago and the agent idle; a measure at seven_day 96%; advance past the reset. Expect no handover and no resume for a session that was neither working nor stopped. Today you get both.
   - Confidence: low-medium on measure delivery to idle sessions; high on the logic.

8. **Auto mode is an account-wide setting that silently covers every `claude -p` and SDK session**
   - Severity: **Important**
   - Where: core/arming.ts:11, 48 (`headless` is never attended); register.tsx:968-976.
   - Scenario: with auto on, any scripted `claude -p` run (orchestrators, CI helpers, the user's agent tooling) that crosses the threshold while working gets a handover instruction turn, a `/clear` and a resume prompt mid-run. The output its caller consumes becomes the handover or resume output, or the run ends before the clear. The README states this ("sdk sessions are unattended from the first turn") but offers no opt-out and no warning in `/vsetup auto`. Early stop and last light also act in `-p` sessions.
   - Exposing test: start with `isInteractive:false` and an `sdk` origin prompt, auto on, threshold crossed. Assert the mod stays out of non-interactive sessions, or at least that this is a deliberate, tested decision.
   - Confidence: medium.

9. **A deferred limit handover drained at the lift ignores presence and a draft, and sends stale text**
   - Severity: **Minor**
   - Where: register.tsx:499.
   - Scenario: an early stop that lands while latched (setLatch runs before earlyStopDue in the same measure) is deferred. Hours later, at the lift, `startHandover('limit')` submits "A usage limit is close…" even though the limit has just reset. It has no attended or draft check; edits do not cancel a deferred handover, only prompts and commands do. The limit resume then follows 5 minutes later.
   - Exposing test: rate limits at 100% and the latch set in the same measure; the person types a draft during the latch; lift. Expect no instruction submit.
   - Confidence: medium.

10. **A failed limit resume leaves `limitResume` set, and that corrupts the next early stop**
    - Severity: **Minor**
    - Where: register.tsx:550-556 returns without `limitResume = null`; register.tsx:530 inherits `path` and `stoppedAt` from it.
    - Scenario: the resume submit is rejected. A week later the next early stop reuses the old `stoppedAt`, so `back` (lastHumanAt > old stoppedAt) is almost certainly true and the new resume is skipped. If the new handover is covered or not yet written, it also names last week's file.
    - Exposing test: `submitRefused` at the first resume; reset `submitRefused`; trigger a second window key; advance. Expect a resume submit.
    - Confidence: high.

11. **The nudge tells the person to "say hand over", but the tool counts a handover the person asked for in chat as unrequested and never clears**
    - Severity: **Minor**
    - Where: core/voice.ts:25 (`say "hand over" (or /vho)`), core/handover.ts:57-58 ("Call it only when context-vigil-mod asks you to"), register.tsx:1071-1075.
    - Scenario: the person says "hand over". Either the model refuses because the description forbids it, or it calls the tool and gets "it was not asked for, so nothing was cleared". The advertised path is a dead end.
    - Exposing test: no `/vho` first; `$.tool.call(call())` after a human "hand over". Assert the voice string never recommends a path that cannot clear.
    - Confidence: high.

12. **`session.start` registers commands and the tool first, unguarded, before stand-down, latch and pending restore**
    - Severity: **Minor**
    - Where: register.tsx:718-721. Field Notes: "A throw skips the rest of the hook: register commands last or wrap them in try/catch".
    - Scenario: if any register rejects (for example a re-registration on reload, or a name clash), `checkInterlock` never runs. `standDown` stays false while classic is installed, and the pending offer and the last-light timer are also skipped.
    - Exposing test: make `command.register` throw for `vho`; start with classic hooks in `/cfg/settings.json`. Expect the stand-down notice.
    - Confidence: low-medium; it depends on whether re-registration throws.

13. **The R2-15 error wrapping does not cover every timer job**
    - Severity: **Minor**
    - Where: `hopResume`'s async callback (register.tsx:535-559: `checkLatch`, `prompt.read`, `notify` and `savePending` are unguarded), `askReturn` (751, 851), `renameSession` (804), `learnSessionTtl` (905).
    - Scenario: a store or `prompt.read` failure inside the resume hop leaves an unhandled rejection. The limit resume silently never happens and there is no `timer-error` log line. That contradicts commit 6bd4018's "a failing timer-driven … job is announced and logged".
    - Exposing test: `promptReadFails.count = 1` at resume time; expect a `guard.wait timer-error` (or `resume-…`) log line and a notice.
    - Confidence: high.

14. **In phone sessions where RC auto-clear is declined or unanswered, every further step past the threshold writes another handover turn and never clears**
    - Severity: **Minor**
    - Where: register.tsx:964-977 together with `reusable` (core/handover.ts:32-35, which goes stale once turns run) and core/surfaces.ts:27-28.
    - Scenario: every +5% step past the threshold runs a full handover instruction turn and writes a file, then parks on `rc-declined` or `rc-unanswered` (notices the phone cannot see). Each step spends tokens on a handover that can never be used automatically.
    - Exposing test: bridge, auto on, `rcAutoClear:'no'`; push context through 35 → 40 → 45 with turns in between. Expect at most one handover written.
    - Confidence: medium.

15. **install.sh lists whatever checkout it ran from, worktrees included**
    - Severity: **Minor**
    - Where: scripts/install.sh:7.
    - Scenario: running it from `.claude/worktrees/context-vigil-mod` points the account at that worktree. Removing the worktree after merge leaves a dead plugin dir, and every git operation in the worktree hot-reloads the mod and triggers #4. There is no warning or check.
    - Exposing test: a pytest that runs install.sh from a path containing `/.claude/worktrees/` and expects a warning or refusal.
    - Confidence: high; impact low-medium.

16. **The test world differs from the engine in three ways that hide #1, #3 and #6**
    - Severity: **Minor**
    - Where: tests/world.tsx:115-122 and 130-145.
    - Detail: `command.run('clear')` runs at once instead of "queued … once the session is idle". `clearHold` exists but no presence or draft test uses it. `$.ui.ask` is answered through the AskUserQuestion `tool.call`, so in tests an ask answer reaches the mod's own AskUserQuestion hook and counts as presence. Live, it does not pass through `tool.call` (PROBES §6, Field Notes). The Field Notes' fidelity checklist asks for a world that wipes what the engine wipes; this one also needs to delay what the engine delays.
    - Exposing test: make `clear` held-until-idle the default and re-run the suite; R1-01 (#3) and any presence-after-queue case should fail.
    - Confidence: high.

17. **A setup card the model paraphrases is dropped silently, and `setupRun` stays set**
    - Severity: **Minor**
    - Where: core/setup.ts:153-155 (exact-text match); register.tsx:994-999 returns with `setupRun` unchanged; register.tsx:217.
    - Scenario: if the model alters a question's text even slightly, or the person dismisses the card, the answers are ignored with no notice. `setupRun` stays non-null until a `/clear`, so `maybeAskRc` never asks the RC question in that session.
    - Exposing test: answer a card whose question text has a trailing space. Expect a notice and `setupRun` cleared.
    - Confidence: medium.

18. **A `spend_limit` window with no `resetsAt` is never watched or latched, and nothing says so**
    - Severity: **Minor**
    - Where: core/limits.ts:18, 38-39.
    - Scenario: the typings mark `resetsAt` optional. A gateway spend cap reported without one never triggers the default-on early stop or the latch, with no log line, even though `/vsetup` lists it as watched by default.
    - Exposing test: `rateLimits=[{kind:'spend_limit',percentUsed:97}]`; expect `limit.early_stop` or at least a logged skip.
    - Confidence: low.
