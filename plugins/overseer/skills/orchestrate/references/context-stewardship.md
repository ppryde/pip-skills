# Context stewardship (via the vigil plugin)

Context handover is provided by the **`vigil`** plugin — a soft dependency. If
`vigil` is not installed, context handover is unavailable: **tell the user once**
that installing `vigil` enables in-session `/clear` handover, and carry on (the
pipeline still runs).

Vigil owns the mechanism (measure + reset); overseer supplies the payload (a card
rollup). Drive it through the **ledger CLI's** `vigil` and `handover` verbs: the
CLI locates the vigil plugin itself (newest installed version), so you never
type a path to vigil's `cli.py`. If vigil isn't found, those verbs print a
one-line notice and exit 0 — tell the user once, then carry on.

- **Begin the watch** when you take a card (or on the user's word):
  `vigil begin`. It reports **auto**
  (tmux — unattended `/clear`) or **manual** (you ask the user to type `/clear`).
- **Watch the number**: run `vigil context` at stage boundaries and card completion — it prints `ctx NN%`
  against the configured threshold — and `resume`/`handoff` auto-append
  `ctx NN%` when vigil is installed.
- **Hand over — you decide, never a blind threshold.** The default trigger is
  every stage boundary once the stage is recorded in the ledger. When you are over
  threshold at a clean stop point, when a card completes, or on command: build
  the enriched handover from the ledger and hand it to vigil as the payload,
  suppressing the generic snapshot — one call, no shell pipe:

  ```
  python3 "<base directory>/../../scripts/cli.py" --root . handover
  ```

  (`handover` already embeds the in-flight/blocked/planned rollup; add prose the
  cards don't capture with `handover --notes "<text>"`.)
  In auto mode the Stop hook sends `/clear` at turn end; in manual mode you tell
  the user to type it. Either way `SessionStart` re-injects the handover and you
  resume lean.
- **Defer for a live human**: never clear a discussion out from under the user.
  Hold off during a live exchange; `vigil pause` when someone joins an overnight
  run, `vigil resume` after. Always wait for an in-flight dispatch to return.

After a `/clear` handover the PreToolUse guard is **off** until your next work
verb (`set-stage`, `log-progress`, `dispatch-prep`, ...) re-stamps you as the
card's orchestrator: `resume` cannot know it is the successor session. So make
your first act after resuming a work verb, not a source read.

No heroic high-context finishes.
