# context-vigil-mod: adversarial review, round 2 (Opus)

Target: `plugins/context-vigil-mod` on `feat/context-vigil-mod` (HEAD ba4f884). Gates at review time were all green: validate passed (with warnings), plugin test 285/285, typecheck clean, pytest 10/10. Line numbers refer to `hooks/register.tsx` unless another file is named.
Engine facts I relied on: the typings say `$.command.run` is "queued and run once the session is idle" and that `$.prompt.submit` "resolves when it starts / when queued". The Field Notes say a hot reload fires on any source change "including a git pull or checkout in the repo that holds it", and "Never trust an open $.ui.ask to end".

Counts: Critical 1 · Important 6 · Minor 12

---

1. **A clear parked by the latch runs when the latch lifts, with no check that you are present and no check that the handover is still fresh. It lands on a person who has just come back.**
   - Severity: Critical
   - Where: register.tsx:436 (`checkLatch` → `scheduleClear($, unattendedClear)`); register.tsx:363-376 (`tryClear` skips the attended re-check when `unattendedClear` is false and never checks `fresh`). Test shell-limits.test.tsx:34 enshrines this, but only with nobody returning.
   - Scenario:
     1. You run `/vho` or press bar `1`, or choose "Resume" in the last-light ask (all of these call `scheduleClear(false)`).
     2. The latch gets set between the instruction and the write. Another session's `StopFailure`, or a measure at 100%, writes it to `$.store`.
     3. `tryClear` parks with `lastWait = 'latched'`.
     4. After the reset you come back and send "carry on". That turn's `session.measure` shows the window under 100%, so `checkLatch` lifts the latch and re-schedules the clear.
     5. The gate passes: the box is empty and the clear is attended by definition, so no RC checks apply. `/clear` runs right after your turn and wipes the exchange you just had.
     6. The clear branch then finds the handover stale (`fresh` is false). It injects the old handover and sends no resume.
     The same happens if the latch's own timer lifts it while you are typing or reading. Your prompt is not recorded anywhere this path looks. `observe` drops only `deferredA`, never a parked clear.
   - Test: in shell-limits, run `/vho`, then latch via StopFailure, then `tool.call(write)` (parked). Then submit `human('carry on')`, run `turn.complete`, and send `measure` with five_hour at 1%. Expect no `clear` in `w.commands` and a `pendingOffer` notice. Today the clear runs.
   - Confidence: high on the code path; medium on how often it happens.

2. **The clear gate is checked when the clear is queued, not when it runs. A /clear can land on a person who arrived in between.**
   - Severity: Important
   - Where: register.tsx:944 (`scheduleClear` from inside the `vigil_handover` tool call, mid-turn); register.tsx:357-382 (attended re-check, draft and RC gate, then `$.command.run({command:'clear'})`).
   - Scenario:
     1. `tryClear` fires 0 ms after the tool call, while the instruction turn is still running: the model still has to answer the tool result.
     2. `$.command.run` is queued until idle (per the typings), so the attended re-check and the draft check are already stale when it runs.
     3. On an unattended (auto) handover you come back during that tail and send a message, or start typing.
     4. `observe` marks you attended, but the queued `/clear` cannot be withdrawn. The mod never sees its own `command.run` in its hooks, so it cannot re-check there.
     5. The clear runs anyway, against spec §2 ("If the session became attended meanwhile, the clear is skipped").
     The test world's `command.run` resolves at once, so no test can see this.
   - Test: have the world hold `command.run('clear')` until the next main `turn.complete`. Arm auto mode and cross the threshold, then call `tool.call(write)`, `human('wait')`, and `turn.complete`. Expect no clear. Fix direction: start the clear attempt from the instruction turn's `turn.complete`, not from the tool call.
   - Confidence: medium (it rests on the documented queue-until-idle behaviour, which has not been probed for this path).

3. **A second `tryClear` can start while the first is still waiting on its queued `/clear`. The result is two `/clear`s, and the fresh session loses its injected handover.**
   - Severity: Important
   - Where: register.tsx:322-324 (`startHandover` reuse path → `scheduleClear`); register.tsx:350-354 (only cancels `retryTimer`, which the running `tryClear` has already nulled at :358); register.tsx:847-855 (measure → `startHandover('threshold')`).
   - Scenario:
     1. An auto handover is at 44%, with steps of 5.
     2. Tool call → `tryClear` A → `$.command.run('clear')` is queued and awaited.
     3. The instruction turn's final response raises `session.measure` at 45%. `armed` and `grownEnough` both pass, and `startHandover('threshold')` runs.
     4. `awaiting` is null (the tool call cleared it), and the pending is `reusable` because `lastApiA` has not moved yet. `scheduleClear` → `tryClear` B finds `pendingA` still set and queues a second `/clear`.
     5. Clear 1 injects the handover and schedules the 500 ms resume.
     6. Clear 2 wipes that session. Its SessionStart finds no pending, because clear 1 deleted the store key.
     7. The resume prompt, "Resume from the handover injected above", lands in a third, empty session. Nobody is watching.
     Nothing marks a clear as in flight.
   - Test: same delayed `command.run` world as #2, with auto armed. Run `tool.call(write)`, then `measure(45)` before `turn.complete`. Expect exactly one `clear` in `w.commands`.
   - Confidence: medium.

4. **`awaiting` never expires. Combined with the R1-11 guard, any lost instruction disables every later handover for the session.**
   - Severity: Important
   - Where: register.tsx:316-320 (refuses while `awaitingA` is set); register.tsx:136-145 (`started` is set only by the submit callback); register.tsx:771 (`turnId` is bound only on exact text equality); register.tsx:800 (attempts are counted only on that turn).
   - Scenario: `awaiting` is cleared only by the tool call, by a matched `turn.complete`, or by a `/clear`. It stays set forever if any of these happens:
     - (a) You delete the queued `[context-vigil-mod] … Call the … tool` prompt before it runs (Claude Code lets you edit or remove queued messages).
     - (b) The `turn.start` `e.text` of a plugin prompt is not byte-identical to `instructionText` (unprobed; it is "the text as the turn proceeds with it", after other plugins' hooks).
     - (c) A hot reload lands between `startHandover` and its 0 ms submit timer, so the timer is dropped and the instruction is never sent.
     After that, every `/vho`, bar `1`, threshold auto handover and last light answers "A handover is already in progress — one at a time" and does nothing, until a `/clear`. Smoke #1 passed only because the model called the tool on its first try; the retry/fail path has never run live.
   - Test: run `/vho` and let the instruction submit resolve. Raise no `turn.start` with the instruction text, then run a main `turn.complete` with another turnId. Advance 10 min and run `/vho` again. Expect a fresh instruction, or a failure notice and a reset. Today you get `handoverInProgress`.
   - Confidence: medium.

5. **A latch that another session set is never lifted in an idle session. A limit resume there polls forever and is never sent.**
   - Severity: Important
   - Where: register.tsx:400-407 (`setLatch` returns early when a latch already exists, so only the setting process ever arms the lift timer); register.tsx:457 (`hopResume` re-hops every 60 s while `readLatch` returns anything, even an expired latch, and never calls `latchCleared`).
   - Scenario:
     1. Session B early-stops at 95% of seven_day and schedules a resume for reset + 5 min.
     2. Session A hits the limit; its StopFailure latches the store and arms A's timer.
     3. B's own StopFailure finds the latch already set, so B arms no timer.
     4. You close A.
     5. At the reset nothing lifts the latch. B is blocked, so it runs no turns and gets no measures.
     6. B's `hopResume` reads the expired latch every minute, forever. The promised "I'll resume after the reset" never happens.
     B's parked clears and deferred handovers also wait for a measure that never comes.
   - Test: put `latch: {kind:'seven_day', resetsAtMs: T}` in the store first, so `setLatch` is skipped. Early-stop B with resetsAt T, advance past T + 5 min with no measure, and expect the resume submit. Fix direction: treat `now >= resetsAtMs` as lifted (call `checkLatch($, [])`) in `hopResume`, and arm a lift timer on every `setLatch` observation.
   - Confidence: high.

6. **After a restart or an in-process `/resume`, a last-light handover is thrown away on your first prompt instead of being offered. The overnight case is exactly what last light exists for.**
   - Severity: Important
   - Where: register.tsx:633-637 (pending restored from `$.store`, `lastApiA` null in a fresh `$.state`); register.tsx:671-675 (the `/resume` branch nulls `lastApiA`); register.tsx:738 (`cacheExpiresAt: lastApi === null ? null : …`); core/last-light.ts:37-38 (`holdOnReturn` is false when `cacheExpiresAt` is null); register.tsx:748-751 (the R1-05 path then drops the pending).
   - Scenario:
     1. Last light writes a handover at 23:00. You close the terminal.
     2. Next morning `claude --resume <id>` shows "A handover is waiting".
     3. Your first message is not held and no question is asked. The pending is deleted (`last_light.dropped`), and the message goes into the full conversation and pays the cold cache.
     Spec §4: on return with the cache past expiry, the prompt is held and the choice asked. A restarted process means the cache is certainly cold.
   - Test: store holds `pending:s1` with reason `last_light` and createdAt 8 h ago. Run `session.start`, then `prompt.submit(human('morning'))`. Expect `{ drop }` and an ask. Today the prompt passes and the pending is deleted.
   - Confidence: high.

7. **The last-light ask has no timeout and no token, despite the Field Notes rule. A hot reload while it is open can lose the held message.**
   - Severity: Important
   - Where: register.tsx:604-620 (`returnHeld` is a module variable; the old ask closure runs on the old module's `$` and timers); register.tsx:740-742.
   - Scenario: hot reloads are frequent here, because the mod is installed from a pip-skills worktree and any checkout or pull reloads it.
     1. You return and your prompt is held; the ask is open.
     2. A reload happens. The new module has `returnHeld = null` and still has `pending.reason = 'last_light'` in `$.state`.
     3. Your next prompt opens a second ask over the first.
     4. The original ask's answer runs on the old module. "Carry on" uses `submitSoon` → `$.clock.after`, whose timers the reload dropped (the comment at :646 says reload drops timers). "Resume" uses `scheduleClear`, the same dead timer.
     5. The first held message is never sent and nothing says so. Spec §4: "the held message is never lost". The Field Notes rule is to race the ask against a timer and guard a late answer with a token.
   - Test: hold a prompt so the ask is open (the world's ask stays pending). Re-run `session.start` to simulate the reload, then answer the old ask "Carry on". Expect the held text in `w.submits`, or a `resumeFailed` notice naming it.
   - Confidence: low-medium (depends on whether the old `$` and its timers still work after a reload).

8. **The instruction retry ignores the latch and stand-down.**
   - Severity: Minor
   - Where: register.tsx:807-809.
   - Scenario: the instruction turn dies on a rate limit. StopFailure sets the latch and `turn.complete` arrives with `reason:'error'` and `attempts < 2`. `submitInstruction` re-submits while latched, against spec §5 ("never submits"); the retry fails against the limit and spends attempt 2. The same happens if stand-down turned on mid-flight.
   - Test: run `/vho`, StopFailure `rate_limit`, then `turn.complete` (matching turnId, not aborted). Expect no second instruction and a deferred or dropped notice.
   - Confidence: medium-high.

9. **A deferred `limit` handover runs after the reset, with no presence check and with a wrong reason in its text.**
   - Severity: Minor
   - Where: register.tsx:426; core/handover.ts:101.
   - Scenario: a measure jumps a window to 100%. `setLatch`, then `earlyStopDue` (100 ≥ 95), then `startHandover('limit')` is deferred. At the lift (reset + 1 s) the mod submits "A usage limit is close. Save the handover…" after the limit has reset, whatever you are doing. Then at reset + 5 min it also sends the resume prompt. The result is a wasted turn with a false premise.
   - Test: measure seven_day at 100 with resetsAt T, then advance past T. Expect no limit instruction.
   - Confidence: high.

10. **Turning auto mode Off does not stop an unattended clear that is already in flight.**
    - Severity: Minor
    - Where: register.tsx:360-364.
    - Scenario: `tryClear` reloads settings but re-checks only `mode === 'attended'`, not `settings.auto`. An auto handover started before you turned auto Off (in another session, or via `/vsetup auto` from the phone) still clears while you are away.
    - Test: store `auto:true` and arm; tool call with unattended set; set `store.settings.auto = false`; settle. Expect no clear.
    - Confidence: high.

11. **Pressing a vigil-bar button is not counted as presence (the bar's version of R1-22).**
    - Severity: Minor
    - Where: register.tsx:978-982; register.tsx:500-505.
    - Scenario: your last prompt was 28 min ago and the bar appeared. You press `2` and keep watching. 2 min later the 30-min idle window has passed while the agent works, so mode is `auto`. The next +5% step hands over and clears unattended, minutes after you pressed a button.
    - Test: shell-bar: press `later`, advance past `idleMin` from the last prompt, measure the next step. Expect a nudge, not an instruction.
    - Confidence: medium.

12. **The first-RC question is asked once per process and again after every hot reload. The README says "asked once per account".**
    - Severity: Minor
    - Where: register.tsx:63, :244; README "Remote Control".
    - Scenario: you dismiss the card, so it stays `unanswered`. Each reload (any checkout in the repo) or new process re-asks on the next phone arm. Each ask submits a prompt whose AskUserQuestion blocks the unattended run (R1-25).
    - Test: arm on the phone, ask, dismiss; run `session.start` again; arm. Expect no second card prompt.
    - Confidence: high.

13. **The early stop fires again on every hot reload, which is far more often than the ruling assumed.**
    - Severity: Minor (needs re-ratification)
    - Where: register.tsx:56, :835-842.
    - Scenario: S16/O13 accepted "a reload may re-fire once". The Field Notes say reloads come from every git pull or checkout in the repo holding the mod, and that is this repo. While seven_day sits at ≥95% (for days), each checkout costs a limit handover turn plus a new resume chain, all near the cap.
    - Test: early stop fires; run `session.start` (reload); measure the same window. Expect no second instruction.
    - Confidence: high on behaviour; the severity is the owner's call.

14. **A failed `$.store.set` in `savePending` is not handled. The tool hook throws after the file is written, with no notice, and a later `/clear` injects nothing.**
    - Severity: Minor
    - Where: register.tsx:299-304, :935.
    - Scenario: the store is near 4 MiB, or the markdown is very large. `pendingA` is updated, then `store.set` rejects and the hook throws. The model sees a tool error, and `awaiting` was already cleared. The clear branch reads only the store, so nothing is injected.
    - Test: `w.onStoreSet` rejects for `pending:` keys; run `tool.call(write)`. Expect a `handoverFailed` notice and a `{result}` that names the failure.
    - Confidence: medium.

15. **A typed answer to the last-light ask counts as "Carry on" and the typed text is lost.**
    - Severity: Minor
    - Where: register.tsx:607-610.
    - Scenario: PROBES §6 shows the dialog adds "Type something." and "Chat about this". `ui.ask` then resolves with your free text. It is not `V.lastLightResume`, so the mod carries on, and the typed text is neither held nor sent.
    - Test: `askAnswer = 'use the handover please'`. Expect resume, or the typed text appended to the held message.
    - Confidence: low-medium.

16. **The last-light re-schedule after a hot reload can never fire, and the comment says otherwise.**
    - Severity: Minor
    - Where: register.tsx:646-652 vs :241 and :587.
    - Scenario: the comment says "the fire the reload's dropped timer owed is scheduled again". But `bindSession` sets `lastHumanAt = now` (after `lastApiAt`), so `youIdle` is false when that timer fires. The test at shell-last-light.test.tsx:237 enshrines the skip. Either the code or the comment is wrong.
    - Test: the existing reload test, asserting the timer's fire logs nothing; or change the comment.
    - Confidence: high.

17. **The in-process `/resume` and fork branch leaves process-wide jobs from the old conversation running.**
    - Severity: Minor
    - Where: register.tsx:663-677.
    - Scenario: `limitResume`/`resumeChain`, `returnHeld` and `standDown` are kept, and `checkInterlock` is not re-run for the new id (`classicSessionPath` is keyed on the session). The old conversation's limit-resume prompt ("Continue the work; the handover you wrote is saved at …") is later submitted into the different, resumed conversation.
    - Test: early stop in s1; `classic.SessionStart` resume as s2; advance past the reset. Expect no limit resume in s2.
    - Confidence: medium.

18. **An early stop silently cancels a requested clear that was waiting.**
    - Severity: Minor
    - Where: register.tsx:326 → :334-341.
    - Scenario: a `/vho` clear is waiting on your draft (2 s retries). An early-stop measure arrives; `startHandover('limit')` finds the non-reusable path (reason limit), and `supersedePending` cancels the retry and deletes the pending. Your requested clear never happens and you are not told.
    - Test: `/vho`, set a draft, tool call (waiting); measure seven_day 96. Expect a notice that the requested clear was replaced, or the clear kept.
    - Confidence: medium.

19. **`install.sh` rewrites `settings.json` by truncating and refilling it in place, and leaks its temp file when `jq` fails.**
    - Severity: Minor
    - Where: scripts/install.sh:19-25.
    - Scenario:
      - `cat "$tmp" > "$file"` truncates and then refills the file. A running Claude Code that watches or writes the account's `settings.json` can read a half-written file, or lose a write made between the script's `jq` read and the `cat`.
      - If `jq` fails inside `write` (for example `{"env":"x"}`), `set -e` exits, and `trap … RETURN` does not run on exit, so `.settings.XXXXXX` is left behind. The existing invalid-JSON test fails earlier, at line 14, so it never reaches this path.
    - Test: `settings.json = {"env":"x"}`; `install` exits non-zero, the original is unchanged, and no `.settings.*` is left in cfg.
    - Confidence: medium.
