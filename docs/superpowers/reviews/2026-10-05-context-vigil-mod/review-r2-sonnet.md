# context-vigil-mod adversarial review, round 2 (sonnet)

Gates run: `claude plugin test` 285 pass; pytest 10 pass. No gate flags any item below.
Paths are relative to `plugins/context-vigil-mod/`.

1. Phone sessions get no notice, so the RC countdown and every "wait" are invisible on the phone
   - Severity: Important (the worst class, gated behind the opt-in RC "Yes")
   - Where: hooks/register.tsx:119-121 (`notify` = `ui.toast` + `ui.log` only), 357-398 (`tryClear`), 490-498 (`showNudge`); README "Remote Control" and "Phone sessions get the notice"
   - Failure: PROBES §1 and SMOKES #4 prove toast/log never reach the phone, and "Fix pending" was never implemented. A phone-only user who answered "Yes" gets no countdown. They are composing a reply longer than the 2-min holdback after their last sent message, nothing is visible to them, and the 30 s countdown ends in a `/clear` over the half-typed message. The README claims (phone notice, every wait shows a notice, countdown "Cancel") are false for the phone. The same applies to the nudge on the phone, to `pendingOffer`, and to the "resume failed ... your message was not sent: <text>" notice.
   - Test: shell test with `onPhone` + `rcAutoClear: 'yes'`. Assert that when the countdown starts (and for `showNudge` on a bridge origin) a `$.prompt.submit` plugin prompt or a slash-command `{text}` reply is emitted. Today only toast/log are asserted.
   - Confidence: high

2. Real human channels are classified as "agent", so a present person is treated as away
   - Severity: Important (unattended /clear on a present human)
   - Where: core/arming.ts:3-9 (`HUMAN` = composer/bridge/slack-ping only), tests/arming.test.ts:13 (codifies it)
   - Failure: the engine's own origin list (d.ts `PromptOrigin`) includes `channel` (a Slack/Telegram message relayed by an MCP server), `auto-continuation` ("user-initiated UI action") and `projects-relay`. A user chatting through a channel server is classified `agent`. That sets `lastAgentAt`, so the session reads as "working", and never sets `lastHumanAt`. With auto on and >30 min since the last composer prompt, the next threshold crossing hands over and `/clear`s in the middle of that chat. The spec does not list these origins either, so it is a spec hole as well.
   - Test: `classifyOrigin('channel')` must not be `agent`. At minimum, `record` of a `channel` prompt must not leave `mode()` at `auto`. Add a shell test: a channel prompt, then idle past the window with agent steps, then a threshold, expecting no unattended clear.
   - Confidence: medium (channel treated as a person is a judgement call, but classifying it as the working agent is the dangerous side)

3. A clear parked on the latch drains hours later with no freshness or presence re-check
   - Severity: Important
   - Where: hooks/register.tsx:436 (`checkLatch` -> `scheduleClear($, unattendedClear)`), with `tryClear` 357-398
   - Failure: `/vho` (attended, `unattendedClear=false`) writes its handover, then a StopFailure `rate_limit` latches. `tryClear` parks (`lastWait='latched'`, `clearParked`). The person returns at the reset and sends "continue". Turns run and the conversation moves on. The latch-lift timer (reset+1 s) or the next `session.measure` then calls `scheduleClear`. `fresh()` and `reusable()` are checked only in `startHandover`, never on this path. So `/clear` lands over a live, progressed conversation, or over the draft or message in flight, and injects an obsolete handover. The spec says a handover "waits for the latch", and the person's next message cancels only the `deferred` object, not a parked pending clear.
   - Test: pending `request` plus latch set; a human prompt plus a `turn.complete`; lift the latch. Expect no `command.run('clear')` (or at least `fresh()` re-checked).
   - Confidence: medium-high

4. An attended /vho or bar-"1" clear lands after the person has already sent a new message, and nothing preserves it
   - Severity: Minor (by design per test "a requested handover is attended by definition", but a data-loss edge)
   - Where: hooks/register.tsx:357-398; tests/shell-handover.test.tsx:178
   - Failure: after `/vho`, the person types a follow-up and presses Enter while the handover turn is still running. The box is empty again, so the draft guard passes. `tryClear` fires `/clear` mid-turn. Their message and any queued prompt are discarded with the old session, and unlike last light's `returnHeld` it is not re-sent. The smoke covered "delete the draft", not "send it".
   - Test: `/vho`; type a draft (guard waits); submit it as a composer prompt; assert the clear does not run (or the message is carried over as `followUp`).
   - Confidence: medium

5. Event log loses the `kind` of limit events
   - Severity: Minor
   - Where: core/eventlog.ts:8 (`{ ...fields, ts, session, kind }`); hooks/register.tsx:403, 416, 838 (`log($, 'limit.latched', { kind: l.kind, ... })`)
   - Failure: the window kind (`seven_day`/`spend_limit`) is silently overwritten by the event kind in `limit.latched`, `limit.cleared` and `limit.early_stop`. Dashboards and the side-by-side comparison cannot tell which window latched. The unit test only proves "fields never overwrite kind" and not that the info is kept under another name.
   - Test: `log` early stop with `kind:'seven_day'`; assert the record has a `window: 'seven_day'` (rename the field) and `kind: 'limit.early_stop'`.
   - Confidence: high

6. A stale or parked handover is injected into unrelated work on a later manual /clear
   - Severity: Minor
   - Where: hooks/register.tsx:686-718 (the inject at 718 happens even when `stale`), 461-466 (`hopResume` skip leaves the `limit` pending), `PENDING_KEEP_MS` 14 days
   - Failure: a threshold handover parked because the person came back, or a limit handover whose resume was skipped, stays in `$.store` under the session id. Hours or days of work later, the person's own `/clear` to start a different topic gets the old handover pushed in as `additionalContext` ("Handover from before the clear"). Only the auto-resume prompt is suppressed. A model asked to follow an obsolete "next step" can act on it.
   - Test: written at t0, turns run for 2 h, then manual `/clear`. Assert `additionalContext` carries no handover (or is marked stale), and that a skipped limit resume deletes its pending.
   - Confidence: medium (R1-10's test codifies the injection)

7. The limit-resume chain survives a session change
   - Severity: Minor
   - Where: hooks/register.tsx:215-231 (`resetCaches` never cancels `resumeChain`/`limitResume`), 663-677 (in-process `/resume`/fork rebinds `session` only)
   - Failure: an early stop in session A schedules the resume prompt. The person `/resume`s session B in the same process. `activity` is not reset, and `back` compares only `lastHumanAt > stoppedAt`. If the `/resume` command was observed that is true and it skips; but a fork/`--resume` through a path the hook does not see, or an observed `/resume` before the stop, makes the chain submit "continue the work; handover at <A's path>" into session B.
   - Test: early stop, then fire `classic.SessionStart` source `resume` without a human signal, then advance the clock past the reset. Expect no submit.
   - Confidence: low-medium

8. `awaiting` can be stranded by a hot reload, permanently blocking handovers
   - Severity: Minor
   - Where: hooks/register.tsx:135-146 (`submitSoon` timer), 623-655 (`session.start` does not reconcile `awaitingA`), 316-319
   - Failure: a reload between `update(awaitingA)` and the 0 ms submit timer drops the timer but keeps `awaiting` in `$.state` with `started:false` and no turn. Every later `/vho`, bar "1" or threshold now says "A handover is already in progress" forever, until a `/clear`. The tests cover a reload for a pending parked clear, not for awaiting.
   - Test: `startHandover`, a reload before the clock ticks, then `/vho`. Expect a new instruction (or awaiting cleared on session.start).
   - Confidence: medium

9. Timer-driven async work has no error handling, so failures are silent
   - Severity: Minor
   - Where: hooks/register.tsx:354, 397 (`void tryClear($)`), 406/539 (`checkLatch`, `maybeFireLastLight`), 619; 935 (`savePending` store.set rejects over 4 MiB after the file is written but before any notice)
   - Failure: any rejection (`$.store`, `$.fs.exists`, `$.prompt.read`, `$.process.run`) inside these `void` calls is an unhandled rejection. `retryTimer` is already null, so the handover sits pending with no notice and no further retry. In the tool hook, a store rejection leaves the model told "error", `awaiting` cleared, no pending and no user notice. The store is a single JSON file with a 4 MiB cap shared by settings, latch and every pending handover (the prune runs only at session start).
   - Test: make `$.store.get` reject once during `tryClear`; expect a notice and a retry. Make `store.set` reject in the tool hook; expect `handoverFailed`.
   - Confidence: medium

10. /vho says "Handing over..." when nothing happens
    - Severity: Minor
    - Where: hooks/register.tsx:306-308 (`if (standDown) return`), 900-905; and 595-599 (last light disarms even if `startHandover` bails)
    - Failure: with classic active, `/vho` and the bar's "1" return "📜 Handing over…" and do nothing, silently. The only notice was the one-off standdown line at session start. Last light logs `last_light.fired` and sets `lastLightArmed=false` before `startHandover`. If that returns early (standDown, or the in-flight notice) the period's last light is spent with no handover written.
    - Test: `standDown` on, then `/vho` must notify (`classic`).
    - Confidence: high

11. Bar digit capture, and the bar's buttons are not recorded as presence
    - Severity: Minor
    - Where: hooks/register.tsx:500-505 (`barChoice` never calls `observe`), 978-982; compare 959 (the cancel button does)
    - Failure: (a) the person returns from a long idle and presses `2`/`0` to dismiss the bar while the agent is working: no signal is recorded, so `mode` stays `auto` and the next step's threshold hands over and clears while they are watching. (b) With the bar up, an empty-box first digit ("1. fix X") is swallowed and starts a handover that clears the session. Documented in the spec, but there is no draft to protect since the digit was consumed.
    - Test: `barChoice('later')` then assert `activity.lastHumanAt` moved (`observe human-command`).
    - Confidence: medium

12. Early stop acts regardless of presence and in-flight work
    - Severity: Minor
    - Where: hooks/register.tsx:836-842, 306-330
    - Failure: at 95% weekly an actively-typing person gets a mod prompt injected, with no draft or attended check. If a handover is already in flight, `startHandover` returns (in-progress) but the window key is already marked fired and `scheduleResume` still runs. The result is a "resume" with `path:null` and no limit handover. Every running session on the account fires its own handover turn at the same moment, spending tokens right at the limit.
    - Test: threshold handover awaiting, then an early-stop measure; assert the limit handover is not silently dropped.
    - Confidence: medium

13. install.sh bakes a checkout path, and writes non-atomically
    - Severity: Minor
    - Where: scripts/install.sh:7-8, 19-26, 36-37
    - Failure: running it from the worktree (`.claude/worktrees/context-vigil-mod`, as the README shows) writes that path into the account-wide `CLAUDE_CODE_PLUGIN_DIRS`. Deleting the worktree leaves a dangling entry. Installing later from the main checkout adds a second copy of the same plugin, and two instances of the hooks would each try to clear. `uninstall` from another checkout reports "not installed". `cat "$tmp" > "$file"` truncates then writes in place, so a concurrent Claude Code settings write or a crash mid-write corrupts the user's `settings.json`; no backup is kept.
    - Test: pytest: install from a copy at path A, then from path B (assert there is no duplicate plugin or a clear warning); simulate a failure mid-cat and assert the original is intact.
    - Confidence: medium

14. The first-RC question stalls the unattended agent, and a dismissed card suppresses the ask
    - Severity: Minor
    - Where: hooks/register.tsx:189-198, 868-898
    - Failure: when auto first arms on the phone, the mod submits a prompt telling the model to call AskUserQuestion. The agent (the very autonomous run auto mode serves) blocks on a dialog the absent person must answer. If the card is dismissed, `setupRun` stays non-null (cleared only by completion or a reload), so `maybeAskRc` returns early. `rcAsked` is also never reset, so RC stays `unanswered` for the rest of the process.
    - Test: dismiss the card (an AskUserQuestion with no answers); assert `setupRun` is cleared or the RC ask is re-armed.
    - Confidence: medium

15. Headless/SDK or dialog states blind the draft guard; `sdk` pins "unattended" for good
    - Severity: Important (low confidence)
    - Where: core/arming.ts:21-31 (`headless` is sticky), hooks/register.tsx:372-376; d.ts `prompt.read` "{ text: '' } where the session draws no box"
    - Failure: an SDK/Desktop host stamps its prompts `sdk` (d.ts: "not typed at a terminal"). If a person is typing in such a host, `headless` is sticky and `mode` is never `attended`, and `$.prompt.read()` always returns empty. Auto mode then clears over a present person with no guard at all. In the terminal, a draft under an open dialog may also read as empty.
    - Test: an `sdk` prompt followed by a human `composer` prompt; decide whether `headless` should clear on a later human origin. Assert the clear is refused while any human origin is recent.
    - Confidence: low

16. The event log can be clobbered or lost
    - Severity: Minor
    - Where: hooks/register.tsx:93-116
    - Failure: the whole day file is rewritten from an in-memory copy. Two processes that share one session id (`--resume` in two terminals) overwrite each other's lines. A crash mid-write truncates the log. `$.fs.write(...).catch(() => {})` swallows write failures, while `dayText` keeps the text, so later events appear to succeed. A day file over 4 MiB is "unreadable" and stops logging, with an `ui.log` each time. The cost grows O(n^2) in hook latency (`await log` sits in hot hooks).
    - Test: two interleaved processes on one session id should produce both lines; a write rejection should be reported once.
    - Confidence: low-medium

17. `returnHeld` text is lost if the hook reloads while the return question is open
    - Severity: Minor
    - Where: hooks/register.tsx:602-620, 738-744
    - Failure: the held prompt is dropped (`{drop}`) and kept only in the module variable `returnHeld`. A hot reload re-evaluates the module, so `returnHeld` is reset and the pending `ask` continuation (old module) re-sends nothing. The person's message is gone, contrary to the spec's "never lost". An unanswered `$.ui.ask` also holds every later prompt forever.
    - Test: held prompt, a reload, then answer `ask`; assert the text is re-sent or the held text is persisted in `$.state`.
    - Confidence: low-medium
