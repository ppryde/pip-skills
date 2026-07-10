---
description: Hand over now — write an enriched handover and reset context (or advise /clear), per the overseer context-stewardship protocol.
argument-hint: [optional note on what a fresh session must know]
---

The user is asking you to hand over context now (a manual context reset). Act as
the overseer orchestrator and follow the context-stewardship protocol in
`skills/orchestrate/references/context-stewardship.md`:

1. **Finish or hold.** If a dispatch is in flight, wait for it to return — never
   hand over mid-dispatch. If a live discussion is mid-thread, confirm with the
   user before clearing.
2. **Write the handover.** Run `request-clear --notes "<the critical prose a
   fresh you must know that the cards/ledger don't already capture>"` via the
   overseer CLI. Fold in anything the user passed as an argument to this command.
   This writes the enriched handover and arms the reset. Keep the notes tight —
   the ledger already holds card/stage/budget state; capture only what a fresh
   session couldn't reconstruct from `resume`.
3. **Reset, per mode.**
   - **auto** (under tmux, promoted): tell the user the Stop hook will send
     `/clear` when this turn ends, and `SessionStart` will re-inject the handover.
   - **manual** (no tmux): tell the user to type `/clear` now; `SessionStart`
     re-injects the handover.
   - If this session isn't a promoted orchestrator yet, run
     `promote-orchestrator` first (it reports auto vs manual).
