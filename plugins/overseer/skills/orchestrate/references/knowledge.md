# Knowledge (mint, inject, verify, retire)

The knowledge base is the orchestrator's memory across cards. You are its only
writer; agents propose, you adjudicate.

- **Inject.** At every dispatch, fill the template's `{{knowledge}}` with the
  facts whose tags/paths intersect this card's `touches`, goal, or chunk brief —
  never the whole corpus. An empty selection injects nothing. Facts marked
  `[STALE]` go in with their marker; the agent treats them as claims to
  re-verify. Select via the `facts` command, which computes effective staleness
  live — never by reading `knowledge.md`, whose staleness only refreshes on the
  next write, so a stale fact could otherwise be injected unmarked.
- **Mint.** Each report may carry a **Learned** line. Adjudicate it: mint only
  falsifiable, non-duplicate facts via `add-fact` (source = the card id). Reject
  the vague and the already-known.
- **Verify.** When an injected fact is relied on and proves true, `verify-fact`
  it — that clears staleness and resets its 90-day clock.
- **Retire.** When a reviewer or worker refutes a fact, `retire-fact` it
  (`--superseded-by` when a newer fact replaces it). Never edit knowledge files
  by hand.
