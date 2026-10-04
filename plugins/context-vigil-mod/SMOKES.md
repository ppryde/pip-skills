# context-vigil-mod live smokes

Owner-run checklist (the controller may also drive a throwaway session via tmux for probes). Run in an account with the mod installed and `/vsetup` done. Fill each result line.

## 1. Requested handover (terminal)
`/vho` -> instruction turn -> `vigil_handover` called -> file under `handovers/` -> `/clear` runs by itself -> handover injected -> resume prompt arrives.
Result: PASS 2026-10-04 (controller, tmux, haiku). /vho -> handover.written (1805 B) -> clear unattended:false -> new session `resume` reason request; resume prompt arrived.

## 2. Draft guard
Type a draft, then `/vho`: it waits with the ✍️ notice. Delete the draft: it clears within 2 s.
Result: PASS 2026-10-04. Draft typed during /vho: `guard.wait` reason draft, ✍️ notice shown (tmux renders the VS16 emoji one cell wide, eating the next letter -- cosmetic). Draft deleted (C-u): clear followed.

## 3. Vigil bar
Push context past 35%: bar shows `context NN% · threshold 35%`. `1` starts a handover; `2` hides until the next step; `0` hides silently until a clear (no notice). When the feedback survey appears the bar hides, and returns after.
Result: PASS 2026-10-04 except the survey half (not forceable). Bar `context 25% · threshold 25%` at setup; `2` hid it until the next step (returned at 48% offering `Remind me at 50%`); `0` hid it silently, threshold lines kept logging with no bar. Survey hide/return: NOT RUN.

## 4. Phone (Remote Control)
Auto mode on, idle window 15 min (`/vsetup auto`), work from the phone. When auto mode first arms, the `📱 RC clear` question is asked (once). Yes: at the threshold the 30 s countdown notice reaches the phone, the terminal bar shows the countdown with `0: ✖ Cancel`; pressing 0 or sending a message cancels. No: handover saved, nothing clears.
Result: NOT RUN by the controller -- owner to test on the phone.

## 5. Last light
`/vsetup last-light` On; leave idle ~55 min at >= 25%: handover written, nothing cleared. Return after the hour: resume/carry-on dialog; the held message is re-sent either way.
Result: PARTIAL 2026-10-04. Fired after 55 min idle at 26%: `last_light.fired` -> handover written, nothing cleared, prompt pre-filled with /clear. Note: the fire's own handover turn refreshes the 1 h cache (spec loop guard), so the return-dialog half needs > 1 h after the fire with no prompt in between. Return half: RESULT_PENDING

## 6. Limits
Force a `rate_limit` (or wait for one): `⏳ resumes HH:MM` notice, no clear until lifted.
Result: NOT RUN -- a rate limit cannot be forced. Covered by limits/shell-limits unit tests.

## 7. Coexistence
With classic installed in the account: one "standing down" notice, nothing else happens.
Result: NOT RUN live (classic is installed in neither account) -- owner accepts unit-test coverage (interlock.test.ts); owner to check manually.

## 8. Event log
`events/<today>/<session>.jsonl` holds `threshold`, `handover.written`, `clear`, `resume` lines with reasons.
Result: PASS 2026-10-04. threshold, handover.requested, handover.written, guard.wait, clear, resume, rename, arm/disarm all logged with reasons. Minor: the `clear` line carries `unattended` but no `reason` field.

## 9. Session naming, unnamed session
Start a fresh session without `/rename`; run a handover. After the clear the prompt border and `/resume` show the handover's `session_name`.
Result: PASS 2026-10-04. Unnamed session took the handover's session_name (`vigil-mod setup and architecture review`) in the prompt border; `rename` logged.

## 10. Session naming, already named
`/rename` the session first, then run a handover. After the clear it keeps YOUR name.
Result: PASS 2026-10-04. `/rename smoke-ten-owner-name` then /vho: name kept after the clear (`rename kept:true`).

## 11. Auto handover crosses the clear (probe section 9 path)
Auto mode armed, run an auto handover to the clear. After it: the handover is injected into the new session and the resume prompt arrives (pending state lives in `$.store`; `$.state` is wiped by `/clear`, which broke this pre-fix).
Result: PASS 2026-10-04, with two DEFECTS found and fixed on fix/cvm-auto-guards (a8404c9). Armed after 19 min away while working, threshold 25% mode auto -> handover -> unattended clear -> new session resumed. Defects: (a) a human prompt during an in-flight auto handover disarmed auto mode but the clear still ran unattended (spec: attended never clears); (b) thrash -- fresh session baseline ~24% sat under the 25% threshold, 3 unattended clears in ~3 min. Fixes: clear re-checks mode at clear time (`clear.skipped`); unattended handover needs one step of growth above the session's first reading (`guard.baseline`).
