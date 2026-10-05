# Ratification of round-2 findings — context-vigil-mod

Ruling on behalf of the absent owner. Read-only on code. Target `feat/context-vigil-mod` HEAD ba4f884,
`plugins/context-vigil-mod/` (`register` = `hooks/register.tsx`). Inputs: `verdict-r2.md` (R2-01..R2-19),
the binding `ratify-r1.md`, the engine typings (`PromptOrigin` union, `command.run` doc), PROBES/SMOKES/README,
spec §2/§3/§5. Every line cited below was read.

Standing intent applied, as in round 1:
1. An unattended `/clear` never lands on a present human or a half-typed message.
2. When in doubt, don't clear; prefer a visible notice.
3. Defaults stand: 35 % / 30 min / 30 s.
4. Merge tonight: minimal, safe fixes; anything bigger goes to a follow-up card if shipping without it is safe.

## One line per id

| id | ruling |
|---|---|
| R2-01 | APPROVE WITH CHANGE — the **R1-09-strict** variant, plus freshness: at lift a parked clear runs only if `settings.auto && mode !== 'attended' && fresh(pending)`, and then as *unattended*; otherwise it becomes an offer with a notice. Any human prompt/command while parked turns it into an offer. The shell-limits test at :34 is rewritten (its auto-Off expectation was never the documented rule). |
| R2-02 | DEFER — timing architecture (13 positive-`clear` tests across 5 files, plus turn-never-ends fallbacks). Safe to ship: the window is the seconds-long tail of the instruction turn after ≥ 30 min away; the handover is written and resumed either way. Follow-up card; two PROBES entries required tonight (see detail). |
| R2-03 | APPROVE WITH CHANGE — expire a lost `awaiting` after 10 min **only when the agent is also idle** (`now - lastAgentAt ≥ WORKING_MS`), so an instruction legitimately queued behind a long turn is not declared lost and re-submitted. |
| R2-04 | APPROVE as directed. |
| R2-05 | APPROVE as directed (restores spec §4). |
| R2-06 | APPROVE — disarm-only for both `channel` and `auto-continuation` (exactly the R1-24 mechanics). Full-human promotion REJECTED for this merge, with reasons. Spec §2 bullet + README line 34 widen by a clause each. |
| R2-07 | APPROVE as directed. |
| R2-08 | APPROVE as directed (new voice line `clearSkippedAutoOff`; wording not binding). |
| R2-09 | APPROVE as directed. |
| R2-10 | APPROVE as directed, **standalone** (R2-02 is deferred): test it with a plain held-promise gate on `command.run('clear')` in the world, not the `turn.complete`-coupled gate. |
| R2-11 | APPROVE WITH CHANGE — whichever answer (old closure or new ask) acts first *consumes* `returnHeldA` atomically; a stale answer that finds it empty does nothing. Free text under "Other" = Carry on with the typed text appended (never a clear on an ambiguous answer). |
| R2-12 | APPROVE as directed. |
| R2-13 | APPROVE as directed. |
| R2-14 | APPROVE as directed. |
| R2-15 | APPROVE as directed. |
| R2-16 | APPROVE as directed. |
| R2-17 | APPROVE WITH CHANGE — do **not** delete the skipped `limit` pending; instead notify on every manual-`/clear` injection that carries no automatic resume. The named handover stays `/clear`-able, as every notice promises. |
| R2-18 | APPROVE — README sentence required; the `$.state` `rcAsked` persistence is optional tonight (fixer's call; a `/clear` re-asking is acceptable). |
| R2-19 | APPROVE — rewrite the comment, keep the call (it is the hook the deferred R1-07 half will use). |

---

## R2-01 — A clear parked on the latch is re-scheduled with no freshness or presence re-check

**Ruling: APPROVE WITH CHANGE — the strict variant, not the minimal one.**

Why strict, when the owner asked for minimal:

- **The documented rule already is the strict one.** Spec §5:344 and README:58 (both landed under R1-09)
  say: "A handover asked for or due while the latch is set waits for it; your next message cancels it. When
  the latch lifts it runs only if auto mode is on and you are still away, as an unattended handover …;
  otherwise a notice tells you it was not run." A parked clear *is* a handover asked for while latched — the
  latch simply landed after the write instead of before it. The minimal fix would leave the only path that
  contradicts the shipped docs in place.
- **The minimal fix does not keep the existing test green either.** In shell-limits.test.tsx:34 no
  `turn.complete` ever fires, so `lastApiA` is null and `fresh()` falls back to `now`; an hour later
  `now ≤ createdAt + 60 s` is false. The verdict's "today's test stays green" is wrong — that test flips
  under *both* fixes, so the cost the orchestrator feared is paid regardless. Pay it for the right rule.
- **Intent #1 and #2.** With auto Off (the default) a person who typed `/vho`, hit the limit and walked
  away gets, an hour later, a notice and an offer — not a clear they can no longer be assumed to want.
  Nothing is lost: the file is on disk, the pending stays, a manual `/clear` injects it and (no turn having
  run) auto-resumes under R1-10. With auto On and the person still away, it clears through the full gate
  (attended re-check, draft, RC countdown/holdback) exactly as the deferred sibling does.
- Code size is the same as the minimal fix: one condition in `checkLatch`, one block in `observe`.

**Behaviour to implement.**

1. **Drop on human return** (`observe`, beside the R1-09 `deferredA` block): when the signal is a human
   `prompt` or a `human-command` and `clearParked && lastWait === 'latched'`: set `lastWait = null` (keep
   `clearParked = true` — the clear is now an *offer*, which `checkLatch` must not touch: "one parked for a
   cancelled countdown or a refusal stays put"), `notify($, V.pendingOffer(pending.path))`,
   `log('guard.wait', { reason: 'parked-dropped' })`. Pending and file untouched. Edits/drafts do not drop it
   (an explicit act does — same as R1-09).
2. **Re-validate at lift** (`checkLatch`, last line): replace
   `if (clearParked && lastWait === 'latched' && pending) scheduleClear($, unattendedClear)` with:
   - `pending = await read($, pendingA)`; if `!clearParked || lastWait !== 'latched' || !pending` → return.
   - `await reloadSettings($)` (already done above when `deferred` is set; do it here too).
   - if `settings.auto && mode(activity, now, settings) !== 'attended' && fresh(pending, await read($, lastApiA), now)`
     → `scheduleClear($, true)` (unattended, whatever the original reason; `request` included — R1-09 §3).
   - else → `lastWait = null` (offer), `notify($, V.pendingOffer(pending.path))`,
     `log('guard.wait', { reason: 'parked-dropped', cause: !settings.auto ? 'auto-off' : mode === 'attended' ? 'attended' : 'stale' })`.
   `fresh` here means "no main turn since the write" — `lastApiA` does not move while a session is blocked on
   a limit, so an hour's wait alone never makes it stale; a `scheduled-trigger`/`peer` turn in between does,
   and then clearing over an advanced conversation is exactly the R1-04 wrong.

**Tests.** Rewrite shell-limits:34 as three cases: (a) as today's setup, auto Off, lift → `w.commands` has no
`clear`, `pendingOffer` notice, `guard.wait parked-dropped`; (b) `settings.auto = true`, terminal, no human in
between, lift → `clear` present and the resume submit follows; (c) auto On, `human('carry on')` while parked →
`pendingOffer` at once, and the lift re-schedules nothing. Variant (d): auto On, a `turn.complete` 5 min after
the park (no human) → offer with `cause: 'stale'`, no clear.

**Spec §5** (line ~344) — append one sentence: "This holds whether the latch landed before or after the
handover file was written: a clear the latch parked follows the same rule." **README:58** — same sentence.

---

## R2-02 — The clear gate is evaluated when the clear is queued, not when it runs

**Ruling: DEFER to a follow-up card.** Two PROBES entries are required tonight.

The finding is real: `tryClear` runs 0 ms after the tool call, mid-turn; the engine queues `command.run('clear')`
"once the session is idle" (typings :2965), so the attended re-check and draft read are stale by the length of
the model's reply to the tool result. But the verdict's own fix is a change of the clear's timing architecture:

- it moves the attempt to the instruction turn's `turn.complete` and needs fallbacks for every way a turn can
  fail to complete (StopFailure rate limit — today's shell-limits flow never raises `turn.complete`; `isAborted`;
  a hot reload dropping the module flag), or the written handover is silently never cleared/offered;
- it touches 13 positive `expect(w.commands).toContain('clear')` sites across shell-handover (8), shell-limits
  (2), shell-bar, shell-last-light and shell-setup, each needing a `turn.complete` raised before the expectation,
  plus a new world gate. That is not a tonight fix for a 285-test suite that must stay green.

No smaller safe alternative exists from inside the mod: there is no `command.cancel`, the hook cannot see when
the queued command executes, and `tryClear` already reads draft and mode milliseconds before `command.run`. A
poll-until-turn-ends variant has the same turn-never-ends failure modes with less to show for it.

**Why shipping without it is safe enough tonight.** The exposure is per *unattended* clear only (a requested one
is attended by definition — spec §2, R1 S10 rejected), so the person has been away ≥ 30 min and must return in
the few-second tail of the instruction turn. If they do, the handover has been written and is injected and
resumed in the new session (continuity kept); a typed-but-unsent draft is in the composer, which `/clear` is not
known to wipe. The harm is bounded and recoverable; the architectural fix is not a tonight change.

**Required tonight (docs only).** Add to PROBES.md two open probes, marked unprobed: (1) does a prompt queued
behind a mod-run `/clear` land in the new session, get dropped, or run first? (2) does a half-typed draft in the
composer survive a mod-run `/clear`? Record the answers when the follow-up card runs them.

**Follow-up card scope.** The verdict's direction (set `clearAfterTurn = { unattended, turnId }` in the `TOOL_FULL`
handler; `scheduleClear` from the matching main `turn.complete`; keep the direct path for `reusable` and reload),
with: StopFailure/`isAborted` converting the pending clear into a parked offer with a notice; a 10-min safety timer
that falls back to today's `scheduleClear` if no turn end arrives; the world's held `command.run` gate. R2-10's
`clearInFlight` flag (landed tonight) is reused.

---

## R2-03 — `awaiting` never expires

**Ruling: APPROVE WITH CHANGE.**

The verdict's "older than ~10 min = lost" has a false positive: an instruction queued behind a long running turn
(`started` stays false until the submit resolves, which is when its turn *starts*) is alive at 10 min, and a
`/vho` then would re-submit — two instructions, two tool calls, the R1-11 problem back. Add one condition:

- `Awaiting.since: number` (set at `startHandover`). In `startHandover`, an existing `awaiting` is treated as
  lost only when `now - awaiting.since ≥ 10 min` **and** `activity.lastAgentAt === null || now - activity.lastAgentAt ≥ WORKING_MS`
  (no agent step for 2 min — nothing is running, so a queued instruction would have started). Then as the
  verdict: null it, notice, `guard.wait { reason: 'awaiting-expired' }`, proceed.
- Otherwise the R1-11 refusal stands (`handoverInProgress`).

Tests as the verdict, plus: `/vho`, no `turn.start`, advance 10 min **with** `tool.call(Bash)` steps every minute,
`/vho` → still one instruction (`handoverInProgress`). PROBES entry for `turn.start.e.text` equality as directed.
No doc change.

---

## R2-06 — `channel` and `auto-continuation` origins are classified `agent`

**Ruling: APPROVE the disarm-only direction for both; REJECT promoting `channel` to full human for this merge.**

What each origin is, from the engine typings (`PromptOrigin`, `.claude-plugin/types/claude-code/index.d.ts` ~8420-8447):

- `channel` — "A message from a channel an MCP server relays (Slack, Telegram)", with the server's name. A
  person is typing, but the engine does not say it is *you*: contrast `slack-ping`, "The session's **owner**
  pinging it from Slack", which is why `slack-ping` is in `HUMAN` and `channel` must not be. Any channel member,
  or a bot in the channel, produces this origin.
- `auto-continuation` — "A programmatic follow-up to a user's UI action, user-initiated but not typed this turn."
  Evidence that you are at a UI; the prompt text is the engine's, not yours.

Both are presence evidence and neither is *your message*. That is precisely the R1-24 shape, so the same ruling:

- `core/arming.ts record()`, case `'prompt'`: the `unclassified` early return becomes a set —
  `DISARM_ONLY = new Set(['unclassified', 'channel', 'auto-continuation'])`; `if (DISARM_ONLY.has(s.origin)) return { ...a, lastHumanAt: s.at }`.
  `classifyOrigin` unchanged (still `'agent'`), so: no `savePhoneFacts`, `lastHumanOrigin`/`lastBridgeAt`
  untouched, `rearm` (last light) ignores it, `holdOnReturn` ignores it, `ttlInfoDismissedA` untouched.
  `command.run` is unaffected (these are prompt origins).

Why not full human for `channel`: (1) it would set `lastHumanOrigin = 'channel'`, turning `onPhone` false after a
`bridge` prompt — a relayed Slack line would strip the RC countdown/holdback from the next unattended clear for
a person who *is* on the phone; (2) §4's return hold would hold a Slack-relayed message and ask a question the
channel user never sees (the ask is terminal/phone-only — PROBES §1), breaching "the held message is never
lost"; (3) `savePhoneFacts` would persist a non-attested origin across reloads. Disarm-only has none of these
and fails on the safe side: the worst case is a nudge instead of a handover for one idle window.

Consequence to state plainly: with auto On, a session being driven over a channel never auto-clears while
messages keep arriving inside the idle window; once the channel goes quiet for the window while the agent works,
it may — the same contract the terminal has.

**Tests** as the verdict (arming.test for both origins: `lastHumanAt` moved, `lastHumanOrigin`/`lastBridgeAt`
unchanged, `mode` attended, `rearm(false, origin)` false, `holdOnReturn` false; one shell case with `channel`).

**Spec §2 "Engaged"** — widen the `unclassified` bullet: "a prompt whose origin is `unclassified` (a same-user
channel the engine cannot attest), `channel` (a message relayed by an MCP channel server such as Slack or
Telegram — a person, but not attestably you) or `auto-continuation` (the engine's programmatic follow-up to a
UI action of yours) disarms auto mode and restarts the idle clock, but counts for nothing else: it is not a
phone fact, does not re-arm last light and is never held on return." **README line 34** — "An `unclassified`,
`channel` or `auto-continuation` prompt disarms auto mode but counts for nothing else."

---

## Rulings on the remaining findings — only where behaviour the owner should know about changes

- **R2-04 — APPROVE.** Visible change: a limit resume now arrives in a session that sat idle under a latch another
  session set (that is the promised behaviour, not a new one). `checkLatch($, [])` is correct: `latchCleared`
  with no limits returns true past `resetsAtMs`.
- **R2-05 — APPROVE.** Visible: after an overnight restart the first prompt is held and the Resume/Carry-on ask
  opens (spec §4). `cacheExpiresAt = (lastApi ?? pending.createdAt) + TTL_1H` for `last_light` pendings; the
  R1-05 drop stays only when `lastApi !== null && now < lastApi + TTL_1H`.
- **R2-07 — APPROVE.** Visible: pressing a bar button makes the session attended for the idle window (30 min),
  so no auto handover follows a `2`/`later` press until another full idle window. That is the owner's intent
  (they are there).
- **R2-08 — APPROVE.** Visible: switching auto Off anywhere (another session, phone `/vsetup auto`) while a clear
  waits stops it, with a notice; the handover stays offered.
- **R2-09 — APPROVE** as directed; `checkLatch` drains it under R1-09/R2-01 rules.
- **R2-10 — APPROVE, standalone.** Since R2-02 is deferred, do not build the `turn.complete`-coupled world gate.
  Give the world a `clearHold: { held: boolean; release(): void }` option that makes `command.run('clear')` return a
  promise resolved by `release()`; test: auto armed, `tool.call(write)` (clear in flight, held), `measure(45)`,
  `settle`, `release()`, `settle` → exactly one `clear`.
- **R2-11 — APPROVE WITH CHANGE.** Two precisions: (a) **consumption, not re-send**: `returnHeldA` is read-and-
  cleared atomically (`update(returnHeldA, …)`) by whichever answer acts first; an answer — stale token or not —
  that finds it empty does nothing, so an old closure's dialog surviving a reload can never double-send.
  (b) Free text under "Other" is Carry on with the typed text appended to the held text (never a clear on an
  ambiguous answer — intent #2); the typed text is thus never lost. Visible: after a reload with an ask open the
  person may see a second dialog; answering either works, the other becomes inert.
- **R2-12 — APPROVE.** Visible: an early stop with a fresh `/vho` handover already on disk writes no second
  handover; the limit resume names the `/vho` file.
- **R2-13, R2-15, R2-16 — APPROVE** as directed; no visible change.
- **R2-14 — APPROVE.** Visible: `/vho` and the bar's `1` reply truthfully under stand-down / in-flight
  (`classicActive`, `handoverInProgress`) instead of "Handing over…"; last light under stand-down logs a skip
  and spends no arm.
- **R2-17 — APPROVE WITH CHANGE.** Do **not** `savePending($, null)` on the skipped-resume path. The R1-12 notice
  names the path, every parking notice says "/clear to resume from it", and README says "A `/clear` you run
  yourself picks up a saved handover the same way" — deleting the pending would make the one case where the
  person was told the path the one case `/clear` ignores. Fix the actual defect (silent injection) instead: in
  the `classic.SessionStart source:'clear'` branch, whenever a pending is injected and **no** automatic resume is
  sent (`!pending.resume || !fresh || latched`), notify — the existing `resumeStale`/latched lines already cover
  two cases; add one for `resume: false`: `📜 Handover injected (<path>) — written at the usage-limit stop; say where to pick up`,
  log `resume { stale: true }` or `{ limit: true }`. Test: early stop, `tool.call(write)`, `human('hi')`, past
  reset + 5 min → `resumeSkipped`, pending **kept**; then `SessionStart({source:'clear'})` → inject + the new
  notice, no resume submit.
- **R2-18 — APPROVE.** README sentence as the verdict ("asked until it is answered — a dismissed card is asked
  again in a later session"); spec §2 "First RC session" the same clause. `$.state` persistence of `rcAsked` is
  optional tonight; if done, remove or use the `PluginState.rcAsked` key so typings and code agree.
- **R2-19 — APPROVE.** Rewrite the comment as the verdict's first option; keep the `scheduleLastLight` call — it is
  where the deferred R1-07 half will land.

Rejected findings (S1, S4, S6-main, S11b, S12, S13, O19, S14, S15, S16, O9, O13): the verdict's reasons stand;
nothing to add. O9's follow-up note (drop a `limit` deferral at drain) and O13's union-mark idea go on the
follow-up card list, not tonight.

## Notes for the fixer

- **Ordering.** R2-02 is deferred, so the verdict's "land R2-02 first" no longer applies. Land in this order:
  R2-10 (`clearInFlight` flag + world `clearHold`) → R2-01 (`checkLatch` lift rule + `observe` drop; rewrite
  shell-limits:34 into the four cases) → R2-08 (same `tryClear` seam) → R2-06 (`arming.ts` set; spec/README
  clause) → R2-03 + R2-09 (`awaiting` lifecycle) → R2-04 + R2-16 (`hopResume`/`limitResume`) → R2-05 then R2-11
  (both touch the last-light `session.start`/`prompt.submit` paths; R2-11's `returnHeldA` goes in `$.state`) →
  R2-12, R2-17 (clear-branch notice) → R2-07, R2-13, R2-14, R2-15, R2-18, R2-19 in any order.
- **R2-01 and R2-08 both add exits to the clear path**; every exit that leaves the pending in place is an
  *offer*: `lastWait = null`, `clearParked = true`, a `pendingOffer`/`clearSkipped*` notice, a `guard.wait` or
  `clear.skipped` log line. No exit is silent.
- **PROBES.md** gains three entries tonight: `turn.start.e.text` equality (R2-03), prompt queued behind a mod-run
  `/clear`, draft survival across a mod-run `/clear` (both R2-02, marked unprobed).
- No default changes anywhere: 35 % / 30 min (15/30/60) / 30 s stand.
- Every notice above is `notify` + `log`; wording is suggested, not binding; each new string lives in
  `core/voice.ts`.
- The three doc edits: spec §5 + README:58 (R2-01 sentence), spec §2 Engaged bullet + README:34 (R2-06),
  README "Remote Control" + spec §2 First RC (R2-18).
