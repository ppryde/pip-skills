# context-vigil-mod live smokes

Owner-run checklist (the controller may also drive a throwaway session via tmux for probes). Run in an account with the mod installed and `/vsetup` done. Fill each result line.

## 1. Requested handover (terminal)
`/vho` -> instruction turn -> `vigil_handover` called -> file under `handovers/` -> `/clear` runs by itself -> handover injected -> resume prompt arrives.
Result: 

## 2. Draft guard
Type a draft, then `/vho`: it waits with the ✍️ notice. Delete the draft: it clears within 2 s.
Result: 

## 3. Vigil bar
Push context past 35%: bar shows `context NN% · threshold 35%`. `1` starts a handover; `2` hides until the next step; `0` hides silently until a clear (no notice). When the feedback survey appears the bar hides, and returns after.
Result: 

## 4. Phone (Remote Control)
Auto mode on, idle window 15 min (`/vsetup auto`), work from the phone. When auto mode first arms, the `📱 RC clear` question is asked (once). Yes: at the threshold the 30 s countdown notice reaches the phone, the terminal bar shows the countdown with `0: ✖ Cancel`; pressing 0 or sending a message cancels. No: handover saved, nothing clears.
Result: 

## 5. Last light
`/vsetup last-light` On; leave idle ~55 min at >= 25%: handover written, nothing cleared. Return after the hour: resume/carry-on dialog; the held message is re-sent either way.
Result: 

## 6. Limits
Force a `rate_limit` (or wait for one): `⏳ resumes HH:MM` notice, no clear until lifted.
Result: 

## 7. Coexistence
With classic installed in the account: one "standing down" notice, nothing else happens.
Result: 

## 8. Event log
`events/<today>/<session>.jsonl` holds `threshold`, `handover.written`, `clear`, `resume` lines with reasons.
Result: 

## 9. Session naming, unnamed session
Start a fresh session without `/rename`; run a handover. After the clear the prompt border and `/resume` show the handover's `session_name`.
Result: 

## 10. Session naming, already named
`/rename` the session first, then run a handover. After the clear it keeps YOUR name.
Result: 

## 11. Auto handover crosses the clear (probe section 9 path)
Auto mode armed, run an auto handover to the clear. After it: the handover is injected into the new session and the resume prompt arrives (pending state lives in `$.store`; `$.state` is wiped by `/clear`, which broke this pre-fix).
Result: 
