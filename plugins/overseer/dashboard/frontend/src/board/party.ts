/**
 * Pure join of the census session poll against board cards (WF-029 chunk 2)
 * — every session becomes exactly one PartyMember, whether or not it's
 * currently claiming a card. Consumers (PartyColumn, PartyOverlay, TopBar's
 * questing count) render this array; none of them re-derive the join
 * themselves (see the card's Decisions: "buildParty() joins sessions <->
 * claimed cards once; consumers render, never join").
 */
import type { BoardCard, SessionSummary } from "../api/types";

export interface PartyMember {
  session: SessionSummary;
  /** The card this session's `claimed_by` matches, or null if unclaimed. */
  questCardId: string | null;
  questTitle: string | null;
}

export function buildParty(
  sessions: SessionSummary[],
  cards: BoardCard[]
): PartyMember[] {
  return sessions.map((session) => {
    const quest = cards.find((c) => c.claimed_by === session.id);
    return {
      session,
      questCardId: quest?.id ?? null,
      questTitle: quest?.title ?? null,
    };
  });
}
