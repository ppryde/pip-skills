# Context stewardship (via the vigil plugin)

Context handover is provided by the **`vigil`** plugin — a soft dependency. If
`vigil` is not installed, context handover is unavailable: **tell the user once**
that installing `vigil` enables in-session `/clear` handover, and carry on (the
pipeline still runs).

Vigil owns the mechanism (measure + reset); overseer supplies the payload (a card
rollup). Drive it through `vigil`'s CLI:

- **Begin the watch** when you take a card (or on the user's word): `vigil begin`.
  It reports **auto** (tmux — unattended `/clear`) or **manual** (you ask the
  user to type `/clear`).
- **Watch the number**: run `vigil context` at stage boundaries and card
  completion — it prints `ctx NN%` against the configured threshold.
- **Hand over — you decide, never a blind threshold.** When you are over
  threshold at a clean stop point, when a card completes, or on command: build
  the enriched handover from the ledger and pipe it to vigil as the payload,
  suppressing the generic snapshot:

  ```
  python plugins/overseer/scripts/cli.py --root . handoff | \
    vigil handover --no-snapshot --content-file -
  ```

  (`handoff` already embeds the in-flight/blocked/planned rollup; add prose the
  cards don't capture by editing before piping, or via a second `--notes`.)
  In auto mode the Stop hook sends `/clear` at turn end; in manual mode you tell
  the user to type it. Either way `SessionStart` re-injects the handover and you
  resume lean.
- **Defer for a live human**: never clear a discussion out from under the user.
  Hold off during a live exchange; `vigil pause` when someone joins an overnight
  run, `vigil resume` after. Always wait for an in-flight dispatch to return.

No heroic high-context finishes.
