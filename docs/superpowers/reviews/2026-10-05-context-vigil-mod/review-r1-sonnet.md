# context-vigil-mod adversarial review, round 1 (sonnet)

Gates run (read-only): `claude plugin test` 244 pass / 0 fail; typecheck clean; pytest tests/context_vigil_mod 6 passed. Every finding below is therefore a gap the suite does not catch. Paths are relative to plugins/context-vigil-mod unless noted. "register" = hooks/register.tsx.

## Critical

1. A stale pending handover is reused after a process restart, so a clear lands on days-old state and loses the intervening work
   - Severity: Critical. Confidence: high.
   - Location: core/handover.ts:24-27 (`reusable`), register:515-519 (session.start restores `stored`), register:248-252 (`startHandover` reuse branch).
   - `reusable()` returns true whenever `lastApiAt === null`. `lastApiA` lives in `$.state`, which a process restart does not keep. session.start restores `pending:<session>` from `$.store` into `pendingA`, so after a restart `lastApi` is null and the stale pending counts as "no turn since".
   - Failure scenario:
     1. An unattended threshold handover is written, the person returns, and the clear is skipped (`clear.skipped`). The pending stays in `$.store`.
     2. The person quits, then `claude --resume <id>` a day later, so the same session id comes back.
     3. They type `/vho` (or auto mode crosses the next threshold with `lastApi` still null).
     4. `startHandover` takes the reuse branch. It does not write a fresh handover. It clears at once and injects the day-old markdown plus "Start with its next step", so all work since is lost from context.
   - Test: the shell test seeds `$.store['pending:<id>']` with `{reason:'request', createdAt: now-86400000}`, runs session.start, then runs `/vho`. Assert that no clear is scheduled and a handover instruction is submitted. The current code clears. Also add a core test: `reusable(p, null)` with an old `createdAt` must be false.

## Important

2. A stale or declined pending handover is injected, and a resume prompt auto-submitted, on any later manual `/clear`
   - Severity: Important (an unattended action while a human is present). Confidence: high.
   - Location: register:546-575 (classic.SessionStart, clear branch), with register:376-385 (`cancelCountdown`) and register:290-296 (skip attended).
   - The clear branch consumes `pendingKey(session)` for any `source:'clear'`. It does not check that the mod ran the clear or that the pending is fresh. After any of these, the pending sits in `$.store`: a countdown Cancel, an attended skip, a `rc-declined` or `latched` park, or a never-consumed last-light pending (finding 3).
   - Failure scenario: the person deliberately cancelled the clear. Hours later they type `/clear` to start something fresh. The mod injects the old handover as `additionalContext` and, 500 ms later, submits "Resume from the handover… Start with its next step" (`pending.resume` is true). The model then acts on abandoned work unprompted.
   - A related breach of spec §5 ("while latched, never submits"): this resume and follow-up submit, at 568-573, never checks the latch or `standDown`.
   - Test: seed a pending with `createdAt` 3 h old and `resume:true`, fire classic.SessionStart `{source:'clear'}` with no mod-run clear in flight. Assert nothing is submitted (or that the person is asked) and that the stale handover is not injected. A second test does the same with the latch set and asserts no submit.

3. A last-light pending handover is never cleared when the person returns inside the cache window, which permanently disables last light and leaks the store key
   - Severity: Important. Confidence: high.
   - Location: register:590-604 (`prompt.submit`), core/last-light.ts:37-39 (`holdOnReturn`), core/last-light.ts:22-31 (`shouldFire` `pending`).
   - `holdOnReturn` only runs `askReturn` (the one place `savePending(null)` is called for this path) when `now >= lastApi + 1h`. A human prompt before expiry (the fire is at +55 min) passes straight through and the `reason:'last_light'` pending stays in `$.state` and `$.store`.
   - Failure scenario:
     1. Last light fires at +55 min and writes a handover.
     2. The person returns at +58 min and carries on. The pending stays.
     3. Every later idle period gets `shouldFire` -> `pending`, so last light never fires again for the session.
     4. The leaked `pending:<id>` key survives restarts. A restart plus `/vho` also hits finding 1, and a manual `/clear` hits finding 2.
   - Test: after a last-light fire, send a composer prompt at `lastApi+58min`. Assert the pending is cleared (or marked consumed). Then advance 1 h of idle with a new turn and assert last light fires again.

4. Limit resume prompt is submitted unconditionally after the reset, into whatever the person is doing
   - Severity: Important. Confidence: medium-high.
   - Location: register:358-374 (`scheduleResume`), 669-675.
   - At reset + 5 min the mod calls `$.prompt.submit(limitResumeText)` with no check of mode, draft, a running turn, or `standDown`. Nothing cancels it on `/clear`, on the person continuing to work, or on `settings.limits` being turned off. The spec says "if the session is still open", not "regardless of what is happening".
   - Failure scenario: the early stop fires at 95% seven_day, the person keeps working manually for hours, and at reset + 5 min a plugin prompt "usage limit has reset. Continue the work" lands mid-conversation or mid-typing, starting a model turn.
   - Two windows over the trigger (seven_day and spend_limit) give two early stops, two `scheduleResume` jobs (`limitResume` is overwritten), and two resume prompts. `startHandover` can also defer or no-op while `scheduleResume` still runs, giving "(no file)".
   - Test: fire an early stop, then send a composer prompt and advance the clock past reset + 5 min. Assert no plugin submit while attended or a draft is present. Add: two windows over the trigger give one resume. Add: a deferred or standDown handover gives no "(no file)" resume.

5. `vigil_handover` called without an `awaiting` request defaults to an attended-style clear that cannot be refused
   - Severity: Important. Confidence: medium-high.
   - Location: register:739-741 (`reason ?? 'request'`, `resume ?? true`), 762 (`scheduleClear($, reason === 'threshold')`).
   - The tool is registered for the whole session. If `awaiting` is null the handler treats the call as the person's request: `scheduleClear($, false)` means no attended re-check, no RC countdown, no holdback. Only the draft and latch guards apply.
   - Failure scenario, two routes:
     - Model-initiated: a prompt-injected file or webpage makes the model call the tool. The next tick runs `/clear` on the live session.
     - Duplicate instruction: the "attempts" duplicate (finding 6) means a second instruction is answered after `awaiting` was cleared by the first call. That call also lands in the `request`/`resume:true` branch and schedules a second clear plus a resume.
   - Test: with `awaitingA` null and an attended mode, fire tool.call on TOOL_FULL. Assert no clear is scheduled and a notice says nothing was requested (return `{result: 'not requested'}`).

6. `turn.complete` retry logic can count the turn in flight as a failed attempt and resubmit a duplicate instruction
   - Severity: Important. Confidence: medium (depends on when the engine fires `turn.complete` for queued submits).
   - Location: register:109-120, 639-649.
   - `submitInstruction` marks `started:true` as soon as `$.prompt.submit` resolves. The unattended trigger comes from `session.measure` mid-run, when a turn is usually still in progress. The submit is queued. That in-flight turn's `turn.complete` then sees `started` and burns attempt 1: it re-submits a second instruction. A human turn completing between the submit and the model's handover turn does the same.
   - Failure scenario: two handover instructions queued, two tool calls, two `handoverCount` bumps, and the second call goes down finding 5's route. If the first call's turn is slow, "tool-not-called" fires as a false failure.
   - Test: submit the instruction, fire `turn.complete` for a turn that began before the submit, then the real tool call. Assert exactly one instruction and exactly one pending. Needs `turn.start` or turn ids to tell the turns apart.

7. Remote Control safety net is invisible on the phone, so the "30 s countdown with Cancel" does not exist for the person it protects
   - Severity: Important. Confidence: high (PROBES §1 documents it; the mitigation is not implemented).
   - Location: register:93-95 (`notify`), 321-322, 766-780 (the countdown band); README "Remote Control".
   - PROBES §1 proved toast, `ui.log` and the band do not reach the phone. The README and setup text still promise "send anything to cancel" and "a 30-second countdown runs first". With `rcAutoClear:'yes'`, the phone user gets no warning and a `/clear` fires 30 s later, mid-message if they are typing (which is exactly why the countdown exists). The PROBES decision ("also send as a plugin prompt") is marked pending and is not in the code.
   - The unattended threshold nudge on the phone (`showNudge` -> `notify`) is likewise unseen.
   - Test (shell): `bridge` origin human prompt, auto armed, rcAutoClear yes. Assert a phone-reachable notice (a `$.prompt.submit` plugin message, or a slash-command reply) is sent when the countdown starts. Currently only `ui.toast` and `ui.log` are called.

8. Event log: concurrent first-log race drops lines, and a failed read truncates the whole day file
   - Severity: Important. Confidence: medium (race) / high (truncation).
   - Location: register:84-90.
   - `if (dayText[path] === undefined) dayText[path] = await $.fs.read(...)` is not atomic. Two hooks logging concurrently right after `resetCaches` (every clear and every session start empties `dayText`) both see `undefined`. Each awaits the read, each assigns the stale file text, and the second assignment erases the first's appended line before it is written. Lost audit events (`clear`, `resume`) can leave the dashboard comparison wrong.
   - `.catch(() => '')` treats any read failure as an empty file. The spec notes `$.fs.read` refuses files over 4 MiB, so the next write replaces the whole day file with one line. The `fs.write` failure is also swallowed (`.catch(() => {})`), so a full disk or a bad path loses events silently.
   - Test: call `log` twice without awaiting between them, right after a reset, with the mock fs returning an existing file. Assert both lines persist. Make `fs.read` reject and assert the existing content is not overwritten.

9. Subagent `turn.complete` refreshes `lastApiA`, so last light schedules from, and the return-hold uses, a time that is not the main cache's last write
   - Severity: Important. Confidence: medium.
   - Location: register:630-651 (`lastApiA` and `scheduleLastLight` run for every `turn.complete`, including `e.agentId !== undefined`). PROBES §11 says subagents write a different 5m bucket.
   - Failure scenario: the main thread idles at T. A subagent's last turn completes at T+30 min. Last light fires at T+85 min, 25 min after the main 1-hour cache expired. `cacheIsOneHour` then reads the transcript tail and sees the old 1h write, so it passes and the handover instruction warms a cold cache: the exact expensive error last light exists to avoid. `holdOnReturn` has the same skew.
   - Test: `turn.complete` with `agentId:'x'` at T+30 min must not move `lastApiA` or the timer. Assert `scheduleLastLight` is only re-armed from main-thread turns.

10. A draft-waiting clear lands on the message the person just sent
    - Severity: Important. Confidence: medium.
    - Location: register:284-324, 590-604; the draft recheck loop at 316-323.
    - For attended (`/vho`, bar `1`) clears, the 2 s draft recheck keeps running. If the person types a follow-up (draft present, clear waits), then sends it, the draft empties, and within 2 s the clear fires. The turn that was just started on their prompt is cut and the message is lost from the fresh session. Only `cancelCountdown` runs on a human `prompt.submit`, and only when a countdown is up.
    - Test: `startHandover` request, handover written, draft "abc" present (wait), then composer `prompt.submit` plus empty draft. Assert the clear is not run (the clear should wait for the turn to end, or re-ask).

11. The interlock and the install check only see the account-level `settings.json`
    - Severity: Important. Confidence: medium (classic's real hook command form is not in this branch to check against).
    - Location: register:216-226, scripts/install.sh:28, core/interlock.ts:4.
    - The check looks at `$root/settings.json` only. Classic hooks in a repo `.claude/settings.json` or `settings.local.json`, or classic installed as a plugin, are not seen, so the mod runs in addition to classic. Both would then clear/inject, which is the failure the interlock exists to prevent.
    - The regex requires a closing quote right after `context-vigil` (`/scripts/context-vigil"\s+hook\s`). An unquoted or differently quoted command (a path with no spaces is commonly stored unquoted) never matches, in TS or in bash. Only the fixture string in the tests proves it.
    - Test: `classicHooksInstalled` with an unquoted command and with a project-level settings fixture. The shell test reads the repo settings.

12. Post-compaction, `lastNudged` and `baselinePct` are never lowered, so nudges and auto handovers go silent
    - Severity: Important. Confidence: medium.
    - Location: register:660-692, core/handover.ts:4-15.
    - `lastNudgedA` is reset only on `/clear`. If `/compact` or autocompact drops context from 60% to 15%, `nextThreshold` returns null until pct > `lastNudged` + step. Then the first 35% crossing after the compaction never nudges. `baselineA` holds the first reading, so with the pre-compact baseline `grownEnough` is false and an auto threshold handover is held back for the rest of the session.
    - Test: measure 50 (nudge, `lastNudged`=50), measure 18, measure 36. Expect a nudge; currently none. Expect the baseline to be reset when pct falls by more than a step.

13. Sticky `headless` makes a session permanently "unattended"
    - Severity: Important. Confidence: low-medium (depends on which origins the IDE and desktop front-ends send).
    - Location: core/arming.ts:28, 41.
    - `headless: a.headless || who === 'headless'` is never cleared. A session that ever receives one `sdk`-origin prompt is never `attended`, even when a person then types at `composer` or `bridge`. If a front-end that drives the session through the SDK also tags human prompts `sdk`, auto mode clears under a human.
    - Test: `record` an `sdk` prompt, then a `composer` prompt. Expect `mode` to be `attended`; currently `auto` or `idle`.

14. Settings are cached per process and written whole, so concurrent sessions clobber each other, and "auto off" does not stop other live sessions
    - Severity: Important. Confidence: medium.
    - Location: register:213, 710-712.
    - `settings` is read once at session start. Session B's `/vsetup auto` Off changes nothing in session A, which keeps clearing unattended until it restarts. A's next `/vsetup` or RC answer calls `$.store.set(STORE_KEY, settings)` with A's stale object and reverts B's changes (for example `rcAutoClear` back to `unanswered`, or auto back On).
    - Test: bind two sessions on one store. B sets `auto:false`. A runs a setup answer. Assert the stored `auto` stays false (merge the changed keys, don't overwrite) and that A re-reads settings before an unattended action.

## Minor

15. Deferred handover is drained with no re-validation
    - Severity: Minor. Confidence: medium.
    - Location: register:345-349.
    - `deferredA` is replayed when the latch lifts, whatever it is by then. A `threshold` deferral, hours later, submits an instruction into a session the person may now be using. A `limit` or `last_light` deferral replays well after its purpose is gone (a last-light handover on a cache that went cold).
    - Test: defer under a latch, advance past the reset with the human attended, and assert nothing is submitted.

16. Early-stop is "once per window" in the spec but "once per process" in the code
    - Severity: Minor. Confidence: high.
    - Location: register:56, 668-675.
    - `firedEarlyStops` is a module variable. Every new session (and every hot reload) with seven_day >= 95% starts a handover and a resume timer immediately, even with the person present. This contradicts the spec's "once per window (keyed on resetsAt)". README says "marks per running session", so the README and spec disagree with each other too.
    - Test: two `bindSession`s with the same limits fixture. Expect one early stop per window per account or document the per-session behaviour.

17. `install.sh` hazards
    - Severity: Minor. Confidence: medium-high.
    - Location: scripts/install.sh:11-12, 18-23.
    - If `settings.json` is a symlink (dotfiles-managed), `mv "$tmp" "$file"` replaces the link with a regular file and breaks the dotfile.
    - `mktemp` gives mode 0600, so the rewritten file's permissions change from the original.
    - A leftover `.settings.XXXXXX` remains on a jq failure (no trap), and `set -e` aborts after `echo '{}' >` has already created a settings file when `jq` is missing (the check comes after the create).
    - `uninstall` on a settings file without `.env` adds `"env": {}`. Path matching is exact string, so installing from a symlinked or worktree path then uninstalling from another leaves the entry silently. A worktree path in the user's global settings dangles when the worktree is removed.
    - Test: pytest cases with `settings.json` as a symlink (assert the link is preserved), with mode 0644 (assert mode kept), invalid JSON (assert the file is untouched and no temp files are left), and jq absent (PATH stripped; assert no file created).

18. Last-light TTL probe reads only the last 64 KiB of the transcript
    - Severity: Minor. Confidence: medium.
    - Location: core/cache-ttl.ts:9.
    - One large tool result row can push the latest `cache_creation` out of the window. The answer is then `unknown` and last light silently never fires (only a `last_light.skip` log line), with no person-visible notice. The first byte of the tail may also cut a row mid-object, which is harmless for the regex but means the answer is only as good as the last few rows.
    - Test: a fixture whose final row is >64 KiB. Expect a deliberate result (widen once, or tell the person), not a silent skip.

19. Duplicate or racing handover requests
    - Severity: Minor. Confidence: medium.
    - Location: register:239-257.
    - `startHandover` does not guard against an `awaiting` already in progress. A double `/vho`, or the bar `1` followed by a threshold crossing, submits two instructions (see findings 5 and 6).
    - Test: two `/vho` in a row. Expect one instruction.

20. `limit_windows` multi-select with nothing picked stores `[]` and silently disables early stop
    - Severity: Minor. Confidence: medium.
    - Location: core/setup.ts:162-167, core/settings.ts:33-36.
    - An empty answer string is applied as `limitWindows = []`, so `limits:true` with no windows watched protects nothing and nothing says so.
    - Test: `applyAnswers` with `''` for `limit_windows` should retell, not store an empty list.

21. First-RC question blocks an unattended session
    - Severity: Minor. Confidence: low-medium.
    - Location: register:138, 156-163.
    - The question is submitted as a plugin prompt on the 'arm' transition, which means the person is away by definition, and AskUserQuestion waits for an answer. The unattended run stalls until they return. This is spec-sanctioned; the failure is a hung auto session with no timeout.
    - Test: arm in a bridge session with `rcAutoClear:'unanswered'`. Assert a timeout or non-blocking fallback exists.

22. Held last-light prompt on the phone may never be answered
    - Severity: Minor. Confidence: low-medium.
    - Location: register:491-503, 595-599.
    - `$.ui.ask` on the phone is "pending" in PROBES §6, and the drop notice does not reach the phone (§1). If `ui.ask` never resolves there, the person's phone message is dropped with no visible notice and no timeout. The `.catch` covers rejection, not a hang.
    - Test: a `bridge` prompt after cache expiry with `ui.ask` never resolving. Assert a timeout path re-sends the held text.

## Test gaps worth adding
- No shell test covers a restart (stored pending with null `lastApi`), a manual `/clear` that consumes a stale pending, or last-light return before the cache expires (findings 1-3).
- No test checks that a late `scheduleResume` is suppressed by attendance (4).
- `tests/context_vigil_mod/test_install.py` has no symlink, mode, malformed-JSON or missing-jq case (17).
