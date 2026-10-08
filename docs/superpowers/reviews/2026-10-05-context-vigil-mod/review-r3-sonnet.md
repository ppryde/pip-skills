# context-vigil-mod adversarial review, round 3 (sonnet)

Gates: all four pass (validate: 1 warning, no author; plugin test 314 pass; typecheck.sh clean; pytest 10 pass). Findings are what the green suite hides.
Paths are relative to /Users/philip.pryde/repos/pip-skills/.claude/worktrees/context-vigil-mod/plugins/context-vigil-mod.

1. A human prompt arriving after the gate said "go" does not stop a queued unattended /clear
   - Severity: Critical (unattended action with a human present)
   - Where: hooks/register.tsx:437-457 (clearGate then `$.command.run({command:'clear'})`), prompt.submit hook :840-865. PROBES §13 is still UNPROBED.
   - Scenario: auto mode, the person away. Gate passes, `clearInFlight=true`, `$.command.run('clear')` is queued until the session is idle (the R2-10 comment says so). The agent is still finishing the handover turn. The person comes back and sends a message. `prompt.submit` calls `observe` (mode becomes attended) and `cancelCountdown`, which does nothing because no countdown is running. Nothing cancels the already-queued clear. Whichever order the engine runs the two, the clear wipes the conversation. If the person's message ran first, the clear lands after it and `classic.SessionStart` injects a handover that predates that exchange. The attended re-check at :429 runs only before the command is queued.
   - Test: in shell-handover.test.tsx, use `w.clearHold.held=true`. Reach the unattended threshold handover and let tryClear block in `command.run`. Then `$.prompt.submit(human('hi'))`, release the hold, and assert either that the clear never ran or that a notice and `clear.skipped` appear. This is the missing human-during-queued-clear test; the existing clearHold test (:684) only covers a second threshold crossing.
   - Fix: the mod's own `command.run{command:'clear'}` hook should veto it (`deny`) when the clear is unattended and `mode()==='attended'` at execution time.
   - Confidence: medium. It depends on the §13 queue ordering, but the code has no re-check at execution time in any ordering.

2. The RC safety countdown and every wait notice are invisible on the phone; the README and spec claim otherwise
   - Severity: Important
   - Where: hooks/register.tsx:132-134 (`notify` is toast plus ui.log), :1081-1095 (the countdown draws in `ui.render` AbovePrompt, terminal only). PROBES §1 says neither toast nor log reaches the phone and the UI never draws there. The "send as a plugin prompt" decision is still "pending owner approval" and is not implemented. README says "notice on the phone" and "Phone sessions get the notice, not the bar"; spec §2 says the countdown is "shown as a notice with a Cancel".
   - Scenario: the person is on the phone and has answered "yes" to RC auto-clear. At countdown-start the mod notifies via toast/log and draws the band, and none of it reaches the phone. 30 s later the session is cleared with no warning. "Any message cancels" is the only protection, and the person cannot know a countdown is running. The same applies to the end-of-turn nudge (`showNudge`), `clear.skipped` and `waiting`.
   - Test: world with `onPhone` (bridge prompt) and rcAutoClear 'yes'. Assert that some phone-reaching channel (a `$.prompt.submit` plugin prompt) announces the countdown before the clear. Today `w.submits` is empty at countdown-start.
   - Confidence: high.

3. A held last-light prompt is silently lost if the session is /clear-ed (or otherwise reset) while the return question is open
   - Severity: Important (spec §4 says "the held message is never lost")
   - Where: hooks/register.tsx:849-852 (`drop` plus `returnHeldA`), :302-315 (`resetSessionState` nulls `returnHeldA` on a clear or resume), :694-698 (`askReturn` returns silently when `taken.v` is empty). PROBES says `$.ui.ask` outlives /clear.
   - Scenario: last light fired and the cache expired. The person types "fix the bug"; it is dropped and held, and the ask opens. They type `/clear` instead of answering. `returnHeldA` is wiped, the ask is eventually answered or dismissed, `taken.v` is null, and the message is gone with no notice. `/resume` or fork does the same through `resetSessionState`.
   - Test: hold a prompt after cache expiry with `askHold.held=true`. Run `$.classic.SessionStart({source:'clear'})`, then release the ask. Assert that the held text was submitted or a notice names it. It currently asserts nothing.
   - Confidence: high.

4. The held-prompt "Resume" path can park the person's message inside the pending handover with no delivery
   - Severity: Minor
   - Where: hooks/register.tsx:705-709. `savePending({...followUp: held})` then `scheduleClear($, false)`. If the latch is set, `tryClear` parks the clear (`latched`, recheckMs null).
   - Scenario: the held message sits in `pending.followUp` and is delivered only on a later clear. The person sees "waiting (latched)" but never their message in the conversation, and a stale `followUp` can leak into a later manual /clear as an unrelated first prompt (:800, :809).
   - Test: latch set, then answer "Resume"; assert the held text is not stranded.
   - Confidence: medium.

5. A model-volunteered or duplicate `vigil_handover` call overwrites the requested pending handover
   - Severity: Important
   - Where: hooks/register.tsx:1043-1071. The unrequested path (awaiting already null) still calls `savePending` with `reason:'request', resume:false`. `startHandover`'s reuse branch (:371-374) ignores the caller's `resume`.
   - Scenario 1: an unattended threshold handover is written (pending: threshold, resume true) and a clear is scheduled. The model calls the tool again, in a parallel tool call or as a repeat (the R1-01 test covers only "no second clear"). The second call overwrites pending with resume:false. The queued clear then runs, injects the handover, sends no resume prompt, and the away person's work stalls with only an "injected, no resume" notice.
   - Scenario 2: `/vho` or bar "1" reuses a fresh volunteered pending (resume:false), clears, and never resumes, although a requested handover should resume.
   - Test: extend the R1-01 duplicate-call test to assert `pending.resume===true` and that a resume prompt is submitted after the clear. For scenario 2: volunteered call, then `/vho`, assert the resume submit.
   - Confidence: medium-high.

6. A hot reload turns a latch-deferred, auto-run handover into an attended clear
   - Severity: Minor
   - Where: hooks/register.tsx:733-736. `Pending` does not store `unattended`. A deferred request that `checkLatch` runs as `startHandover(...,'request', true)` (:501) is saved with reason 'request'. After a reload it matches `live.reason==='request'`, so `scheduleClear($, false)` runs.
   - Scenario: the person is on the phone with RC "yes". The unattended handover is written, the mod is hot-reloaded (a git pull in the repo triggers it), and it comes back as an attended clear. That bypasses the RC holdback, the countdown and the attended re-check, which is exactly what the Field Notes rule "a hot reload must not run an unattended action" forbids.
   - Test: deferred request resumed under latch, session.start reload while pending, onPhone and unattended. Assert there is no clear without the countdown.
   - Confidence: medium.

7. The classic interlock only runs at session.start, resume/fork and tryClear
   - Severity: Minor, TEMPORARY code
   - Where: hooks/register.tsx:284-294 and the callers; core/interlock.ts reads only `<root>/settings.json` and a per-session record.
   - Scenario A: the classic record or hooks appear after the mod's session.start, or classic is installed project-level in `.claude/settings.json`. `standDown` stays false for threshold nudges, last light and limit handover instructions. Both tools then run, and a double handover or double clear is possible. Only `tryClear` rechecks.
   - Scenario B: after a /clear the new session id's classic record is never rechecked until the next `tryClear`.
   - Test: install classic hooks after session.start, cross the threshold, and assert the mod stands down.
   - Confidence: medium.

8. Unguarded `$.prompt.read()` and store/fs errors inside hooks that must call `next`
   - Severity: Minor
   - Where: `observe` (register.tsx:179) is awaited in the generic tool.call hook (:884-891, after `next`) and in prompt.edit and turn.complete. `session.measure` (:946-982) awaits store, `startHandover` and `showNudge` before `return next(e)`.
   - Scenario: `$.prompt.read()` rejecting (no terminal, headless or sdk sessions, odd surface) makes every tool.call and turn.complete hook throw. A throw in the measure hook skips `next(e)`, so the measurement chain breaks. The test world only injects `promptReadFails` into tryClear.
   - Test: `promptReadFails.count=100`, then run tool.call, turn.complete and session.measure; assert they still resolve and `next` runs.
   - Confidence: medium-low (depends on engine behaviour for a throwing hook).

9. A deferred `limit` handover is run after the latch lifts regardless of presence
   - Severity: Minor
   - Where: hooks/register.tsx:499. `if (deferred.reason === 'limit') await startHandover(...)` with no attended check, while threshold and request are gated at :500.
   - Scenario: hours later the person is typing; the mod submits a "[context-vigil-mod] write a handover, do nothing else" prompt into their live conversation, unrelated to any limit still being near. The resume chain is separate. The same happens when an early stop fires while the person is attended: `startHandover($,'limit')` has no presence guard.
   - Test: latch set, early-stop deferred, human prompt, latch lifts; assert there is no instruction submit.
   - Confidence: medium.

10. Timer-driven last-light/limit-resume jobs vanish on a hot reload with no notice
    - Severity: Minor
    - Where: hooks/register.tsx:59-65 (module-level `limitResume`, `resumeChain`, `firedEarlyStops`). `session.start` re-arms last light but not the limit resume.
    - Scenario: the 95% early stop fires, a handover is written and the resume is scheduled for the reset +5 min. The plugin dir is updated or reloaded overnight. `limitResume` and the chain are gone; `firedEarlyStops` is also reset, so the early stop may re-fire once (noisy) or, if the window cleared, never. The README promises a resume after the reset, and the person wakes to a dead session and no notice.
    - Test: early stop, then reload (`session.start`), advance the clock past the reset; assert a resume submit or a notice.
    - Confidence: medium.

11. A countdown or clear is cancelled by non-human, non-plugin prompts
    - Severity: Minor (fails safe, hurts liveness)
    - Where: hooks/register.tsx:863. `if (e.origin.kind !== 'plugin') await cancelCountdown($)`.
    - Scenario: a `task-notification`, `scheduled-trigger` or peer message during the 30 s countdown cancels it and parks the clear (`clearParked=true`). The handover is only "offered" and the away person's session keeps growing.
    - Test: countdown running, `prompt.submit` with origin 'task-notification'; assert the clear still goes ahead (or is deliberately cancelled and documented).
    - Confidence: medium.

12. install.sh hazards
    - Severity: Minor
    - Where: scripts/install.sh:7, :25, :36-42.
    - (a) The path written to `CLAUDE_CODE_PLUGIN_DIRS` is the script's own checkout. Installing from this worktree writes `.claude/worktrees/context-vigil-mod/...` into the account settings. When the worktree is removed or merged the plugin silently disappears. Running `uninstall` from another checkout reports "not installed" and leaves the stale entry (`grep -Fx` against a different path).
    - (b) `cat "$tmp" > "$file"` truncates and rewrites settings.json non-atomically. Claude Code or another session reading mid-write sees a truncated or corrupt settings file, and a concurrent write by Claude Code is lost or clobbered. There is no backup.
    - (c) Install, status and uninstall read only the account `settings.json`; the classic check misses a classic hook in `settings.local.json` or project settings.
    - Test: a bash test with a fake `$CLAUDE_CONFIG_DIR` (tmp_path). Install from path A, uninstall from path B, and assert it is reported. A concurrent-reader test is also possible.
    - Confidence: high on (a) and (c), medium on (b).

13. Event log is O(n^2) per session and hides a silent write failure
    - Severity: Minor
    - Where: hooks/register.tsx:106-120. The whole day text is cached in `dayText` and rewritten on every record. `$.fs.write(...).catch(() => {})` swallows write errors with no signal. The read-failure message fires on every event for a day file over 4 MiB (the `$.fs.read` limit) because the file is never read.
    - Test: 5k `log()` calls; assert linear cost and a visible notice on write failure.
    - Confidence: medium.

14. A mod-run clear queued behind work leaves `lastWait` and the countdown state stale
    - Severity: Minor
    - Where: hooks/register.tsx:442-457 vs :402-405. `retryTimer` can be overwritten without cancel: `tryClearInner` ends with `retryTimer = $.clock.after(...)` (:465), but a concurrent `scheduleClear` has replaced `retryTimer` during the awaits. Two retry loops can run at once (one is cancelled only if its handle is still referenced). This is harmless today only because `clearInFlight` and the missing-pending check cap it, but the draft-wait loop (2 s polling with `reloadSettings` plus `checkInterlock` file reads each tick) doubles.
    - Test: `scheduleClear` during an in-flight `tryClear`; assert a single timer and one poll per 2 s.
    - Confidence: low-medium.
