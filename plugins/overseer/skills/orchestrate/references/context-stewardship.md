# Context stewardship

You reset your OWN context in place — via `/clear` — at points you choose, then
resume from a re-injected handover. This keeps per-turn context small and
cache-friendly on long unsupervised runs. It is real and measured, not
aspirational.

- **Become an orchestrator.** A plain chat is inert until promoted. On first
  taking a card (or on the user's word), run `promote-orchestrator`. It reports
  **auto** (under tmux — the Stop hook can send `/clear` unattended) or
  **manual** (no tmux — you checkpoint and ask the user to type `/clear`).
- **Watch the number.** `resume` and `handoff` now carry a `ctx NN%` footer
  (pulled from config, shown against the threshold only when over — never a
  hardcoded number). Read it at stage boundaries and card completion.
- **You decide to hand over — never a blind threshold.** Hand over when:
  (a) `ctx NN%` is over the configured threshold AND you are at a clean stop
  point (between stages, not mid-dispatch); or (b) a card completes — hand over
  and start fresh regardless of the exact percentage; or (c) the user commands it.
- **How.** Run `request-clear --notes "<the critical prose a fresh you must
  know that the cards don't already capture>"`. It writes the enriched handover
  and arms the reset. In auto mode the Stop hook sends `/clear` when your turn
  ends; in manual mode you tell the user to type `/clear`. Either way
  `SessionStart` re-injects the handover and you resume lean.
- **Defer for a live human.** Never clear a discussion out from under the user:
  while a live exchange is in progress, hold off, and run `context-guard pause`
  when someone joins an overnight run (e.g. on mobile). `context-guard resume`
  re-arms. Always wait for an in-flight dispatch to return before handing over.
- Gaps >5 minutes between actions cost cache re-reads — a fresh session can be
  cheaper for a big batch. No heroic high-context finishes.

Manual trigger: the `/handover` command runs this flow on demand.
