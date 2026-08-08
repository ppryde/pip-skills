/**
 * Distinct, sorted branch names across cards and sessions (WF-031 branch
 * filter) — the union that seeds `BranchFilter`'s options and, via App.tsx,
 * drives the board's dim/spotlight treatment. Case-sensitive exact-string
 * dedupe; empty/undefined branches are dropped rather than surfacing a
 * spurious blank option.
 */
import type { BoardCard, SessionSummary } from "../api/types";

export function distinctBranches(
  cards: BoardCard[],
  sessions: SessionSummary[]
): string[] {
  const branches = new Set<string>();

  for (const card of cards) {
    if (card.branch) branches.add(card.branch);
  }
  for (const session of sessions) {
    if (session.branch) branches.add(session.branch);
  }

  return [...branches].sort();
}
